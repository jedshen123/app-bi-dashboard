CREATE TABLE `dws_pump_session_df` (

  -- ── 维度 ──────────────────────────────────────────────────
  `evt_dt`              date            NOT NULL COMMENT "session 开始的硬件事件日期（UTC，分区键）",
  `useSessionId`        varchar(64)     NOT NULL COMMENT "吸奶过程唯一标识",
  `dt`              date            NULL COMMENT "上报日期",
  `uid`                 varchar(65533)  NULL     COMMENT "用户 id",
  `pump_device_id`      varchar(128)    NULL     COMMENT "吸奶器唯一设备 ID（uid + payload第9–12位），用于统计活跃设备、新增设备、设备留存",
  `deviceCode`          varchar(32)     NULL     COMMENT "吸奶器设备型号（如 TP-A1），用于看板全局筛选，非唯一设备 ID",
  `os`                  varchar(16)     NULL     COMMENT "手机操作系统",

  -- ── 时间特征 ──────────────────────────────────────────────
  `start_time`          datetime        NULL     COMMENT "session 开始时间（pump_session_start 事件的 evtTimestamp_local）",
  `end_time`            datetime        NULL     COMMENT "session 结束时间（pump_session_end 事件的 evtTimestamp_local）",
  `local_hour`          tinyint         NULL     COMMENT "开始时的用户本地小时 0-23",
  `is_weekday`          tinyint(1)      NULL     COMMENT "是否工作日：1=工作日，0=周末",

  -- ── 时长 & 有效性 ─────────────────────────────────────────
  `total_duration_sec`  int(11)         NULL     COMMENT "吸奶总时长（秒），来自 pump_session_end 的 modeDuration 列表 durationSec 加总",
  `total_duration_min`  decimal(8,2)    NULL     COMMENT "吸奶总时长（分钟）",
  `is_complete`         tinyint(1)      NULL     COMMENT "是否有 pump_session_end 事件：1=完整结束，0=未完整结束",
  `is_valid`            tinyint(1)      NULL     COMMENT "是否有效进程：1=total_duration_min > 10，0=否",

  -- ── 结束时状态（来自 pump_session_end）───────────────────
  `finalModeType`       varchar(32)     NULL     COMMENT "结束时使用的模式",
  `finalSuctionLevel`   varchar(8)      NULL     COMMENT "结束时使用的档位",
  `endReason`           varchar(32)     NULL     COMMENT "结束原因",
  `usedModeCount`       int(11)         NULL     COMMENT "整个过程使用过的模式数量",

  -- ── 模式调节行为 ──────────────────────────────────────────
  `mode_adj_cnt`        int(11)         NULL     COMMENT "过程中模式调节总次数",
  `mode_adj_path`       varchar(65533)  NULL     COMMENT "调节路径序列，如 泌乳→按摩,按摩→刺激",

  -- ── 档位调节行为 ──────────────────────────────────────────
  `level_adj_cnt`       int(11)         NULL     COMMENT "过程中档位调节总次数",
  `level_up_cnt`        int(11)         NULL     COMMENT "档位上调次数",
  `level_down_cnt`      int(11)         NULL     COMMENT "档位下调次数",

  -- ── 暂停行为 ──────────────────────────────────────────────
  `pause_cnt`           int(11)         NULL     COMMENT "暂停次数",

  -- ── 操作来源 ──────────────────────────────────────────────
  `app_op_cnt`          int(11)         NULL     COMMENT "APP 操作次数（evtSource=remote_app）",
  `manual_op_cnt`       int(11)         NULL     COMMENT "硬件操作次数（evtSource=manual）"

) ENGINE=OLAP
PRIMARY KEY(`evt_dt`, `useSessionId`)
COMMENT "吸奶 session 粒度聚合宽表（按硬件事件日期分区）"
PARTITION BY date_trunc('day', evt_dt)
DISTRIBUTED BY HASH(`useSessionId`)
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

truncate table dws_pump_session_df;

