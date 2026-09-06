import json, os
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Auto-Analyst", page_icon="📄", layout="wide")

COMPANIES = ["Tesla", "Nvidia", "Microsoft", "Amazon"]
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "positive": 3}
SEVERITY_LABEL = {"high": "🔴 High", "medium": "🟠 Medium", "low": "🟡 Low", "positive": "🟢 Positive"}

st.markdown("""
<style>
  .block-container { max-width: 1100px; padding-top: 2rem; }
  h1 { font-weight: 600; letter-spacing: -0.02em; }
  .note-body p { max-width: 72ch; line-height: 1.6; }
  .signal { padding: 0.55rem 0.8rem; border-left: 3px solid #999; margin-bottom: 0.5rem; background: rgba(128,128,128,0.06); }
  .signal.high { border-color: #c0392b; }
  .signal.medium { border-color: #e67e22; }
  .signal.low { border-color: #d4ac0d; }
  .signal.positive { border-color: #27ae60; }
  .signal small { opacity: 0.65; }
</style>
""", unsafe_allow_html=True)


@st.cache_data
def load_financials(company):
    return pd.read_csv(f"data/{company}.csv", index_col="fiscal_year")


@st.cache_data
def load_flags(company):
    with open("data/flags.json") as fh:
        return json.load(fh)[company]


def load_note(company):
    path = f"notes/{company}.md"
    if not os.path.exists(path):
        return None, None
    text = open(path, encoding="utf-8").read()
    text = "\n".join(line for line in text.splitlines() if not line.startswith("# "))
    if "## Verification pass" in text:
        body, verification = text.split("## Verification pass", 1)
        return body.strip().rstrip("-").strip(), verification.strip()
    return text, None


# ---------- sidebar ----------
with st.sidebar:
    st.header("Auto-Analyst")
    st.caption("Reads SEC filings, flags what changed, writes the note. Every figure traces back to a 10-K.")
    company = st.selectbox("Company", COMPANIES)
    if st.button("Regenerate note", width="stretch"):
        from write_note import write_note
        with st.spinner("Reading filings and writing the note…"):
            write_note(company)
        st.rerun()
    st.divider()
    st.caption("Pipeline: EDGAR XBRL → normalise → rule-based flags → Claude drafts → Claude verifies")

# ---------- header + headline metrics ----------
t = load_financials(company)
flags = load_flags(company)
latest, prior = t.iloc[-1], t.iloc[-2]
fy = int(t.index[-1])

st.title(f"{company}")
st.caption(f"Fiscal year {fy}, from the annual 10-K. Deltas are versus the prior year.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Revenue", f"${latest['revenue']/1e9:,.1f}bn",
          f"{latest['revenue_growth']*100:+.1f}% y/y")
c2.metric("Operating margin", f"{latest['operating_margin']*100:.1f}%",
          f"{(latest['operating_margin']-prior['operating_margin'])*100:+.1f} pts")
c3.metric("Free cash flow", f"${latest['fcf']/1e9:,.1f}bn",
          f"{(latest['fcf']/prior['fcf']-1)*100:+.1f}%" if prior['fcf'] > 0 else None)
c4.metric("Capex / operating cash flow", f"{latest['capex_to_cfo']*100:.0f}%",
          f"{(latest['capex_to_cfo']-prior['capex_to_cfo'])*100:+.0f} pts", delta_color="inverse")

# ---------- signals ----------
st.subheader("What the rules flagged")
if not flags["flags"]:
    st.write("No thresholds breached this year.")
for f in sorted(flags["flags"], key=lambda x: SEVERITY_ORDER[x["severity"]]):
    st.markdown(
        f'<div class="signal {f["severity"]}"><b>{SEVERITY_LABEL[f["severity"]]}</b> — {f["message"]}'
        f'<br><small>rule: {f["id"]}</small></div>',
        unsafe_allow_html=True,
    )

# ---------- tabs ----------
tab_note, tab_fin, tab_check = st.tabs(["Analyst note", "Six-year financials", "Verification"])

with tab_note:
    body, verification = load_note(company)
    if body is None:
        st.info("No note yet for this company. Use “Regenerate note” in the sidebar.")
    else:
        st.markdown(f'<div class="note-body">', unsafe_allow_html=True)
        st.markdown(body.replace("$", "\\$"))
        st.markdown("</div>", unsafe_allow_html=True)

with tab_fin:
    left, right = st.columns(2)
    with left:
        st.caption("Revenue, $bn")
        st.bar_chart(t["revenue"] / 1e9)
    with right:
        st.caption("Margins, %")
        st.line_chart((t[["gross_margin", "operating_margin", "fcf_margin"]] * 100).round(1))

    show = pd.DataFrame({
        "Revenue $bn": t["revenue"] / 1e9,
        "Growth %": t["revenue_growth"] * 100,
        "Gross margin %": t["gross_margin"] * 100,
        "Op margin %": t["operating_margin"] * 100,
        "Op cash flow $bn": t["cfo"] / 1e9,
        "Capex $bn": t["capex"] / 1e9,
        "FCF $bn": t["fcf"] / 1e9,
        "Capex/CFO %": t["capex_to_cfo"] * 100,
        "Receivables $bn": t["receivables"] / 1e9,
        "Inventory $bn": t["inventory"] / 1e9,
        "SBC % rev": t["sbc_pct_revenue"] * 100,
    }).round(1)
    st.dataframe(show.T, width="stretch")
    st.caption("Source: SEC EDGAR XBRL company facts. Ratios computed in code, not by the model.")

with tab_check:
    _, verification = load_note(company)
    if verification is None:
        st.write("Run the note first.")
    elif verification.startswith("ALL FIGURES VERIFIED"):
        st.success("Independent verification pass: every figure in the note traces to the filing data.")
    else:
        st.warning("The verifier found figures it could not trace:")
        st.text(verification)
    st.caption("A second model call reads the finished note against the source data and reports any number it cannot reconcile.")
