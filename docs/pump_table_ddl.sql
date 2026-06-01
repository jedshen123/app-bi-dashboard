-- ============================================================
-- 吸奶器数据看板 · 数仓建表语句 & ETL SQL
-- 数据库：lute_app_dw（StarRocks）
-- 更新日期：2026-05-28
--
-- 表清单：
--   1. dwd_tp_app_pump_log_di       原始事件宽表（JSON 字段展开）
--   2. dws_pump_session_di          Session 粒度聚合表
--   3. dws_pump_session_mode_di     Session×模式粒度明细表（modeDuration 展开）
--   4. dws_pump_daily_di            日粒度汇总表
--   5. dws_pump_retention_di        留存率计算表
--
-- ── 时间字段说明 ──────────────────────────────────────────────
--   dt              上报日期（UTC 0 时区），等于数据写入消息队列的日期；
--                   DWD 分区键，与上游 dwd_tp_app_log_di 保持一致，不可更改。
--                   设备离线期间事件会暂存硬件，重连后批量上报，此时 dt 为重连日，
--                   而 evtTimestamp 仍为事件实际发生时间。
--
--   evtTimestamp    硬件记录的事件发生时间戳（毫秒，UTC 0 时区）。
--                   这是业务分析的正确时间基准。
--
--   evt_dt          由 evtTimestamp 转换的事件发生日期（UTC），ETL 衍生字段。
--                   DWS 各表的分区键均使用 evt_dt，以保证离线补报数据落入正确的业务日期。
--
--   evtTimestamp_local  evtTimestamp 结合 timezoneOffset 还原的用户本地时间，
--                       用于时段分布、工作日判断等用户行为分析。
--
-- ── 设备字段说明 ──────────────────────────────────────────────
--   deviceCode      吸奶器设备型号（如 TP-A1），非唯一 ID，用于看板全局筛选器。
--                   同一型号可有多台设备，不可用于计数唯一设备。
--
--   pump_device_id  吸奶器唯一设备 ID，ETL 衍生字段。
--                   拼接规则：uid + SUBSTRING(payload, 9, 4)
--                   （payload 第 9–12 位字符为硬件编码中的设备唯一标识段）
--                   用于统计活跃设备数、新增设备数、设备留存等所有"设备唯一"指标。
--
--   deviceId        手机设备 ID（content.deviceId），非吸奶器设备 ID，一般不用于分析。
--
-- ── 增量同步策略 ──────────────────────────────────────────────
--   DWD ETL：按 dt 增量，每日跑 @busi_date 分区。
--   DWS ETL：每日扫描最近 @late_days（建议 7）天的 DWD dt 分区，
--             用 INSERT OVERWRITE 按 evt_dt 覆写 DWS 对应分区。
--             StarRocks INSERT OVERWRITE 只覆写结果集实际涉及的分区，
--             幂等安全，不影响其他日期数据。
--
-- ── 调度依赖顺序（每日 T+1 运行）────────────────────────────
--   dwd_tp_app_pump_log_di  （上游 dwd_tp_app_log_di 写入后触发）
--       ↓  T+1 00:30
--   dws_pump_session_di
--       ↓  T+1 01:00
--   dws_pump_session_mode_di
--       ↓  T+1 01:15
--   dws_pump_daily_di
--       ↓  T+1 01:30
--   dws_pump_retention_di   （D14 留存需等 base_dt+14 有数据后才完整，每日补算近15天）
--
-- 参数说明：
--   @busi_date   调度工具传入的业务日期（今日），格式 YYYY-MM-DD
--   @late_days   离线补报容忍天数，建议 7；DWS ETL 扫 dt >= @busi_date - @late_days 的分区
--
-- eventname 枚举值：
--   pump_manual_adjust_evt  手动调节（模式/档位）
--   pump_user_evt           用户操作（开始/暂停/恢复）
--   pump_session_start      吸奶过程开始
--   pump_session_end        吸奶过程结束（含时长、模式等汇总信息）
--   pump_startup_evt        开机
--   pump_shutdown_evt       关机
--   bt_connect_evt          蓝牙连接
--   bat_charge_start        开始充电
--   bat_charge_end          充电结束
--
-- adjustFrom / adjustTo pumpmode 对应关系：
--   0=刺激  1=泌乳  2=混合  3=自定义
--
-- modeDuration 字段格式（JSON 数组，pump_session_end 事件有值）：
--   [{"durationSec": 1797, "modeType": "expression"}, ...]
--   吸奶总时长 = 列表中所有 durationSec 加总
-- ============================================================


