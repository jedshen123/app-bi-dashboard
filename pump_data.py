"""
吸奶器用户行为看板 — 经 MCP 查询美东 StarRocks
数据来源：lute_app_dw DWS 中间表（见 docs/pump_dashboard_sql.md）
"""

from datetime import date, timedelta
from typing import Optional

from mcp_client import run_sql, health_check as mcp_health_check, MCP_URL, MCP_DATABASE_ID

DB    = "lute_app_dw"
DWD   = f"{DB}.dwd_tp_app_breast_pump_log_di"
SESS  = f"{DB}.dws_pump_session_df"
DAILY = f"{DB}.dws_pump_daily_df"
MODE  = f"{DB}.dws_pump_session_mode_df"
RET   = f"{DB}.dws_pump_retention_di"

SECTIONS = ("overview", "retention", "sessions", "duration", "habits", "funnel", "firmware")
_db_checked = False
_active_device_code = ""   # 当前请求的型号过滤（空=全部）


def _dc_and() -> str:
    """返回 DAILY/SESS 的 deviceCode 过滤条件（AND 开头），空=全品类不加过滤。"""
    if _active_device_code:
        return f" AND deviceCode = '{_active_device_code}'"
    return ""


def query_device_codes() -> list:
    """返回 DAILY 表中所有有效 deviceCode 列表（排除 NULL/ALL）。"""
    rows = _safe(run_sql(f"""
        SELECT deviceCode
        FROM {DAILY}
        WHERE deviceCode IS NOT NULL AND deviceCode != 'ALL'
        GROUP BY deviceCode
        ORDER BY deviceCode
    """, []))
    return [r["deviceCode"] for r in rows if r.get("deviceCode")]


def ensure_db():
    global _db_checked
    if _db_checked:
        return
    try:
        mcp_health_check()
    except Exception as e:
        raise RuntimeError(
            f"无法通过 MCP 访问美东数据库（{MCP_URL}，database_id={MCP_DATABASE_ID}）：{e}"
        ) from e
    _db_checked = True


def parse_date_range(start_dt: str = "", end_dt: str = "", days: int = 90) -> tuple:
    end = date.today() if not end_dt else date.fromisoformat(end_dt[:10])
    if start_dt:
        start = date.fromisoformat(start_dt[:10])
    else:
        start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def _safe(rows):
    out = []
    for r in rows:
        row = {}
        for k, v in r.items():
            if v is None:
                row[k] = None
            elif hasattr(v, "isoformat"):
                row[k] = str(v)[:10]
            else:
                try:
                    from decimal import Decimal
                    if isinstance(v, Decimal):
                        row[k] = float(v) if "." in str(v) else int(v)
                        continue
                except ImportError:
                    pass
                row[k] = v
        out.append(row)
    return out


def _one(rows):
    return _safe(rows)[0] if rows else {}


def _q(sql: str, params: list):
    return _safe(run_sql(sql, params))


