"""Fetch XAUUSD daily bars from TradeLocker -> data/XAUUSD_TL_D1.csv (used by xau_bot via XAU_DATA env).

Needs env vars: TL_EMAIL, TL_PASSWORD, TL_SERVER, (optional) TL_ACCOUNT_ID.
Usage: python3 fetch_tl_xau.py [start=2019-01-01]
"""
import os, sys, datetime as dt, requests, pandas as pd

BASE = "https://demo.tradelocker.com/backend-api"
start = dt.datetime.fromisoformat(sys.argv[1] if len(sys.argv) > 1 else "2018-06-01").replace(tzinfo=dt.timezone.utc)
end = dt.datetime.now(dt.timezone.utc)
tok = requests.post(f"{BASE}/auth/jwt/token", json={"email": os.environ["TL_EMAIL"],
      "password": os.environ["TL_PASSWORD"], "server": os.environ["TL_SERVER"]}, timeout=20).json()
H = {"Authorization": f"Bearer {tok['accessToken']}", "accept": "application/json"}
accs = requests.get(f"{BASE}/auth/jwt/all-accounts", headers=H, timeout=20).json()["accounts"]
acc = next((a for a in accs if str(a["id"]) == os.environ.get("TL_ACCOUNT_ID", "")), accs[0])
H["accNum"] = str(acc["accNum"])
ins = requests.get(f"{BASE}/trade/accounts/{acc['id']}/instruments", headers=H, timeout=20).json()["d"]["instruments"]
x = next(i for i in ins if i["name"].upper().startswith("XAUUSD"))
route = next(r["id"] for r in x["routes"] if r["type"] == "INFO")
rows, cur = [], start
while cur < end:                                   # chunk to stay under per-request bar limits
    nxt = min(cur + dt.timedelta(days=365), end)
    r = requests.get(f"{BASE}/trade/history", headers=H, timeout=30, params={
        "tradableInstrumentId": x["tradableInstrumentId"], "routeId": route, "resolution": "1D",
        "from": int(cur.timestamp() * 1000), "to": int(nxt.timestamp() * 1000)}).json()
    rows += [(b["t"], b["o"], b["h"], b["l"], b["c"]) for b in r.get("d", {}).get("barDetails", [])]
    cur = nxt
df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close"])
df["time"] = pd.to_datetime(df.t, unit="ms", utc=True)
df = df.drop(columns="t").drop_duplicates("time").sort_values("time")
os.makedirs("data", exist_ok=True); df.to_csv("data/XAUUSD_TL_D1.csv", index=False)
print(len(df), df.time.min(), df.time.max())
