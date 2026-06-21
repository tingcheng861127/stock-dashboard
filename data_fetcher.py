"""
data_fetcher.py
抓取 18 項指標所需的原始數據
資料來源：yfinance (免費) / TWSE Open API (免費) / FRED API (免費需key) / TAIFEX (免費)
"""

import os, json, time, logging
from datetime import datetime, timedelta
import requests
import yfinance as yf
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")   # 申請: https://fred.stlouisfed.org/
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _save(name: str, obj):
    path = os.path.join(DATA_DIR, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, default=str)

def _load(name: str):
    path = os.path.join(DATA_DIR, f"{name}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None

def _yf_close(ticker: str, period="60d") -> pd.Series:
    try:
        df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
        return df["Close"].dropna()
    except Exception as e:
        log.warning(f"yfinance {ticker} error: {e}")
        return pd.Series(dtype=float)

def _twse_get(url: str, params=None):
    try:
        r = requests.get(url, params=params, timeout=15,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"TWSE API error {url}: {e}")
        return None


# ─── 1. 外資期貨淨未平倉 (TAIFEX) ─────────────────────────────────────────────

def fetch_foreign_futures():
    """TAIFEX 外資台指期淨未平倉口數"""
    url = "https://www.taifex.com.tw/cht/3/futContractsDateDown"
    try:
        today = datetime.now().strftime("%Y/%m/%d")
        params = {
            "queryStartDate": (datetime.now() - timedelta(days=5)).strftime("%Y/%m/%d"),
            "queryEndDate": today,
            "commodityId": "TXF",
        }
        r = requests.post(url, data=params, timeout=15,
                          headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.taifex.com.tw/"})
        lines = r.text.strip().split("\n")
        # 找最新外資數據
        for line in reversed(lines):
            if "外資" in line or "Foreign" in line.upper():
                parts = line.split(",")
                if len(parts) >= 8:
                    try:
                        net = int(parts[7].replace('"', '').replace(',', '').strip())
                        result = {"net_position": net, "date": today, "source": "taifex"}
                        _save("foreign_futures", result)
                        return result
                    except:
                        pass
    except Exception as e:
        log.warning(f"TAIFEX futures error: {e}")

    # fallback: 從 TAIFEX JSON endpoint
    try:
        url2 = "https://www.taifex.com.tw/cht/3/futContractsDate"
        r2 = requests.get(url2, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        data = _load("foreign_futures") or {"net_position": 0, "date": "N/A", "source": "cache"}
        return data
    except:
        return _load("foreign_futures") or {"net_position": 0, "date": "N/A", "source": "cache"}


# ─── 2. 外資現貨買賣超 (TWSE) ──────────────────────────────────────────────────

def fetch_foreign_spot():
    """TWSE 外資現貨每日買賣超"""
    url = "https://www.twse.com.tw/rwd/zh/fund/TWT38U"
    date_str = datetime.now().strftime("%Y%m%d")
    data = _twse_get(url, {"date": date_str, "response": "json"})
    if data and data.get("stat") == "OK" and data.get("data"):
        rows = data["data"]
        # 找外資合計
        for row in rows:
            if "外資" in str(row[0]) and "合計" in str(row[0]):
                try:
                    buy = float(str(row[1]).replace(",", ""))
                    sell = float(str(row[2]).replace(",", ""))
                    net = buy - sell
                    result = {"buy": buy, "sell": sell, "net": net, "date": date_str}
                    _save("foreign_spot", result)
                    return result
                except:
                    pass
        # 用最後一行
        try:
            row = rows[-1]
            net = float(str(row[-1]).replace(",", "").replace("+", ""))
            result = {"net": net, "date": date_str}
            _save("foreign_spot", result)
            return result
        except:
            pass
    return _load("foreign_spot") or {"net": 0, "date": "N/A"}


# ─── 3. 台幣 + DXY 壓力 ────────────────────────────────────────────────────────

def fetch_twd_dxy():
    """DXY 美元指數 + 台幣匯率"""
    dxy = _yf_close("DX-Y.NYB", period="30d")
    twd = _yf_close("TWD=X", period="30d")
    result = {
        "dxy": float(dxy.iloc[-1]) if len(dxy) else None,
        "dxy_5d_change": float((dxy.iloc[-1] - dxy.iloc[-6]) / dxy.iloc[-6] * 100) if len(dxy) >= 6 else None,
        "usd_twd": float(twd.iloc[-1]) if len(twd) else None,
        "usd_twd_5d_change": float((twd.iloc[-1] - twd.iloc[-6]) / twd.iloc[-6] * 100) if len(twd) >= 6 else None,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }
    _save("twd_dxy", result)
    return result


# ─── 4. 融資餘額日變化 (TWSE) ──────────────────────────────────────────────────

def fetch_margin():
    """TWSE 全市場融資餘額"""
    url = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
    date_str = datetime.now().strftime("%Y%m%d")
    data = _twse_get(url, {"date": date_str, "selectType": "MS", "response": "json"})
    cached = _load("margin") or {}
    if data and data.get("stat") == "OK":
        try:
            rows = data.get("data", [])
            if rows:
                # 最後一列通常是合計
                total_row = rows[-1]
                balance = float(str(total_row[3]).replace(",", ""))
                prev = cached.get("balance", balance)
                chg_pct = (balance - prev) / prev * 100 if prev else 0
                result = {"balance": balance, "change_pct": chg_pct, "date": date_str}
                _save("margin", result)
                return result
        except Exception as e:
            log.warning(f"margin parse error: {e}")
    return cached or {"balance": 0, "change_pct": 0, "date": "N/A"}


# ─── 5. ADL 漲跌家數 (TWSE) ────────────────────────────────────────────────────

def fetch_adl():
    """TWSE 上漲/下跌/平盤家數"""
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
    date_str = datetime.now().strftime("%Y%m%d")
    data = _twse_get(url, {"date": date_str, "type": "MS", "response": "json"})
    if data and data.get("stat") == "OK":
        try:
            # 找漲跌家數
            tables = data.get("tables", [data])
            for t in tables if isinstance(tables, list) else [data]:
                rows = t.get("data", [])
                for row in rows:
                    if any("漲" in str(c) for c in row):
                        pass
            # 直接用另一個 endpoint
            pass
        except:
            pass

    # 改用 MI_INDEX5
    url2 = "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d"
    data2 = _twse_get(url2, {"date": date_str, "selectType": "ALL", "response": "json"})

    # fallback to 交易量統計
    url3 = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
    params3 = {"response": "json", "date": date_str, "type": "IND"}
    data3 = _twse_get(url3, params3)

    cached = _load("adl") or {}

    # 嘗試從大盤統計抓漲跌家數
    try:
        url4 = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_MARKET"
        r = requests.get(url4, params={"response": "json"}, timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        d = r.json()
        if d.get("stat") == "OK":
            rows = d.get("data", [])
            up = dn = flat = 0
            for row in rows:
                row_str = str(row)
                if "上漲" in row_str:
                    up = int(str(row[1]).replace(",", "")) if len(row) > 1 else 0
                elif "下跌" in row_str:
                    dn = int(str(row[1]).replace(",", "")) if len(row) > 1 else 0
                elif "平盤" in row_str:
                    flat = int(str(row[1]).replace(",", "")) if len(row) > 1 else 0
            if up or dn:
                result = {"up": up, "down": dn, "flat": flat,
                          "ad_ratio": round(up / (up + dn), 3) if (up + dn) else 0.5,
                          "date": date_str}
                _save("adl", result)
                return result
    except Exception as e:
        log.warning(f"ADL error: {e}")

    return cached or {"up": 0, "down": 0, "flat": 0, "ad_ratio": 0.5, "date": "N/A"}


# ─── 6. 國際技術面 MA20 ─────────────────────────────────────────────────────────

def fetch_intl_tech():
    """主要指數站上 MA20 的比例"""
    tickers = {
        "S&P500": "^GSPC", "NASDAQ": "^IXIC", "道瓊": "^DJI",
        "日經": "^N225", "韓股": "^KS11", "德股": "^GDAXI",
    }
    above_ma20 = 0
    total = len(tickers)
    details = {}
    for name, ticker in tickers.items():
        s = _yf_close(ticker, period="60d")
        if len(s) >= 20:
            ma20 = s.rolling(20).mean().iloc[-1]
            price = s.iloc[-1]
            above = price > ma20
            above_ma20 += int(above)
            details[name] = {"price": round(float(price), 2), "ma20": round(float(ma20), 2), "above": above}
    result = {"above_count": above_ma20, "total": total, "ratio": above_ma20 / total, "details": details,
              "date": datetime.now().strftime("%Y-%m-%d")}
    _save("intl_tech", result)
    return result


# ─── 7. 台指期動能 ─────────────────────────────────────────────────────────────

def fetch_twii_momentum():
    """台股加權指數近期動能"""
    s = _yf_close("^TWII", period="90d")
    if len(s) < 20:
        return _load("twii_momentum") or {}
    price = float(s.iloc[-1])
    prev = float(s.iloc[-2])
    ma5 = float(s.rolling(5).mean().iloc[-1])
    ma20 = float(s.rolling(20).mean().iloc[-1])
    ma60 = float(s.rolling(60).mean().iloc[-1]) if len(s) >= 60 else None
    chg_pct = (price - prev) / prev * 100
    # 5日內日變化
    daily_chg = float(s.iloc[-1] - s.iloc[-6]) if len(s) >= 6 else 0
    result = {
        "price": round(price, 2), "prev": round(prev, 2),
        "chg_pct": round(chg_pct, 2),
        "ma5": round(ma5, 2), "ma20": round(ma20, 2),
        "ma60": round(ma60, 2) if ma60 else None,
        "above_ma20": price > ma20, "above_ma60": (price > ma60) if ma60 else None,
        "5d_change": round(daily_chg, 2),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "history": [round(float(v), 2) for v in s.tail(30).tolist()],
        "history_dates": [str(d.date()) for d in s.tail(30).index],
    }
    _save("twii_momentum", result)
    return result


# ─── 8. TSM + SOX ──────────────────────────────────────────────────────────────

def fetch_tsm_sox():
    tsm = _yf_close("TSM", period="30d")
    sox = _yf_close("^SOX", period="30d")
    result = {}
    if len(tsm) >= 2:
        result["tsm"] = round(float(tsm.iloc[-1]), 2)
        result["tsm_chg"] = round((float(tsm.iloc[-1]) - float(tsm.iloc[-2])) / float(tsm.iloc[-2]) * 100, 2)
    if len(sox) >= 2:
        result["sox"] = round(float(sox.iloc[-1]), 2)
        result["sox_chg"] = round((float(sox.iloc[-1]) - float(sox.iloc[-2])) / float(sox.iloc[-2]) * 100, 2)
    result["date"] = datetime.now().strftime("%Y-%m-%d")
    _save("tsm_sox", result)
    return result


# ─── 9. VIX 恐慌指數 ────────────────────────────────────────────────────────────

def fetch_vix():
    s = _yf_close("^VIX", period="60d")
    if len(s) < 5:
        return _load("vix") or {}
    val = float(s.iloc[-1])
    ma5 = float(s.rolling(5).mean().iloc[-1])
    # 分級：<15 平靜, 15-20 正常, 20-30 警戒, >30 恐慌
    if val < 15:
        level = "平靜"
    elif val < 20:
        level = "正常"
    elif val < 30:
        level = "警戒"
    else:
        level = "恐慌"
    result = {
        "vix": round(val, 2), "ma5": round(ma5, 2), "level": level,
        "history": [round(float(v), 2) for v in s.tail(30).tolist()],
        "history_dates": [str(d.date()) for d in s.tail(30).index],
        "date": datetime.now().strftime("%Y-%m-%d"),
    }
    _save("vix", result)
    return result


# ─── 10. 美債 10Y ────────────────────────────────────────────────────────────────

def fetch_us10y():
    s = _yf_close("^TNX", period="60d")
    if len(s) < 5:
        return _load("us10y") or {}
    val = float(s.iloc[-1])
    prev = float(s.iloc[-2])
    ma20 = float(s.rolling(20).mean().iloc[-1])
    # >4.5% 略高, >5% 高壓
    if val < 3.5:
        level = "低"
    elif val < 4.5:
        level = "正常"
    elif val < 5.0:
        level = "略高"
    else:
        level = "高壓"
    result = {
        "yield": round(val, 3), "prev": round(prev, 3),
        "chg": round(val - prev, 3), "ma20": round(ma20, 3), "level": level,
        "history": [round(float(v), 3) for v in s.tail(30).tolist()],
        "history_dates": [str(d.date()) for d in s.tail(30).index],
        "date": datetime.now().strftime("%Y-%m-%d"),
    }
    _save("us10y", result)
    return result


# ─── 11. 大盤 P/E ────────────────────────────────────────────────────────────────

def fetch_pe():
    """台股大盤 P/E — 從 TWSE 抓或用代理估算"""
    # TWSE 本益比月報
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d"
    date_str = datetime.now().strftime("%Y%m%d")
    data = _twse_get(url, {"date": date_str, "selectType": "ALL", "response": "json"})
    cached = _load("pe") or {}

    if data and data.get("stat") == "OK":
        try:
            rows = data.get("data", [])
            # 找加權指數 P/E (0050 or 台灣50)
            pes = []
            for row in rows[:50]:  # 只看前50支
                if len(row) >= 7:
                    try:
                        pe_val = float(str(row[6]).replace(",", ""))
                        if 5 < pe_val < 100:
                            pes.append(pe_val)
                    except:
                        pass
            if pes:
                avg_pe = sum(pes) / len(pes)
                # 大盤平均 P/E 估算
                if 12 < avg_pe < 25:
                    level = "合理"
                elif avg_pe >= 25:
                    level = "略高"
                elif avg_pe >= 30:
                    level = "高估"
                else:
                    level = "低估"
                result = {"pe": round(avg_pe, 2), "level": level, "date": date_str, "sample_count": len(pes)}
                _save("pe", result)
                return result
        except Exception as e:
            log.warning(f"PE parse error: {e}")

    # fallback: 用台灣50 ETF (0050) P/E 估算
    try:
        info = yf.Ticker("0050.TW").info
        pe = info.get("trailingPE") or info.get("forwardPE")
        if pe:
            level = "合理" if pe < 20 else ("略高" if pe < 25 else "高估")
            result = {"pe": round(float(pe), 2), "level": level, "date": date_str, "source": "0050.TW"}
            _save("pe", result)
            return result
    except:
        pass

    return cached or {"pe": 18.0, "level": "合理", "date": "N/A"}


# ─── 12. 銅價 ────────────────────────────────────────────────────────────────────

def fetch_copper():
    s = _yf_close("HG=F", period="60d")
    if len(s) < 5:
        return _load("copper") or {}
    val = float(s.iloc[-1])
    prev = float(s.iloc[-2])
    ma20 = float(s.rolling(20).mean().iloc[-1])
    chg = (val - prev) / prev * 100
    result = {
        "price": round(val, 4), "chg_pct": round(chg, 2),
        "ma20": round(ma20, 4), "above_ma20": val > ma20,
        "history": [round(float(v), 4) for v in s.tail(30).tolist()],
        "history_dates": [str(d.date()) for d in s.tail(30).index],
        "date": datetime.now().strftime("%Y-%m-%d"),
    }
    _save("copper", result)
    return result


# ─── 13. 三大法人合計 (TWSE) ────────────────────────────────────────────────────

def fetch_institutional():
    """TWSE 三大法人今日買賣超合計"""
    url = "https://www.twse.com.tw/rwd/zh/fund/T86"
    date_str = datetime.now().strftime("%Y%m%d")
    data = _twse_get(url, {"date": date_str, "selectType": "ALL", "response": "json"})
    cached = _load("institutional") or {}
    if data and data.get("stat") == "OK":
        try:
            rows = data.get("data", [])
            # 最後一行通常是合計
            for row in reversed(rows):
                if "合計" in str(row[0]) or row[0] == "":
                    net = float(str(row[-1]).replace(",", "").replace("+", ""))
                    result = {"net": net, "date": date_str}
                    _save("institutional", result)
                    return result
            # 若沒有合計行，加總所有
            total_net = 0
            for row in rows:
                try:
                    total_net += float(str(row[-1]).replace(",", "").replace("+", ""))
                except:
                    pass
            result = {"net": total_net, "date": date_str}
            _save("institutional", result)
            return result
        except Exception as e:
            log.warning(f"institutional parse error: {e}")
    return cached or {"net": 0, "date": "N/A"}


# ─── 14. 大盤量比 ────────────────────────────────────────────────────────────────

def fetch_volume_ratio():
    """今日量 vs 近5日均量"""
    s = yf.download("^TWII", period="30d", progress=False, auto_adjust=True)
    if len(s) < 6:
        return _load("volume_ratio") or {}
    volumes = s["Volume"].dropna()
    today_vol = float(volumes.iloc[-1])
    avg5 = float(volumes.iloc[-6:-1].mean())
    ratio = today_vol / avg5 if avg5 else 1.0
    if ratio < 0.7:
        level = "縮量"
    elif ratio < 1.3:
        level = "正常"
    elif ratio < 1.8:
        level = "放量"
    else:
        level = "爆量"
    result = {
        "today_vol": int(today_vol), "avg5_vol": int(avg5),
        "ratio": round(ratio, 3), "level": level,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }
    _save("volume_ratio", result)
    return result


# ─── 15. MA60 乖離率 ─────────────────────────────────────────────────────────────

def fetch_ma60_bias():
    """台股加權指數對 MA60 的乖離率"""
    s = _yf_close("^TWII", period="120d")
    if len(s) < 60:
        return _load("ma60_bias") or {}
    price = float(s.iloc[-1])
    ma60 = float(s.rolling(60).mean().iloc[-1])
    bias = (price - ma60) / ma60 * 100
    # 乖離率 > +15% 過熱, < -15% 超跌
    if bias > 15:
        level = "過熱"
    elif bias > 8:
        level = "偏高"
    elif bias < -15:
        level = "超跌"
    elif bias < -8:
        level = "偏低"
    else:
        level = "正常"
    result = {
        "price": round(price, 2), "ma60": round(ma60, 2),
        "bias_pct": round(bias, 2), "level": level,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }
    _save("ma60_bias", result)
    return result


# ─── 16. HY 信用利差 (FRED) ──────────────────────────────────────────────────────

def fetch_hy_spread():
    """美國 HY 信用利差 (ICE BofA) via FRED or Yahoo proxy"""
    # 嘗試 FRED API
    if FRED_API_KEY:
        try:
            url = "https://api.stlouisfed.org/fred/series/observations"
            params = {
                "series_id": "BAMLH0A0HYM2",
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "observation_start": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
                "sort_order": "desc",
                "limit": 5,
            }
            r = requests.get(url, params=params, timeout=10)
            obs = r.json().get("observations", [])
            if obs:
                val = float(obs[0]["value"])
                prev = float(obs[1]["value"]) if len(obs) > 1 else val
                level = "正常" if val < 4.0 else ("警戒" if val < 6.0 else "危險")
                result = {"spread": round(val, 3), "prev": round(prev, 3),
                          "chg": round(val - prev, 3), "level": level,
                          "date": obs[0]["date"]}
                _save("hy_spread", result)
                return result
        except Exception as e:
            log.warning(f"FRED error: {e}")

    # 無 FRED key → 用 ^HYG proxy (HYG ETF 作為 HY 替代)
    try:
        s_hyg = _yf_close("HYG", period="30d")
        s_ief = _yf_close("IEF", period="30d")  # 7-10Y Treasury
        if len(s_hyg) >= 2 and len(s_ief) >= 2:
            # HY spread proxy = HYG yield - Treasury yield (估算)
            hyg_price = float(s_hyg.iloc[-1])
            hyg_prev = float(s_hyg.iloc[-2])
            chg_pct = (hyg_price - hyg_prev) / hyg_prev * 100
            # 用 HYG vs LQD 相對表現估算利差壓力
            s_lqd = _yf_close("LQD", period="30d")
            if len(s_lqd) >= 2:
                spread_proxy = float(s_lqd.iloc[-1] / s_hyg.iloc[-1]) * 3.0  # 粗估
                level = "正常" if spread_proxy < 4.5 else ("警戒" if spread_proxy < 6.5 else "危險")
            else:
                spread_proxy = 3.5
                level = "正常"
            result = {"spread": round(spread_proxy, 2), "hyg_price": round(hyg_price, 2),
                      "hyg_chg": round(chg_pct, 2), "level": level,
                      "note": "估算值(無FRED key)", "date": datetime.now().strftime("%Y-%m-%d")}
            _save("hy_spread", result)
            return result
    except Exception as e:
        log.warning(f"HYG proxy error: {e}")

    return _load("hy_spread") or {"spread": 3.5, "level": "正常", "date": "N/A"}


# ─── 17. 權買 vs 加權 (Put/Call + Options) ──────────────────────────────────────

def fetch_options_ratio():
    """台指選擇權 Put/Call 比 → 用 Yahoo Finance SPY options 估算 + 台指期"""
    # SPY P/C ratio 作為美股情緒代理
    try:
        spy = yf.Ticker("SPY")
        # 最近到期日
        exp_dates = spy.options
        if exp_dates:
            opt = spy.option_chain(exp_dates[0])
            call_vol = opt.calls["volume"].sum()
            put_vol = opt.puts["volume"].sum()
            pc_ratio = put_vol / call_vol if call_vol > 0 else 1.0
            # P/C > 1.2 = 恐慌/看空, < 0.7 = 過度樂觀
            if pc_ratio > 1.2:
                sentiment = "看空/恐慌"
            elif pc_ratio < 0.7:
                sentiment = "過度樂觀"
            else:
                sentiment = "中性"
            result = {
                "pc_ratio": round(float(pc_ratio), 3),
                "call_vol": int(call_vol), "put_vol": int(put_vol),
                "sentiment": sentiment,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "source": "SPY options",
            }
            _save("options_ratio", result)
            return result
    except Exception as e:
        log.warning(f"options error: {e}")

    # fallback: 從台股期貨買賣超估算
    try:
        url = "https://www.taifex.com.tw/cht/3/callsAndPutsDate"
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        # 抓取頁面文字解析
        import re
        matches = re.findall(r'買入[\s\S]*?(\d[\d,]+)[\s\S]*?賣出[\s\S]*?(\d[\d,]+)', r.text[:3000])
        if matches:
            pass
    except:
        pass

    return _load("options_ratio") or {"pc_ratio": 1.0, "sentiment": "中性", "date": "N/A"}


# ─── 18. 大戶持股 (TDCC 集保) ──────────────────────────────────────────────────

def fetch_tdcc():
    """TDCC 大戶(400張+)持股比例變化 — 公開資料每週更新"""
    # 台灣集保的開放資料 API
    try:
        url = "https://openapi.tdcc.com.tw/v1/opendata/1-5"
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0",
                                                    "Accept": "application/json"})
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            # 找大戶(400張以上)持股比例
            # 通常資料欄位: StockNo, HolderLevel, HolderCount, SharesHeld, ...
            # 聚合所有股票的大戶比例
            big_holders = []
            for item in data[:100]:  # 取前100支
                try:
                    level = str(item.get("HolderLevel", ""))
                    if "400" in level or "1000" in level or "超過" in level:
                        ratio = float(str(item.get("HoldingSharesRatio", "0")).replace("%", ""))
                        big_holders.append(ratio)
                except:
                    pass
            if big_holders:
                avg_ratio = sum(big_holders) / len(big_holders)
                cached = _load("tdcc") or {}
                prev_ratio = cached.get("ratio", avg_ratio)
                chg = avg_ratio - prev_ratio
                result = {"ratio": round(avg_ratio, 2), "change": round(chg, 2),
                          "date": datetime.now().strftime("%Y-%m-%d"), "source": "tdcc_api"}
                _save("tdcc", result)
                return result
    except Exception as e:
        log.warning(f"TDCC API error: {e}")

    # fallback: 抓0050大戶持股估算
    try:
        cached = _load("tdcc") or {}
        info = yf.Ticker("0050.TW").info
        inst_pct = info.get("institutionsPercentHeld", 0) * 100
        if inst_pct:
            chg = inst_pct - cached.get("ratio", inst_pct)
            result = {"ratio": round(inst_pct, 2), "change": round(chg, 3),
                      "date": datetime.now().strftime("%Y-%m-%d"), "source": "0050 inst%"}
            _save("tdcc", result)
            return result
    except:
        pass

    return _load("tdcc") or {"ratio": 70.0, "change": 0, "date": "N/A"}


# ─── 買賣推薦候選股票池 ──────────────────────────────────────────────────────────

TW_STOCKS = {
    "半導體": ["2330.TW", "2303.TW", "2308.TW", "2454.TW", "3711.TW"],
    "電子製造": ["2317.TW", "2354.TW", "2382.TW", "3034.TW"],
    "金融": ["2882.TW", "2884.TW", "2886.TW", "2891.TW"],
    "傳產/汽車": ["2207.TW", "2105.TW", "1301.TW", "1303.TW"],
    "ETF": ["0050.TW", "0056.TW", "00878.TW", "00929.TW"],
}

US_STOCKS = {
    "科技": ["NVDA", "AAPL", "MSFT", "META", "GOOGL"],
    "半導體": ["AMD", "INTC", "AVGO", "QCOM", "MU"],
    "AI/雲端": ["AMZN", "CRM", "PLTR", "SNOW"],
    "ETF": ["SPY", "QQQ", "SOXX", "SMH", "XLK", "VT"],
    "防禦": ["GLD", "TLT", "VYM", "XLV"],
    "加密相關": ["MSTR", "COIN", "IBIT"],
}

CRYPTO_TICKERS = {
    "Bitcoin": "BTC-USD",
    "Ethereum": "ETH-USD",
    "Solana": "SOL-USD",
}


def fetch_crypto() -> dict:
    """抓取 BTC、ETH、SOL 價格、技術指標與市場情緒"""
    result = {}
    for name, ticker in CRYPTO_TICKERS.items():
        try:
            s = _yf_close(ticker, period="90d")
            if len(s) < 20:
                continue
            price = float(s.iloc[-1])
            prev  = float(s.iloc[-2])
            ma7   = float(s.rolling(7).mean().iloc[-1])
            ma20  = float(s.rolling(20).mean().iloc[-1])
            ma50  = float(s.rolling(50).mean().iloc[-1]) if len(s) >= 50 else None

            # RSI(14)
            delta = s.diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            rsi   = float(100 - 100 / (1 + gain.iloc[-1] / loss.iloc[-1])) if loss.iloc[-1] != 0 else 50

            chg_pct_1d  = (price - prev) / prev * 100
            chg_pct_7d  = (price - float(s.iloc[-8]))  / float(s.iloc[-8])  * 100 if len(s) >= 8  else 0
            chg_pct_30d = (price - float(s.iloc[-31])) / float(s.iloc[-31]) * 100 if len(s) >= 31 else 0

            # 趨勢判斷
            if price > ma20 and ma20 > ma50 if ma50 else price > ma20:
                trend = "上升趨勢"
            elif price < ma20 and (ma50 is None or ma20 < ma50):
                trend = "下降趨勢"
            else:
                trend = "整理區間"

            # 超買超賣
            if rsi > 75:
                rsi_label = "超買❗"
            elif rsi > 60:
                rsi_label = "偏強"
            elif rsi < 30:
                rsi_label = "超賣💡"
            elif rsi < 40:
                rsi_label = "偏弱"
            else:
                rsi_label = "中性"

            # MA乖離
            bias_ma20 = (price - ma20) / ma20 * 100

            result[name] = {
                "ticker": ticker,
                "price": round(price, 2),
                "chg_1d": round(chg_pct_1d, 2),
                "chg_7d": round(chg_pct_7d, 2),
                "chg_30d": round(chg_pct_30d, 2),
                "ma7": round(ma7, 2),
                "ma20": round(ma20, 2),
                "ma50": round(ma50, 2) if ma50 else None,
                "above_ma20": price > ma20,
                "above_ma50": (price > ma50) if ma50 else None,
                "rsi": round(rsi, 1),
                "rsi_label": rsi_label,
                "trend": trend,
                "bias_ma20": round(bias_ma20, 2),
                "history": [round(float(v), 2) for v in s.tail(30).tolist()],
                "history_dates": [str(d.date()) for d in s.tail(30).index],
                "date": datetime.now().strftime("%Y-%m-%d"),
            }
            time.sleep(0.3)
        except Exception as e:
            log.warning(f"crypto {ticker}: {e}")

    # 加密市場恐懼貪婪指數代理（用 BTC RSI + 波動率估算）
    if "Bitcoin" in result:
        btc = result["Bitcoin"]
        btc_rsi = btc.get("rsi", 50)
        btc_bias = abs(btc.get("bias_ma20", 0))
        # 簡易估算：RSI 高 + 偏離大 = 貪婪；RSI 低 + 跌多 = 恐懼
        fg_score = int(btc_rsi * 0.6 + (50 - btc_bias * 0.5))
        fg_score = max(0, min(100, fg_score))
        if fg_score >= 75:
            fg_label = "極度貪婪 🤑"
        elif fg_score >= 55:
            fg_label = "貪婪"
        elif fg_score >= 45:
            fg_label = "中性"
        elif fg_score >= 25:
            fg_label = "恐懼"
        else:
            fg_label = "極度恐懼 😱"
        result["fear_greed"] = {"score": fg_score, "label": fg_label}

    _save("crypto", result)
    return result


def fetch_stock_technicals(tickers: list) -> dict:
    """批次抓個股技術指標"""
    results = {}
    for ticker in tickers:
        try:
            s = _yf_close(ticker, period="120d")
            if len(s) < 20:
                continue
            price = float(s.iloc[-1])
            ma5 = float(s.rolling(5).mean().iloc[-1])
            ma20 = float(s.rolling(20).mean().iloc[-1])
            ma60 = float(s.rolling(60).mean().iloc[-1]) if len(s) >= 60 else None

            # RSI(14)
            delta = s.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss
            rsi = float(100 - 100 / (1 + rs.iloc[-1]))

            # 成交量比
            vol_df = yf.download(ticker, period="30d", progress=False, auto_adjust=True)
            vols = vol_df["Volume"].dropna()
            vol_ratio = float(vols.iloc[-1] / vols.iloc[-6:-1].mean()) if len(vols) >= 6 else 1.0

            # MACD
            ema12 = s.ewm(span=12).mean()
            ema26 = s.ewm(span=26).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9).mean()
            macd_cross = (macd_line.iloc[-1] > signal_line.iloc[-1]) and (macd_line.iloc[-2] < signal_line.iloc[-2])

            # 近60日歷史（用於走勢圖）
            hist_s = s.tail(60)
            results[ticker] = {
                "price": round(price, 2),
                "ma5": round(ma5, 2), "ma20": round(ma20, 2),
                "ma60": round(ma60, 2) if ma60 else None,
                "above_ma5": price > ma5, "above_ma20": price > ma20,
                "above_ma60": (price > ma60) if ma60 else None,
                "rsi": round(rsi, 1),
                "vol_ratio": round(vol_ratio, 2),
                "macd_golden_cross": bool(macd_cross),
                "macd_value": round(float(macd_line.iloc[-1]), 4),
                "macd_signal": round(float(signal_line.iloc[-1]), 4),
                "5d_return":  round((float(s.iloc[-1]) - float(s.iloc[-6]))  / float(s.iloc[-6])  * 100, 2) if len(s) >= 6  else 0,
                "20d_return": round((float(s.iloc[-1]) - float(s.iloc[-21])) / float(s.iloc[-21]) * 100, 2) if len(s) >= 21 else 0,
                "60d_return": round((float(s.iloc[-1]) - float(s.iloc[-61])) / float(s.iloc[-61]) * 100, 2) if len(s) >= 61 else 0,
                "history": [round(float(v), 4) for v in hist_s.tolist()],
                "history_dates": [str(d.date()) for d in hist_s.index],
            }
            time.sleep(0.3)  # rate limit
        except Exception as e:
            log.warning(f"technicals {ticker}: {e}")
    return results


def fetch_all_recommendations():
    """抓取所有推薦候選的技術數據"""
    all_tickers = []
    for group in TW_STOCKS.values():
        all_tickers += group
    for group in US_STOCKS.values():
        all_tickers += group
    # 加密相關股票也納入技術分析
    all_tickers += ["MSTR", "COIN", "IBIT"]

    log.info(f"Fetching technicals for {len(all_tickers)} stocks...")
    data = fetch_stock_technicals(all_tickers)
    _save("stock_technicals", data)
    return data


# ─── 主要入口 ────────────────────────────────────────────────────────────────────

def fetch_all():
    """抓取全部 18 項指標數據（每日排程呼叫）"""
    log.info("=== 開始抓取所有指標數據 ===")
    results = {}

    tasks = [
        ("foreign_futures",   fetch_foreign_futures),
        ("foreign_spot",      fetch_foreign_spot),
        ("twd_dxy",           fetch_twd_dxy),
        ("margin",            fetch_margin),
        ("adl",               fetch_adl),
        ("intl_tech",         fetch_intl_tech),
        ("twii_momentum",     fetch_twii_momentum),
        ("tsm_sox",           fetch_tsm_sox),
        ("vix",               fetch_vix),
        ("us10y",             fetch_us10y),
        ("pe",                fetch_pe),
        ("copper",            fetch_copper),
        ("institutional",     fetch_institutional),
        ("volume_ratio",      fetch_volume_ratio),
        ("ma60_bias",         fetch_ma60_bias),
        ("hy_spread",         fetch_hy_spread),
        ("options_ratio",     fetch_options_ratio),
        ("tdcc",              fetch_tdcc),
    ]

    for name, fn in tasks:
        try:
            log.info(f"  抓取: {name}")
            results[name] = fn()
            time.sleep(0.5)
        except Exception as e:
            log.error(f"  {name} 失敗: {e}")
            results[name] = _load(name) or {}

    # 推薦股票技術面
    try:
        log.info("  抓取推薦股票技術面...")
        results["stock_technicals"] = fetch_all_recommendations()
    except Exception as e:
        log.error(f"  stock_technicals 失敗: {e}")
        results["stock_technicals"] = _load("stock_technicals") or {}

    # 加密貨幣
    try:
        log.info("  抓取加密貨幣數據...")
        results["crypto"] = fetch_crypto()
    except Exception as e:
        log.error(f"  crypto 失敗: {e}")
        results["crypto"] = _load("crypto") or {}

    _save("last_fetch", {"timestamp": datetime.now().isoformat(), "success": True})
    log.info("=== 數據抓取完成 ===")
    return results


if __name__ == "__main__":
    fetch_all()
