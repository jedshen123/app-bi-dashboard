"""
用户标签数据看板 - 后端服务
直接通过 MySQL 协议连接 StarRocks，提供看板 API
运行前设置环境变量（或直接在下方配置）：
  export STARROCKS_PASSWORD="你的密码"
  python server.py
然后访问 http://localhost:5000
"""

import os
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# ===================== 数据库配置 =====================
DB_HOST     = os.getenv("STARROCKS_HOST",     "starrocks-us.cozyinnov.com")
DB_PORT     = int(os.getenv("STARROCKS_PORT", "9030"))
DB_USER     = os.getenv("STARROCKS_USER",     "lute_app_dw_readonly")
DB_PASSWORD = os.getenv("STARROCKS_PASSWORD", "")   # ← 必须通过环境变量设置
DB_DATABASE = os.getenv("STARROCKS_DB",       "lute_app_dw")
TABLE_NAME  = "dwd_app_user_flag_info"
SERVER_PORT = int(os.getenv("PORT", "5000"))
# =====================================================


def get_conn():
    """创建 StarRocks（MySQL 协议）连接，优先使用 mysql-connector，降级到 pymysql"""
    try:
        import mysql.connector
        return mysql.connector.connect(
            host=DB_HOST, port=DB_PORT,
            user=DB_USER, password=DB_PASSWORD,
            database=DB_DATABASE, connect_timeout=10
        )
    except ImportError:
        pass
    try:
        import pymysql
        return pymysql.connect(
            host=DB_HOST, port=DB_PORT,
            user=DB_USER, password=DB_PASSWORD,
            database=DB_DATABASE,
            connect_timeout=10, charset="utf8mb4"
        )
    except ImportError:
        raise RuntimeError(
            "请安装数据库驱动：pip install mysql-connector-python  或  pip install pymysql"
        )


