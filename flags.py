import json, glob, os
import pandas as pd

# Each rule receives the company's table (rows = fiscal years, latest last)
# and returns a flag dict or None. Numbers in "evidence" are what the LLM
# is later allowed to quote. Nothing here is decided by an AI model.

def pct(x):
    return None if pd.isna(x) else round(float(x) * 100, 1)

def bn(x):
    return None if pd.isna(x) else round(float(x) / 1e9, 1)


def revenue_decline(t):
    g = t["revenue_growth"].iloc[-1]
    if g < 0:
        return dict(id="revenue_decline", severity="high",
                    message=f"Revenue fell {pct(-g)}% in FY{t.index[-1]}",
                    evidence={"revenue_growth_pct": pct(g),
                              "revenue_bn": bn(t["revenue"].iloc[-1]),
                              "prior_revenue_bn": bn(t["revenue"].iloc[-2])})


def growth_deceleration(t):
    g_now, g_prev = t["revenue_growth"].iloc[-1], t["revenue_growth"].iloc[-2]
    if pd.notna(g_prev) and g_prev > 0.05 and g_now < g_prev * 0.5:
        return dict(id="growth_deceleration", severity="medium",
                    message=f"Revenue growth slowed from {pct(g_prev)}% to {pct(g_now)}%",
                    evidence={"growth_now_pct": pct(g_now), "growth_prior_pct": pct(g_prev)})


def margin_compression(t):
    m_now, m_prev = t["operating_margin"].iloc[-1], t["operating_margin"].iloc[-2]
    if m_now < m_prev - 0.03:
        return dict(id="operating_margin_compression", severity="high",
                    message=f"Operating margin fell {pct(m_prev - m_now)} pts to {pct(m_now)}%",
                    evidence={"op_margin_now_pct": pct(m_now), "op_margin_prior_pct": pct(m_prev)})


def gross_margin_drop(t):
    m_now, m_prev = t["gross_margin"].iloc[-1], t["gross_margin"].iloc[-2]
    if m_now < m_prev - 0.02:
        return dict(id="gross_margin_drop", severity="medium",
                    message=f"Gross margin fell {pct(m_prev - m_now)} pts to {pct(m_now)}%",
                    evidence={"gross_margin_now_pct": pct(m_now), "gross_margin_prior_pct": pct(m_prev)})


def receivables_outpacing_revenue(t):
    r, g = t["receivables_growth"].iloc[-1], t["revenue_growth"].iloc[-1]
    if pd.notna(r) and r > g + 0.10:
        return dict(id="receivables_outpacing_revenue", severity="medium",
                    message=f"Receivables grew {pct(r)}% vs revenue {pct(g)}% (possible aggressive revenue recognition or slower collections)",
                    evidence={"receivables_growth_pct": pct(r), "revenue_growth_pct": pct(g)})


def inventory_build(t):
    inv_g = t["inventory"].pct_change().iloc[-1]
    g = t["revenue_growth"].iloc[-1]
    if pd.notna(inv_g) and inv_g > g + 0.15:
        return dict(id="inventory_build", severity="medium",
                    message=f"Inventory grew {pct(inv_g)}% vs revenue {pct(g)}%",
                    evidence={"inventory_growth_pct": pct(inv_g), "revenue_growth_pct": pct(g)})


def capex_surge(t):
    c_now, c_prev = t["capex_to_cfo"].iloc[-1], t["capex_to_cfo"].iloc[-2]
    if c_now > 0.75 or (pd.notna(c_prev) and c_now > c_prev + 0.15):
        return dict(id="capex_surge", severity="medium",
                    message=f"Capex consumed {pct(c_now)}% of operating cash flow (prior year {pct(c_prev)}%)",
                    evidence={"capex_to_cfo_now_pct": pct(c_now), "capex_to_cfo_prior_pct": pct(c_prev),
                              "capex_bn": bn(t["capex"].iloc[-1]), "fcf_bn": bn(t["fcf"].iloc[-1])})


def negative_fcf(t):
    f = t["fcf"].iloc[-1]
    if f < 0:
        return dict(id="negative_fcf", severity="high",
                    message=f"Free cash flow was negative (${bn(f)}bn)",
                    evidence={"fcf_bn": bn(f)})


def heavy_sbc(t):
    s = t["sbc_pct_revenue"].iloc[-1]
    if pd.notna(s) and s > 0.05:
        return dict(id="heavy_sbc", severity="low",
                    message=f"Stock-based compensation is {pct(s)}% of revenue",
                    evidence={"sbc_pct_revenue": pct(s), "sbc_bn": bn(t["sbc"].iloc[-1])})


def share_dilution(t):
    d = t["share_change"].iloc[-1]
    if pd.notna(d) and d > 0.02:
        return dict(id="share_dilution", severity="low",
                    message=f"Diluted share count rose {pct(d)}%",
                    evidence={"share_change_pct": pct(d)})


# Positive signals: a real analyst note has these too
def margin_expansion(t):
    m_now, m_prev = t["operating_margin"].iloc[-1], t["operating_margin"].iloc[-2]
    if m_now > m_prev + 0.03:
        return dict(id="operating_margin_expansion", severity="positive",
                    message=f"Operating margin expanded {pct(m_now - m_prev)} pts to {pct(m_now)}%",
                    evidence={"op_margin_now_pct": pct(m_now), "op_margin_prior_pct": pct(m_prev)})


def fcf_outgrowing_revenue(t):
    f_g = t["fcf"].pct_change().iloc[-1]
    g = t["revenue_growth"].iloc[-1]
    if pd.notna(f_g) and t["fcf"].iloc[-2] > 0 and f_g > g + 0.10:
        return dict(id="fcf_outgrowing_revenue", severity="positive",
                    message=f"Free cash flow grew {pct(f_g)}% vs revenue {pct(g)}%",
                    evidence={"fcf_growth_pct": pct(f_g), "revenue_growth_pct": pct(g),
                              "fcf_bn": bn(t["fcf"].iloc[-1])})


def buybacks(t):
    d = t["share_change"].iloc[-1]
    if pd.notna(d) and d < -0.01:
        return dict(id="share_count_shrinking", severity="positive",
                    message=f"Diluted share count fell {pct(-d)}% (buybacks)",
                    evidence={"share_change_pct": pct(d)})


RULES = [revenue_decline, growth_deceleration, margin_compression, gross_margin_drop,
         receivables_outpacing_revenue, inventory_build, capex_surge, negative_fcf,
         heavy_sbc, share_dilution, margin_expansion, fcf_outgrowing_revenue, buybacks]


def run(table):
    flags = []
    for rule in RULES:
        try:
            f = rule(table)
        except (IndexError, KeyError):
            f = None
        if f:
            flags.append(f)
    return flags


if __name__ == "__main__":
    results = {}
    for path in sorted(glob.glob("data/*.csv")):
        name = os.path.basename(path).replace(".csv", "")
        t = pd.read_csv(path, index_col="fiscal_year")
        flags = run(t)
        results[name] = {"latest_fiscal_year": int(t.index[-1]), "flags": flags}
        print(f"\n=== {name} (FY{t.index[-1]}) ===")
        for f in flags:
            print(f"  [{f['severity']:8s}] {f['message']}")

    with open("data/flags.json", "w") as fh:
        json.dump(results, fh, indent=2)
    print("\nSaved data/flags.json")