-- ============================================================
-- 1. dwd_tp_app_pump_log_di
--    原始事件宽表，从 dwd_tp_app_log_di 过滤 Pump Log 事件后展开
--    分区粒度：dt（按天，与上游对齐，不可改为 evt_dt）
--    主键：id + dt
-- ============================================================
CREATE TABLE `dwd_tp_app_pump_log_di` (

  -- ── 原始基础字段（来自 dwd_tp_app_log_di）────────────────
  `id`            bigint(20)      NOT NULL COMMENT "主键 id",
  `dt`            date            NOT NULL COMMENT "上报日期（UTC，分区键，与上游对齐；离线补报时 dt=重连日而非事件日，分析请用 evt_dt）",
  `app`           varchar(64)     NOT NULL COMMENT "app 标识",
  `appid`         varchar(64)     NOT NULL COMMENT "应用 id",
  `writetime`     bigint(20)      NOT NULL COMMENT "埋点写入消息队列的时间戳（毫秒）",
  `url`           varchar(65533)  NULL     COMMENT "路由地址",
  `traceid`       varchar(65533)  NULL     COMMENT "traceid",
  `uid`           varchar(65533)  NULL     COMMENT "用户 id",
  `eventtype`     varchar(65533)  NOT NULL COMMENT "事件类型",
  `content`       varchar(65533)  NULL     COMMENT "事件详情（原始 JSON，含 extraData）",
  `createtime`    bigint(20)      NOT NULL COMMENT "创建时间（毫秒）",
  `data_source`   varchar(32)     NULL     COMMENT "数据来源",

  -- ── 从 content 展开的一级字段 ────────────────────────────
  `extraData`     varchar(65533)  NULL     COMMENT "content.extraData 原始 JSON，吸奶器操作扩展信息",
  `eventName`     varchar(128)    NULL     COMMENT "吸奶器事件名称（extraData.eventName）",
  `evtTimestamp`  bigint(20)      NULL     COMMENT "硬件记录的事件发生时间戳（毫秒，UTC 0 时区），业务分析的正确时间基准",
  `useSessionId`  varchar(64)     NULL     COMMENT "吸奶过程唯一标识，统计吸奶次数的 key",

  -- ── 从 extraData 进一步展开的字段 ────────────────────────
  `eventSessionId`      varchar(64)     NULL COMMENT "吸奶过程子流程 ID（content.eventSessionId），每次暂停后重启会更新",
  `deviceCode`          varchar(32)     NULL COMMENT "吸奶器设备型号（extraData.deviceCode），如 TP-A1；同一型号可有多台设备，仅用于看板全局筛选，不代表唯一设备",
  `deviceId`            varchar(64)     NULL COMMENT "手机设备 ID（content.deviceId），非吸奶器设备 ID",
  `os`                  varchar(16)     NULL COMMENT "手机操作系统（content.os），如 iOS / Android",
  `timezoneOffset`      varchar(16)     NULL COMMENT "用户时区（content.timezoneOffset），如 GMT+8 / GMT+2",
  `evtType`             varchar(32)     NULL COMMENT "细分事件类型（extraData.evtType）：suction_level=调节档位 / pump_mode=调节模式 / pause / start 等",
  `evtSource`           varchar(16)     NULL COMMENT "事件来源（extraData.evtSource）：remote_app=APP 操作，manual=硬件按键操作",
  `adjustFrom`          varchar(32)     NULL COMMENT "调节前的值（extraData.adjustFrom）；pump_mode 时为数字（0=刺激/1=泌乳/2=混合/3=自定义），suction_level 时为档位数字",
  `adjustTo`            varchar(32)     NULL COMMENT "调节后的值（extraData.adjustTo），同 adjustFrom 说明",
  `finalModeType`       varchar(32)     NULL COMMENT "吸奶过程结束时使用的模式（extraData.finalModeType），pump_session_end 事件有值",
  `finalSuctionLevel`   varchar(8)      NULL COMMENT "吸奶过程结束时使用的档位（extraData.finalSuctionLevel），pump_session_end 事件有值",
  `modeDuration`        varchar(65533)  NULL COMMENT "各模式使用时长列表（extraData.modeDuration），JSON 数组：[{\"durationSec\":1797,\"modeType\":\"expression\"},...]，pump_session_end 事件有值",
  `payload`             varchar(128)    NULL COMMENT "硬件编码（extraData.payload）；pump_device_id = uid + SUBSTRING(payload,9,4)",
  `usedModeCount`       int(11)         NULL COMMENT "整个吸奶过程使用过的模式数量（extraData.usedModeCount），pump_session_end 事件有值",
  `endReason`           varchar(32)     NULL COMMENT "结束原因（extraData.endReason），pump_session_end 事件有值",

  -- ── ETL 衍生字段 ─────────────────────────────────────────
  `writetime_dt`        datetime        NULL COMMENT "writetime 毫秒转可读时间",
  `createtime_dt`       datetime        NULL COMMENT "createtime 毫秒转可读时间",
  `evtTimestamp_dt`     datetime        NULL COMMENT "evtTimestamp 毫秒转 UTC 可读时间",
  `evt_dt`              date            NULL COMMENT "evtTimestamp 对应的 UTC 日期（业务分析用分区键）；离线补报时与 dt 不同，DWS 各表按此字段分区",
  `evtTimestamp_local`  datetime        NULL COMMENT "evtTimestamp 结合 timezoneOffset 还原的用户本地时间",
  `local_hour`          tinyint         NULL COMMENT "用户本地操作小时 0-23（取自 evtTimestamp_local）",
  `is_weekday`          tinyint(1)      NULL COMMENT "是否工作日：1=工作日，0=周末（基于 evtTimestamp_local）",
  `adjust_direction`    varchar(8)      NULL COMMENT "档位调节方向：up=上调 / down=下调 / same=不变（evtType=suction_level 时计算）",
  `total_duration_sec`  int(11)         NULL COMMENT "吸奶总时长（秒），从 modeDuration 列表中所有 durationSec 加总（pump_session_end 事件有值）",
  `pump_device_id`      varchar(128)    NULL COMMENT "吸奶器唯一设备 ID，ETL 衍生：uid + SUBSTRING(payload,9,4)；用于统计活跃设备数、新增设备数、设备留存"

) ENGINE=OLAP
PRIMARY KEY(`id`, `dt`)
COMMENT "app 埋点吸奶器日志宽表，从 dwd_tp_app_log_di 过滤 Pump Log 并展开 JSON 字段"
PARTITION BY date_trunc('day', dt)
DISTRIBUTED BY HASH(`id`)
PROPERTIES (
  "replication_num" = "1",
  "in_memory" = "false",
  "storage_format" = "DEFAULT",
  "enable_persistent_index" = "false",
  "replicated_storage" = "true",
  "partition_live_number" = "3600",
  "compression" = "LZ4"
);


