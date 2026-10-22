import httpx, pandas as pd, sys
from concurrent.futures import ThreadPoolExecutor
def get(tf, start):
    c = httpx.Client(timeout=20); rows=[]; t=int(pd.Timestamp(start, tz="UTC").timestamp()*1000)
    while True:
        r = c.get("https://api.binance.com/api/v3/klines", params={"symbol":"BTCUSDT","interval":tf,"startTime":t,"limit":1000}).json()
        if not r: break
        rows += r; t = r[-1][0]+1
        if len(r)<1000: break
    df = pd.DataFrame([x[:6] for x in rows], columns=["ts","open","high","low","close","volume"]).astype(float)
    df["ts"]=pd.to_datetime(df.ts,unit="ms",utc=True)
    df.to_csv(f"research/btc_{tf}.csv", index=False)
    return tf, len(df), str(df.ts.iloc[0]), str(df.ts.iloc[-1])
with ThreadPoolExecutor(3) as ex:
    for r in ex.map(lambda a: get(*a), [("1h","2019-01-01"),("15m","2022-01-01"),("4h","2018-01-01"),("1d","2017-09-01")]): print(r)
