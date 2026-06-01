"""
Superset MCP HTTP 客户端 — 通过美东 StarRocks（SQL Lab）执行查询

环境变量：
  MCP_URL              MCP 端点，默认 http://54.226.190.74:8000/mcp
  MCP_DATABASE_ID      Superset 数据库 ID，美东 StarRocks 默认为 1
  MCP_PROTOCOL_VERSION MCP 协议版本，默认 2024-11-05
"""

import json
import os
import re
import threading
import urllib.error
import urllib.request
from typing import Any, List, Optional

_env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.isfile(_env_file):
    with open(_env_file, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            _k, _v = _k.strip(), _v.strip().strip('"').strip("'")
            if _k and _k not in os.environ:
                os.environ[_k] = _v

MCP_URL = os.getenv("MCP_URL", "http://54.226.190.74:8000/mcp").rstrip("/")
MCP_DATABASE_ID = int(os.getenv("MCP_DATABASE_ID", "1"))
MCP_PROTOCOL = os.getenv("MCP_PROTOCOL_VERSION", "2024-11-05")
MCP_TIMEOUT = int(os.getenv("MCP_TIMEOUT", "120"))

_lock = threading.Lock()
_session_id: Optional[str] = None
_request_id = 0


def _parse_sse_or_json(raw: str) -> Optional[dict]:
    raw = (raw or "").strip()
    if not raw:
        return None
    if "data: " in raw:
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                return json.loads(line[6:])
    return json.loads(raw)


def _next_id() -> int:
    global _request_id
    _request_id += 1
    return _request_id


def _post(session_id: Optional[str], body: dict) -> tuple:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MCP_PROTOCOL,
    }
    if session_id:
        headers["mcp-session-id"] = session_id

    req = urllib.request.Request(
        MCP_URL,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=MCP_TIMEOUT) as resp:
            sid = resp.headers.get("mcp-session-id") or session_id
            data = _parse_sse_or_json(resp.read().decode("utf-8"))
            return sid, data
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"MCP HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"无法连接 MCP（{MCP_URL}）：{e.reason}") from e


def _ensure_session() -> str:
    global _session_id
    with _lock:
        if _session_id:
            return _session_id

        sid, init = _post(None, {
            "jsonrpc": "2.0",
            "id": _next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "app-bi-dashboard", "version": "1.0"},
            },
        })
        if not init or "error" in init:
            raise RuntimeError(f"MCP initialize 失败: {init}")

        sid, _ = _post(sid, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        sid, auth = _post(sid, {
            "jsonrpc": "2.0",
            "id": _next_id(),
            "method": "tools/call",
            "params": {
                "name": "superset_auth_authenticate_user",
                "arguments": {},
            },
        })
        if auth and auth.get("error"):
            raise RuntimeError(f"MCP 认证失败: {auth['error']}")

        _session_id = sid
        return sid


def _reset_session():
    global _session_id
    with _lock:
        _session_id = None


def _tool_call(name: str, arguments: dict) -> Any:
    for attempt in range(2):
        sid = _ensure_session()
        sid, resp = _post(sid, {
            "jsonrpc": "2.0",
            "id": _next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        global _session_id
        _session_id = sid

        if resp and resp.get("error"):
            err = resp["error"]
            if err.get("code") == -32600 and attempt == 0:
                _reset_session()
                continue
            raise RuntimeError(f"MCP 工具 {name} 错误: {err}")

        if not resp or "result" not in resp:
            raise RuntimeError(f"MCP 工具 {name} 无返回")

        content = resp["result"].get("content") or []
        if not content:
            return resp["result"]

        text = content[0].get("text", "")
        if content[0].get("type") == "text" and text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        return resp["result"]

    raise RuntimeError("MCP 会话重试失败")


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SAFE_STR_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def bind_sql(sql: str, params: Optional[List]) -> str:
    """将 %s 占位符替换为安全字面量（仅日期 / 数字 / 安全标识符）。"""
    if not params:
        return sql
    out = sql
    for p in params:
        if p is None:
            rep = "NULL"
        elif isinstance(p, bool):
            rep = "1" if p else "0"
        elif isinstance(p, (int, float)):
            rep = str(p)
        elif isinstance(p, str):
            if _DATE_RE.match(p):
                rep = f"'{p}'"
            elif _SAFE_STR_RE.match(p):
                rep = f"'{p}'"
            else:
                raise ValueError(f"不安全的 SQL 参数: {p!r}")
        else:
            raise ValueError(f"不支持的 SQL 参数类型: {type(p)}")
        out = out.replace("%s", rep, 1)
    return out


def run_sql(sql: str, params: Optional[List] = None) -> List[dict]:
    """
    通过 MCP → Superset SQL Lab 执行 SQL，返回字典列表（与 server.run_sql 兼容）。
    """
    bound = bind_sql(sql, params or [])
    result = _tool_call("superset_sqllab_execute_query", {
        "database_id": MCP_DATABASE_ID,
        "sql": bound,
    })

    if not isinstance(result, dict):
        raise RuntimeError(f"SQL Lab 返回异常: {result!r}")

    status = result.get("status")
    if status != "success":
        q = result.get("query") or {}
        msg = result.get("error") or q.get("errorMessage") or status or "unknown"
        raise RuntimeError(f"SQL 执行失败: {msg}\nSQL: {bound[:500]}")

    rows = result.get("data") or []
    if not isinstance(rows, list):
        raise RuntimeError(f"SQL Lab data 格式异常: {type(rows)}")

    return [dict(r) for r in rows]


def health_check() -> dict:
    """连通性检查：MCP + 美东库简单查询。"""
    rows = run_sql(
        "SELECT 1 AS ok FROM lute_app_dw.dwd_tp_app_breast_pump_log_di LIMIT 1",
        [],
    )
    return {
        "mcp_url": MCP_URL,
        "database_id": MCP_DATABASE_ID,
        "ok": bool(rows),
    }