-- ------------------------------------------------------------
-- ETL-1：dwd_tp_app_pump_log_di
-- 调度参数：@busi_date
-- 依赖：dwd_tp_app_log_di @busi_date 分区已就绪
-- ------------------------------------------------------------
INSERT INTO dwd_tp_app_pump_log_di
WITH log_info AS (
  SELECT
    *,
    get_json_string(content, '$.extraData') AS extraData_raw
  FROM dwd_tp_app_log_di
  WHERE eventname = 'Pump Log'
    AND dt = @busi_date
)
SELECT
  -- ── 原始基础字段 ──────────────────────────────────────────
  `id`,
  `dt`,
  `app`,
  `appid`,
  `writetime`,
  `url`,
  `traceid`,
  `uid`,
  `eventtype`,
  `content`,
  `createtime`,
  `data_source`,

  -- ── content 一级展开 ──────────────────────────────────────
  extraData_raw                                                         AS extraData,
  get_json_string(extraData_raw, '$.eventName')                         AS eventName,
  CAST(get_json_string(extraData_raw, '$.evtTimestamp') AS bigint)      AS evtTimestamp,
  get_json_string(extraData_raw, '$.useSessionId')                      AS useSessionId,

  -- ── extraData 进一步展开 ──────────────────────────────────
  get_json_string(content,      '$.eventSessionId')                     AS eventSessionId,
  get_json_string(extraData_raw,'$.deviceCode')                         AS deviceCode,
  get_json_string(content,      '$.deviceId')                           AS deviceId,
  get_json_string(content,      '$.os')                                 AS os,
  get_json_string(content,      '$.timezoneOffset')                     AS timezoneOffset,
  get_json_string(extraData_raw,'$.evtType')                            AS evtType,
  get_json_string(extraData_raw,'$.evtSource')                          AS evtSource,
  get_json_string(extraData_raw,'$.adjustFrom')                         AS adjustFrom,
  get_json_string(extraData_raw,'$.adjustTo')                           AS adjustTo,
  get_json_string(extraData_raw,'$.finalModeType')                      AS finalModeType,
  get_json_string(extraData_raw,'$.finalSuctionLevel')                  AS finalSuctionLevel,
  get_json_string(extraData_raw,'$.modeDuration')                       AS modeDuration,
  get_json_string(extraData_raw,'$.payload')                            AS payload,
  CAST(get_json_string(extraData_raw,'$.usedModeCount') AS int)         AS usedModeCount,
  get_json_string(extraData_raw,'$.endReason')                          AS endReason,

  -- ── ETL 衍生字段 ──────────────────────────────────────────
  from_unixtime(CAST(writetime   / 1000 AS bigint))                     AS writetime_dt,
  from_unixtime(CAST(createtime  / 1000 AS bigint))                     AS createtime_dt,

  from_unixtime(CAST(get_json_string(extraData_raw,'$.evtTimestamp') / 1000 AS bigint))
                                                                        AS evtTimestamp_dt,

  -- evt_dt：evtTimestamp 对应的 UTC 日期，DWS 分区键
  DATE(from_unixtime(CAST(get_json_string(extraData_raw,'$.evtTimestamp') / 1000 AS bigint)))
                                                                        AS evt_dt,

  -- 用户本地时间（timezoneOffset 格式如 "GMT+8"）
  from_unixtime(
    CAST(get_json_string(extraData_raw,'$.evtTimestamp') / 1000 AS bigint)
    + CAST(
        regexp_extract(get_json_string(content,'$.timezoneOffset'), 'GMT([+-]\\d+)', 1)
      AS int) * 3600
  )                                                                     AS evtTimestamp_local,

  hour(
    from_unixtime(
      CAST(get_json_string(extraData_raw,'$.evtTimestamp') / 1000 AS bigint)
      + CAST(
          regexp_extract(get_json_string(content,'$.timezoneOffset'), 'GMT([+-]\\d+)', 1)
        AS int) * 3600
    )
  )                                                                     AS local_hour,

  IF(
    dayofweek(
      from_unixtime(
        CAST(get_json_string(extraData_raw,'$.evtTimestamp') / 1000 AS bigint)
        + CAST(
            regexp_extract(get_json_string(content,'$.timezoneOffset'), 'GMT([+-]\\d+)', 1)
          AS int) * 3600
      )
    ) BETWEEN 2 AND 6,
    1, 0
  )                                                                     AS is_weekday,

  CASE
    WHEN get_json_string(extraData_raw,'$.evtType') = 'suction_level'
      AND CAST(get_json_string(extraData_raw,'$.adjustTo')   AS int)
        > CAST(get_json_string(extraData_raw,'$.adjustFrom') AS int) THEN 'up'
    WHEN get_json_string(extraData_raw,'$.evtType') = 'suction_level'
      AND CAST(get_json_string(extraData_raw,'$.adjustTo')   AS int)
        < CAST(get_json_string(extraData_raw,'$.adjustFrom') AS int) THEN 'down'
    WHEN get_json_string(extraData_raw,'$.evtType') = 'suction_level' THEN 'same'
    ELSE NULL
  END                                                                   AS adjust_direction,

  -- 吸奶总时长（秒）：从 modeDuration JSON 数组中加总所有 durationSec
  (
    SELECT SUM(CAST(val AS int))
    FROM (
      SELECT regexp_extract_all(
        get_json_string(extraData_raw,'$.modeDuration'),
        '"durationSec"\\s*:\\s*(\\d+)'
      ) AS vals
    ) t
    LATERAL VIEW explode(t.vals) tmp AS val
  )                                                                     AS total_duration_sec,

  -- 吸奶器唯一设备 ID：uid + payload 第 9–12 位字符
  -- payload 为空或 uid 为空时返回 NULL
  IF(
    uid IS NOT NULL AND get_json_string(extraData_raw,'$.payload') IS NOT NULL
      AND LENGTH(get_json_string(extraData_raw,'$.payload')) >= 12,
    CONCAT(uid, SUBSTRING(get_json_string(extraData_raw,'$.payload'), 9, 4)),
    NULL
  )                                                                     AS pump_device_id

