CREATE TABLE `dws_pump_daily_df` (

  `evt_dt`                date            NOT NULL COMMENT "硬件事件日期（UTC，分区键）",
  `deviceCode`            varchar(32)     NOT NULL     COMMENT "设备型号（全局筛选器，NULL 行代表全型号汇总）",

  -- ── 活跃指标 ──────────────────────────────────────────────
  `dau`                   int(11)         NULL COMMENT "日活跃用户数（有吸奶行为的去重 uid 数）",
  `active_devices`        int(11)         NULL COMMENT "活跃设备数（去重 pump_device_id 数，非型号数）",
  `new_users`             int(11)         NULL COMMENT "新增用户数（历史首次出现的 uid，以 evt_dt 为准）",
  `new_devices`           int(11)         NULL COMMENT "新增设备数（历史首次出现的 pump_device_id，以 evt_dt 为准）",

  -- ── 次数指标 ──────────────────────────────────────────────
  `total_sessions`        int(11)         NULL COMMENT "总吸奶次数（useSessionId 去重）",
  `complete_sessions`     int(11)         NULL COMMENT "完整结束次数（is_complete=1）",
  `valid_sessions`        int(11)         NULL COMMENT "有效进程次数（is_valid=1，时长>10min）",
  `power_on_cnt`          int(11)         NULL COMMENT "开机次数（pump_startup_evt 事件数，按 evt_dt 归日）",
  `avg_sessions_per_user` decimal(8,2)    NULL COMMENT "人均吸奶次数 = total_sessions / dau",

  -- ── 时长指标 ──────────────────────────────────────────────
  `total_duration_sec`    bigint(20)      NULL COMMENT "当日总吸奶时长（秒）",
  `total_duration_h`      decimal(12,2)   NULL COMMENT "当日总吸奶时长（小时）",
  `avg_duration_min`      decimal(8,2)    NULL COMMENT "次均时长（分钟）= total_duration_sec/60 / total_sessions",
  `avg_duration_per_user` decimal(8,2)    NULL COMMENT "人均每日时长（分钟）= total_duration_sec/60 / dau",

  -- ── 转化率（小数，保留5位）────────────────────────────────
  `start_rate`            decimal(8,5)    NULL COMMENT "开始率 = total_sessions / power_on_cnt",
  `completion_rate`       decimal(8,5)    NULL COMMENT "完整进程率 = complete_sessions / total_sessions",
  `valid_rate`            decimal(8,5)    NULL COMMENT "有效进程率 = valid_sessions / total_sessions",

  -- ── 累计指标 ──────────────────────────────────────────────
  `cumulative_users`      bigint(20)      NULL COMMENT "截至当日累计活跃用户数（历史去重 uid）",
  `cumulative_devices`    bigint(20)      NULL COMMENT "截至当日累计活跃设备数（历史去重 pump_device_id）",
  `cumulative_sessions`   bigint(20)      NULL COMMENT "截至当日累计吸奶次数",
  `cumulative_duration_h` decimal(16,2)   NULL COMMENT "截至当日累计吸奶时长（小时）"

) ENGINE=OLAP
PRIMARY KEY(`evt_dt`, `deviceCode`)
COMMENT "吸奶日粒度汇总表（按硬件事件日期分区，设备计数基于 pump_device_id）"
PARTITION BY date_trunc('day', evt_dt)
DISTRIBUTED BY HASH(`evt_dt`)
PROPERTIES (
  "replication_num" = "1",
  "in_memory" = "false",
  "storage_format" = "DEFAULT",
  "enable_persistent_index" = "false",
  "replicated_storage" = "true",
  "partition_live_number" = "3600",
  "compression" = "LZ4"
);

set oneservice.allow.full.scan = true;
SET query_timeout = 1800;  

truncate table dws_pump_daily_df;

