"""
Metabase 通用大屏看板 - 后端代理服务
无第三方依赖，使用 Python 标准库

环境变量：
  METABASE_URL      Metabase 地址，如 https://app-data.luteos.site
  METABASE_USER     账号邮箱
  METABASE_PASS     密码
  MB_PORT           服务端口，默认 5001

访问示例：http://localhost:5001/?dashboard_id=14
"""

import os, json, time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen, Request
from urllib.error import HTTPError

METABASE_URL  = os.getenv("METABASE_URL",  "http://localhost:3000").rstrip("/")
METABASE_USER = os.getenv("METABASE_USER", "")
METABASE_PASS = os.getenv("METABASE_PASS", "")
SERVER_PORT   = int(os.getenv("MB_PORT",   "5001"))

# Session 缓存（Metabase session 默认 14 天，这里 12h 主动刷新）
_session = {"token": None, "expires_at": 0}


def get_token() -> str:
    now = time.time()
    if _session["token"] and now < _session["expires_at"]:
        return _session["token"]
    payload = json.dumps({"username": METABASE_USER, "password": METABASE_PASS}).encode()
    req = Request(
        f"{METABASE_URL}/api/session", data=payload,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urlopen(req, timeout=15) as r:
        _session["token"] = json.loads(r.read())["id"]
    _session["expires_at"] = now + 12 * 3600
    print(f"[auth] 获取新 session token")
    return _session["token"]


def mb_get(path: str) -> dict:
    req = Request(
        f"{METABASE_URL}{path}",
        headers={"X-Metabase-Session": get_token(), "Accept": "application/json"}
    )
    with urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def mb_post(path: str, body: dict) -> dict:
    payload = json.dumps(body).encode()
    req = Request(
        f"{METABASE_URL}{path}", data=payload,
        headers={
            "X-Metabase-Session": get_token(),
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        method="POST"
    )
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read())


# ================================================================
# HTTP 处理器
# ================================================================

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"[{self.date_time_string()}] {fmt % args}")

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type",             "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length",           str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, fp: str, ct: str):
        try:
            body = open(fp, "rb").read()
        except FileNotFoundError:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type",   ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ------------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/") or "/"
        q      = parse_qs(parsed.query)
        def qs(k): return q.get(k, [""])[0]

        try:
            # ---- 看板元信息 ----
            if path == "/api/meta":
                did = qs("dashboard_id")
                if not did:
                    return self.send_json({"error": "缺少 dashboard_id"}, 400)

                raw = mb_get(f"/api/dashboard/{did}")

                dashcards = []
                for dc in raw.get("dashcards", []):
                    card = dc.get("card") or {}
                    vc   = dc.get("virtual_card") or {}
                    dashcards.append({
                        "id":                 dc["id"],
                        "col":                dc.get("col", 0),
                        "row":                dc.get("row", 0),
                        "size_x":             dc.get("size_x", 6),
                        "size_y":             dc.get("size_y", 4),
                        "card_id":            card.get("id"),
                        "name":               card.get("name") or vc.get("name") or "",
                        "display":            card.get("display") or vc.get("display", "table"),
                        "viz_settings":       card.get("visualization_settings") or {},
                        "parameter_mappings": dc.get("parameter_mappings", []),
                    })

                # 按布局顺序排列（先行后列）
                dashcards.sort(key=lambda x: (x["row"], x["col"]))

                self.send_json({
                    "name":        raw.get("name", ""),
                    "description": raw.get("description") or "",
                    "parameters":  raw.get("parameters", []),
                    "dashcards":   dashcards,
                })

            # ---- 筛选器可选值 ----
            elif path == "/api/param_values":
                did  = qs("dashboard_id")
                pkey = qs("param_key")
                if not did or not pkey:
                    return self.send_json({"error": "缺少参数"}, 400)
                self.send_json(mb_get(f"/api/dashboard/{did}/params/{pkey}/values"))

            # ---- 前端页面 ----
            elif path in ("/", "/metabase_dashboard.html"):
                self.serve_file(
                    os.path.join(
                        os.path.dirname(os.path.abspath(__file__)),
                        "metabase_dashboard.html"
                    ),
                    "text/html; charset=utf-8"
                )

            else:
                self.send_response(404); self.end_headers()

        except HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            self.send_json({"error": f"Metabase API {e.code}", "detail": detail[:500]}, 502)
        except Exception as e:
            import traceback; traceback.print_exc()
            self.send_json({"error": str(e)}, 500)

    # ------------------------------------------------------------------
    def do_POST(self):
        parsed  = urlparse(self.path)
        path    = parsed.path.rstrip("/")
        q       = parse_qs(parsed.query)
        length  = int(self.headers.get("Content-Length", 0))
        body    = json.loads(self.rfile.read(length) if length else b"{}")
        def qs(k): return q.get(k, [""])[0]

        try:
            # ---- 卡片数据查询 ----
            if path == "/api/card_data":
                did  = qs("dashboard_id")
                dcid = qs("dashcard_id")
                cid  = qs("card_id")
                if not all([did, dcid, cid]):
                    return self.send_json({"error": "缺少参数"}, 400)

                result = mb_post(
                    f"/api/dashboard/{did}/dashcard/{dcid}/card/{cid}/query",
                    {"parameters": body.get("parameters", [])}
                )
                data = result.get("data", {})
                # 精简 cols，只保留前端需要的字段
                slim_cols = [
                    {
                        "name":         c.get("name"),
                        "display_name": c.get("display_name") or c.get("name"),
                        "base_type":    c.get("base_type", ""),
                    }
                    for c in data.get("cols", [])
                ]
                self.send_json({
                    "cols":  slim_cols,
                    "rows":  data.get("rows", []),
                    "error": result.get("error"),
                })
            else:
                self.send_response(404); self.end_headers()

        except HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            self.send_json({"error": f"Metabase API {e.code}", "detail": detail[:500]}, 502)
        except Exception as e:
            import traceback; traceback.print_exc()
            self.send_json({"error": str(e)}, 500)


# ================================================================
if __name__ == "__main__":
    missing = [v for v in ["METABASE_USER", "METABASE_PASS"] if not os.getenv(v)]
    if missing:
        print(f"⚠️  未设置环境变量：{', '.join(missing)}")
    print("=" * 58)
    print("  Metabase 通用大屏看板 - 代理服务")
    print("=" * 58)
    print(f"  Metabase:   {METABASE_URL}")
    print(f"  账号:       {METABASE_USER}")
    print(f"  端口:       {SERVER_PORT}")
    print(f"  访问示例:   http://localhost:{SERVER_PORT}/?dashboard_id=14")
    print("=" * 58)
    server = HTTPServer(("0.0.0.0", SERVER_PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