FROM log_info
WHERE extraData_raw IS NOT NULL
;


-- ============================================================
-- 2. dws_pump_session_di
--    Session 粒度聚合宽表，每行 = 一次吸奶过程
--    数据来源：dwd_tp_app_pump_log_di 按 useSessionId 聚合
--    分区粒度：evt_dt（硬件事件日期）
--    主键：evt_dt + useSessionId
-- ============================================================
CREATE TABLE `dws_pump_session_di` (

  -- ── 维度 ──────────────────────────────────────────────────
  `evt_dt`              date            NOT NULL COMMENT "session 开始的硬件事件日期（UTC，分区键）",
  `useSessionId`        varchar(64)     NOT NULL COMMENT "吸奶过程唯一标识",
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


-- ------------------------------------------------------------
-- ETL-2：dws_pump_session_di
-- 调度参数：@busi_date、@late_days（建议 7）
-- 策略：INSERT OVERWRITE 按 evt_dt 覆写，扫描最近 @late_days 天 DWD dt 分区
-- ------------------------------------------------------------
INSERT OVERWRITE dws_pump_session_di
SELECT
  s.evt_dt,
  s.useSessionId,
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
         evt_dt, evtTimestamp_local, local_hour, is_weekday
  FROM dwd_tp_app_pump_log_di
  WHERE dt >= DATE_SUB(@busi_date, INTERVAL @late_days DAY)
    AND dt <= @busi_date
    AND eventName = 'pump_session_start'
    AND useSessionId IS NOT NULL
    AND evt_dt IS NOT NULL
) s

LEFT JOIN (
  SELECT useSessionId, evtTimestamp_local, total_duration_sec,
         finalModeType, finalSuctionLevel, endReason, usedModeCount
  FROM dwd_tp_app_pump_log_di
  WHERE dt >= DATE_SUB(@busi_date, INTERVAL @late_days DAY)
    AND dt <= @busi_date
    AND eventName = 'pump_session_end'
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
  FROM dwd_tp_app_pump_log_di
  WHERE dt >= DATE_SUB(@busi_date, INTERVAL @late_days DAY)
    AND dt <= @busi_date
    AND eventName = 'pump_manual_adjust_evt' AND evtType = 'pump_mode'
  GROUP BY useSessionId
) adj_mode ON s.useSessionId = adj_mode.useSessionId

LEFT JOIN (
  SELECT
    useSessionId,
    COUNT(*)                                    AS level_adj_cnt,
    SUM(IF(adjust_direction = 'up',   1, 0))    AS level_up_cnt,
    SUM(IF(adjust_direction = 'down', 1, 0))    AS level_down_cnt
  FROM dwd_tp_app_pump_log_di
  WHERE dt >= DATE_SUB(@busi_date, INTERVAL @late_days DAY)
    AND dt <= @busi_date
    AND eventName = 'pump_manual_adjust_evt' AND evtType = 'suction_level'
  GROUP BY useSessionId
) adj_level ON s.useSessionId = adj_level.useSessionId

