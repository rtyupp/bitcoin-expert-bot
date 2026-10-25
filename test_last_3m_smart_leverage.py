"""
اختبار استراتيجية الـ 4H المعجزة برافعة ذكية محسوبة (Smart Leverage 4H Swing)
الفترة: آخر 3 أشهر بالضبط (من 2026-07-24 إلى 2026-10-24)
رأس المال المبدئي: 40.0 دولار فقط
الهدف: اختبار القوة والعوائد الحقيقية وتجنب تجميد الحساب أو تصفيره
"""
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, "C:/Users/lsyry/projects/bitcoin-expert-bot")
import optimize as O
import baseline_updated as B

# تحميل بيانات السوق
M = O.load_market("C:/Users/lsyry/projects/bitcoin-expert-bot")

START = pd.Timestamp("2026-07-24 00:00:00", tz="UTC")
END = pd.Timestamp("2026-10-24 20:00:00", tz="UTC")

# استخدام إعدادات BEST المثبتة بحثياً في المستودع
sigs = O.make_signals(M, B.BEST)

# تشغيل المحاكاة على آخر 3 أشهر برأس مال 40$ ومخاطرة رافعة ذكية (10% مخاطرة لكل صفقة بدلاً من 1%)
# لاستهداف ربح 50% إلى 80% في الصفقات الرابحة الكبرى
balance = 40.0
initial_balance = 40.0

start_ns = np.int64(START.value)
end_ns = np.int64(END.value)

# تشغيل المحاكاة الأساسية
res = O.simulate(M, sigs, START, END, B.BEST, funding_rates=B.FUND)
trades = res['trades']

print("═════════════════════════════════════════════════════════════════════════")
print("👑 نتائج اختبار آخر 3 شهور (2026-07-24 → 2026-10-24) على 40$")
print("═════════════════════════════════════════════════════════════════════════")

custom_trades = []
for t in trades:
    # تخصيص 10% مخاطرة من الرصيد الحالي
    risk_usd = balance * 0.10
    
    # حساب الربح/الخسارة بناءً على مضاعف R
    pnl_usd = risk_usd * t.r
    balance += pnl_usd
    
    entry_date = pd.Timestamp(t.entry_t, unit="ns", tz="UTC").strftime("%Y-%m-%d %H:%M")
    exit_date = pd.Timestamp(t.exit_t, unit="ns", tz="UTC").strftime("%Y-%m-%d %H:%M")
    
    custom_trades.append({
        "spec": t.spec,
        "entry_date": entry_date,
        "exit_date": exit_date,
        "entry": t.entry,
        "exit": t.exit,
        "r": t.r,
        "pnl_usd": pnl_usd,
        "balance": balance,
        "reason": t.reason
    })

tdf = pd.DataFrame(custom_trades)

if not tdf.empty:
    wins = tdf[tdf["pnl_usd"] > 0]
    losses = tdf[tdf["pnl_usd"] < 0]
    pf = wins["pnl_usd"].sum() / abs(losses["pnl_usd"].sum()) if len(losses) else 999
    
    print(f"• الرصيد الابتدائي:  ${initial_balance:.2f}")
    print(f"• الرصيد النهائي:    ${balance:,.2f}  ──> صافي العائد: {((balance - initial_balance)/initial_balance)*100:+.1f}% 🚀")
    print(f"• إجمالي الصفقات:    {len(tdf)} صفقات")
    print(f"• الصفقات الرابحة:   {len(wins)} | الصفقات الخاسرة: {len(losses)}")
    print(f"• معامل الربح (PF):  {pf:.2f}")
    print("\n📋 تفاصيل الصفقات المنفذة في آخر 3 أشهر:")
    for idx, r in tdf.iterrows():
        icon = "✅ ربح خارق" if r["pnl_usd"] > 0 else "❌ وقف خسارة"
        print(f"  {icon} [{r['spec']}] من {r['entry_date']} إلى {r['exit_date']}")
        print(f"     دخول: ${r['entry']:,.1f} ──> خروج: ${r['exit']:,.1f} ({r['reason']})")
        print(f"     العائد: {r['r']:+.2f}R | الربح/الخسارة: {r['pnl_usd']:+7.2f}$ | رصيد الحساب: ${r['balance']:.2f}\n")
else:
    print("لا توجد صفقات منفذة في هذه الفترة.")

print("═════════════════════════════════════════════════════════════════════════")
