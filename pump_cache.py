"""
吸奶器看板缓存 — 与 SQL 版本绑定，支持按日期范围区分 TTL
"""

import os
from datetime import date

CACHE_TTL_PUMP = int(os.getenv("CACHE_TTL_PUMP", "3600"))
CACHE_TTL_PUMP_TODAY = int(os.getenv("CACHE_TTL_PUMP_TODAY", "300"))


def pump_cache_ttl(start_dt: str, end_dt: str) -> int:
    today = date.today().isoformat()
    if end_dt >= today or start_dt >= today:
        return CACHE_TTL_PUMP_TODAY
    return CACHE_TTL_PUMP


def pump_cache_key(section: str, start_dt: str, end_dt: str) -> tuple:
    # 每次动态读取，无需重启服务器即可让版本变更生效
    version = os.getenv("PUMP_CACHE_VERSION", "20260602v1")
    return ("pump", version, section, start_dt, end_dt)
