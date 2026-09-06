
import os, time
import requests, pandas as pd

HEADERS = {"User-Agent": "Shiney Fotedar shinefot@email.com"}   # <-- change this

COMPANIES = {
    "Tesla":     "0001318605",
    "Nvidia":    "0001045810",
    "Microsoft": "0000789019",
    "Amazon":    "0001018724",
}

# Each metric has a list of XBRL tags to try. Companies use different tags for
# the same concept; the tag with the most RECENT data wins.
METRICS = {
    "revenue":          ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "cost_of_revenue":  ["CostOfRevenue", "CostOfGoodsAndServicesSold"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income":       ["NetIncomeLoss"],
    "rnd":              ["ResearchAndDevelopmentExpense"],
    "sbc":              ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    "cfo":              ["NetCashProvidedByUsedInOperatingActivities"],
    "capex":            ["PaymentsToAcquirePropertyPlantAndEquipment",
                         "PaymentsToAcquireProductiveAssets",
                         "PaymentsToAcquireOtherPropertyPlantAndEquipment"],
    "receivables":      ["AccountsReceivableNetCurrent"],
    "inventory":        ["InventoryNet"],
    "cash":             ["CashAndCashEquivalentsAtCarryingValue"],
    "diluted_shares":   ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}

YEARS_BACK = 6


def series_for_tag(facts, tag):
    """One value per fiscal year for a single tag (empty if tag absent)."""
    if tag not in facts:
        return pd.Series(dtype=float)
    units = facts[tag]["units"]
    unit = "USD" if "USD" in units else list(units)[0]
    df = pd.DataFrame(units[unit])
    df = df[df["form"].isin(["10-K", "10-K/A"])]
    if "start" in df.columns:  # flow items: keep only full-year periods
        days = (pd.to_datetime(df["end"]) - pd.to_datetime(df["start"])).dt.days
        df = df[days.between(340, 380)]
    if df.empty:
        return pd.Series(dtype=float)
    # every 10-K restates prior years; keep the most recently filed value
    df = df.sort_values("filed").drop_duplicates("end", keep="last")
    df["year"] = pd.to_datetime(df["end"]).dt.year
    return df.set_index("year")["val"].sort_index()


def best_series(facts, tags):
    """Try every tag; return the one whose data reaches the most recent year."""
    best, best_tag = pd.Series(dtype=float), None
    for tag in tags:
        s = series_for_tag(facts, tag)
        if len(s) and (best.empty or s.index.max() > best.index.max()):
            best, best_tag = s, tag
    return best, best_tag


def build_company(name, cik):
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    facts = requests.get(url, headers=HEADERS).json()["facts"]["us-gaap"]

    columns, coverage = {}, {}
    for metric, tags in METRICS.items():
        s, tag = best_series(facts, tags)
        columns[metric] = s
        coverage[metric] = tag or "MISSING"

    t = pd.DataFrame(columns)
    latest = t.index.max()
    t = t[t.index > latest - YEARS_BACK]
    t.index.name = "fiscal_year"

    # Derived metrics: computed in code, never by the LLM
    t["revenue_growth"]     = t["revenue"].pct_change()
    t["gross_margin"]       = (t["revenue"] - t["cost_of_revenue"]) / t["revenue"]
    t["operating_margin"]   = t["operating_income"] / t["revenue"]
    t["net_margin"]         = t["net_income"] / t["revenue"]
    t["fcf"]                = t["cfo"] - t["capex"]
    t["fcf_margin"]         = t["fcf"] / t["revenue"]
    t["capex_to_cfo"]       = t["capex"] / t["cfo"]
    t["receivables_growth"] = t["receivables"].pct_change()
    t["rnd_pct_revenue"]    = t["rnd"] / t["revenue"]
    t["sbc_pct_revenue"]    = t["sbc"] / t["revenue"]
    t["share_change"]       = t["diluted_shares"].pct_change()
    return t, coverage


if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    for name, cik in COMPANIES.items():
        table, coverage = build_company(name, cik)
        table.to_csv(f"data/{name}.csv")

        print(f"\n=== {name} ===")
        print("tags used:", {m: t for m, t in coverage.items()})
        view = pd.DataFrame({
            "revenue_bn":  (table["revenue"] / 1e9).round(1),
            "growth":      (table["revenue_growth"] * 100).round(1),
            "gross_mgn":   (table["gross_margin"] * 100).round(1),
            "op_mgn":      (table["operating_margin"] * 100).round(1),
            "fcf_bn":      (table["fcf"] / 1e9).round(1),
            "capex/cfo":   (table["capex_to_cfo"] * 100).round(0),
        })
        print(view.to_string())
        time.sleep(0.5)