INSERT into dws_pump_daily_df
WITH daily_agg AS (
    SELECT
        evt_dt,
        deviceCode,
        COUNT(DISTINCT uid)                 AS dau,
        COUNT(DISTINCT pump_device_id)     AS active_devices,
        COUNT(DISTINCT useSessionId)       AS total_sessions,
        SUM(is_complete)                   AS complete_sessions,
        SUM(is_valid)                      AS valid_sessions,
        SUM(total_duration_sec)            AS total_duration_sec
    FROM dws_pump_session_df
    GROUP BY evt_dt, deviceCode
),
user_first AS (
    SELECT uid, MIN(evt_dt) AS first_dt
    FROM dws_pump_session_df
    GROUP BY uid
),
device_first AS (
    SELECT pump_device_id, MIN(evt_dt) AS first_dt
    FROM dws_pump_session_df
    WHERE pump_device_id IS NOT NULL
    GROUP BY pump_device_id
),
daily_new AS (
    SELECT
        s.evt_dt,
        s.deviceCode,
        COUNT(DISTINCT CASE WHEN f.first_dt = s.evt_dt THEN s.uid END)     AS new_users,
        COUNT(DISTINCT CASE WHEN df.first_dt = s.evt_dt THEN s.pump_device_id END) AS new_devices
    FROM dws_pump_session_df s
    LEFT JOIN user_first f ON s.uid = f.uid
    LEFT JOIN device_first df ON s.pump_device_id = df.pump_device_id
    GROUP BY s.evt_dt, s.deviceCode
),
power AS (
    SELECT evt_dt, COUNT(*) AS power_on_cnt
    FROM dwd_tp_app_breast_pump_log_di
    WHERE eventName = 'pump_startup_evt'
    GROUP BY evt_dt
),
-- 生成 日期+设备 全维度（关键修复点）
day_device AS (
    SELECT DISTINCT evt_dt, deviceCode
    FROM daily_agg
),
-- 累计指标（范围JOIN，StarRocks 100%支持）
cumulative AS (
    SELECT
        d.evt_dt,
        d.deviceCode,
        COUNT(DISTINCT t.uid)                 AS cumulative_users,
        COUNT(DISTINCT t.pump_device_id)     AS cumulative_devices,
        COUNT(DISTINCT t.useSessionId)       AS cumulative_sessions,
        SUM(t.total_duration_sec)            AS cumulative_duration_sec
    FROM day_device d
    LEFT JOIN dws_pump_session_df t
        ON t.evt_dt <= d.evt_dt
        AND t.deviceCode = d.deviceCode
    GROUP BY d.evt_dt, d.deviceCode
)
SELECT
    base.evt_dt,
    base.deviceCode,

    base.dau,
    base.active_devices,
    n.new_users,
    n.new_devices,

    base.total_sessions,
    base.complete_sessions,
    base.valid_sessions,
    COALESCE(p.power_on_cnt, 0) AS power_on_cnt,
    ROUND(base.total_sessions / NULLIF(base.dau, 0), 2)                     AS avg_sessions_per_user,
    base.total_duration_sec,
    ROUND(base.total_duration_sec / 3600.0, 2)                               AS total_duration_h,
    ROUND(base.total_duration_sec / 60.0 / NULLIF(base.total_sessions, 0), 2) AS avg_duration_min,
    ROUND(base.total_duration_sec / 60.0 / NULLIF(base.dau, 0), 2)          AS avg_duration_per_user,

    ROUND(base.total_sessions / NULLIF(COALESCE(p.power_on_cnt, 0), 0), 5)   AS start_rate,
    ROUND(base.complete_sessions / NULLIF(base.total_sessions, 0), 5)        AS completion_rate,
    ROUND(base.valid_sessions / NULLIF(base.total_sessions, 0), 5)           AS valid_rate,

    COALESCE(c.cumulative_users, 0)                  AS cumulative_users,
    COALESCE(c.cumulative_devices, 0)               AS cumulative_devices,
    COALESCE(c.cumulative_sessions, 0)              AS cumulative_sessions,
    ROUND(COALESCE(c.cumulative_duration_sec, 0)/3600.0, 2) AS cumulative_duration_h

FROM daily_agg base
INNER JOIN daily_new n
    ON base.evt_dt = n.evt_dt AND base.deviceCode = n.deviceCode
LEFT JOIN power p
    ON base.evt_dt = p.evt_dt
LEFT JOIN cumulative c
    ON base.evt_dt = c.evt_dt AND base.deviceCode = c.deviceCode
where base.evt_dt >='2025-05-01' and base.evt_dt <='2028-05-01'
ORDER BY base.evt_dt, base.deviceCode
