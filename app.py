"""
app.py — Flask 主伺服器
每日台股收盤後自動抓取數據並更新預測
支援本機 (python app.py) 與雲端部署 (gunicorn) 兩種模式
"""

import os, json, logging, atexit
from datetime import datetime
from flask import Flask, jsonify, render_template
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from data_fetcher import fetch_all, DATA_DIR, _load
from indicators import compute_all_scores, generate_recommendations, save_score_history

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["JSON_ENSURE_ASCII"] = False

# ─── 記憶體快取 ──────────────────────────────────────────────────────────────
_cached_result = None
_cached_recs = None


def _build_result():
    """從磁碟快取重算結果"""
    global _cached_result, _cached_recs

    data = {}
    for key in [
        "foreign_futures", "foreign_spot", "twd_dxy", "margin", "adl",
        "intl_tech", "twii_momentum", "tsm_sox", "vix", "us10y", "pe",
        "copper", "institutional", "volume_ratio", "ma60_bias",
        "hy_spread", "options_ratio", "tdcc"
    ]:
        data[key] = _load(key) or {}

    tech_data   = _load("stock_technicals") or {}
    crypto_data = _load("crypto") or {}
    scores = compute_all_scores(data)
    recs   = generate_recommendations(scores, tech_data, scores["signal"], crypto_data)

    _cached_result = scores
    _cached_recs   = recs
    log.info(f"結果已更新: {scores['signal_text']} | 分數={scores['total_weighted']}")
    return scores, recs


def daily_update():
    """每日排程任務：抓數據 → 計算 → 儲存"""
    log.info("=== 開始每日更新 ===")
    try:
        fetch_all()
        scores, recs = _build_result()
        save_score_history(scores)
        path = os.path.join(DATA_DIR, "today_result.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"scores": scores, "recs": recs}, f, ensure_ascii=False, default=str)
        log.info("=== 每日更新完成 ===")
    except Exception as e:
        log.error(f"daily_update 失敗: {e}", exc_info=True)


# ─── 排程器（模組層級，gunicorn 也會執行）────────────────────────────────────
scheduler = BackgroundScheduler(timezone="Asia/Taipei")

# 台股 15:30（週一至週五）
scheduler.add_job(daily_update, CronTrigger(
    day_of_week="mon-fri", hour=15, minute=30, timezone="Asia/Taipei"))

# 美股收盤後 06:00（週二至週六台灣時間）
scheduler.add_job(daily_update, CronTrigger(
    day_of_week="tue-sat", hour=6, minute=0, timezone="Asia/Taipei"))


def _startup():
    """應用程式啟動初始化（本機 + gunicorn 共用）"""
    global _cached_result, _cached_recs
    needs_fetch = False

    try:
        existing = _load("today_result")
        if existing:
            _cached_result = existing.get("scores")
            _cached_recs   = existing.get("recs")
            log.info(f"已載入快取: {_cached_result.get('signal_text', '')}")
        else:
            needs_fetch = True
            log.info("無快取，將於排程器啟動後立即抓取數據")
    except Exception as e:
        log.warning(f"初始載入失敗: {e}")
        needs_fetch = True

    if not scheduler.running:
        scheduler.start()
        atexit.register(lambda: scheduler.shutdown(wait=False))
        log.info("排程器已啟動（每日 15:30 + 06:00 自動更新）")

    # 若無快取，立即在背景排程一次完整抓取
    if needs_fetch:
        try:
            scheduler.add_job(
                daily_update, 'date',
                run_date=datetime.now(),
                id='init_fetch',
                misfire_grace_time=600,
            )
            log.info("已排程立即執行初始數據抓取（背景執行，約需 2–3 分鐘）")
        except Exception as e:
            log.warning(f"初始排程失敗: {e}")


# 模組被 import 時執行（gunicorn worker 也會觸發）
_startup()


# ─── 路由 ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/dashboard")
def api_dashboard():
    global _cached_result, _cached_recs
    if _cached_result is None:
        try:
            _build_result()
        except Exception as e:
            log.error(f"build result error: {e}")
            return jsonify({"error": "數據尚未就緒，請稍後再試或點選「更新數據」"}), 503
    return jsonify({
        "scores": _cached_result,
        "recs":   _cached_recs,
        "last_update": _cached_result.get("timestamp", ""),
    })


@app.route("/api/history")
def api_history():
    hist = _load("score_history") or []
    return jsonify(hist)


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    try:
        log.info("手動觸發更新...")
        fetch_all()
        scores, recs = _build_result()
        save_score_history(scores)
        return jsonify({"status": "ok", "signal": scores["signal_text"]})
    except Exception as e:
        log.error(f"refresh error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/indicator/<int:idx>")
def api_indicator_detail(idx: int):
    key_map = {
        1: "foreign_futures", 2: "foreign_spot", 3: "twd_dxy",
        4: "margin",          5: "adl",          6: "intl_tech",
        7: "twii_momentum",   8: "tsm_sox",       9: "vix",
        10: "us10y",          11: "pe",            12: "copper",
        13: "institutional",  14: "volume_ratio",  15: "ma60_bias",
        16: "hy_spread",      17: "options_ratio", 18: "tdcc",
    }
    key = key_map.get(idx)
    if not key:
        return jsonify({"error": "invalid indicator"}), 400
    return jsonify(_load(key) or {})


@app.route("/api/crypto")
def api_crypto():
    return jsonify(_load("crypto") or {})


@app.route("/api/stock/<ticker>")
def api_stock(ticker: str):
    tech = _load("stock_technicals") or {}
    t = ticker.upper()
    if t in tech:
        return jsonify(tech[t])
    tw = t + ".TW"
    if tw in tech:
        return jsonify(tech[tw])
    return jsonify({"error": "not found"}), 404


# ─── 本機開發模式 ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)
