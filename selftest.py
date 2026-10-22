"""اختبارات تحقق شاملة لنظام البيتكوين (End-to-End Self Test)."""
import os
import pandas as pd
import strategy as S
import markets
import chart
import engine
import state
import backtest

def test_system():
    print("▶ 1. اختبار تحميل البيانات من المنصة...")
    h4, d1, src = engine.load_data()
    assert len(h4) >= 260, f"شموع 4H غير كافية: {len(h4)}"
    assert len(d1) >= 260, f"شموع 1D غير كافية: {len(d1)}"
    print(f"  ✓ تم جلب {len(h4)} شمعة 4H و {len(d1)} شمعة 1D بنجاح من {src}")

    print("▶ 2. اختبار محرك الاستراتيجيات والمؤشرات...")
    st = S.market_state(h4, d1)
    assert st["price"] > 0, "سعر غير صحيح"
    assert "regime" in st, "نظام السوق مفقود"
    print(f"  ✓ حالة السوق: سعر {st['price']:,.2f} | نظام {st['regime']} | RSI2 {st['rsi2']:.1f}")

    print("▶ 3. اختبار رسم الشارت (Pillow)...")
    png = chart.render(h4, "BTC End-to-End Test", live=st["price"])
    assert len(png) > 5000, "ملف الشارت فارغ أو تالف"
    print(f"  ✓ تم بناء صورة الشارت بنجاح ({len(png):,} bytes)")

    print("▶ 4. اختبار حفظ واسترجاع الحالة (State)...")
    state.set_setting("test_key", "test_val")
    assert state.setting("test_key", None) == "test_val"
    print("  ✓ حفظ واسترجاع الحالة الذرية يعمل بنجاح")

    print("▶ 5. اختبار محاكاة الاختبار التاريخي (Backtest)...")
    h4_bt, d1_bt = backtest.load("research")
    t = backtest.simulate(h4_bt, d1_bt)
    stats = backtest.stats(t)
    assert stats["n"] > 100, f"عدد صفقات قليل: {stats['n']}"
    assert stats["pf"] > 1.3, f"عامل الربح ضعيف: {stats['pf']}"
    print(f"  ✓ نتائج الاختبار التاريخي: {stats['n']} صفقة | فوز {stats['win']}% | PF {stats['pf']} | +{stats['total_r']}R")

    print("▶ 6. اختبار دورة المحرك (Engine Tick)...")
    events = engine.tick()
    print(f"  ✓ دورة المحرك اكتملت بنجاح (الأحداث: {len(events)})")

    print("\n✅ كل الاختبارات اجتازت بنجاح تام 100%!")

if __name__ == "__main__":
    test_system()
