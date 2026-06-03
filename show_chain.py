"""Fetch and display NIFTY option chain."""
import urllib.request, json

url = "http://localhost:8000/api/v1/fno/option-chain?underlying_symbol=NIFTY&expiry=1780424999000"
with urllib.request.urlopen(url) as resp:
    d = json.load(resp)

print(f"Symbol: {d['underlying_symbol']} | Expiry: {d['expiry_date']} | Underlying Price: {d.get('underlying_price','-')} | Strikes: {len(d['instruments'])}")
print(f"  {'Strike':>8} | {'Type':>2} | {'LTP':>8} | {'OI':>10} | {'IV':>6}")
print("  " + "-"*48)
live_ct = 0
for i in d["instruments"]:
    lp = i.get("last_price")
    if lp is not None: live_ct += 1
    print(f"  {i['strike_price']:>8} | {i['instrument_type']:>2} | {str(lp or '-'):>8} | {str(i.get('oi') or '-'):>10} | {str(i.get('iv') or '-'):>6}")
print(f"\nStrikes with live prices: {live_ct}/{len(d['instruments'])}")
