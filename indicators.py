"""
indicators.py
18 項指標評分引擎 + 大跌預測 + 買賣建議
加權邏輯仿照截圖：核心1.5x / 標準1.0x / 輔助0.7x
"""

import os, json
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

def _load(name):
    path = os.path.join(DATA_DIR, f"{name}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


# ─── 指標定義 ────────────────────────────────────────────────────────────────────
# weight_class: core(1.5x), standard(1.0x), auxiliary(0.7x)
# max_score: 該指標最多扣幾分

INDICATOR_META = [
    {"id": 1,  "name": "外資期貨淨未平倉",  "class": "core",      "max": 3, "category": "外資/融資/技術面/三大法人"},
    {"id": 2,  "name": "外資現貨買賣超",   "class": "core",      "max": 3, "category": "外資/融資/技術面/三大法人"},
    {"id": 3,  "name": "台幣+DXY壓力",    "class": "standard",  "max": 2, "category": "期貨/匯率/VIX/量能/乖離"},
    {"id": 4,  "name": "融資餘額日變化",   "class": "core",      "max": 3, "category": "外資/融資/技術面/三大法人"},
    {"id": 5,  "name": "ADL漲跌家數",     "class": "standard",  "max": 2, "category": "期貨/匯率/VIX/量能/乖離"},
    {"id": 6,  "name": "國際技術面(MA20)", "class": "core",      "max": 3, "category": "外資/融資/技術面/三大法人"},
    {"id": 7,  "name": "台指期動能",       "class": "standard",  "max": 2, "category": "期貨/匯率/VIX/量能/乖離"},
    {"id": 8,  "name": "TSM+SOX",        "class": "standard",  "max": 2, "category": "期貨/匯率/VIX/量能/乖離"},
    {"id": 9,  "name": "VIX恐慌指數",     "class": "standard",  "max": 2, "category": "期貨/匯率/VIX/量能/乖離"},
    {"id": 10, "name": "美債10Y",         "class": "standard",  "max": 2, "category": "期貨/匯率/VIX/量能/乖離"},
    {"id": 11, "name": "大盤P/E",         "class": "auxiliary", "max": 1, "category": "基本面背景(P/E)"},
    {"id": 12, "name": "銅價",            "class": "auxiliary", "max": 1, "category": "基本面背景(P/E)"},
    {"id": 13, "name": "三大法人合計",    "class": "core",      "max": 3, "category": "外資/融資/技術面/三大法人"},
    {"id": 14, "name": "大盤量比",        "class": "standard",  "max": 2, "category": "期貨/匯率/VIX/量能/乖離"},
    {"id": 15, "name": "MA60乖離率",      "class": "standard",  "max": 2, "category": "期貨/匯率/VIX/量能/乖離"},
    {"id": 16, "name": "HY信用利差",      "class": "standard",  "max": 2, "category": "期貨/匯率/VIX/量能/乖離"},
    {"id": 17, "name": "權買vs加權",      "class": "standard",  "max": 2, "category": "期貨/匯率/VIX/量能/乖離"},
    {"id": 18, "name": "TDCC大戶持股",   "class": "auxiliary", "max": 1, "category": "基本面背景(P/E)"},
]

WEIGHT = {"core": 1.5, "standard": 1.0, "auxiliary": 0.7}


# ─── 各指標評分邏輯 ──────────────────────────────────────────────────────────────

def score_indicator(idx: int, data: dict) -> dict:
    """
    回傳 {score, max_score, weighted_score, status, detail, severity}
    score = 0(安全) ~ max(危險)
    status: safe / warn / danger
    severity: normal / SEVERE
    """

    def _result(score, status, detail, severity="normal"):
        meta = INDICATOR_META[idx - 1]
        w = WEIGHT[meta["class"]]
        raw_max = meta["max"]
        # weighted_score: 按比例換算到加權分數空間
        ws = round(score * w, 2)
        return {
            "id": idx, "name": meta["name"], "class": meta["class"],
            "score": score, "max_score": raw_max,
            "weighted_score": ws, "weight": w,
            "status": status, "detail": detail, "severity": severity,
        }

    # 1. 外資期貨淨未平倉
    if idx == 1:
        d = data.get("foreign_futures", {})
        net = d.get("net_position", 0)
        if net < -30000:
            return _result(3, "danger", f"極度空頭 {net:+,} 口", "SEVERE")
        elif net < -15000:
            return _result(2, "warn", f"偏空 {net:+,} 口")
        elif net < -5000:
            return _result(1, "warn", f"略偏空 {net:+,} 口")
        else:
            return _result(0, "safe", f"多方 {net:+,} 口")

    # 2. 外資現貨買賣超
    elif idx == 2:
        d = data.get("foreign_spot", {})
        net = d.get("net", 0)
        if net < -500:  # 億
            return _result(3, "danger", f"大賣超 {net/1e8:+.1f}億", "SEVERE")
        elif net < -200:
            return _result(2, "warn", f"賣超 {net/1e8:+.1f}億")
        elif net < 0:
            return _result(1, "warn", f"小幅賣超 {net/1e8:+.1f}億")
        else:
            return _result(0, "safe", f"買超 +{net/1e8:.1f}億")

    # 3. 台幣+DXY壓力
    elif idx == 3:
        d = data.get("twd_dxy", {})
        dxy_chg = d.get("dxy_5d_change", 0) or 0
        twd_chg = d.get("usd_twd_5d_change", 0) or 0
        dxy = d.get("dxy", 100) or 100
        score = 0
        detail_parts = []
        if dxy > 106:
            score += 1
            detail_parts.append(f"DXY={dxy:.1f}(高壓)")
        if dxy_chg > 1.5:
            score += 1
            detail_parts.append(f"DXY 5日+{dxy_chg:.1f}%")
        if twd_chg > 1.0:
            score += 1
            detail_parts.append(f"台幣貶值{twd_chg:.1f}%")
        score = min(score, 2)
        status = "danger" if score >= 2 else ("warn" if score == 1 else "safe")
        detail = " | ".join(detail_parts) if detail_parts else f"DXY={dxy:.1f} 台幣穩定"
        return _result(score, status, detail)

    # 4. 融資餘額日變化
    elif idx == 4:
        d = data.get("margin", {})
        chg = d.get("change_pct", 0) or 0
        bal = d.get("balance", 0)
        if chg > 3.0:
            return _result(3, "danger", f"融資急增 +{chg:.1f}% (過熱)", "SEVERE")
        elif chg > 1.5:
            return _result(2, "warn", f"融資增加 +{chg:.1f}%")
        elif chg > 0.5:
            return _result(1, "warn", f"融資小增 +{chg:.1f}%")
        else:
            return _result(0, "safe", f"融資 {chg:+.1f}% (健康)")

    # 5. ADL 漲跌家數
    elif idx == 5:
        d = data.get("adl", {})
        up = d.get("up", 0)
        dn = d.get("down", 0)
        ratio = d.get("ad_ratio", 0.5)
        total = up + dn
        detail = f"漲:{up} 跌:{dn} (A/D={ratio:.2f})" if total else "數據待更新"
        if ratio < 0.25:
            return _result(2, "danger", detail)
        elif ratio < 0.40:
            return _result(1, "warn", detail)
        else:
            return _result(0, "safe", detail)

    # 6. 國際技術面 MA20
    elif idx == 6:
        d = data.get("intl_tech", {})
        above = d.get("above_count", 0)
        total = d.get("total", 6)
        ratio = above / total if total else 0.5
        detail = f"{above}/{total} 市場站上MA20"
        if ratio < 0.33:
            return _result(3, "danger", detail, "SEVERE")
        elif ratio < 0.5:
            return _result(2, "warn", detail)
        elif ratio < 0.67:
            return _result(1, "warn", detail)
        else:
            return _result(0, "safe", detail)

    # 7. 台指期動能
    elif idx == 7:
        d = data.get("twii_momentum", {})
        price = d.get("price", 0)
        ma20 = d.get("ma20", 0)
        ma60 = d.get("ma60")
        chg = d.get("chg_pct", 0)
        score = 0
        detail_parts = [f"加權{price:.0f}"]
        if ma20 and price < ma20:
            score += 1
            detail_parts.append(f"跌破MA20")
        if ma60 and price < ma60:
            score += 1
            detail_parts.append(f"跌破MA60")
        score = min(score, 2)
        status = "danger" if score == 2 else ("warn" if score == 1 else "safe")
        detail_parts.append(f"日內{chg:+.2f}%")
        return _result(score, status, " | ".join(detail_parts))

    # 8. TSM + SOX
    elif idx == 8:
        d = data.get("tsm_sox", {})
        tsm_chg = d.get("tsm_chg", 0) or 0
        sox_chg = d.get("sox_chg", 0) or 0
        score = 0
        detail_parts = []
        if tsm_chg < -3:
            score += 1
            detail_parts.append(f"TSM {tsm_chg:+.2f}%")
        if sox_chg < -3:
            score += 1
            detail_parts.append(f"SOX {sox_chg:+.2f}%")
        score = min(score, 2)
        status = "danger" if score == 2 else ("warn" if score == 1 else "safe")
        if not detail_parts:
            detail_parts = [f"TSM {tsm_chg:+.2f}% | SOX {sox_chg:+.2f}%"]
        return _result(score, status, " | ".join(detail_parts))

    # 9. VIX
    elif idx == 9:
        d = data.get("vix", {})
        vix = d.get("vix", 16)
        level = d.get("level", "正常")
        detail = f"VIX {vix:.2f} ({level})"
        if vix > 30:
            return _result(2, "danger", detail, "SEVERE")
        elif vix > 20:
            return _result(1, "warn", detail)
        else:
            return _result(0, "safe", detail)

    # 10. 美債 10Y
    elif idx == 10:
        d = data.get("us10y", {})
        y = d.get("yield", 4.0)
        chg = d.get("chg", 0)
        level = d.get("level", "正常")
        detail = f"10Y {y:.2f}% ({level})"
        if y > 5.0 or (chg > 0.15):
            return _result(2, "danger", detail)
        elif y > 4.5:
            return _result(1, "warn", detail)
        else:
            return _result(0, "safe", detail)

    # 11. 大盤 P/E
    elif idx == 11:
        d = data.get("pe", {})
        pe = d.get("pe", 18)
        level = d.get("level", "合理")
        detail = f"大盤P/E {pe:.1f} ({level})"
        if pe > 28:
            return _result(1, "danger", detail)
        elif pe > 22:
            return _result(1, "warn", detail)
        else:
            return _result(0, "safe", detail)

    # 12. 銅價
    elif idx == 12:
        d = data.get("copper", {})
        chg = d.get("chg_pct", 0)
        above_ma20 = d.get("above_ma20", True)
        price = d.get("price", 4.0)
        detail = f"銅價 ${price:.2f} | {chg:+.2f}%"
        if chg < -3 and not above_ma20:
            return _result(1, "danger", detail)
        elif chg < -2:
            return _result(1, "warn", detail)
        else:
            return _result(0, "safe", detail)

    # 13. 三大法人合計
    elif idx == 13:
        d = data.get("institutional", {})
        net = d.get("net", 0)
        if net < -500:  # 億
            return _result(3, "danger", f"三大法人賣超 {net/1e8:.1f}億", "SEVERE")
        elif net < -200:
            return _result(2, "warn", f"三大法人賣超 {net/1e8:.1f}億")
        elif net < 0:
            return _result(1, "warn", f"三大法人略賣 {net/1e8:.1f}億")
        else:
            return _result(0, "safe", f"三大法人買超 +{net/1e8:.1f}億")

    # 14. 大盤量比
    elif idx == 14:
        d = data.get("volume_ratio", {})
        ratio = d.get("ratio", 1.0)
        level = d.get("level", "正常")
        detail = f"量比 {ratio:.2f} ({level})"
        # 縮量下跌才危險; 爆量要看方向
        if ratio < 0.6:
            return _result(1, "warn", f"極度縮量 {detail}")
        elif ratio > 2.5:
            return _result(1, "warn", f"爆量異常 {detail}")
        else:
            return _result(0, "safe", detail)

    # 15. MA60 乖離率
    elif idx == 15:
        d = data.get("ma60_bias", {})
        bias = d.get("bias_pct", 0)
        level = d.get("level", "正常")
        detail = f"MA60乖離 {bias:+.2f}% ({level})"
        if bias > 15:
            return _result(2, "danger", detail)
        elif bias > 10:
            return _result(1, "warn", detail)
        else:
            return _result(0, "safe", detail)

    # 16. HY 信用利差
    elif idx == 16:
        d = data.get("hy_spread", {})
        spread = d.get("spread", 3.5)
        level = d.get("level", "正常")
        detail = f"HY利差 {spread:.2f}% ({level})"
        if spread > 6.0:
            return _result(2, "danger", detail, "SEVERE")
        elif spread > 4.5:
            return _result(1, "warn", detail)
        else:
            return _result(0, "safe", detail)

    # 17. 權買 vs 加權 (P/C ratio)
    elif idx == 17:
        d = data.get("options_ratio", {})
        pc = d.get("pc_ratio", 1.0)
        sentiment = d.get("sentiment", "中性")
        detail = f"P/C比 {pc:.2f} | {sentiment}"
        if pc > 1.3:
            return _result(2, "danger", detail)
        elif pc > 1.1:
            return _result(1, "warn", detail)
        else:
            return _result(0, "safe", detail)

    # 18. TDCC 大戶持股
    elif idx == 18:
        d = data.get("tdcc", {})
        ratio = d.get("ratio", 70)
        chg = d.get("change", 0)
        detail = f"大戶持股 {ratio:.1f}% | 7日{chg:+.2f}pp"
        if chg < -1.0:
            return _result(1, "danger", detail)
        elif chg < -0.3:
            return _result(1, "warn", detail)
        else:
            return _result(0, "safe", detail)

    return _result(0, "safe", "N/A")


# ─── 綜合評分 ────────────────────────────────────────────────────────────────────

def compute_all_scores(data: dict) -> dict:
    """
    計算全部 18 項評分，回傳完整報告
    """
    indicator_scores = []
    total_weighted = 0.0
    severe_count = 0
    severe_list = []

    for i in range(1, 19):
        s = score_indicator(i, data)
        indicator_scores.append(s)
        total_weighted += s["weighted_score"]
        if s["severity"] == "SEVERE":
            severe_count += 1
            severe_list.append(s["name"])

    total_weighted = round(total_weighted, 1)

    # 分級判斷
    # 安全 0-5, 警戒 6-12, 危險 13-22
    # 另外 SEVERE 數量升級
    if total_weighted <= 5 and severe_count == 0:
        signal = "safe"
        signal_text = "🟢 安全觀望"
        action = "維持正常持股比例"
        crash_prob = min(int(total_weighted * 5), 20)
    elif total_weighted <= 8 and severe_count == 0:
        signal = "yellow_light"
        signal_text = "🟡 黃燈注意"
        action = "可減碼 10-20%，加強停損"
        crash_prob = int(total_weighted * 4 + 10)
    elif total_weighted <= 12 or (total_weighted <= 10 and severe_count >= 1):
        signal = "yellow_deep"
        signal_text = "🟠 黃燈深度・階梯減碼"
        action = "減碼 30-40%（25% 0050 + 15% 現金）"
        crash_prob = int(total_weighted * 3.5 + 15)
    elif severe_count >= 2 or total_weighted > 12:
        signal = "red"
        signal_text = "🔴 紅燈強訊號・大舉保守"
        action = "大幅減碼 50%+（25% 0050 + 50% 現金 + 公債）"
        crash_prob = min(int(total_weighted * 4 + 30), 90)
    else:
        signal = "orange"
        signal_text = "🟠 橙燈警示"
        action = "減碼 25-35%，嚴格停損"
        crash_prob = int(total_weighted * 3 + 20)

    crash_prob = max(5, min(crash_prob, 90))

    # 訊號強度
    if severe_count >= 2 or total_weighted > 14:
        signal_strength = "STRONG"
    elif severe_count >= 1 or total_weighted > 9:
        signal_strength = "MEDIUM"
    else:
        signal_strength = "WEAK"

    # 核心層 / 標準層分數
    core_ws = sum(s["weighted_score"] for s in indicator_scores if s["class"] == "core")
    std_ws = sum(s["weighted_score"] for s in indicator_scores if s["class"] == "standard")
    core_max = sum(m["max"] * WEIGHT["core"] for m in INDICATOR_META if m["class"] == "core")
    std_max = sum(m["max"] * WEIGHT["standard"] for m in INDICATOR_META if m["class"] == "standard")

    # 過去3日動能（從歷史快取取）
    hist = _load("score_history") or []
    hist_scores = [h["total_weighted"] for h in hist[-3:]] + [total_weighted]
    momentum_label = "惡化" if (len(hist_scores) >= 2 and hist_scores[-1] > hist_scores[-2]) else \
                     "改善" if (len(hist_scores) >= 2 and hist_scores[-1] < hist_scores[-2]) else "持平"

    return {
        "timestamp": datetime.now().isoformat(),
        "signal": signal,
        "signal_text": signal_text,
        "signal_strength": signal_strength,
        "action": action,
        "crash_prob": crash_prob,
        "total_weighted": total_weighted,
        "severe_count": severe_count,
        "severe_list": severe_list,
        "core_score": round(core_ws, 1),
        "core_max": round(core_max, 1),
        "std_score": round(std_ws, 1),
        "std_max": round(std_max, 1),
        "momentum_label": momentum_label,
        "momentum_history": hist_scores[-4:],
        "indicators": indicator_scores,
    }


# ─── 買賣建議引擎 ────────────────────────────────────────────────────────────────

TW_NAMES = {
    "2330.TW": "台積電", "2303.TW": "聯電", "2308.TW": "台達電",
    "2454.TW": "聯發科", "3711.TW": "日月光投控",
    "2317.TW": "鴻海", "2354.TW": "鴻準", "2382.TW": "廣達", "3034.TW": "聯詠",
    "2882.TW": "國泰金", "2884.TW": "玉山金", "2886.TW": "兆豐金", "2891.TW": "中信金",
    "2207.TW": "和泰車", "2105.TW": "正新", "1301.TW": "台塑", "1303.TW": "南亞",
    "0050.TW": "元大台灣50", "0056.TW": "元大高股息",
    "00878.TW": "國泰永續高股息", "00929.TW": "復華台灣科技優息",
}

TW_SECTORS = {
    "2330.TW": "半導體", "2303.TW": "半導體", "2308.TW": "電子製造",
    "2454.TW": "半導體", "3711.TW": "半導體",
    "2317.TW": "電子製造", "2354.TW": "電子製造", "2382.TW": "電子製造", "3034.TW": "IC設計",
    "2882.TW": "金融", "2884.TW": "金融", "2886.TW": "金融", "2891.TW": "金融",
    "2207.TW": "傳產", "2105.TW": "傳產", "1301.TW": "石化", "1303.TW": "石化",
    "0050.TW": "ETF", "0056.TW": "ETF", "00878.TW": "ETF", "00929.TW": "ETF",
}

US_NAMES = {
    "NVDA": "輝達", "AAPL": "蘋果", "MSFT": "微軟", "META": "Meta", "GOOGL": "Google",
    "AMD": "AMD", "INTC": "英特爾", "AVGO": "博通", "QCOM": "高通", "MU": "美光",
    "AMZN": "亞馬遜", "CRM": "Salesforce", "PLTR": "Palantir", "SNOW": "Snowflake",
    "SPY": "S&P500 ETF", "QQQ": "NASDAQ ETF", "SOXX": "半導體ETF",
    "SMH": "半導體ETF(VanEck)", "XLK": "科技ETF", "VT": "全球股票ETF",
    "GLD": "黃金ETF", "TLT": "長債ETF", "VYM": "高息ETF", "XLV": "醫療ETF",
    "MSTR": "MicroStrategy(BTC代理)", "COIN": "Coinbase", "IBIT": "比特幣ETF",
}


def _stock_buy_score(tech: dict) -> float:
    """技術面買入評分 0-100"""
    score = 0
    if tech.get("above_ma20"): score += 20
    if tech.get("above_ma5"):  score += 10
    if tech.get("above_ma60"): score += 15
    rsi = tech.get("rsi", 50)
    if 40 < rsi < 65:  score += 20  # 健康RSI
    elif rsi < 35:     score += 10  # 超賣反彈機會
    if tech.get("macd_golden_cross"): score += 20
    vol_ratio = tech.get("vol_ratio", 1)
    if 1.2 < vol_ratio < 2.5: score += 10  # 量增
    ret5 = tech.get("5d_return", 0)
    ret20 = tech.get("20d_return", 0)
    if ret5 > 0 and ret20 > 0: score += 5
    return min(score, 100)


def _stock_sell_score(tech: dict) -> float:
    """技術面賣出風險評分 0-100"""
    score = 0
    if not tech.get("above_ma20"): score += 20
    if not tech.get("above_ma5"):  score += 10
    if not tech.get("above_ma60"): score += 15
    rsi = tech.get("rsi", 50)
    if rsi > 75: score += 25  # 超買
    elif rsi > 70: score += 15
    bias_from_ma20 = (tech.get("price", 0) - tech.get("ma20", 1)) / tech.get("ma20", 1) * 100 if tech.get("ma20") else 0
    if bias_from_ma20 > 15: score += 15  # 乖離過大
    ret5 = tech.get("5d_return", 0)
    if ret5 < -3: score += 15
    return min(score, 100)


def generate_crypto_signals(crypto_data: dict) -> list:
    """根據加密貨幣技術面產出買賣訊號"""
    signals = []
    for name, d in crypto_data.items():
        if name == "fear_greed" or not isinstance(d, dict):
            continue
        rsi = d.get("rsi", 50)
        trend = d.get("trend", "整理區間")
        chg_7d = d.get("chg_7d", 0)
        bias = d.get("bias_ma20", 0)
        above_ma20 = d.get("above_ma20", False)
        above_ma50 = d.get("above_ma50", True)

        # 買進條件：站上 MA20、RSI 健康、趨勢向上
        if above_ma20 and rsi < 70 and rsi > 35 and trend == "上升趨勢":
            action = "可買進 / 持有"
            action_class = "buy"
        elif rsi < 30 and chg_7d < -15:
            action = "超賣反彈機會"
            action_class = "buy"
        elif rsi > 75 or bias > 20:
            action = "超買注意 / 減碼"
            action_class = "sell"
        elif not above_ma20 and trend == "下降趨勢":
            action = "觀望 / 不追"
            action_class = "sell"
        else:
            action = "區間整理 / 觀望"
            action_class = "neutral"

        signals.append({
            "name": name,
            "ticker": d.get("ticker", ""),
            "price": d.get("price"),
            "chg_1d": d.get("chg_1d"),
            "chg_7d": chg_7d,
            "chg_30d": d.get("chg_30d"),
            "rsi": rsi,
            "rsi_label": d.get("rsi_label", ""),
            "trend": trend,
            "bias_ma20": bias,
            "above_ma20": above_ma20,
            "action": action,
            "action_class": action_class,
            "history": d.get("history", []),
            "history_dates": d.get("history_dates", []),
        })
    return signals


def generate_recommendations(all_scores: dict, tech_data: dict, market_signal: str, crypto_data: dict = None) -> dict:
    """生成買賣建議"""
    buy_tw = []
    sell_tw = []
    buy_us = []
    sell_us = []
    sector_rotation = []

    is_dangerous = market_signal in ("red", "orange", "yellow_deep")
    is_safe = market_signal == "safe"

    # ── 台股個股 ──
    for ticker, name in TW_NAMES.items():
        if ticker not in tech_data:
            continue
        t = tech_data[ticker]
        buy_s = _stock_buy_score(t)
        sell_s = _stock_sell_score(t)
        sector = TW_SECTORS.get(ticker, "其他")

        if is_dangerous:
            # 危險期：只推 ETF 防禦
            if ticker in ("0050.TW", "0056.TW", "00878.TW") and sell_s < 40:
                buy_tw.append({
                    "ticker": ticker, "name": name, "sector": sector,
                    "price": t.get("price"), "rsi": t.get("rsi"),
                    "buy_score": buy_s, "reason": "大盤危險期，防禦型ETF",
                    "action": "分批布局",
                })
        else:
            if buy_s >= 60 and sell_s < 35:
                buy_tw.append({
                    "ticker": ticker, "name": name, "sector": sector,
                    "price": t.get("price"), "rsi": t.get("rsi"),
                    "buy_score": buy_s, "reason": _buy_reason(t),
                    "action": "可買進",
                    "history": t.get("history", []),
                    "history_dates": t.get("history_dates", []),
                    "ret5d": t.get("5d_return"), "ret20d": t.get("20d_return"), "ret60d": t.get("60d_return"),
                })

        if sell_s >= 65:
            sell_tw.append({
                "ticker": ticker, "name": name, "sector": sector,
                "price": t.get("price"), "rsi": t.get("rsi"),
                "sell_score": sell_s, "reason": _sell_reason(t),
                "action": "建議減碼" if sell_s < 80 else "建議出場",
                "history": t.get("history", []),
                "history_dates": t.get("history_dates", []),
                "ret5d": t.get("5d_return"), "ret20d": t.get("20d_return"), "ret60d": t.get("60d_return"),
            })

    # ── 美股個股 ──
    for ticker, name in US_NAMES.items():
        if ticker not in tech_data:
            continue
        t = tech_data[ticker]
        buy_s = _stock_buy_score(t)
        sell_s = _stock_sell_score(t)

        if is_dangerous:
            if ticker in ("GLD", "TLT", "VYM", "SPY") and sell_s < 40:
                buy_us.append({
                    "ticker": ticker, "name": name,
                    "price": t.get("price"), "rsi": t.get("rsi"),
                    "buy_score": buy_s, "reason": "大盤危險，避險資產",
                    "action": "可買進",
                })
        else:
            if buy_s >= 65 and sell_s < 30:
                buy_us.append({
                    "ticker": ticker, "name": name,
                    "price": t.get("price"), "rsi": t.get("rsi"),
                    "buy_score": buy_s, "reason": _buy_reason(t),
                    "action": "可買進",
                    "history": t.get("history", []),
                    "history_dates": t.get("history_dates", []),
                    "ret5d": t.get("5d_return"), "ret20d": t.get("20d_return"), "ret60d": t.get("60d_return"),
                })

        if sell_s >= 65:
            sell_us.append({
                "ticker": ticker, "name": name,
                "price": t.get("price"), "rsi": t.get("rsi"),
                "sell_score": sell_s, "reason": _sell_reason(t),
                "action": "建議減碼" if sell_s < 80 else "建議出場",
                "history": t.get("history", []),
                "history_dates": t.get("history_dates", []),
                "ret5d": t.get("5d_return"), "ret20d": t.get("20d_return"), "ret60d": t.get("60d_return"),
            })

    # ── 類股輪動 ──
    sector_scores = {}
    sector_tickers = {
        "半導體": ["2330.TW", "2454.TW", "NVDA", "AMD", "SOXX"],
        "AI/科技": ["MSFT", "GOOGL", "META", "PLTR"],
        "金融": ["2882.TW", "2884.TW"],
        "防禦/黃金": ["GLD", "TLT", "XLV"],
        "傳產/能源": ["1301.TW", "1303.TW"],
    }
    for sector, tickers in sector_tickers.items():
        scores = []
        for tk in tickers:
            if tk in tech_data:
                scores.append(_stock_buy_score(tech_data[tk]))
        if scores:
            avg = sum(scores) / len(scores)
            sector_scores[sector] = round(avg, 1)

    sorted_sectors = sorted(sector_scores.items(), key=lambda x: x[1], reverse=True)
    for rank, (sector, score) in enumerate(sorted_sectors):
        trend = "強勢" if score >= 65 else ("中性" if score >= 45 else "弱勢")
        sector_rotation.append({
            "rank": rank + 1, "sector": sector,
            "score": score, "trend": trend,
            "suggestion": "加碼" if (score >= 65 and not is_dangerous) else
                          ("觀望" if score >= 45 else "減碼"),
        })

    # 排序
    buy_tw.sort(key=lambda x: x["buy_score"], reverse=True)
    sell_tw.sort(key=lambda x: x["sell_score"], reverse=True)
    buy_us.sort(key=lambda x: x["buy_score"], reverse=True)
    sell_us.sort(key=lambda x: x["sell_score"], reverse=True)

    # 加密貨幣訊號
    crypto_signals = generate_crypto_signals(crypto_data or {})
    fear_greed = (crypto_data or {}).get("fear_greed", {"score": 50, "label": "中性"})

    return {
        "buy_tw": buy_tw[:8],
        "sell_tw": sell_tw[:8],
        "buy_us": buy_us[:8],
        "sell_us": sell_us[:8],
        "sector_rotation": sector_rotation,
        "crypto_signals": crypto_signals,
        "fear_greed": fear_greed,
        "market_signal": market_signal,
        "timestamp": datetime.now().isoformat(),
    }


def _buy_reason(t: dict) -> str:
    """多維度買進分析，回傳結構化原因字串"""
    lines = []
    rsi = t.get("rsi", 50)
    vol = t.get("vol_ratio", 1)
    ret5  = t.get("5d_return", 0)
    ret20 = t.get("20d_return", 0)
    ret60 = t.get("60d_return", 0)
    ma20  = t.get("ma20", 0)
    ma60  = t.get("ma60")
    price = t.get("price", 0)
    macd_cross = t.get("macd_golden_cross", False)
    macd_val   = t.get("macd_value", 0)
    bias_ma20  = (price - ma20) / ma20 * 100 if ma20 else 0

    # 📐 趨勢分析
    trend_parts = []
    if t.get("above_ma20") and t.get("above_ma60"):
        trend_parts.append("多頭排列（站上MA20/MA60）")
    elif t.get("above_ma20"):
        trend_parts.append("站上MA20，短期偏多")
    if ret20 > 5:
        trend_parts.append(f"20日漲幅+{ret20:.1f}%，趨勢強勁")
    if ret60 > 10:
        trend_parts.append(f"60日漲幅+{ret60:.1f}%，中期動能佳")
    if trend_parts:
        lines.append("📐 趨勢：" + "；".join(trend_parts))

    # ⚡ 動能訊號
    momentum_parts = []
    if macd_cross:
        momentum_parts.append("MACD剛黃金交叉（短線買進訊號）")
    elif macd_val > 0:
        momentum_parts.append("MACD在零軸上方（多頭動能持續）")
    if vol > 1.8:
        momentum_parts.append(f"成交量暴增{vol:.1f}x（主力進場跡象）")
    elif vol > 1.3:
        momentum_parts.append(f"量比{vol:.1f}x，溫和放量")
    if ret5 > 3:
        momentum_parts.append(f"近5日+{ret5:.1f}%，短線強勢")
    if momentum_parts:
        lines.append("⚡ 動能：" + "；".join(momentum_parts))

    # 📊 RSI 評估
    if rsi < 35:
        lines.append(f"📊 RSI={rsi:.0f}，技術面超賣，存在反彈機會")
    elif 40 <= rsi <= 60:
        lines.append(f"📊 RSI={rsi:.0f}，健康區間，未過熱")
    elif rsi < 70:
        lines.append(f"📊 RSI={rsi:.0f}，偏強但尚未超買")

    # 📏 乖離率
    if -5 < bias_ma20 < 8:
        lines.append(f"📏 MA20乖離{bias_ma20:+.1f}%，位置合理")
    elif bias_ma20 < -8:
        lines.append(f"📏 MA20乖離{bias_ma20:+.1f}%，逢低布局機會")

    return "\n".join(lines) if lines else "技術面多項指標偏多"


def _sell_reason(t: dict) -> str:
    """多維度賣出分析，回傳結構化原因字串"""
    lines = []
    rsi = t.get("rsi", 50)
    vol = t.get("vol_ratio", 1)
    ret5  = t.get("5d_return", 0)
    ret20 = t.get("20d_return", 0)
    ma20  = t.get("ma20", 0)
    ma60  = t.get("ma60")
    price = t.get("price", 0)
    macd_val = t.get("macd_value", 0)
    macd_sig = t.get("macd_signal", 0)
    bias_ma20 = (price - ma20) / ma20 * 100 if ma20 else 0

    # 📐 趨勢破壞
    trend_parts = []
    if not t.get("above_ma20") and not t.get("above_ma60"):
        trend_parts.append("空頭排列（跌破MA20與MA60）")
    elif not t.get("above_ma20"):
        trend_parts.append("跌破MA20，短期轉弱")
    elif not t.get("above_ma60"):
        trend_parts.append("跌破MA60，中期趨勢轉空")
    if ret20 < -5:
        trend_parts.append(f"20日跌幅{ret20:.1f}%，下行趨勢明確")
    if trend_parts:
        lines.append("📐 趨勢：" + "；".join(trend_parts))

    # ⚠️ 超買警示
    warning_parts = []
    if rsi > 78:
        warning_parts.append(f"RSI={rsi:.0f}，嚴重超買，歷史高位易回調")
    elif rsi > 70:
        warning_parts.append(f"RSI={rsi:.0f}，進入超買區間")
    if bias_ma20 > 18:
        warning_parts.append(f"MA20乖離+{bias_ma20:.1f}%，過熱風險高")
    elif bias_ma20 > 12:
        warning_parts.append(f"MA20乖離+{bias_ma20:.1f}%，短線偏高")
    if warning_parts:
        lines.append("⚠️ 超買：" + "；".join(warning_parts))

    # ⚡ 動能轉弱
    mom_parts = []
    if macd_val < macd_sig and macd_val < 0:
        mom_parts.append("MACD死亡交叉且在零軸下（賣出訊號）")
    elif macd_val < macd_sig:
        mom_parts.append("MACD轉弱（多頭動能消退）")
    if ret5 < -3:
        mom_parts.append(f"近5日{ret5:.1f}%，短線急跌")
    if vol > 2.0 and ret5 < -2:
        mom_parts.append(f"爆量{vol:.1f}x下跌，恐有機構出貨")
    if mom_parts:
        lines.append("⚡ 動能：" + "；".join(mom_parts))

    return "\n".join(lines) if lines else "技術面多項指標轉弱"


# ─── 歷史分數紀錄 ────────────────────────────────────────────────────────────────

def save_score_history(result: dict):
    hist = _load("score_history") or []
    hist.append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_weighted": result["total_weighted"],
        "signal": result["signal"],
        "crash_prob": result["crash_prob"],
    })
    # 只保留最近 90 天
    hist = hist[-90:]
    path = os.path.join(DATA_DIR, "score_history.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False)