def _avg_field(rows, field):
    vals = [r.get(field) for r in rows if r.get(field) is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


# ---------------------------------------------------------------------------
# KPI helpers
# ---------------------------------------------------------------------------

def query_kpi01(start: str, end: str) -> dict:
    """总览 KPI：来自 dws_pump_daily_df，SUM all deviceCodes（无全品类行）。"""
    return _one(_q(f"""
        SELECT
            MAX(cumulative_users)    AS total_users,
            MAX(cumulative_devices)  AS total_devices,
            SUM(total_sessions)      AS total_sessions,
            ROUND(SUM(total_sessions) / NULLIF(MAX(cumulative_users), 0), 0) AS avg_sessions_per_user,
            ROUND(SUM(valid_sessions) / NULLIF(SUM(total_sessions), 0), 5) AS valid_session_rate_pct,
            ROUND(SUM(total_duration_h), 2)  AS total_duration_hours,
            ROUND(SUM(total_duration_sec) / 60.0 / NULLIF(SUM(total_sessions), 0), 2) AS avg_duration_min,
            ROUND(MAX(cumulative_devices) / NULLIF(MAX(cumulative_users), 0), 4) AS devices_per_user
        FROM {DAILY}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
    """, [start, end]))


def query_kpi02(start: str, end: str) -> dict:
    """漏斗 KPI：来自 dws_pump_daily_df。"""
    return _one(_q(f"""
        SELECT
            SUM(power_on_cnt)      AS power_on_cnt,
            MAX(cumulative_devices) AS total_devices,
            SUM(total_sessions)    AS started_sessions,
            SUM(complete_sessions) AS ended_sessions,
            SUM(valid_sessions)    AS valid_sessions
        FROM {DAILY}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
    """, [start, end]))


def query_d1_ret(start: str, end: str) -> Optional[float]:
    """时间范围内每日 D1 用户留存率的均值（0-1 小数）。"""
    row = _one(_q(f"""
        SELECT ROUND(AVG(d1_user_ret), 5) AS d1_user_ret
        FROM {RET}
        WHERE deviceCode = 'ALL'
          AND base_dt BETWEEN %s AND %s
    """, [start, end]))
    v = row.get("d1_user_ret")
    return float(v) if v is not None else None


def _delta_pct(new_val, old_val) -> Optional[float]:
    """计算环比变化百分比，返回带一位小数的 float，如 +3.2 或 -1.4。"""
    if new_val is None or old_val is None or old_val == 0:
        return None
    return round((float(new_val) - float(old_val)) / abs(float(old_val)) * 100, 1)


def _delta_pp(new_val, old_val) -> Optional[float]:
    """计算留存率等比例值的绝对差（百分点 pp），如 0.807-0.795 → +1.2 pp。"""
    if new_val is None or old_val is None:
        return None
    return round((float(new_val) - float(old_val)) * 100, 1)


def _day_before(dt_str: str) -> str:
    return (date.fromisoformat(dt_str) - timedelta(days=1)).isoformat()


def _day_offset(dt_str: str, offset: int) -> str:
    return (date.fromisoformat(dt_str) + timedelta(days=offset)).isoformat()


def _query_daily_snapshot(dt: str) -> dict:
    """查询某一天的核心日指标（自动选 <= dt 的最近有数据日期）。"""
    return _one(_q(f"""
        SELECT
            SUM(dau)            AS dau,
            SUM(active_devices) AS active_devices,
            SUM(new_users)      AS new_users,
            SUM(new_devices)    AS new_devices,
            SUM(total_sessions) AS sessions,
            ROUND(SUM(total_duration_h), 2) AS duration_hours,
            ROUND(SUM(avg_duration_min * total_sessions)
                / NULLIF(SUM(total_sessions), 0), 2) AS avg_dur_min,
            ROUND(SUM(valid_sessions) / NULLIF(SUM(total_sessions), 0), 5) AS valid_rate,
            ROUND(SUM(total_sessions) / NULLIF(SUM(dau), 0), 2) AS avg_sessions_per_user,
            ROUND(SUM(total_duration_sec) / 60.0
                / NULLIF(SUM(dau), 0), 2) AS dur_per_user_min,
            SUM(power_on_cnt)      AS power_on_cnt,
            SUM(complete_sessions) AS complete_sessions,
            SUM(valid_sessions)    AS valid_sessions
        FROM {DAILY}
        WHERE evt_dt = (SELECT MAX(evt_dt) FROM {DAILY} WHERE evt_dt <= %s)
    """, [dt]))


def _query_daily_7d_avg(end: str) -> dict:
    """查询 end 前7天（含 end）的日均核心指标。"""
    start7 = _day_offset(end, -6)
    return _one(_q(f"""
        WITH d AS (
            SELECT
                evt_dt,
                SUM(dau)            AS dau,
                SUM(active_devices) AS active_devices,
                SUM(new_users)      AS new_users,
                SUM(new_devices)    AS new_devices,
                SUM(total_sessions) AS sessions,
                SUM(total_duration_h) AS duration_hours,
                SUM(avg_duration_min * total_sessions)
                    / NULLIF(SUM(total_sessions), 0) AS avg_dur_min,
                SUM(valid_sessions) / NULLIF(SUM(total_sessions), 0) AS valid_rate,
                SUM(total_sessions) / NULLIF(SUM(dau), 0) AS avg_sessions_per_user,
                SUM(total_duration_sec) / 60.0
                    / NULLIF(SUM(dau), 0) AS dur_per_user_min,
                SUM(power_on_cnt)      AS power_on_cnt,
                SUM(complete_sessions) AS complete_sessions,
                SUM(valid_sessions)    AS valid_sessions
            FROM {DAILY}
            WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
            GROUP BY evt_dt
        )
        SELECT
            ROUND(AVG(dau), 0)               AS dau,
            ROUND(AVG(active_devices), 0)    AS active_devices,
            ROUND(AVG(new_users), 0)         AS new_users,
            ROUND(AVG(new_devices), 0)       AS new_devices,
            ROUND(AVG(sessions), 0)          AS sessions,
            ROUND(AVG(duration_hours), 2)    AS duration_hours,
            ROUND(AVG(avg_dur_min), 2)       AS avg_dur_min,
            ROUND(AVG(valid_rate), 5)        AS valid_rate,
            ROUND(AVG(avg_sessions_per_user), 2) AS avg_sessions_per_user,
            ROUND(AVG(dur_per_user_min), 2)  AS dur_per_user_min,
            ROUND(AVG(power_on_cnt), 0)      AS power_on_cnt,
            ROUND(AVG(complete_sessions), 0) AS complete_sessions,
            ROUND(AVG(valid_sessions), 0)    AS valid_sessions
        FROM d
    """, [start7, end]))


def query_kpi_yesterday(end: str) -> dict:
    """昨日快照 + 前1日/前7日均值对比，用于概览板块下方的 kpiCardCmp 卡片。"""
    latest_dt = end
    prev1_dt = _day_before(end)

    today_row  = _query_daily_snapshot(latest_dt)
    prev1_row  = _query_daily_snapshot(prev1_dt)
    prev7_avg  = _query_daily_7d_avg(prev1_dt)

    d1_ret_row = _one(_q(f"""
        SELECT d1_user_ret FROM {RET}
        WHERE deviceCode = 'ALL'
        ORDER BY base_dt DESC LIMIT 1
    """, []))
    d1_ret_val = d1_ret_row.get("d1_user_ret")
    d1_ret_val_prev = _one(_q(f"""
        SELECT d1_user_ret FROM {RET}
        WHERE deviceCode = 'ALL' AND base_dt <= %s
        ORDER BY base_dt DESC LIMIT 1
    """, [prev1_dt])).get("d1_user_ret")
    d1_ret_7d_avg = _one(_q(f"""
        SELECT ROUND(AVG(d1_user_ret), 5) AS d1_user_ret
        FROM (
            SELECT d1_user_ret FROM {RET}
            WHERE deviceCode='ALL' AND base_dt <= %s
            ORDER BY base_dt DESC LIMIT 7
        ) t
    """, [prev1_dt])).get("d1_user_ret")

    def cmp(field):
        return {
            "d1_delta":  _delta_pct(today_row.get(field), prev1_row.get(field)),
            "d7_delta":  _delta_pct(today_row.get(field), prev7_avg.get(field)),
        }

    def cmp_pp(field):
        return {
            "d1_delta": _delta_pp(today_row.get(field), prev1_row.get(field)),
            "d7_delta": _delta_pp(today_row.get(field), prev7_avg.get(field)),
        }

    return {
        "dau":           today_row.get("dau"),
        "active_devices": today_row.get("active_devices"),
        "sessions":      today_row.get("sessions"),
        "duration_hours": today_row.get("duration_hours"),
        "avg_dur_min":   today_row.get("avg_dur_min"),
        "d1_ret":        round(float(d1_ret_val) * 100, 1) if d1_ret_val is not None else None,
        "valid_rate":    today_row.get("valid_rate"),
        # comparison deltas
        "dau_cmp":           cmp("dau"),
        "active_devices_cmp": cmp("active_devices"),
        "sessions_cmp":      cmp("sessions"),
        "duration_hours_cmp": cmp("duration_hours"),
        "d1_ret_cmp": {
            "d1_delta": _delta_pp(d1_ret_val, d1_ret_val_prev),
            "d7_delta": _delta_pp(d1_ret_val, d1_ret_7d_avg),
        },
        "valid_rate_cmp":    cmp_pp("valid_rate"),
    }


def query_pause_stats(start: str, end: str) -> dict:
    """暂停行为统计，来自 dws_pump_session_df.pause_cnt。"""
    row = _one(_q(f"""
        SELECT
            ROUND(COUNT(CASE WHEN pause_cnt > 0 THEN 1 END)
                / NULLIF(COUNT(useSessionId), 0) * 100, 1) AS pause_rate_pct,
            ROUND(SUM(pause_cnt) / NULLIF(COUNT(CASE WHEN pause_cnt > 0 THEN 1 END), 0), 1) AS avg_pauses_per_paused_session,
            COUNT(CASE WHEN pause_cnt = 0 THEN 1 END) AS cnt_0,
            COUNT(CASE WHEN pause_cnt = 1 THEN 1 END) AS cnt_1,
            COUNT(CASE WHEN pause_cnt = 2 THEN 1 END) AS cnt_2,
            COUNT(CASE WHEN pause_cnt >= 3 THEN 1 END) AS cnt_3plus,
            COUNT(useSessionId) AS total
        FROM {SESS}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
          AND pause_cnt IS NOT NULL
    """, [start, end]))
    total = row.get("total") or 1
    return {
        "pause_rate_pct": row.get("pause_rate_pct"),
        "avg_pauses":     row.get("avg_pauses_per_paused_session"),
        "dist": [
            {"label": "0次（无暂停）", "pct": round((row.get("cnt_0") or 0) / total * 100, 1)},
            {"label": "1次",          "pct": round((row.get("cnt_1") or 0) / total * 100, 1)},
            {"label": "2次",          "pct": round((row.get("cnt_2") or 0) / total * 100, 1)},
            {"label": "3+次",         "pct": round((row.get("cnt_3plus") or 0) / total * 100, 1)},
        ],
    }


def query_evt_source(start: str, end: str) -> list:
    """操作来源分布（APP vs 硬件），来自 DWD evtsource 字段。"""
    return _q(f"""
        SELECT
            CASE evtsource
                WHEN 'remote_app'    THEN 'APP操作'
                WHEN 'local_device'  THEN '硬件操作'
                ELSE evtsource
            END AS source_type,
            COUNT(*) AS event_count,
            ROUND(COUNT(*) / SUM(COUNT(*)) OVER(), 4) AS pct
        FROM {DWD}
        WHERE evt_dt BETWEEN %s AND %s
          AND evtsource IS NOT NULL
          AND eventname IN ('pump_start', 'pump_end', 'pump_manual_adjust_evt')
        GROUP BY source_type
        ORDER BY event_count DESC
    """, [start, end])


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

def query_chart01(start: str, end: str):
    return _q(f"""
        SELECT evt_dt AS dt,
            SUM(dau)            AS dau,
            SUM(active_devices) AS active_devices
        FROM {DAILY}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
        GROUP BY evt_dt ORDER BY evt_dt
    """, [start, end])


def query_chart02(start: str, end: str):
    return _q(f"""
        SELECT evt_dt AS dt,
            SUM(total_sessions) AS session_count
        FROM {DAILY}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
        GROUP BY evt_dt ORDER BY evt_dt
    """, [start, end])


def query_chart03(start: str, end: str):
    return _q(f"""
        SELECT finalModeType AS mode_type,
            COUNT(DISTINCT useSessionId) AS session_count,
            ROUND(COUNT(DISTINCT useSessionId)
                / SUM(COUNT(DISTINCT useSessionId)) OVER(), 5) AS pct
        FROM {SESS}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
          AND finalModeType IS NOT NULL
        GROUP BY mode_type
        ORDER BY session_count DESC
    """, [start, end])


def query_chart04(start: str, end: str):
    return _q(f"""
        SELECT
            CASE
                WHEN CAST(finalSuctionLevel AS INT) BETWEEN 1 AND 3 THEN '1–3档'
                WHEN CAST(finalSuctionLevel AS INT) BETWEEN 4 AND 6 THEN '4–6档'
                WHEN CAST(finalSuctionLevel AS INT) BETWEEN 7 AND 9 THEN '7–9档'
                ELSE '9+档'
            END AS level_bucket,
            CASE
                WHEN CAST(finalSuctionLevel AS INT) BETWEEN 1 AND 3 THEN 1
                WHEN CAST(finalSuctionLevel AS INT) BETWEEN 4 AND 6 THEN 2
                WHEN CAST(finalSuctionLevel AS INT) BETWEEN 7 AND 9 THEN 3
                ELSE 4
            END AS bucket_order,
            COUNT(DISTINCT useSessionId) AS session_count,
            ROUND(COUNT(DISTINCT useSessionId)
                / SUM(COUNT(DISTINCT useSessionId)) OVER(), 5) AS pct
        FROM {SESS}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
          AND finalSuctionLevel IS NOT NULL
        GROUP BY level_bucket, bucket_order
        ORDER BY bucket_order
    """, [start, end])


def query_chart05(start: str, end: str):
    return _q(f"""
        SELECT local_hour,
            COUNT(DISTINCT useSessionId) AS session_count,
            ROUND(COUNT(DISTINCT useSessionId)
                / SUM(COUNT(DISTINCT useSessionId)) OVER(), 5) AS pct
        FROM {SESS}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
          AND local_hour IS NOT NULL
        GROUP BY local_hour
        ORDER BY session_count DESC
        LIMIT 6
    """, [start, end])


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

def query_chart06_user(start: str, end: str):
    return _q(f"""
        SELECT base_dt AS base_date,
            d1_user_ret AS d1_user_retention_pct,
            d7_user_ret AS d7_user_retention_pct
        FROM {RET}
        WHERE deviceCode = 'ALL'
          AND base_dt BETWEEN %s AND %s
        ORDER BY base_dt
    """, [start, end])


def query_chart06_device(start: str, end: str):
    return _q(f"""
        SELECT base_dt AS base_date,
            d1_device_ret AS d1_device_retention_pct,
            d7_device_ret AS d7_device_retention_pct
        FROM {RET}
        WHERE deviceCode = 'ALL'
          AND base_dt BETWEEN %s AND %s
        ORDER BY base_dt
    """, [start, end])


def query_new_user_dev(start: str, end: str):
    return _q(f"""
        SELECT evt_dt AS dt,
            SUM(new_users)   AS new_users,
            SUM(new_devices) AS new_devices
        FROM {DAILY}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
        GROUP BY evt_dt ORDER BY evt_dt
    """, [start, end])


def query_chart07(start: str, end: str):
    """用户最长连续活跃天数分布，基于 dws_pump_session_df uid+evt_dt。"""
    return _q(f"""
        WITH user_dates AS (
            SELECT uid, evt_dt AS active_date
            FROM {SESS}
            WHERE uid IS NOT NULL
            GROUP BY uid, evt_dt
        ),
        numbered AS (
            SELECT uid, active_date,
                ROW_NUMBER() OVER (PARTITION BY uid ORDER BY active_date) AS rn
            FROM user_dates
        ),
        grouped AS (
            SELECT uid, active_date,
                DATE_SUB(active_date, INTERVAL rn DAY) AS grp_key
            FROM numbered
        ),
        streak_len AS (
            SELECT uid, grp_key, COUNT(*) AS streak_days
            FROM grouped GROUP BY uid, grp_key
        ),
        max_streak AS (
            SELECT uid, MAX(streak_days) AS max_consecutive_days
            FROM streak_len GROUP BY uid
        )
        SELECT
            CASE
                WHEN max_consecutive_days = 1 THEN '1天'
                WHEN max_consecutive_days BETWEEN 2 AND 3 THEN '2–3天'
                WHEN max_consecutive_days BETWEEN 4 AND 7 THEN '4–7天'
                WHEN max_consecutive_days BETWEEN 8 AND 14 THEN '8–14天'
                WHEN max_consecutive_days BETWEEN 15 AND 30 THEN '15–30天'
                ELSE '30+天'
            END AS streak_bucket,
            CASE
                WHEN max_consecutive_days = 1 THEN 1
                WHEN max_consecutive_days BETWEEN 2 AND 3 THEN 2
                WHEN max_consecutive_days BETWEEN 4 AND 7 THEN 4
                WHEN max_consecutive_days BETWEEN 8 AND 14 THEN 8
                WHEN max_consecutive_days BETWEEN 15 AND 30 THEN 15
                ELSE 31
            END AS bucket_order,
            COUNT(uid) AS user_count,
            ROUND(COUNT(uid) / SUM(COUNT(uid)) OVER(), 4) AS pct
        FROM max_streak
        GROUP BY streak_bucket, bucket_order
        ORDER BY bucket_order
    """, [])


def query_table01(start: str, end: str):
    """新用户同期留存队列表，按激活日期范围过滤。"""
    return _q(f"""
        WITH user_first AS (
            SELECT uid, MIN(evt_dt) AS install_date
            FROM {SESS}
            WHERE uid IS NOT NULL{_dc_and()}
            GROUP BY uid
        ),
        user_active AS (
            SELECT uid, evt_dt AS active_date
            FROM {SESS}
            WHERE uid IS NOT NULL{_dc_and()}
            GROUP BY uid, evt_dt
        ),
        week_base AS (
            SELECT uid, install_date,
                CAST(date_trunc('week', install_date) AS DATE) AS install_week
            FROM user_first
            WHERE install_date BETWEEN %s AND %s
        )
        SELECT w.install_week,
            COUNT(DISTINCT w.uid) AS new_users,
            ROUND(COUNT(DISTINCT CASE WHEN a.active_date = DATE_ADD(w.install_date, INTERVAL 1 DAY)
                THEN w.uid END) / NULLIF(COUNT(DISTINCT w.uid), 0), 4) AS d1_pct,
            ROUND(COUNT(DISTINCT CASE WHEN a.active_date = DATE_ADD(w.install_date, INTERVAL 3 DAY)
                THEN w.uid END) / NULLIF(COUNT(DISTINCT w.uid), 0), 4) AS d3_pct,
            ROUND(COUNT(DISTINCT CASE WHEN a.active_date = DATE_ADD(w.install_date, INTERVAL 7 DAY)
                THEN w.uid END) / NULLIF(COUNT(DISTINCT w.uid), 0), 4) AS d7_pct,
            ROUND(COUNT(DISTINCT CASE WHEN a.active_date = DATE_ADD(w.install_date, INTERVAL 14 DAY)
                THEN w.uid END) / NULLIF(COUNT(DISTINCT w.uid), 0), 4) AS d14_pct
        FROM week_base w
        LEFT JOIN user_active a ON w.uid = a.uid
        GROUP BY w.install_week
        ORDER BY w.install_week
    """, [start, end])


def query_retention_summary(start: str, end: str) -> dict:
    """留存汇总指标：日均 DAU/设备数、区间内平均留存率，昨日新增数 + 环比对比。"""
    avg_row = _one(_q(f"""
        SELECT
            ROUND(AVG(d1_user_ret), 5)    AS avg_d1_user_ret,
            ROUND(AVG(d7_user_ret), 5)    AS avg_d7_user_ret,
            ROUND(AVG(d1_device_ret), 5)  AS avg_d1_device_ret,
            ROUND(AVG(d7_device_ret), 5)  AS avg_d7_device_ret
        FROM {RET}
        WHERE deviceCode = 'ALL'
          AND base_dt BETWEEN %s AND %s
    """, [start, end]))
    dau_row = _one(_q(f"""
        SELECT
            ROUND(AVG(total_dau), 0)     AS avg_dau,
            ROUND(AVG(total_devices), 0) AS avg_devices
        FROM (
            SELECT evt_dt,
                SUM(dau)            AS total_dau,
                SUM(active_devices) AS total_devices
            FROM {DAILY}
            WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
            GROUP BY evt_dt
        ) t
    """, [start, end]))
    new_row = _one(_q(f"""
        SELECT SUM(new_users) AS new_users_yday, SUM(new_devices) AS new_devices_yday
        FROM {DAILY}
        WHERE evt_dt = (SELECT MAX(evt_dt) FROM {DAILY} WHERE evt_dt <= %s)
    """, [end]))

    # comparison: latest day vs day-before and 7d avg
    today_snap = _query_daily_snapshot(end)
    prev1_snap = _query_daily_snapshot(_day_before(end))
    prev7_avg  = _query_daily_7d_avg(_day_before(end))

    def cmp(field):
        return {
            "d1_delta": _delta_pct(today_snap.get(field), prev1_snap.get(field)),
            "d7_delta": _delta_pct(today_snap.get(field), prev7_avg.get(field)),
        }

    # retention rate comparison (latest within range vs day before and 7d avg)
    ret_today = _one(_q(f"""
        SELECT d1_user_ret, d7_user_ret, d1_device_ret, d7_device_ret
        FROM {RET} WHERE deviceCode='ALL' AND base_dt <= %s ORDER BY base_dt DESC LIMIT 1
    """, [end]))
    ret_prev = _one(_q(f"""
        SELECT d1_user_ret, d7_user_ret, d1_device_ret, d7_device_ret
        FROM {RET} WHERE deviceCode='ALL' AND base_dt <= %s ORDER BY base_dt DESC LIMIT 1
    """, [_day_before(end)]))
    ret_7d_avg = _one(_q(f"""
        SELECT
            ROUND(AVG(d1_user_ret), 5)   AS d1_user_ret,
            ROUND(AVG(d7_user_ret), 5)   AS d7_user_ret,
            ROUND(AVG(d1_device_ret), 5) AS d1_device_ret,
            ROUND(AVG(d7_device_ret), 5) AS d7_device_ret
        FROM (
            SELECT d1_user_ret, d7_user_ret, d1_device_ret, d7_device_ret
            FROM {RET} WHERE deviceCode='ALL' AND base_dt <= %s
            ORDER BY base_dt DESC LIMIT 7
        ) t
    """, [_day_before(end)]))

    return {
        "avg_dau":         dau_row.get("avg_dau"),
        "avg_devices":     dau_row.get("avg_devices"),
        # KPI cards show latest day's retention (most recent row in RET table)
        "d1_user_pct":     ret_today.get("d1_user_ret"),
        "d7_user_pct":     ret_today.get("d7_user_ret"),
        "d1_device_pct":   ret_today.get("d1_device_ret"),
        "d7_device_pct":   ret_today.get("d7_device_ret"),
        # period averages (for summary reference)
        "avg_d1_user_pct":   avg_row.get("avg_d1_user_ret"),
        "avg_d7_user_pct":   avg_row.get("avg_d7_user_ret"),
        "avg_d1_device_pct": avg_row.get("avg_d1_device_ret"),
        "avg_d7_device_pct": avg_row.get("avg_d7_device_ret"),
        "new_users_yday":  new_row.get("new_users_yday"),
        "new_devices_yday": new_row.get("new_devices_yday"),
        # comparisons
        "dau_cmp":           cmp("dau"),
        "d1_user_cmp": {
            "d1_delta": _delta_pp(ret_today.get("d1_user_ret"), ret_prev.get("d1_user_ret")),
            "d7_delta": _delta_pp(ret_today.get("d1_user_ret"), ret_7d_avg.get("d1_user_ret")),
        },
        "d7_user_cmp": {
            "d1_delta": _delta_pp(ret_today.get("d7_user_ret"), ret_prev.get("d7_user_ret")),
            "d7_delta": _delta_pp(ret_today.get("d7_user_ret"), ret_7d_avg.get("d7_user_ret")),
        },
        "d1_device_cmp": {
            "d1_delta": _delta_pp(ret_today.get("d1_device_ret"), ret_prev.get("d1_device_ret")),
            "d7_delta": _delta_pp(ret_today.get("d1_device_ret"), ret_7d_avg.get("d1_device_ret")),
        },
        "d7_device_cmp": {
            "d1_delta": _delta_pp(ret_today.get("d7_device_ret"), ret_prev.get("d7_device_ret")),
            "d7_delta": _delta_pp(ret_today.get("d7_device_ret"), ret_7d_avg.get("d7_device_ret")),
        },
        "dau_yday":        today_snap.get("dau"),
        "new_users_cmp":   cmp("new_users"),
        "new_devices_cmp": cmp("new_devices"),
    }


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def query_chart_sess_daily_trend(start: str, end: str):
    return _q(f"""
        SELECT evt_dt AS dt, SUM(total_sessions) AS session_count
        FROM {DAILY}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
        GROUP BY evt_dt ORDER BY evt_dt
    """, [start, end])


def query_chart_sess_avg_per_user(start: str, end: str):
    return _q(f"""
        SELECT evt_dt AS dt,
            ROUND(SUM(total_sessions) / NULLIF(SUM(dau), 0), 2) AS avg_sessions
        FROM {DAILY}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
        GROUP BY evt_dt ORDER BY evt_dt
    """, [start, end])


def query_chart08(start: str, end: str):
    return _q(f"""
        WITH session_cnt AS (
            SELECT evt_dt, uid,
                COUNT(DISTINCT useSessionId) AS pump_sessions
            FROM {SESS}
            WHERE evt_dt BETWEEN %s AND %s AND uid IS NOT NULL
            GROUP BY evt_dt, uid
        )
        SELECT
            CASE
                WHEN pump_sessions = 1  THEN '1次'
                WHEN pump_sessions = 2  THEN '2次'
                WHEN pump_sessions = 3  THEN '3次'
                WHEN pump_sessions = 4  THEN '4次'
                WHEN pump_sessions = 5  THEN '5次'
                WHEN pump_sessions BETWEEN 6  AND 10 THEN '6–10次'
                WHEN pump_sessions BETWEEN 11 AND 20 THEN '11–20次'
                ELSE '21+次'
            END AS session_bucket,
            CASE
                WHEN pump_sessions = 1  THEN 1
                WHEN pump_sessions = 2  THEN 2
                WHEN pump_sessions = 3  THEN 3
                WHEN pump_sessions = 4  THEN 4
                WHEN pump_sessions = 5  THEN 5
                WHEN pump_sessions BETWEEN 6  AND 10 THEN 6
                WHEN pump_sessions BETWEEN 11 AND 20 THEN 11
                ELSE 21
            END AS bucket_order,
            COUNT(*) AS user_day_count,
            ROUND(COUNT(*) / SUM(COUNT(*)) OVER(), 4) AS pct
        FROM session_cnt
        GROUP BY session_bucket, bucket_order
        ORDER BY bucket_order
    """, [start, end])


def query_chart09(start: str, end: str):
    return _q(f"""
        WITH session_cnt AS (
            SELECT evt_dt, uid,
                COUNT(DISTINCT useSessionId) AS pump_sessions
            FROM {SESS}
            WHERE evt_dt BETWEEN %s AND %s AND uid IS NOT NULL
            GROUP BY evt_dt, uid
        ),
        bucketed AS (
            SELECT evt_dt, uid,
                CASE
                    WHEN pump_sessions = 1 THEN '1次'
                    WHEN pump_sessions = 2 THEN '2次'
                    WHEN pump_sessions = 3 THEN '3次'
                    WHEN pump_sessions BETWEEN 4 AND 5 THEN '4–5次'
                    ELSE '6+次'
                END AS session_bucket
            FROM session_cnt
        )
        SELECT evt_dt AS dt, session_bucket,
            COUNT(uid) AS cnt_of_day,
            ROUND(COUNT(uid) / SUM(COUNT(uid)) OVER (PARTITION BY evt_dt), 4) AS pct_of_day
        FROM bucketed
        GROUP BY evt_dt, session_bucket
        ORDER BY evt_dt, session_bucket
    """, [start, end])


def query_chart10(start: str, end: str):
    return _q(f"""
        WITH user_total AS (
            SELECT uid, COUNT(DISTINCT useSessionId) AS total_sessions
            FROM {SESS}
            WHERE evt_dt BETWEEN %s AND %s AND uid IS NOT NULL
            GROUP BY uid
        )
        SELECT
            CASE
                WHEN total_sessions = 1                      THEN '1次'
                WHEN total_sessions BETWEEN 2   AND 5        THEN '2–5次'
                WHEN total_sessions BETWEEN 6   AND 10       THEN '6–10次'
                WHEN total_sessions BETWEEN 11  AND 20       THEN '11–20次'
                WHEN total_sessions BETWEEN 21  AND 50       THEN '21–50次'
                WHEN total_sessions BETWEEN 51  AND 100      THEN '51–100次'
                ELSE '100+次'
            END AS cumulative_bucket,
            CASE
                WHEN total_sessions = 1                 THEN 1
                WHEN total_sessions BETWEEN 2  AND 5    THEN 2
                WHEN total_sessions BETWEEN 6  AND 10   THEN 6
                WHEN total_sessions BETWEEN 11 AND 20   THEN 11
                WHEN total_sessions BETWEEN 21 AND 50   THEN 21
                WHEN total_sessions BETWEEN 51 AND 100  THEN 51
                ELSE 101
            END AS bucket_order,
            COUNT(uid) AS user_count,
            ROUND(COUNT(uid) / SUM(COUNT(uid)) OVER(), 4) AS pct
        FROM user_total
        GROUP BY cumulative_bucket, bucket_order
        ORDER BY bucket_order
    """, [start, end])


def query_chart11(start: str, end: str):
    return _q(f"""
        WITH device_total AS (
            SELECT pump_device_id,
                COUNT(DISTINCT useSessionId) AS total_sessions
            FROM {SESS}
            WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
              AND pump_device_id IS NOT NULL
            GROUP BY pump_device_id
        )
        SELECT
            CASE
                WHEN total_sessions = 1                      THEN '1次'
                WHEN total_sessions BETWEEN 2   AND 5        THEN '2–5次'
                WHEN total_sessions BETWEEN 6   AND 10       THEN '6–10次'
                WHEN total_sessions BETWEEN 11  AND 20       THEN '11–20次'
                WHEN total_sessions BETWEEN 21  AND 50       THEN '21–50次'
                WHEN total_sessions BETWEEN 51  AND 100      THEN '51–100次'
                ELSE '100+次'
            END AS cumulative_bucket,
            CASE
                WHEN total_sessions = 1                 THEN 1
                WHEN total_sessions BETWEEN 2  AND 5    THEN 2
                WHEN total_sessions BETWEEN 6  AND 10   THEN 6
                WHEN total_sessions BETWEEN 11 AND 20   THEN 11
                WHEN total_sessions BETWEEN 21 AND 50   THEN 21
                WHEN total_sessions BETWEEN 51 AND 100  THEN 51
                ELSE 101
            END AS bucket_order,
            COUNT(pump_device_id) AS device_count,
            ROUND(COUNT(pump_device_id) / SUM(COUNT(pump_device_id)) OVER(), 4) AS pct
        FROM device_total
        GROUP BY cumulative_bucket, bucket_order
        ORDER BY bucket_order
    """, [start, end])


def query_chart_mode_sess_avg_per_user(start: str, end: str):
    """各模式下人均每日吸奶次数：该模式总session数 / 统计天数 / 日均DAU"""
    return _q(f"""
        WITH mode_daily AS (
            SELECT evt_dt,
                modeType AS mode_type,
                COUNT(DISTINCT useSessionId) AS sess_cnt
            FROM {MODE}
            WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
            GROUP BY evt_dt, modeType
        ),
        dau_daily AS (
            SELECT evt_dt, SUM(dau) AS dau
            FROM {DAILY}
            WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
            GROUP BY evt_dt
        )
        SELECT
            m.mode_type,
            ROUND(SUM(m.sess_cnt) / NULLIF(SUM(d.dau), 0), 4) AS avg_sess_per_user
        FROM mode_daily m
        JOIN dau_daily d ON m.evt_dt = d.evt_dt
        GROUP BY m.mode_type
        ORDER BY avg_sess_per_user DESC
    """, [start, end, start, end])


def query_chart_mode_dur_avg_per_sess(start: str, end: str):
    """各模式下人均每次吸奶时长（分钟）：该模式总时长 / 该模式总session数"""
    return _q(f"""
        SELECT
            modeType AS mode_type,
            ROUND(SUM(duration_sec) / 60.0 / NULLIF(COUNT(DISTINCT useSessionId), 0), 2) AS avg_dur_per_sess_min
        FROM {MODE}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
          AND duration_sec <= 3600
        GROUP BY modeType
        ORDER BY avg_dur_per_sess_min DESC
    """, [start, end])


def query_chart_mode_sess_dist(start: str, end: str):
    return _q(f"""
        SELECT modeType AS mode_type,
            COUNT(DISTINCT useSessionId) AS cnt
        FROM {MODE}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
        GROUP BY modeType
        ORDER BY cnt DESC
    """, [start, end])


def query_chart_mode_sess_trend(start: str, end: str):
    return _q(f"""
        SELECT evt_dt AS dt,
            modeType AS mode_type,
            COUNT(DISTINCT useSessionId) AS cnt,
            ROUND(COUNT(DISTINCT useSessionId)
                / SUM(COUNT(DISTINCT useSessionId)) OVER (PARTITION BY evt_dt), 5) AS pct
        FROM {MODE}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
        GROUP BY evt_dt, modeType
        ORDER BY evt_dt
    """, [start, end])


def query_sessions_summary(start: str, end: str) -> dict:
    row = _one(_q(f"""
        WITH ud AS (
            SELECT evt_dt, uid, COUNT(DISTINCT useSessionId) AS pump_sessions
            FROM {SESS}
            WHERE evt_dt BETWEEN %s AND %s AND uid IS NOT NULL
            GROUP BY evt_dt, uid
        )
        SELECT
            ROUND(SUM(IF(pump_sessions = 1, 1, 0)) / COUNT(*), 4) AS one_per_day_pct,
            MAX(pump_sessions) AS max_sessions_single_user
        FROM ud
    """, [start, end]))

    today_snap = _query_daily_snapshot(end)
    prev1_snap = _query_daily_snapshot(_day_before(end))
    prev7_avg  = _query_daily_7d_avg(_day_before(end))

    def cmp(field):
        return {
            "d1_delta": _delta_pct(today_snap.get(field), prev1_snap.get(field)),
            "d7_delta": _delta_pct(today_snap.get(field), prev7_avg.get(field)),
        }

    return {
        "one_per_day_pct":          row.get("one_per_day_pct"),
        "max_sessions_single_user": row.get("max_sessions_single_user"),
        "sessions_cmp":             cmp("sessions"),
        "avg_sessions_per_user_cmp": cmp("avg_sessions_per_user"),
        "max_sessions_cmp": {"d1_delta": None, "d7_delta": None},
        "one_per_day_cmp":  {"d1_delta": None, "d7_delta": None},
    }


# ---------------------------------------------------------------------------
# Duration
# ---------------------------------------------------------------------------

def query_chart_dur_daily_trend(start: str, end: str):
    return _q(f"""
        SELECT evt_dt AS dt,
            ROUND(SUM(total_duration_h), 2) AS total_hours
        FROM {DAILY}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
        GROUP BY evt_dt ORDER BY evt_dt
    """, [start, end])


def query_chart_dur_avg_per_user(start: str, end: str):
    return _q(f"""
        SELECT evt_dt AS dt,
            ROUND(SUM(total_duration_sec) / 60.0 / NULLIF(SUM(dau), 0), 2) AS avg_min_per_user
        FROM {DAILY}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
        GROUP BY evt_dt ORDER BY evt_dt
    """, [start, end])


def query_chart12(start: str, end: str):
    return _q(f"""
        SELECT
            CASE
                WHEN total_duration_sec <  300 THEN '0–5min'
                WHEN total_duration_sec <  600 THEN '5–10min'
                WHEN total_duration_sec <  900 THEN '10–15min'
                WHEN total_duration_sec < 1200 THEN '15–20min'
                WHEN total_duration_sec < 1500 THEN '20–25min'
                WHEN total_duration_sec < 1800 THEN '25–30min'
                WHEN total_duration_sec < 2100 THEN '30–35min'
                WHEN total_duration_sec < 2400 THEN '35–40min'
                WHEN total_duration_sec < 2700 THEN '40–45min'
                ELSE '45min+'
            END AS duration_bucket,
            CASE
                WHEN total_duration_sec <  300 THEN 1
                WHEN total_duration_sec <  600 THEN 2
                WHEN total_duration_sec <  900 THEN 3
                WHEN total_duration_sec < 1200 THEN 4
                WHEN total_duration_sec < 1500 THEN 5
                WHEN total_duration_sec < 1800 THEN 6
                WHEN total_duration_sec < 2100 THEN 7
                WHEN total_duration_sec < 2400 THEN 8
                WHEN total_duration_sec < 2700 THEN 9
                ELSE 10
            END AS bucket_order,
            COUNT(useSessionId) AS session_count,
            ROUND(COUNT(useSessionId) / SUM(COUNT(useSessionId)) OVER(), 4) AS pct
        FROM {SESS}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
          AND total_duration_sec IS NOT NULL
        GROUP BY duration_bucket, bucket_order
        ORDER BY bucket_order
    """, [start, end])


def query_chart13(start: str, end: str):
    return _q(f"""
        SELECT evt_dt AS dt,
            ROUND(SUM(avg_duration_min * total_sessions)
                / NULLIF(SUM(total_sessions), 0), 2) AS avg_duration_min
        FROM {DAILY}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
        GROUP BY evt_dt ORDER BY evt_dt
    """, [start, end])


def query_chart14(start: str, end: str):
    return _q(f"""
        SELECT evt_dt AS dt,
            ROUND(SUM(total_duration_h), 2) AS daily_hours,
            ROUND(MAX(cumulative_duration_h) / 1000.0, 3) AS cumulative_hours_k
        FROM {DAILY}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
        GROUP BY evt_dt ORDER BY evt_dt
    """, [start, end])


def query_chart_mode_dur_dist(start: str, end: str):
    return _q(f"""
        SELECT modeType AS mode_type,
            ROUND(SUM(duration_sec) / 60.0, 2) AS duration_min
        FROM {MODE}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
          AND duration_sec <= 3600
        GROUP BY modeType
        ORDER BY duration_min DESC
    """, [start, end])


def query_chart_mode_dur_trend(start: str, end: str):
    return _q(f"""
        SELECT evt_dt AS dt,
            modeType AS mode_type,
            ROUND(SUM(duration_sec) / 60.0, 2) AS dur_min,
            ROUND(SUM(duration_sec)
                / NULLIF(SUM(SUM(duration_sec)) OVER (PARTITION BY evt_dt), 0), 5) AS pct
        FROM {MODE}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
        GROUP BY evt_dt, modeType
        ORDER BY evt_dt
    """, [start, end])


def query_duration_summary(start: str, end: str) -> dict:
    row = _one(_q(f"""
        SELECT
            ROUND(SUM(total_duration_h), 2) AS total_duration_hours,
            ROUND(SUM(avg_duration_min * total_sessions)
                / NULLIF(SUM(total_sessions), 0), 2) AS avg_duration_min,
            ROUND(SUM(total_duration_sec) / 60.0
                / NULLIF(SUM(dau), 0)
                / NULLIF(COUNT(DISTINCT evt_dt), 0), 2) AS daily_min_per_user,
            ROUND(SUM(valid_sessions) / NULLIF(SUM(total_sessions), 0), 5) AS valid_session_rate_pct
        FROM {DAILY}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
    """, [start, end]))

    today_snap = _query_daily_snapshot(end)
    prev1_snap = _query_daily_snapshot(_day_before(end))
    prev7_avg  = _query_daily_7d_avg(_day_before(end))

    def cmp(field):
        return {
            "d1_delta": _delta_pct(today_snap.get(field), prev1_snap.get(field)),
            "d7_delta": _delta_pct(today_snap.get(field), prev7_avg.get(field)),
        }

    def cmp_pp(field):
        return {
            "d1_delta": _delta_pp(today_snap.get(field), prev1_snap.get(field)),
            "d7_delta": _delta_pp(today_snap.get(field), prev7_avg.get(field)),
        }

    return {
        "total_duration_hours":   row.get("total_duration_hours"),
        "avg_duration_min":       row.get("avg_duration_min"),
        "daily_min_per_user":     row.get("daily_min_per_user"),
        "valid_session_rate_pct": row.get("valid_session_rate_pct"),
        "total_hours_cmp":     cmp("duration_hours"),
        "avg_dur_min_cmp":     cmp("avg_dur_min"),
        "dur_per_user_cmp":    cmp("dur_per_user_min"),
        "valid_rate_cmp":      cmp_pp("valid_rate"),
    }


def query_sessions_kpi_yesterday(end: str) -> dict:
    """昨日次数快照：总次数、人均次数、1次/天占比、单日最高。"""
    today_snap = _query_daily_snapshot(end)
    prev1_snap = _query_daily_snapshot(_day_before(end))
    prev7_avg  = _query_daily_7d_avg(_day_before(end))

    def cmp(field):
        return {
            "d1_delta": _delta_pct(today_snap.get(field), prev1_snap.get(field)),
            "d7_delta": _delta_pct(today_snap.get(field), prev7_avg.get(field)),
        }

    # 昨日1次/天占比和单日最高从session表查
    yday_dt = today_snap.get("_dt") if today_snap.get("_dt") else end
    # use same date as snapshot (MAX evt_dt <= end)
    yday_row = _one(_q(f"""
        WITH ud AS (
            SELECT uid, COUNT(DISTINCT useSessionId) AS pump_sessions
            FROM {SESS}
            WHERE evt_dt = (SELECT MAX(evt_dt) FROM {DAILY} WHERE evt_dt <= %s)
              AND uid IS NOT NULL{_dc_and()}
            GROUP BY uid
        )
        SELECT
            ROUND(SUM(IF(pump_sessions = 1, 1, 0)) / NULLIF(COUNT(*), 0), 4) AS one_per_day_pct,
            MAX(pump_sessions) AS max_sessions_single_user
        FROM ud
    """, [end]))

    # 昨日1次/天占比和单日最高需要前一日数据做对比
    prev1_yday_row = _one(_q(f"""
        WITH ud AS (
            SELECT uid, COUNT(DISTINCT useSessionId) AS pump_sessions
            FROM {SESS}
            WHERE evt_dt = (SELECT MAX(evt_dt) FROM {DAILY} WHERE evt_dt <= %s)
              AND uid IS NOT NULL{_dc_and()}
            GROUP BY uid
        )
        SELECT
            ROUND(SUM(IF(pump_sessions = 1, 1, 0)) / NULLIF(COUNT(*), 0), 4) AS one_per_day_pct
        FROM ud
    """, [_day_before(end)]))

    prev7_one_per_day = _one(_q(f"""
        WITH base AS (
            SELECT evt_dt,
                COUNT(DISTINCT CASE WHEN sess_cnt = 1 THEN uid END) AS cnt_one,
                COUNT(DISTINCT uid) AS cnt_total
            FROM (
                SELECT evt_dt, uid, COUNT(DISTINCT useSessionId) AS sess_cnt
                FROM {SESS}
                WHERE evt_dt BETWEEN %s AND %s AND uid IS NOT NULL{_dc_and()}
                GROUP BY evt_dt, uid
            ) t
            GROUP BY evt_dt
        )
        SELECT ROUND(AVG(cnt_one / NULLIF(cnt_total, 0)), 4) AS one_per_day_pct
        FROM base
    """, [_day_offset(_day_before(end), -6), _day_before(end)]))

    return {
        "total_sessions":        today_snap.get("sessions"),
        "avg_sessions_per_user": today_snap.get("avg_sessions_per_user"),
        "one_per_day_pct":       yday_row.get("one_per_day_pct"),
        "max_sessions_single_user": yday_row.get("max_sessions_single_user"),
        "sessions_cmp":              cmp("sessions"),
        "avg_sessions_per_user_cmp": cmp("avg_sessions_per_user"),
        "one_per_day_cmp": {
            "d1_delta": _delta_pp(yday_row.get("one_per_day_pct"), prev1_yday_row.get("one_per_day_pct")),
            "d7_delta": _delta_pp(yday_row.get("one_per_day_pct"), prev7_one_per_day.get("one_per_day_pct")),
        },
    }


def query_duration_kpi_yesterday(end: str) -> dict:
    row = _one(_q(f"""
        SELECT
            ROUND(SUM(total_duration_h), 2) AS total_hours_yday,
            ROUND(SUM(avg_duration_min * total_sessions)
                / NULLIF(SUM(total_sessions), 0), 2) AS avg_dur_min_yday,
            ROUND(SUM(total_duration_sec) / 60.0
                / NULLIF(SUM(dau), 0), 2) AS daily_per_user_yday,
            ROUND(SUM(valid_sessions) / NULLIF(SUM(total_sessions), 0), 5) AS valid_rate_yday
        FROM {DAILY}
        WHERE evt_dt = (SELECT MAX(evt_dt) FROM {DAILY} WHERE evt_dt <= %s)
    """, [end]))
    return {
        "total_hours_yday":  row.get("total_hours_yday"),
        "avg_dur_min_yday":  row.get("avg_dur_min_yday"),
        "daily_per_user_yday": row.get("daily_per_user_yday"),
        "valid_rate_yday":   row.get("valid_rate_yday"),
    }


# ---------------------------------------------------------------------------
# Habits
# ---------------------------------------------------------------------------

def query_chart15(start: str, end: str):
    return _q(f"""
        SELECT
            CASE WHEN is_weekday = 1 THEN '工作日' ELSE '周末' END AS day_type,
            local_hour,
            COUNT(DISTINCT useSessionId) AS session_count,
            ROUND(COUNT(DISTINCT useSessionId)
                / SUM(COUNT(DISTINCT useSessionId)) OVER (
                    PARTITION BY is_weekday
                ), 5) AS pct
        FROM {SESS}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
          AND local_hour IS NOT NULL
        GROUP BY day_type, is_weekday, local_hour
        ORDER BY day_type, local_hour
    """, [start, end])


def query_table02(start: str, end: str):
    return _q(f"""
        SELECT finalModeType AS final_mode,
            CASE
                WHEN CAST(finalSuctionLevel AS INT) BETWEEN 1 AND 3 THEN '1–3档'
                WHEN CAST(finalSuctionLevel AS INT) BETWEEN 4 AND 6 THEN '4–6档'
                WHEN CAST(finalSuctionLevel AS INT) BETWEEN 7 AND 9 THEN '7–9档'
                ELSE '9+档'
            END AS level_bucket,
            COUNT(DISTINCT useSessionId) AS session_count,
            ROUND(COUNT(DISTINCT useSessionId)
                / SUM(COUNT(DISTINCT useSessionId))
                    OVER (PARTITION BY finalModeType), 4) AS pct_within_mode
        FROM {SESS}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
          AND finalModeType IS NOT NULL
          AND finalSuctionLevel IS NOT NULL
        GROUP BY final_mode, level_bucket
        ORDER BY final_mode, level_bucket
    """, [start, end])


def query_chart16(start: str, end: str):
    return _q(f"""
        SELECT
            CASE
                WHEN usedModeCount = 1  THEN '单一模式'
                WHEN usedModeCount = 2  THEN '混合 2 种'
                WHEN usedModeCount >= 3 THEN '混合 3+ 种'
                ELSE '未知'
            END AS mode_mix_type,
            CASE
                WHEN usedModeCount = 1  THEN 1
                WHEN usedModeCount = 2  THEN 2
                WHEN usedModeCount >= 3 THEN 3
                ELSE 4
            END AS bucket_order,
            COUNT(DISTINCT useSessionId) AS session_count,
            ROUND(COUNT(DISTINCT useSessionId)
                / SUM(COUNT(DISTINCT useSessionId)) OVER(), 4) AS pct
        FROM {SESS}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
          AND usedModeCount IS NOT NULL
        GROUP BY mode_mix_type, bucket_order
        ORDER BY bucket_order
    """, [start, end])


def query_chart17(start: str, end: str):
    """模式调节路径 — 仍需从 DWD 事件明细取（DWS 只存 path 字符串，不便于聚合）。"""
    return _q(f"""
        SELECT
            CASE adjustfrom
                WHEN '0' THEN '刺激' WHEN '1' THEN '泌乳'
                WHEN '2' THEN '混合' WHEN '3' THEN '自定义'
                ELSE adjustfrom END AS from_mode,
            CASE adjustto
                WHEN '0' THEN '刺激' WHEN '1' THEN '泌乳'
                WHEN '2' THEN '混合' WHEN '3' THEN '自定义'
                ELSE adjustto END AS to_mode,
            CONCAT(
                CASE adjustfrom
                    WHEN '0' THEN '刺激' WHEN '1' THEN '泌乳'
                    WHEN '2' THEN '混合' WHEN '3' THEN '自定义'
                    ELSE adjustfrom END,
                ' → ',
                CASE adjustto
                    WHEN '0' THEN '刺激' WHEN '1' THEN '泌乳'
                    WHEN '2' THEN '混合' WHEN '3' THEN '自定义'
                    ELSE adjustto END
            ) AS adjust_path,
            COUNT(*) AS adjust_count,
            ROUND(COUNT(*) / SUM(COUNT(*)) OVER(), 4) AS pct
        FROM {DWD}
        WHERE evt_dt BETWEEN %s AND %s
          AND eventname = 'pump_manual_adjust_evt'
          AND evttype = 'pump_mode'
          AND adjustfrom IS NOT NULL
          AND adjustto IS NOT NULL
        GROUP BY from_mode, to_mode, adjust_path
        ORDER BY adjust_count DESC
        LIMIT 6
    """, [start, end])


def query_chart18(start: str, end: str):
    return _q(f"""
        SELECT '调高档位' AS direction, SUM(level_up_cnt)   AS adjust_count FROM {SESS}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
        UNION ALL
        SELECT '调低档位' AS direction, SUM(level_down_cnt) AS adjust_count FROM {SESS}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
        UNION ALL
        SELECT '不变' AS direction,
            SUM(level_adj_cnt - level_up_cnt - level_down_cnt) AS adjust_count
        FROM {SESS}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
    """, [start, end, start, end, start, end])


def _chart18_with_pct(rows):
    total = sum((r.get("adjust_count") or 0) for r in rows)
    out = []
    for r in rows:
        cnt = r.get("adjust_count") or 0
        out.append({**r, "pct": round(cnt / total, 4) if total else None})
    return out


def query_chart19(start: str, end: str):
    level = _q(f"""
        WITH lvl AS (
            SELECT
                CASE WHEN level_adj_cnt >= 10 THEN 10 ELSE level_adj_cnt END AS adj_times
            FROM {SESS}
            WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
        )
        SELECT
            CASE WHEN adj_times >= 10 THEN '10次+' ELSE CAST(adj_times AS VARCHAR) END AS adj_bucket,
            adj_times AS bucket_order,
            COUNT(*) AS session_count,
            ROUND(COUNT(*) / SUM(COUNT(*)) OVER(), 4) AS pct
        FROM lvl
        GROUP BY adj_bucket, bucket_order
        ORDER BY bucket_order
    """, [start, end])
    mode = _q(f"""
        WITH md AS (
            SELECT
                CASE WHEN mode_adj_cnt >= 10 THEN 10 ELSE mode_adj_cnt END AS adj_times
            FROM {SESS}
            WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
        )
        SELECT
            CASE WHEN adj_times >= 10 THEN '10次+' ELSE CAST(adj_times AS VARCHAR) END AS adj_bucket,
            adj_times AS bucket_order,
            COUNT(*) AS session_count,
            ROUND(COUNT(*) / SUM(COUNT(*)) OVER(), 4) AS pct
        FROM md
        GROUP BY adj_bucket, bucket_order
        ORDER BY bucket_order
    """, [start, end])
    return {"level": level, "mode": mode}


def query_habits_summary(start: str, end: str) -> dict:
    """模式/档位调节汇总：占比 + 次均调节次数。"""
    row = _one(_q(f"""
        SELECT
            COUNT(DISTINCT useSessionId)                                  AS total_sessions,
            COUNT(DISTINCT CASE WHEN mode_adj_cnt  > 0 THEN useSessionId END) AS mode_adj_sessions,
            COUNT(DISTINCT CASE WHEN level_adj_cnt > 0 THEN useSessionId END) AS level_adj_sessions,
            ROUND(SUM(mode_adj_cnt)  / NULLIF(COUNT(DISTINCT useSessionId), 0), 2) AS avg_mode_adj,
            ROUND(SUM(level_adj_cnt) / NULLIF(COUNT(DISTINCT useSessionId), 0), 2) AS avg_level_adj
        FROM {SESS}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
    """, [start, end]))
    total = row.get("total_sessions") or 0
    mode_adj = row.get("mode_adj_sessions") or 0
    level_adj = row.get("level_adj_sessions") or 0
    return {
        "mode_adj_rate_pct":  round(mode_adj  / total * 100, 1) if total else None,
        "level_adj_rate_pct": round(level_adj / total * 100, 1) if total else None,
        "avg_mode_adj":  row.get("avg_mode_adj"),
        "avg_level_adj": row.get("avg_level_adj"),
    }


# ---------------------------------------------------------------------------
# Funnel
# ---------------------------------------------------------------------------

def query_chart20(start: str, end: str):
    return _q(f"""
        SELECT evt_dt AS dt,
            SUM(power_on_cnt)      AS power_on_cnt,
            SUM(total_sessions)    AS started_cnt,
            SUM(complete_sessions) AS ended_cnt,
            SUM(valid_sessions)    AS valid_cnt
        FROM {DAILY}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
        GROUP BY evt_dt ORDER BY evt_dt
    """, [start, end])


def query_chart21(start: str, end: str):
    return _q(f"""
        SELECT evt_dt AS dt,
            ROUND(SUM(complete_sessions) / NULLIF(SUM(total_sessions), 0) * 100, 2) AS completion_rate_pct,
            ROUND(SUM(valid_sessions) / NULLIF(SUM(complete_sessions), 0) * 100, 2) AS valid_rate_pct
        FROM {DAILY}
        WHERE evt_dt BETWEEN %s AND %s{_dc_and()}
        GROUP BY evt_dt ORDER BY evt_dt
    """, [start, end])


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def build_section(section: str, start: str, end: str, device_code: str = "") -> dict:
    global _active_device_code
    _active_device_code = device_code
    if section == "overview":
        kpi01 = query_kpi01(start, end)
        d1_ret = query_d1_ret(start, end)
        return {
            "kpi01": {
                "total_users":           kpi01.get("total_users"),
                "total_devices":         kpi01.get("total_devices"),
                "total_sessions":        kpi01.get("total_sessions"),
                "avg_sessions_per_user": kpi01.get("avg_sessions_per_user"),
            },
            "kpi01_extra": {
                "total_duration_hours":   kpi01.get("total_duration_hours"),
                "avg_duration_min":       kpi01.get("avg_duration_min"),
                "d1_retention_pct":       d1_ret,
                "devices_per_user":       kpi01.get("devices_per_user"),
                "valid_session_rate_pct": kpi01.get("valid_session_rate_pct"),
            },
            "kpi_yesterday":  query_kpi_yesterday(end),
            "chart01": query_chart01(start, end),
            "chart02": query_chart02(start, end),
            "chart03": query_chart03(start, end),
            "chart04": query_chart04(start, end),
            "chart05": query_chart05(start, end),
        }

    if section == "retention":
        summary = query_retention_summary(start, end)
        return {
            "summary": summary,
            "chart06_user":   query_chart06_user(start, end),
            "chart06_device": query_chart06_device(start, end),
            "newUserDev":     query_new_user_dev(start, end),
            "chart07":        query_chart07(start, end),
            "table01":        query_table01(start, end),
        }

    if section == "sessions":
        kpi = query_kpi01(start, end)
        summary = query_sessions_summary(start, end)
        return {
            "kpi01": {
                "total_sessions":        kpi.get("total_sessions"),
                "avg_sessions_per_user": kpi.get("avg_sessions_per_user"),
            },
            "summary": summary,
            "kpi_yesterday":            query_sessions_kpi_yesterday(end),
            "chart_sess_daily_trend":   query_chart_sess_daily_trend(start, end),
            "chart_sess_avg_per_user":  query_chart_sess_avg_per_user(start, end),
            "chart08":                  query_chart08(start, end),
            "chart09":                  query_chart09(start, end),
            "chart10":                  query_chart10(start, end),
            "chart11":                  query_chart11(start, end),
            "chart_mode_sess_dist":     query_chart_mode_sess_dist(start, end),
            "chart_mode_sess_trend":    query_chart_mode_sess_trend(start, end),
            "chart_mode_sess_avg":      query_chart_mode_sess_avg_per_user(start, end),
        }

    if section == "duration":
        summary = query_duration_summary(start, end)
        return {
            "summary":           summary,
            "kpi_yesterday":     query_duration_kpi_yesterday(end),
            "chart_dur_daily_trend":   query_chart_dur_daily_trend(start, end),
            "chart_dur_avg_per_user":  query_chart_dur_avg_per_user(start, end),
            "chart12":                 query_chart12(start, end),
            "chart13":                 query_chart13(start, end),
            "chart14":                 query_chart14(start, end),
            "chart_mode_dur_dist":     query_chart_mode_dur_dist(start, end),
            "chart_mode_dur_trend":    query_chart_mode_dur_trend(start, end),
            "chart_mode_dur_avg":      query_chart_mode_dur_avg_per_sess(start, end),
        }

    if section == "habits":
        c18_raw = query_chart18(start, end)
        return {
            "chart15":      query_chart15(start, end),
            "table02":      query_table02(start, end),
            "chart16":      query_chart16(start, end),
            "chart17":      query_chart17(start, end),
            "chart18":      _chart18_with_pct(c18_raw),
            "chart19":      query_chart19(start, end),
            "adj_summary":  query_habits_summary(start, end),
            "pause_stats":  query_pause_stats(start, end),
            "evt_source":   query_evt_source(start, end),
        }

    if section == "funnel":
        kpi02 = query_kpi02(start, end)
        po = kpi02.get("power_on_cnt") or 0
        st = kpi02.get("started_sessions") or 0
        en = kpi02.get("ended_sessions") or 0
        va = kpi02.get("valid_sessions") or 0
        # charts use a fixed 30-day trailing window for readability
        trend_start = _day_offset(end, -29)
        return {
            "kpi02": kpi02,
            "funnel": {
                "power_on_cnt":       po,
                "started_sessions":   st,
                "ended_sessions":     en,
                "valid_sessions":     va,
                "start_rate_pct":      round(st * 100 / po, 1) if po else None,
                "completion_rate_pct": round(en * 100 / st, 1) if st else None,
                "valid_rate_pct":      round(va * 100 / st, 1) if st else None,
            },
            "chart20": query_chart20(trend_start, end),
            "chart21": query_chart21(trend_start, end),
        }

    if section == "firmware":
        # firmware 数据由 metabase_server.py 直接调用 Metabase card API 返回
        # pump_data.py 不直接访问 Metabase，此处返回空占位
        return {"_firmware_via_mb": True}

    raise ValueError(f"unknown section: {section}")


def build_pump_dashboard(start_dt: str = "", end_dt: str = "", section: str = "overview", device_code: str = "") -> dict:
    ensure_db()
    start, end = parse_date_range(start_dt, end_dt)
    sec = section if section in SECTIONS else "overview"
    data = build_section(sec, start, end, device_code)
    return {"code": 0, "start_dt": start, "end_dt": end, "section": sec, "data": data}