INSERT into dws_pump_session_df
SELECT
  s.evt_dt,
  s.useSessionId,
  s.dt,
  s.uid,
  s.pump_device_id,
  s.deviceCode,
  s.os,

  s.evtTimestamp_local                                          AS start_time,
  e.evtTimestamp_local                                          AS end_time,
  s.local_hour,
  s.is_weekday,

  e.total_duration_sec,
  ROUND(e.total_duration_sec / 60.0, 2)                        AS total_duration_min,
  IF(e.useSessionId IS NOT NULL, 1, 0)                         AS is_complete,
  IF(e.total_duration_sec > 600, 1, 0)                         AS is_valid,

  e.finalModeType,
  e.finalSuctionLevel,
  e.endReason,
  e.usedModeCount,

  COALESCE(adj_mode.mode_adj_cnt, 0)                           AS mode_adj_cnt,
  adj_mode.mode_adj_path,

  COALESCE(adj_level.level_adj_cnt, 0)                         AS level_adj_cnt,
  COALESCE(adj_level.level_up_cnt,  0)                         AS level_up_cnt,
  COALESCE(adj_level.level_down_cnt,0)                         AS level_down_cnt,

  COALESCE(pause.pause_cnt, 0)                                 AS pause_cnt,

  COALESCE(src.app_op_cnt,    0)                               AS app_op_cnt,
  COALESCE(src.manual_op_cnt, 0)                               AS manual_op_cnt

FROM (
  SELECT useSessionId, uid, pump_device_id, deviceCode, os,
         evt_dt, evtTimestamp_local, local_hour, is_weekday, dt
  FROM dwd_tp_app_breast_pump_log_di
  WHERE eventName = 'pump_session_start'
    AND useSessionId IS NOT NULL
    AND evt_dt IS NOT NULL
) s

LEFT JOIN (
  SELECT useSessionId, evtTimestamp_local, total_duration_sec,
         finalModeType, finalSuctionLevel, endReason, usedModeCount
  FROM dwd_tp_app_breast_pump_log_di
  WHERE eventName = 'pump_session_end'
) e ON s.useSessionId = e.useSessionId

LEFT JOIN (
  SELECT
    useSessionId,
    COUNT(*) AS mode_adj_cnt,
    GROUP_CONCAT(
      CONCAT(
        CASE adjustFrom WHEN '0' THEN '刺激' WHEN '1' THEN '泌乳' WHEN '2' THEN '混合' WHEN '3' THEN '自定义' ELSE adjustFrom END,
        '→',
        CASE adjustTo   WHEN '0' THEN '刺激' WHEN '1' THEN '泌乳' WHEN '2' THEN '混合' WHEN '3' THEN '自定义' ELSE adjustTo   END
      )
      ORDER BY evtTimestamp SEPARATOR ','
    ) AS mode_adj_path
  FROM dwd_tp_app_breast_pump_log_di
  WHERE eventName = 'pump_manual_adjust_evt' AND evtType = 'pump_mode'
  GROUP BY useSessionId
) adj_mode ON s.useSessionId = adj_mode.useSessionId

LEFT JOIN (
  SELECT
    useSessionId,
    COUNT(*)                                    AS level_adj_cnt,
    SUM(IF(adjust_direction = 'up',   1, 0))    AS level_up_cnt,
    SUM(IF(adjust_direction = 'down', 1, 0))    AS level_down_cnt
  FROM dwd_tp_app_breast_pump_log_di
  WHERE eventName = 'pump_manual_adjust_evt' AND evtType = 'suction_level'
  GROUP BY useSessionId
) adj_level ON s.useSessionId = adj_level.useSessionId

LEFT JOIN (
  SELECT useSessionId, COUNT(*) AS pause_cnt
  FROM dwd_tp_app_breast_pump_log_di
  WHERE eventName = 'pump_user_evt' AND evtType = 'pause'
  GROUP BY useSessionId
) pause ON s.useSessionId = pause.useSessionId

LEFT JOIN (
  SELECT
    useSessionId,
    SUM(IF(evtSource = 'remote_app', 1, 0)) AS app_op_cnt,
    SUM(IF(evtSource = 'manual',     1, 0)) AS manual_op_cnt
  FROM dwd_tp_app_breast_pump_log_di
  WHERE eventName = 'pump_manual_adjust_evt'
  GROUP BY useSessionId
) src ON s.useSessionId = src.useSessionId;