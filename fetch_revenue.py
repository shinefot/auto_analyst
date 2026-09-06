import requests, pandas as pd

HEADERS = {"User-Agent": "Shiney Fotedar shinefot@email.com"}
CIK = "0001318605"   # Tesla

url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json"
data = requests.get(url, headers=HEADERS).json()

revenue = data["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
df = pd.DataFrame(revenue)

annual = df[df["frame"].str.match(r"^CY\d{4}$", na=False)]
annual = annual[["frame", "end", "val", "form"]].copy()
annual["val_bn"] = (annual["val"] / 1e9).round(1)

print(annual.tail(8).to_string(index=False))
