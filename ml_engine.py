"""محرك تعلّم آلي + كشف نظام السوق — تحقق زمني صادق (walk-forward، بلا lookahead).

المنهجية:
- ميزات فنية ~20 (عوائد متعددة الآجال، RSI، MACD، بولينجر، ATR، حجم، ADX، شموع)
- الهدف: اتجاه الإغلاق بعد 6 شموع (24 ساعة على فريم 4h)
- تحقق زمني: 5 أقسام متتابعة (تدريب على الماضي فقط)
- 3 نماذج: Logistic / HistGradientBoosting / RandomForest → الأفضل بـ AUC
- لا تسريب مستقبلي: كل الميزات عند t تستخدم بيانات ≤ t
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HORIZON = 6  # عدد الشموع المستقبلية للهدف


def _rsi(series: pd.Series, n: int) -> pd.Series:
    d = series.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """ميزات بلا lookahead — كل صف يعتمد على شموع ≤ t."""
    c, o, h, l, v = df["close"], df["open"], df["high"], df["low"], df["volume"]
    f = pd.DataFrame(index=df.index)

    for n in (1, 3, 6, 12, 24, 48):
        f[f"ret{n}"] = c.pct_change(n)

    f["rsi14"] = _rsi(c, 14) / 100
    f["rsi2"] = _rsi(c, 2) / 100

    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    ema200 = c.ewm(span=200, adjust=False).mean()
    f["ema20_d"] = (c - ema20) / c
    f["ema50_d"] = (c - ema50) / c
    f["ema200_d"] = (c - ema200) / c
    f["ema20_50"] = (ema20 - ema50) / c

    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    sig = macd.ewm(span=9, adjust=False).mean()
    f["macd_h"] = (macd - sig) / c

    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    f["bb_pos"] = (c - mid) / sd.replace(0, np.nan)
    f["bb_width"] = (4 * sd) / mid.replace(0, np.nan)

    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    f["atr_pct"] = atr / c
    f["atr_ratio"] = atr / atr.rolling(100).mean()

    f["vol_z"] = (v - v.rolling(20).mean()) / v.rolling(20).std().replace(0, np.nan)
    f["vol_ratio"] = v / v.rolling(20).mean().replace(0, np.nan)

    # ADX
    up_move = h.diff()
    dn_move = -l.diff()
    plus_dm = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)
    tr_s = pd.Series(tr, index=df.index)
    atr_s = tr_s.rolling(14).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(14).mean() / atr_s.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(14).mean() / atr_s.replace(0, np.nan)
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    f["adx"] = dx.rolling(14).mean() / 100
    f["di_diff"] = (plus_di - minus_di) / 100

    # شكل الشمعة
    rng = (h - l).replace(0, np.nan)
    f["body"] = (c - o) / rng
    f["upper_wick"] = (h - np.maximum(c, o)) / rng
    f["lower_wick"] = (np.minimum(c, o) - l) / rng

    # موقع داخل قناة 55
    hi55, lo55 = h.rolling(55).max(), l.rolling(55).min()
    f["don_pos"] = (c - lo55) / (hi55 - lo55).replace(0, np.nan)

    # كفاءة الاتجاه (Efficiency Ratio)
    f["er"] = (c - c.shift(20)).abs() / c.diff().abs().rolling(20).sum().replace(0, np.nan)

    return f.replace([np.inf, -np.inf], np.nan)


def build_target(df: pd.DataFrame, horizon: int = HORIZON) -> pd.Series:
    """1 إذا ارتفع الإغلاق بعد horizon شمعة."""
    return (df["close"].shift(-horizon) > df["close"]).astype(int)


def dataset(df: pd.DataFrame, horizon: int = HORIZON):
    X = build_features(df)
    y = build_target(df, horizon)
    mask = X.notna().all(axis=1) & y.notna()
    X, y = X[mask], y[mask]
    # آخر horizon شمعة ليس لها هدف
    X = X.iloc[:-horizon] if horizon else X
    y = y.iloc[:-horizon] if horizon else y
    return X, y


def _models():
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    return {
        "Logistic": Pipeline([("sc", StandardScaler()), ("m", LogisticRegression(max_iter=1000, C=0.5))]),
        "HistGB": HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=120),
        "Forest": RandomForestClassifier(n_estimators=120, max_depth=6, min_samples_leaf=20, n_jobs=-1),
    }


def walk_forward(df: pd.DataFrame, horizon: int = HORIZON, splits: int = 4) -> dict:
    """تحقق زمني: تدريب على الماضي، اختبار على المستقبل. يرجع أفضل نموذج ومقاييسه."""
    from sklearn.metrics import accuracy_score, brier_score_loss, roc_auc_score

    X, y = dataset(df, horizon)
    if len(X) < 400:
        return {"ok": False, "reason": "بيانات غير كافية", "n": len(X)}

    models = _models()
    results = {}
    n = len(X)
    test_size = n // (splits + 2)

    for name in models:
        aucs, accs, briers = [], [], []
        for k in range(splits):
            tr_end = n - (splits - k) * test_size
            te_end = tr_end + test_size
            if tr_end < 250:
                continue
            Xtr, ytr = X.iloc[:tr_end], y.iloc[:tr_end]
            Xte, yte = X.iloc[tr_end:te_end], y.iloc[tr_end:te_end]
            if len(Xte) < 20 or ytr.nunique() < 2 or yte.nunique() < 2:
                continue
            m = models[name]
            m.fit(Xtr, ytr)
            p = m.predict_proba(Xte)[:, 1]
            aucs.append(roc_auc_score(yte, p))
            accs.append(accuracy_score(yte, (p > 0.5).astype(int)))
            briers.append(brier_score_loss(yte, p))
        if aucs:
            results[name] = {
                "auc": round(float(np.mean(aucs)), 4),
                "acc": round(float(np.mean(accs)), 4),
                "brier": round(float(np.mean(briers)), 4),
                "folds": len(aucs),
            }

    if not results:
        return {"ok": False, "reason": "تعذّر التحقق", "n": n}

    best = max(results, key=lambda k: results[k]["auc"])
    # تدريب كل النماذج على كل البيانات ثم مزج مرجّح بـ AUC (أكثر ثباتاً من اختيار نموذج واحد)
    # الاستنتاج على أحدث صف ميزات مكتمل من df نفسها (X مقصوص بعمق الأفق = قديم)
    Xnow = build_features(df).dropna().iloc[[-1]]
    probs = {}
    for name, m in models.items():
        m.fit(X, y)
        probs[name] = float(m.predict_proba(Xnow)[:, 1][0]) if len(Xnow) else 0.5
    weights = {k: max(results[k]["auc"] - 0.5, 0.01) for k in probs if k in results}
    tw = sum(weights.values())
    prob = sum(probs[k] * weights[k] for k in weights) / tw if tw else 0.5

    return {
        "ok": True,
        "model": best,
        "prob_up": round(prob, 3),
        "model_probs": {k: round(v, 3) for k, v in probs.items()},
        "weights": {k: round(v / tw, 3) for k, v in weights.items()} if tw else {},
        "metrics": results[best],
        "all_models": results,
        "n_samples": n,
        "horizon": horizon,
        "features": list(X.columns),
    }


# ── كشف نظام السوق ────────────────────────────────────────────

def regime(df: pd.DataFrame) -> dict:
    """يصنّف السوق: اتجاه صاعد/هابط/تذبذب/تقلب عالٍ + قوة الاتجاه."""
    c = df["close"]
    h, l = df["high"], df["low"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    atr_pct = (atr / c).iloc[-1]
    atr_rank = float((atr / c).tail(200).rank(pct=True).iloc[-1])

    er = (c - c.shift(20)).abs() / c.diff().abs().rolling(20).sum().replace(0, np.nan)
    er_now = float(er.iloc[-1]) if not pd.isna(er.iloc[-1]) else 0.0

    ema200 = c.ewm(span=200, adjust=False).mean()
    slope = (ema200.iloc[-1] - ema200.iloc[-20]) / ema200.iloc[-20] if len(c) > 220 else 0.0
    above = bool(c.iloc[-1] > ema200.iloc[-1])

    if atr_rank > 0.85:
        name, note = "تقلب عالٍ", "تجنّب الدخول أو صغّر الحجم"
    elif er_now > 0.35 and above and slope > 0:
        name, note = "اتجاه صاعد", "الاستراتيجيات الاتجاهية مناسبة"
    elif er_now > 0.35 and not above and slope < 0:
        name, note = "اتجاه هابط", "الاتجاه الهابط قوي"
    else:
        name, note = "تذبذب / عرضي", "الاختراقات الكاذبة أكثر — كن حذراً"

    return {
        "name": name,
        "note": note,
        "efficiency": round(er_now, 3),
        "atr_pct": round(float(atr_pct) * 100, 2),
        "atr_rank": round(atr_rank, 3),
        "ema200_slope": round(float(slope) * 100, 2),
        "above_ema200": above,
    }
