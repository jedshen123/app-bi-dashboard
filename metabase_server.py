"""
Metabase 通用大屏看板 - 后端代理服务
无第三方依赖，使用 Python 标准库

环境变量：
  METABASE_URL      Metabase 地址，如 https://app-data.luteos.site
  METABASE_USER     服务账号邮箱（用于后台数据拉取）
  METABASE_PASS     服务账号密码
  MB_PORT           服务端口，默认 5001
  CACHE_TTL         卡片数据缓存秒数，默认 300（5分钟）；设为 0 禁用缓存
  CACHE_TTL_META    看板元信息/筛选器选项缓存秒数，默认 600（10分钟）
  SESSION_TTL       用户登录会话时长（秒），默认 28800（8小时）

访问示例：http://localhost:5001/
"""

import os, json, time, hashlib, secrets
import http.cookies
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen, Request
from urllib.error import HTTPError

# 加载 .env 文件（仅补充未设置的变量，显式 export 的优先级更高）
_env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.isfile(_env_file):
    with open(_env_file, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            _k, _v = _k.strip(), _v.strip().strip('"').strip("'")
            if _k and _k not in os.environ:   # 不覆盖已有的环境变量
                os.environ[_k] = _v

METABASE_URL  = os.getenv("METABASE_URL",  "http://localhost:3000").rstrip("/")
METABASE_USER = os.getenv("METABASE_USER", "")
METABASE_PASS = os.getenv("METABASE_PASS", "")
SERVER_PORT   = int(os.getenv("MB_PORT",   "5001"))
CACHE_TTL      = int(os.getenv("CACHE_TTL",      "300"))   # 卡片数据缓存，秒
CACHE_TTL_META = int(os.getenv("CACHE_TTL_META", "600"))   # 元信息缓存，秒
SESSION_TTL    = int(os.getenv("SESSION_TTL",    str(8 * 3600)))  # 用户会话时长，秒
SESSION_COOKIE = "mb_sess"

# Session 缓存（Metabase session 默认 14 天，这里 12h 主动刷新）
_session = {"token": None, "expires_at": 0}

# ================================================================
# 内存缓存
# ================================================================
# 结构：{ key: {"data": ..., "expires_at": float} }
_cache: dict = {}


def _cache_get(key: str):
    """命中且未过期返回缓存数据，否则返回 None。"""
    entry = _cache.get(key)
    if entry and time.time() < entry["expires_at"]:
        return entry["data"]
    if entry:
        del _cache[key]   # 过期主动清除
    return None


def _cache_set(key: str, data, ttl: int):
    """写入缓存；ttl<=0 时不缓存。"""
    if ttl > 0:
        _cache[key] = {"data": data, "expires_at": time.time() + ttl}


def _make_key(*parts) -> str:
    """将任意参数序列化为稳定的缓存键（MD5 前缀 + 原文截断，便于调试）。"""
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.md5(raw.encode()).hexdigest()[:8]
    return f"{digest}:{raw[:80]}"


# ================================================================
# 用户会话管理
# ================================================================
_user_sessions: dict = {}


def _sess_create(mb_token: str, email: str, first_name: str = "") -> str:
    """创建用户会话，返回会话 token。"""
    token = secrets.token_urlsafe(32)
    _user_sessions[token] = {
        "mb_token":   mb_token,
        "email":      email,
        "first_name": first_name,
        "expires_at": time.time() + SESSION_TTL,
    }
    return token


def _sess_get(cookie_header: str):
    """从 Cookie 头解析会话，过期或不存在返回 None。"""
    if not cookie_header:
        return None
    try:
        jar = http.cookies.SimpleCookie(cookie_header)
        morsel = jar.get(SESSION_COOKIE)
        if not morsel:
            return None
        sess = _user_sessions.get(morsel.value)
        if not sess:
            return None
        if time.time() > sess["expires_at"]:
            del _user_sessions[morsel.value]
            return None
        return sess
    except Exception:
        return None


def _sess_delete(cookie_header: str):
    """删除 Cookie 对应的会话记录。"""
    if not cookie_header:
        return
    try:
        jar = http.cookies.SimpleCookie(cookie_header)
        morsel = jar.get(SESSION_COOKIE)
        if morsel:
            _user_sessions.pop(morsel.value, None)
    except Exception:
        pass


def _mb_check_permission(dashboard_id: str, user_token: str) -> bool:
    """用用户自己的 Metabase token 检查是否有权访问指定看板。"""
    req = Request(
        f"{METABASE_URL}/api/dashboard/{dashboard_id}",
        headers={"X-Metabase-Session": user_token, "Accept": "application/json"}
    )
    try:
        with urlopen(req, timeout=10) as r:
            return r.status == 200
    except HTTPError as e:
        return False


def _do_login() -> str:
    """向 Metabase 请求新 session token，并校验凭据非空。"""
    if not METABASE_USER or not METABASE_PASS:
        raise RuntimeError(
            "未设置 METABASE_USER 或 METABASE_PASS 环境变量，"
            "请先执行：export METABASE_USER=xxx METABASE_PASS=yyy"
        )
    payload = json.dumps({"username": METABASE_USER, "password": METABASE_PASS}).encode()
    req = Request(
        f"{METABASE_URL}/api/session", data=payload,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urlopen(req, timeout=15) as r:
        token = json.loads(r.read())["id"]
    print(f"[auth] 获取新 session token OK")
    return token


def get_token(force: bool = False) -> str:
    """返回有效 token；force=True 时强制重新登录。"""
    now = time.time()
    if not force and _session["token"] and now < _session["expires_at"]:
        return _session["token"]
    _session["token"] = _do_login()
    _session["expires_at"] = now + 12 * 3600
    return _session["token"]


def mb_get(path: str) -> dict:
    """带自动重登录的 GET 请求（遇到 401 重试一次）。"""
    for attempt in (False, True):          # False=用缓存, True=强制刷新
        try:
            req = Request(
                f"{METABASE_URL}{path}",
                headers={"X-Metabase-Session": get_token(force=attempt),
                         "Accept": "application/json"}
            )
            with urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except HTTPError as e:
            if e.code == 401 and not attempt:
                print("[auth] token 失效，重新登录...")
                continue
            raise


def mb_post(path: str, body: dict) -> dict:
    """带自动重登录的 POST 请求（遇到 401 重试一次）。"""
    payload = json.dumps(body).encode()
    for attempt in (False, True):
        try:
            req = Request(
                f"{METABASE_URL}{path}", data=payload,
                headers={
                    "X-Metabase-Session": get_token(force=attempt),
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                method="POST"
            )
            with urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except HTTPError as e:
            if e.code == 401 and not attempt:
                print("[auth] token 失效，重新登录...")
                continue
            raise


# ================================================================
# HTTP 处理器
# ================================================================

# 不需要登录即可访问的路径
_PUBLIC_PATHS = {"/login", "/api/login"}

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

    def send_redirect(self, location: str):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

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

    def _base_dir(self):
        return os.path.dirname(os.path.abspath(__file__))

    def _current_session(self):
        return _sess_get(self.headers.get("Cookie", ""))

    def _require_auth(self) -> bool:
        """返回 True 表示已登录可继续；False 表示已发送 401/302 响应。"""
        sess = self._current_session()
        if sess:
            return True
        # API 请求返回 401 JSON；页面请求重定向到登录页
        if self.path.startswith("/api/"):
            self.send_json({"error": "未登录", "code": "unauthenticated"}, 401)
        else:
            self.send_redirect("/login")
        return False

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

        # 公开路径：登录页
        if path == "/login":
            # 已登录则直接跳首页
            if self._current_session():
                return self.send_redirect("/")
            return self.serve_file(
                os.path.join(self._base_dir(), "login.html"),
                "text/html; charset=utf-8"
            )

        if path == "/favicon.png":
            return self.serve_file(
                os.path.join(self._base_dir(), "favicon.png"),
                "image/png"
            )

        # 其余所有路径需鉴权
        if not self._require_auth():
            return

        try:
            # ---- 登出 ----
            if path == "/logout":
                _sess_delete(self.headers.get("Cookie", ""))
                self.send_response(302)
                self.send_header("Location", "/login")
                self.send_header("Set-Cookie",
                    f"{SESSION_COOKIE}=; Path=/; HttpOnly; Max-Age=0")
                self.send_header("Content-Length", "0")
                self.end_headers()

            # ---- 当前用户信息 ----
            elif path == "/api/me":
                sess = self._current_session()
                self.send_json({
                    "email":      sess["email"],
                    "first_name": sess.get("first_name", ""),
                })

            # ---- 看板元信息 ----
            elif path == "/api/meta":
                did = qs("dashboard_id")
                if not did:
                    return self.send_json({"error": "缺少 dashboard_id"}, 400)

                # 用用户 token 检查权限
                sess = self._current_session()
                if not _mb_check_permission(did, sess["mb_token"]):
                    return self.send_json({"error": "无查看看板权限", "code": "forbidden"}, 403)

                cache_key = _make_key("meta", did)
                cached = _cache_get(cache_key)
                if cached:
                    print(f"[cache] HIT  meta dashboard_id={did}")
                    return self.send_json(cached)

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

                dashcards.sort(key=lambda x: (x["row"], x["col"]))

                result = {
                    "name":        raw.get("name", ""),
                    "description": raw.get("description") or "",
                    "parameters":  raw.get("parameters", []),
                    "dashcards":   dashcards,
                }
                _cache_set(cache_key, result, CACHE_TTL_META)
                self.send_json(result)

            # ---- 筛选器可选值 ----
            elif path == "/api/param_values":
                did  = qs("dashboard_id")
                pkey = qs("param_key")
                if not did or not pkey:
                    return self.send_json({"error": "缺少参数"}, 400)

                cache_key = _make_key("param_values", did, pkey)
                cached = _cache_get(cache_key)
                if cached:
                    print(f"[cache] HIT  param_values dashboard_id={did} param_key={pkey}")
                    return self.send_json(cached)

                result = mb_get(f"/api/dashboard/{did}/params/{pkey}/values")
                _cache_set(cache_key, result, CACHE_TTL_META)
                self.send_json(result)

            # ---- 前端页面 ----
            elif path in ("/", "/nav", "/nav.html"):
                if path == "/" and qs("dashboard_id"):
                    self.serve_file(
                        os.path.join(self._base_dir(), "metabase_dashboard.html"),
                        "text/html; charset=utf-8"
                    )
                else:
                    self.serve_file(
                        os.path.join(self._base_dir(), "nav.html"),
                        "text/html; charset=utf-8"
                    )

            elif path in ("/dashboard", "/metabase_dashboard.html"):
                self.serve_file(
                    os.path.join(self._base_dir(), "metabase_dashboard.html"),
                    "text/html; charset=utf-8"
                )

            elif path in ("/dashboard-v2", "/metabase_dashboard_v2.html"):
                self.serve_file(
                    os.path.join(self._base_dir(), "metabase_dashboard_v2.html"),
                    "text/html; charset=utf-8"
                )

            elif path in ("/preview", "/dashboard_preview.html"):
                self.serve_file(
                    os.path.join(self._base_dir(), "dashboard_preview.html"),
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

        # ---- 登录接口（公开） ----
        if path == "/api/login":
            email    = (body.get("email") or "").strip()
            password = (body.get("password") or "").strip()
            if not email or not password:
                return self.send_json({"error": "请输入邮箱和密码"}, 400)
            try:
                payload = json.dumps({"username": email, "password": password}).encode()
                req = Request(
                    f"{METABASE_URL}/api/session", data=payload,
                    headers={"Content-Type": "application/json"}, method="POST"
                )
                with urlopen(req, timeout=15) as r:
                    mb_resp = json.loads(r.read())
                mb_token = mb_resp.get("id", "")

                # 取用户信息
                first_name = ""
                try:
                    me_req = Request(
                        f"{METABASE_URL}/api/user/current",
                        headers={"X-Metabase-Session": mb_token, "Accept": "application/json"}
                    )
                    with urlopen(me_req, timeout=10) as r:
                        me = json.loads(r.read())
                    first_name = me.get("first_name") or me.get("email") or email
                except Exception:
                    first_name = email

                sess_token = _sess_create(mb_token, email, first_name)
                print(f"[login] {email} 登录成功")

                # 返回响应并设置 Cookie
                resp_body = json.dumps({"ok": True, "name": first_name}, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(resp_body)))
                self.send_header("Set-Cookie",
                    f"{SESSION_COOKIE}={sess_token}; Path=/; HttpOnly; Max-Age={SESSION_TTL}")
                self.end_headers()
                self.wfile.write(resp_body)

            except HTTPError as e:
                print(f"[login] {email} 登录失败: HTTP {e.code}")
                if e.code in (400, 401):
                    self.send_json({"error": "邮箱或密码错误"}, 401)
                else:
                    self.send_json({"error": f"Metabase 服务异常（{e.code}）"}, 502)
            except OSError as e:
                self.send_json({"error": f"无法连接 Metabase：{e}"}, 502)
            return

        # 其余 POST 需鉴权
        if not self._require_auth():
            return

        try:
            # ---- 卡片数据查询 ----
            if path == "/api/card_data":
                did  = qs("dashboard_id")
                dcid = qs("dashcard_id")
                cid  = qs("card_id")
                if not all([did, dcid, cid]):
                    return self.send_json({"error": "缺少参数"}, 400)

                req_params = body.get("parameters", [])
                cache_key = _make_key("card_data", did, dcid, cid, req_params)
                cached = _cache_get(cache_key)
                if cached:
                    print(f"[cache] HIT  card_data dashcard_id={dcid}")
                    return self.send_json(cached)

                result = mb_post(
                    f"/api/dashboard/{did}/dashcard/{dcid}/card/{cid}/query",
                    {"parameters": req_params}
                )
                data = result.get("data", {})
                slim_cols = [
                    {
                        "name":         c.get("name"),
                        "display_name": c.get("display_name") or c.get("name"),
                        "base_type":    c.get("base_type", ""),
                    }
                    for c in data.get("cols", [])
                ]
                response = {
                    "cols":  slim_cols,
                    "rows":  data.get("rows", []),
                    "error": result.get("error"),
                }
                _cache_set(cache_key, response, CACHE_TTL)
                self.send_json(response)
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
    print("=" * 58)
    print("  Metabase 通用大屏看板 - 代理服务")
    print("=" * 58)
    print(f"  Metabase:   {METABASE_URL}")
    print(f"  账号:       {METABASE_USER or '(未设置 METABASE_USER)'}")
    print(f"  端口:       {SERVER_PORT}")
    if CACHE_TTL > 0:
        print(f"  缓存:       卡片数据 {CACHE_TTL}s · 元信息 {CACHE_TTL_META}s")
    else:
        print(f"  缓存:       已禁用（CACHE_TTL=0）")
    print(f"  导航页:     http://localhost:{SERVER_PORT}/")
    print(f"  看板示例:   http://localhost:{SERVER_PORT}/?dashboard_id=14")
    print("=" * 58)

    # 启动前验证登录，出错时给出具体原因
    print("  正在验证 Metabase 连接...", end=" ", flush=True)
    try:
        get_token(force=True)
        print("OK ✓")
    except HTTPError as e:
        print(f"失败!\n\n错误: Metabase 返回 HTTP {e.code}")
        if e.code in (400, 401):
            print("→ 账号或密码错误，请检查 METABASE_USER / METABASE_PASS")
        else:
            print(f"→ 服务端异常，请确认 {METABASE_URL} 是否可访问")
        raise SystemExit(1)
    except OSError as e:
        # 包含 socket.timeout / ConnectionRefusedError / URLError 等所有网络异常
        msg = str(e).lower()
        print(f"失败!\n\n错误: {e}")
        if "timed out" in msg or "timeout" in msg:
            print(f"→ 连接超时，本机无法访问 {METABASE_URL}")
            print("  请检查：1) 服务器出站 443 端口是否开放（安全组/防火墙）")
            print("          2) 目标地址是否正确")
        elif "refused" in msg:
            print(f"→ 连接被拒绝，{METABASE_URL} 可能未运行")
        else:
            print(f"→ 网络错误，请确认服务器能访问 {METABASE_URL}")
        raise SystemExit(1)
    except Exception as e:
        print(f"失败!\n\n错误: {e}")
        raise SystemExit(1)

    server = HTTPServer(("0.0.0.0", SERVER_PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
