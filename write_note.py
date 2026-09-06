import json, os, sys
import pandas as pd
from anthropic import Anthropic

MODEL = "claude-sonnet-5"
client = Anthropic()  # reads ANTHROPIC_API_KEY from the environment

ANALYST_SYSTEM = """You are a senior equity research analyst writing an internal note for a
private equity investment committee. You are rigorous, sceptical and concise.

Hard rules:
1. Use ONLY the numbers provided in the data block. Never introduce figures from memory.
2. Every number you cite must be followed by the fiscal year it belongs to, in the form (10-K, FY2022). When comparing two years, cite both.
3. If the data does not support a claim, say so rather than speculate.
4. Do not give a buy/sell recommendation. Frame conclusions as questions for diligence.
5. Write in plain prose. No bullet lists except in the final two sections.

Structure the note with exactly these headings:
## Summary
Three sentences: what the business is doing, the single most important change this year, and why it matters.
## What changed this year
Walk through the flagged signals in order of severity. Explain the mechanism behind each, not just the number.
## Cross-checks
Where two metrics tell conflicting stories (e.g. revenue falls but cash flow rises), reconcile them.
## Key questions for management
Four to six pointed questions a diligence team should ask.
## Data limitations
What this analysis cannot see from filings alone.
"""

VERIFIER_SYSTEM = """You are a fact-checker. You receive a research note and the data block it was
written from. List every numeric figure in the note that does NOT appear in the data block
(allowing for rounding to one decimal place and for simple differences/sums of provided numbers).
If every figure is traceable, reply with exactly: ALL FIGURES VERIFIED
Otherwise reply with one line per problem: the figure, and why it is not supported."""


def load(company):
    t = pd.read_csv(f"data/{company}.csv", index_col="fiscal_year")
    with open("data/flags.json") as fh:
        flags = json.load(fh)[company]
    return t, flags


def data_block(company, t, flags):
    keep = ["revenue", "revenue_growth", "gross_margin", "operating_margin", "net_margin",
            "cfo", "capex", "fcf", "fcf_margin", "capex_to_cfo", "receivables", "inventory",
            "cash", "rnd_pct_revenue", "sbc_pct_revenue", "diluted_shares", "share_change"]
    view = t[[c for c in keep if c in t.columns]].copy()
    for c in view.columns:
        if c in ("revenue", "cfo", "capex", "fcf", "receivables", "inventory", "cash"):
            view[c] = (view[c] / 1e9).round(2)          # USD billions
        elif c == "diluted_shares":
            view[c] = (view[c] / 1e6).round(0)          # millions
        else:
            view[c] = (view[c] * 100).round(1)          # percentages
    return f"""COMPANY: {company}
SOURCE: SEC EDGAR XBRL company facts, annual 10-K filings. Fiscal years labelled by period end.
UNITS: revenue/cfo/capex/fcf/receivables/inventory/cash in USD billions; diluted_shares in millions; everything else in percent.

METRICS (rows are fiscal years, latest last):
{view.to_string()}

RULE-BASED FLAGS (computed in code, latest fiscal year FY{flags['latest_fiscal_year']}):
{json.dumps(flags['flags'], indent=2)}
"""


def ask(system, user, max_tokens=16000):
    msg = client.messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                                 messages=[{"role": "user", "content": user}])
    text = "".join(b.text for b in msg.content if b.type == "text")
    if msg.stop_reason == "max_tokens":
        print(f"  WARNING: output cut off at {max_tokens} tokens")
    print(f"  ({msg.usage.output_tokens} output tokens, stop_reason={msg.stop_reason})")
    return text


def write_note(company):
    t, flags = load(company)
    block = data_block(company, t, flags)

    note = ask(ANALYST_SYSTEM, f"Write the research note.\n\n{block}")
    check = ask(VERIFIER_SYSTEM, f"DATA BLOCK:\n{block}\n\nNOTE:\n{note}", max_tokens=4000)

    os.makedirs("notes", exist_ok=True)
    with open(f"notes/{company}.md", "w", encoding="utf-8") as fh:
        fh.write(f"# {company} — Auto-Analyst Note (FY{flags['latest_fiscal_year']})\n\n")
        fh.write(note)
        fh.write("\n\n---\n## Verification pass\n" + check + "\n")
    verdict = check.splitlines()[0] if check.strip() else "(verifier returned nothing)"
    print(f"Saved notes/{company}.md   | verifier: {verdict}")
    return note, check


if __name__ == "__main__":
    companies = sys.argv[1:] or ["Tesla", "Nvidia", "Microsoft", "Amazon"]
    for c in companies:
        write_note(c)