def run_sql(sql: str) -> list[dict]:
    """执行查询，返回字典列表"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()


def build_dashboard_data() -> dict:
    """执行所有看板查询，返回聚合 JSON"""

    # ---------- 1. 总体概览 ----------
    ov_rows = run_sql(f"""
        SELECT
          COUNT(DISTINCT uid)                                            AS total_users,
          SUM(CASE WHEN active_status = '1' THEN 1 ELSE 0 END)         AS active_users,
          SUM(CASE WHEN active_status = '0' THEN 1 ELSE 0 END)         AS inactive_users,
          SUM(CASE WHEN deleted = '1'       THEN 1 ELSE 0 END)         AS deleted_users,
          COUNT(DISTINCT country_ad_ch)                                 AS country_count,
          MAX(update_date)                                              AS latest_update_date,
          MAX(event_date)                                               AS latest_event_date
        FROM {TABLE_NAME}
    """)
    ov = ov_rows[0] if ov_rows else {}
    total  = int(ov.get("total_users")  or 1)
    active = int(ov.get("active_users") or 0)

    # ---------- 2. 数据来源分布 ----------
    source_rows = run_sql(f"""
        SELECT data_source, COUNT(DISTINCT uid) AS user_count
        FROM {TABLE_NAME}
        WHERE data_source IS NOT NULL AND data_source != ''
        GROUP BY data_source
        ORDER BY user_count DESC
    """)

    # ---------- 3. 国家 TOP 10 ----------
    country_rows = run_sql(f"""
        SELECT country_ad_ch, COUNT(DISTINCT uid) AS user_count
        FROM {TABLE_NAME}
        WHERE country_ad_ch IS NOT NULL AND country_ad_ch != ''
        GROUP BY country_ad_ch
        ORDER BY user_count DESC
        LIMIT 10
    """)

    # ---------- 4. 近 30 天日活趋势 ----------
    trend_rows = run_sql(f"""
        SELECT event_date, COUNT(DISTINCT uid) AS daily_users
        FROM {TABLE_NAME}
        WHERE event_date IS NOT NULL AND event_date != ''
        GROUP BY event_date
        ORDER BY event_date DESC
        LIMIT 30
    """)
    trend_rows = list(reversed(trend_rows))  # 升序显示

    # ---------- 5. 行为标记统计 ----------
    flag_rows = run_sql(f"""
        SELECT
          SUM(CASE WHEN act_flag         = '1' THEN 1 ELSE 0 END) AS act_users,
          SUM(CASE WHEN device_vis_flag  = '1' THEN 1 ELSE 0 END) AS device_vis_users,
          SUM(CASE WHEN stat_vis_flag    = '1' THEN 1 ELSE 0 END) AS stat_vis_users,
          SUM(CASE WHEN dynamic_vis_flag = '1' THEN 1 ELSE 0 END) AS dynamic_vis_users,
          SUM(CASE WHEN account_vis_flag = '1' THEN 1 ELSE 0 END) AS account_vis_users,
          SUM(CASE WHEN member_vis_flag  = '1' THEN 1 ELSE 0 END) AS member_vis_users,
          SUM(CASE WHEN moment_act_flag  = '1' THEN 1 ELSE 0 END) AS moment_act_users,
          COUNT(*)                                                 AS total_records
        FROM {TABLE_NAME}
    """)
    flags = flag_rows[0] if flag_rows else {}

    # ---------- 序列化（datetime/Decimal 转为字符串/int）----------
    def safe(v):
        if v is None: return None
        try:
            import decimal
            if isinstance(v, decimal.Decimal): return int(v)
        except ImportError:
            pass
        if hasattr(v, 'isoformat'): return str(v)
        return v

    def to_int(v): return int(v) if v is not None else 0

    return {
        "overview": {
            "total_users":         total,
            "active_users":        active,
            "inactive_users":      to_int(ov.get("inactive_users")),
            "deleted_users":       to_int(ov.get("deleted_users")),
            "active_rate":         round(active / total * 100, 2),
            "country_count":       to_int(ov.get("country_count")),
            "latest_update_date":  safe(ov.get("latest_update_date")),
            "latest_event_date":   safe(ov.get("latest_event_date")),
        },
        "data_source":  [{k: safe(v) for k, v in r.items()} for r in source_rows],
        "country_top10":[{k: safe(v) for k, v in r.items()} for r in country_rows],
        "daily_trend":  [{k: safe(v) for k, v in r.items()} for r in trend_rows],
        "behavior_flags": {
            "行为活跃":      to_int(flags.get("act_users")),
            "设备访问":      to_int(flags.get("device_vis_users")),
            "统计访问":      to_int(flags.get("stat_vis_users")),
            "动态访问":      to_int(flags.get("dynamic_vis_users")),
            "账户访问":      to_int(flags.get("account_vis_users")),
            "成员访问":      to_int(flags.get("member_vis_users")),
            "动态互动":      to_int(flags.get("moment_act_users")),
            "total_records": to_int(flags.get("total_records")),
        }
    }


# ================================================================
# 简单 HTTP 服务器
# ================================================================
class DashboardHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"[{self.date_time_string()}] {fmt % args}")

    def send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",  "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, filepath: str, content_type: str):
        try:
            with open(filepath, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type",   content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/") or "/"

        if path == "/api/dashboard":
            try:
                data = build_dashboard_data()
                self.send_json(data)
            except Exception as e:
                import traceback; traceback.print_exc()
                self.send_json({"error": str(e)}, status=500)

        elif path in ("/", "/index.html", "/dashboard.html"):
            self.serve_file(
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html"),
                "text/html; charset=utf-8"
            )
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    if not DB_PASSWORD:
        print("⚠️  警告：STARROCKS_PASSWORD 未设置，连接可能失败")
        print("   设置方式：export STARROCKS_PASSWORD='你的密码'")
        print()
    print("=" * 55)
    print(f"  用户标签数据看板 - 后端服务")
    print("=" * 55)
    print(f"  StarRocks 主机: {DB_HOST}:{DB_PORT}")
    print(f"  数据库:         {DB_DATABASE}")
    print(f"  用户名:         {DB_USER}")
    print(f"  数据表:         {TABLE_NAME}")
    print(f"  看板地址:       http://localhost:{SERVER_PORT}")
    print("=" * 55)
    server = HTTPServer(("0.0.0.0", SERVER_PORT), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
