"""
吸奶器看板缓存 — 与 SQL 版本绑定，支持按日期范围区分 TTL
"""

import os
from datetime import date

# SQL 逻辑变更时递增，使旧缓存自动失效
PUMP_SQL_VERSION = os.getenv("PUMP_CACHE_VERSION", "20260601v3")

CACHE_TTL_PUMP = int(os.getenv("CACHE_TTL_PUMP", "3600"))          # 历史区间默认 1 小时
CACHE_TTL_PUMP_TODAY = int(os.getenv("CACHE_TTL_PUMP_TODAY", "300"))  # 含今天 5 分钟


def pump_cache_ttl(start_dt: str, end_dt: str) -> int:
    """统计区间包含今天则用较短 TTL。"""
    today = date.today().isoformat()
    if end_dt >= today or start_dt >= today:
        return CACHE_TTL_PUMP_TODAY
    return CACHE_TTL_PUMP


def pump_cache_key(section: str, start_dt: str, end_dt: str) -> tuple:
    return ("pump", PUMP_SQL_VERSION, section, start_dt, end_dt)