LEFT JOIN (
  SELECT useSessionId, COUNT(*) AS pause_cnt
  FROM dwd_tp_app_pump_log_di
  WHERE dt >= DATE_SUB(@busi_date, INTERVAL @late_days DAY)
    AND dt <= @busi_date
    AND eventName = 'pump_user_evt' AND evtType = 'pause'
  GROUP BY useSessionId
) pause ON s.useSessionId = pause.useSessionId

LEFT JOIN (
  SELECT
    useSessionId,
    SUM(IF(evtSource = 'remote_app', 1, 0)) AS app_op_cnt,
    SUM(IF(evtSource = 'manual',     1, 0)) AS manual_op_cnt
  FROM dwd_tp_app_pump_log_di
  WHERE dt >= DATE_SUB(@busi_date, INTERVAL @late_days DAY)
    AND dt <= @busi_date
    AND eventName = 'pump_manual_adjust_evt'
  GROUP BY useSessionId
) src ON s.useSessionId = src.useSessionId
;


-- ============================================================
-- 3. dws_pump_session_mode_di
--    Session×模式粒度明细表，每行 = 一次吸奶过程中一个模式的使用记录
--    数据来源：dwd_tp_app_pump_log_di pump_session_end 事件，展开 modeDuration JSON 数组
--    分区粒度：evt_dt（硬件事件日期）
--    主键：evt_dt, useSessionId, modeType
-- ============================================================
CREATE TABLE `dws_pump_session_mode_di` (

  `evt_dt`          date            NOT NULL COMMENT "session 开始的硬件事件日期（UTC，分区键）",
  `useSessionId`    varchar(64)     NOT NULL COMMENT "吸奶过程唯一标识",
  `uid`             varchar(65533)  NULL     COMMENT "用户 id",
  `pump_device_id`  varchar(128)    NULL     COMMENT "吸奶器唯一设备 ID（uid + payload第9–12位）",
  `deviceCode`      varchar(32)     NULL     COMMENT "吸奶器设备型号，用于全局筛选",
  `modeType`        varchar(32)     NULL     COMMENT "模式类型，如 expression/stimulation/mixed/custom",
  `duration_sec`    int(11)         NULL     COMMENT "该模式在本次吸奶过程中的使用时长（秒）",
  `duration_min`    decimal(8,2)    NULL     COMMENT "该模式使用时长（分钟）"

) ENGINE=OLAP
PRIMARY KEY(`evt_dt`, `useSessionId`, `modeType`)
COMMENT "吸奶 session×模式粒度明细表（modeDuration 数组展开，按硬件事件日期分区）"
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


-- ------------------------------------------------------------
-- ETL-3：dws_pump_session_mode_di
-- 调度参数：@busi_date、@late_days
-- ------------------------------------------------------------
INSERT OVERWRITE dws_pump_session_mode_di
SELECT
  src.evt_dt,
  src.useSessionId,
  src.uid,
  src.pump_device_id,
  src.deviceCode,
  mode_arr[pos]                                                         AS modeType,
  CAST(dur_arr[pos] AS int)                                             AS duration_sec,
  ROUND(CAST(dur_arr[pos] AS int) / 60.0, 2)                           AS duration_min
FROM (
  SELECT
    evt_dt,
    useSessionId,
    uid,
    pump_device_id,
    deviceCode,
    regexp_extract_all(modeDuration, '"modeType"\\s*:\\s*"([^"]+)"')    AS mode_arr,
    regexp_extract_all(modeDuration, '"durationSec"\\s*:\\s*(\\d+)')    AS dur_arr
  FROM dwd_tp_app_pump_log_di
  WHERE dt >= DATE_SUB(@busi_date, INTERVAL @late_days DAY)
    AND dt <= @busi_date
    AND eventName = 'pump_session_end'
    AND modeDuration IS NOT NULL
    AND evt_dt IS NOT NULL
) src
LATERAL VIEW posexplode(src.mode_arr) tmp AS pos, _mode_val
WHERE pos < cardinality(src.dur_arr)
;


