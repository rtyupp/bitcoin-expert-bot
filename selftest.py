import sys
sys.path.insert(0, 'C:/Users/lsyry/projects/bitcoin-expert-bot')
import config
import capital
import strategy
import charts
import engine
import state

print('--- Self-Test Verification ---')
# 1. Config
print('Assets:', list(config.ASSETS.keys()))

# 2. Capital Connection
acc = capital.client.account_summary()
print(f"Capital Account Balance: ${acc['balance']:,.2f} | Available: ${acc['available']:,.2f}")

# 3. Live Prices & Spread
for a, cfg in config.ASSETS.items():
    p = capital.client.live_price(cfg['epic'])
    print(f"  {a}: Price {p['price']} | Spread {p['spread']}")

# 4. Fetch OHLCV & Strategy Summary
for a, cfg in config.ASSETS.items():
    df = capital.client.fetch_ohlcv(cfg['epic'], '4h', 80)
    summary = strategy.get_asset_summary(df, cfg)
    print(f"  {a} (4H): Close {summary.get('price')} | Regime {summary.get('regime')} | ATR {summary.get('atr')}")
    
    # Render chart
    img = charts.render_asset_chart(a, df, summary)
    print(f"  {a} Chart generated: {len(img):,} bytes")

# 5. Engine evaluate
st = state.load_state()
actions, logs = engine.evaluate_and_trade(st)
print(f"Engine evaluation complete. Logs count: {len(logs)}, Actions: {len(actions)}")
print('ALL SYSTEMS VERIFIED SUCCESSFULLY!')