-- ============================================================
-- 4. dws_pump_daily_di
--    日粒度汇总表，每天每设备型号一行
--    分区粒度：evt_dt（硬件事件日期）
--    主键：evt_dt, deviceCode
--
--    注意：
--      active_devices / new_devices / cumulative_devices 均以 pump_device_id 计数，
--      而非 deviceCode（型号）。
--      主键仍用 deviceCode 是因为看板按型号筛选，每个 evt_dt×deviceCode 一行汇总。
-- ============================================================
CREATE TABLE `dws_pump_daily_di` (

  `evt_dt`                date            NOT NULL COMMENT "硬件事件日期（UTC，分区键）",
  `deviceCode`            varchar(32)     NULL     COMMENT "设备型号（全局筛选器，NULL 行代表全型号汇总）",

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


-- ------------------------------------------------------------
-- ETL-4：dws_pump_daily_di
-- 调度参数：@busi_date、@late_days
-- 注意：cumulative_* 全量扫描历史分区，数据量大时建议改为增量写法
-- ------------------------------------------------------------
INSERT OVERWRITE dws_pump_daily_di
SELECT
  s.evt_dt,
  s.deviceCode,

  COUNT(DISTINCT s.uid)                                                 AS dau,
  -- 活跃设备：以 pump_device_id 去重计数，而非 deviceCode（型号）
  COUNT(DISTINCT s.pump_device_id)                                      AS active_devices,

  -- 新增用户：该 uid 历史首次 evt_dt = 当日
  COUNT(DISTINCT IF(fu.first_evt_dt = s.evt_dt, s.uid, NULL))          AS new_users,
  -- 新增设备：该 pump_device_id 历史首次 evt_dt = 当日
  COUNT(DISTINCT IF(fd.first_evt_dt = s.evt_dt, s.pump_device_id, NULL)) AS new_devices,

  COUNT(DISTINCT s.useSessionId)                                        AS total_sessions,
  SUM(s.is_complete)                                                    AS complete_sessions,
  SUM(s.is_valid)                                                       AS valid_sessions,
  COALESCE(pow.power_on_cnt, 0)                                         AS power_on_cnt,
  ROUND(COUNT(DISTINCT s.useSessionId) * 1.0
        / NULLIF(COUNT(DISTINCT s.uid), 0), 2)                         AS avg_sessions_per_user,

  SUM(s.total_duration_sec)                                             AS total_duration_sec,
  ROUND(SUM(s.total_duration_sec) / 3600.0, 2)                         AS total_duration_h,
  ROUND(SUM(s.total_duration_sec) / 60.0
        / NULLIF(COUNT(DISTINCT s.useSessionId), 0), 2)                AS avg_duration_min,
  ROUND(SUM(s.total_duration_sec) / 60.0
        / NULLIF(COUNT(DISTINCT s.uid), 0), 2)                         AS avg_duration_per_user,

  ROUND(COUNT(DISTINCT s.useSessionId) * 1.0
        / NULLIF(COALESCE(pow.power_on_cnt, 0), 0), 5)                 AS start_rate,
  ROUND(SUM(s.is_complete) * 1.0
        / NULLIF(COUNT(DISTINCT s.useSessionId), 0), 5)                AS completion_rate,
  ROUND(SUM(s.is_valid) * 1.0
        / NULLIF(COUNT(DISTINCT s.useSessionId), 0), 5)                AS valid_rate,

  -- 累计指标（以 evt_dt 为时间轴，设备累计用 pump_device_id）
  (SELECT COUNT(DISTINCT uid)
   FROM dws_pump_session_di
   WHERE evt_dt <= s.evt_dt
     AND (deviceCode = s.deviceCode OR s.deviceCode IS NULL))          AS cumulative_users,
  (SELECT COUNT(DISTINCT pump_device_id)
   FROM dws_pump_session_di
   WHERE evt_dt <= s.evt_dt
     AND (deviceCode = s.deviceCode OR s.deviceCode IS NULL))          AS cumulative_devices,
  (SELECT COUNT(DISTINCT useSessionId)
   FROM dws_pump_session_di
   WHERE evt_dt <= s.evt_dt
     AND (deviceCode = s.deviceCode OR s.deviceCode IS NULL))          AS cumulative_sessions,
  ROUND(
    (SELECT SUM(total_duration_sec) / 3600.0
     FROM dws_pump_session_di
     WHERE evt_dt <= s.evt_dt
       AND (deviceCode = s.deviceCode OR s.deviceCode IS NULL))
  , 2)                                                                  AS cumulative_duration_h

FROM dws_pump_session_di s

LEFT JOIN (
  SELECT uid, MIN(evt_dt) AS first_evt_dt
  FROM dws_pump_session_di
  GROUP BY uid
) fu ON s.uid = fu.uid

LEFT JOIN (
  -- 新增设备判断：以 pump_device_id 历史首次出现日期为准
  SELECT pump_device_id, MIN(evt_dt) AS first_evt_dt
  FROM dws_pump_session_di
  WHERE pump_device_id IS NOT NULL
  GROUP BY pump_device_id
) fd ON s.pump_device_id = fd.pump_device_id

LEFT JOIN (
  SELECT
    evt_dt,
    COUNT(*) AS power_on_cnt
  FROM dwd_tp_app_pump_log_di
  WHERE dt >= DATE_SUB(@busi_date, INTERVAL @late_days DAY)
    AND dt <= @busi_date
    AND eventName = 'pump_startup_evt'
    AND evt_dt IS NOT NULL
  GROUP BY evt_dt
) pow ON s.evt_dt = pow.evt_dt

WHERE s.evt_dt >= DATE_SUB(@busi_date, INTERVAL @late_days DAY)
  AND s.evt_dt <= @busi_date
GROUP BY s.evt_dt, s.deviceCode
;


-- ============================================================
-- 5. dws_pump_retention_di
--    留存率计算表
--    分区粒度：base_dt（观测日）
--    主键：base_dt, deviceCode
--
--    用户留存：以 uid 为粒度
--    设备留存：以 pump_device_id 为粒度（唯一设备 ID，非型号）
--    所有活跃判断均基于 evt_dt（硬件事件日期）
-- ============================================================
CREATE TABLE `dws_pump_retention_di` (

  `base_dt`               date            NOT NULL COMMENT "观测日期（今天，分区键），所有留存到达日以 evt_dt 为准",
  `deviceCode`            varchar(32)     NULL     COMMENT "设备型号筛选器（NULL 行代表全型号汇总）",

  -- ── 用户留存 ──────────────────────────────────────────────
  `base_users`            int(11)         NULL COMMENT "昨日（base_dt-1）活跃用户数（留存分母，以 evt_dt 归日）",
  `d1_retained_users`     int(11)         NULL COMMENT "昨日活跃且今日（base_dt）仍活跃的用户数",
  `d7_retained_users`     int(11)         NULL COMMENT "7天前（base_dt-7）活跃且今日仍活跃的用户数",
  `d14_retained_users`    int(11)         NULL COMMENT "14天前（base_dt-14）活跃且今日仍活跃的用户数",
  `d1_user_ret`           decimal(8,5)    NULL COMMENT "用户 D1 留存率（小数，如 0.64200）",
  `d7_user_ret`           decimal(8,5)    NULL COMMENT "用户 D7 留存率（小数）",
  `d14_user_ret`          decimal(8,5)    NULL COMMENT "用户 D14 留存率（小数）",

  -- ── 设备留存（以 pump_device_id 为粒度）──────────────────
  `base_devices`          int(11)         NULL COMMENT "昨日（base_dt-1）活跃设备数（以 pump_device_id 去重，留存分母）",
  `d1_retained_devices`   int(11)         NULL COMMENT "昨日活跃且今日仍活跃的设备数（pump_device_id）",
  `d7_retained_devices`   int(11)         NULL COMMENT "7天前活跃且今日仍活跃的设备数",
  `d14_retained_devices`  int(11)         NULL COMMENT "14天前活跃且今日仍活跃的设备数",
  `d1_device_ret`         decimal(8,5)    NULL COMMENT "设备 D1 留存率（小数）",
  `d7_device_ret`         decimal(8,5)    NULL COMMENT "设备 D7 留存率（小数）",
  `d14_device_ret`        decimal(8,5)    NULL COMMENT "设备 D14 留存率（小数）",

  -- ── 新用户同期留存（未来口径）────────────────────────────
  `new_users_base`        int(11)         NULL COMMENT "base_dt 新增用户数（历史首次 evt_dt = base_dt）",
  `cohort_d1_ret`         decimal(8,5)    NULL COMMENT "新用户同期 D1 留存率（小数）",
  `cohort_d7_ret`         decimal(8,5)    NULL COMMENT "新用户同期 D7 留存率（小数）",
  `cohort_d14_ret`        decimal(8,5)    NULL COMMENT "新用户同期 D14 留存率（小数）"

) ENGINE=OLAP
PRIMARY KEY(`base_dt`, `deviceCode`)
COMMENT "吸奶留存率计算表（用户留存基于 uid，设备留存基于 pump_device_id，活跃判断基于 evt_dt）"
PARTITION BY date_trunc('day', base_dt)
DISTRIBUTED BY HASH(`base_dt`)
PROPERTIES (
  "replication_num" = "1",
  "in_memory" = "false",
  "storage_format" = "DEFAULT",
  "enable_persistent_index" = "false",
  "replicated_storage" = "true",
  "partition_live_number" = "3600",
  "compression" = "LZ4"
);


-- ------------------------------------------------------------
-- ETL-5：dws_pump_retention_di
-- 调度参数：@busi_date（观测日）
-- 所有活跃判断均基于 evt_dt；设备留存使用 pump_device_id
-- 建议：每日对近 15 天的 base_dt 循环执行（INSERT OVERWRITE 幂等）
-- ------------------------------------------------------------
INSERT OVERWRITE dws_pump_retention_di
WITH
-- 今日（base_dt）活跃用户集合
today_users AS (
  SELECT DISTINCT uid
  FROM dws_pump_session_di
  WHERE evt_dt = @busi_date
),
-- 今日活跃设备集合（pump_device_id）
today_devices AS (
  SELECT DISTINCT pump_device_id
  FROM dws_pump_session_di
  WHERE evt_dt = @busi_date AND pump_device_id IS NOT NULL
),
-- 昨日（base_dt-1）活跃用户集合（D1 留存分母）
base_users AS (
  SELECT DISTINCT uid
  FROM dws_pump_session_di
  WHERE evt_dt = DATE_SUB(@busi_date, INTERVAL 1 DAY)
),
-- 昨日活跃设备集合（pump_device_id）
base_devices AS (
  SELECT DISTINCT pump_device_id
  FROM dws_pump_session_di
  WHERE evt_dt = DATE_SUB(@busi_date, INTERVAL 1 DAY) AND pump_device_id IS NOT NULL
),
-- 7天前活跃用户集合
d7_base_users AS (
  SELECT DISTINCT uid
  FROM dws_pump_session_di
  WHERE evt_dt = DATE_SUB(@busi_date, INTERVAL 7 DAY)
),
-- 14天前活跃用户集合
d14_base_users AS (
  SELECT DISTINCT uid
  FROM dws_pump_session_di
  WHERE evt_dt = DATE_SUB(@busi_date, INTERVAL 14 DAY)
),
-- 7天前活跃设备集合
d7_base_devices AS (
  SELECT DISTINCT pump_device_id
  FROM dws_pump_session_di
  WHERE evt_dt = DATE_SUB(@busi_date, INTERVAL 7 DAY) AND pump_device_id IS NOT NULL
),
-- 14天前活跃设备集合
d14_base_devices AS (
  SELECT DISTINCT pump_device_id
  FROM dws_pump_session_di
  WHERE evt_dt = DATE_SUB(@busi_date, INTERVAL 14 DAY) AND pump_device_id IS NOT NULL
),
-- 今日新增用户（历史首次 evt_dt = base_dt）
new_users AS (
  SELECT uid
  FROM (
    SELECT uid, MIN(evt_dt) AS first_evt_dt
    FROM dws_pump_session_di
    GROUP BY uid
  ) t
  WHERE first_evt_dt = @busi_date
),
-- 新用户同期留存到达日（向未来看）
cohort_d1_users  AS (SELECT DISTINCT uid FROM dws_pump_session_di WHERE evt_dt = DATE_ADD(@busi_date, INTERVAL  1 DAY)),
cohort_d7_users  AS (SELECT DISTINCT uid FROM dws_pump_session_di WHERE evt_dt = DATE_ADD(@busi_date, INTERVAL  7 DAY)),
cohort_d14_users AS (SELECT DISTINCT uid FROM dws_pump_session_di WHERE evt_dt = DATE_ADD(@busi_date, INTERVAL 14 DAY))

SELECT
  @busi_date                                                            AS base_dt,
  NULL                                                                  AS deviceCode,

  -- 用户留存
  (SELECT COUNT(*) FROM base_users)                                     AS base_users,
  (SELECT COUNT(*) FROM base_users   JOIN today_users   USING(uid))     AS d1_retained_users,
  (SELECT COUNT(*) FROM d7_base_users  JOIN today_users USING(uid))     AS d7_retained_users,
  (SELECT COUNT(*) FROM d14_base_users JOIN today_users USING(uid))     AS d14_retained_users,
  ROUND((SELECT COUNT(*) FROM base_users   JOIN today_users USING(uid)) * 1.0
        / NULLIF((SELECT COUNT(*) FROM base_users), 0), 5)              AS d1_user_ret,
  ROUND((SELECT COUNT(*) FROM d7_base_users  JOIN today_users USING(uid)) * 1.0
        / NULLIF((SELECT COUNT(*) FROM d7_base_users), 0), 5)           AS d7_user_ret,
  ROUND((SELECT COUNT(*) FROM d14_base_users JOIN today_users USING(uid)) * 1.0
        / NULLIF((SELECT COUNT(*) FROM d14_base_users), 0), 5)          AS d14_user_ret,

  -- 设备留存（pump_device_id，非 deviceCode 型号）
  (SELECT COUNT(*) FROM base_devices)                                   AS base_devices,
  (SELECT COUNT(*) FROM base_devices    JOIN today_devices   USING(pump_device_id)) AS d1_retained_devices,
  (SELECT COUNT(*) FROM d7_base_devices  JOIN today_devices  USING(pump_device_id)) AS d7_retained_devices,
  (SELECT COUNT(*) FROM d14_base_devices JOIN today_devices  USING(pump_device_id)) AS d14_retained_devices,
  ROUND((SELECT COUNT(*) FROM base_devices   JOIN today_devices USING(pump_device_id)) * 1.0
        / NULLIF((SELECT COUNT(*) FROM base_devices), 0), 5)            AS d1_device_ret,
  ROUND((SELECT COUNT(*) FROM d7_base_devices  JOIN today_devices USING(pump_device_id)) * 1.0
        / NULLIF((SELECT COUNT(*) FROM d7_base_devices), 0), 5)         AS d7_device_ret,
  ROUND((SELECT COUNT(*) FROM d14_base_devices JOIN today_devices USING(pump_device_id)) * 1.0
        / NULLIF((SELECT COUNT(*) FROM d14_base_devices), 0), 5)        AS d14_device_ret,

  -- 新用户同期留存
  (SELECT COUNT(*) FROM new_users)                                      AS new_users_base,
  ROUND((SELECT COUNT(*) FROM new_users JOIN cohort_d1_users  USING(uid)) * 1.0
        / NULLIF((SELECT COUNT(*) FROM new_users), 0), 5)               AS cohort_d1_ret,
  ROUND((SELECT COUNT(*) FROM new_users JOIN cohort_d7_users  USING(uid)) * 1.0
        / NULLIF((SELECT COUNT(*) FROM new_users), 0), 5)               AS cohort_d7_ret,
  ROUND((SELECT COUNT(*) FROM new_users JOIN cohort_d14_users USING(uid)) * 1.0
        / NULLIF((SELECT COUNT(*) FROM new_users), 0), 5)               AS cohort_d14_ret
;
