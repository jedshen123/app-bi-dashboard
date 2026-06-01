CREATE TABLE `dws_pump_retention_di` (

  `base_dt`               date            NOT NULL COMMENT "观测日期（今天，分区键），所有留存到达日以 evt_dt 为准",
  `deviceCode`            varchar(32)     NOT NULL     COMMENT "设备型号筛选器（ALL 行代表全型号汇总）",

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


--StarRocks SQL
--********************************************************************--
--所属主题: 数据属于哪个数据域或业务场景下---如交易域、运营数据报表
--功能描述: 数据记录的描述，如数据是什么、统计粒度等
--创建者: 沈健
--创建日期: 2026-05-28 18:19:47
--修改日期     修改人     修改内容
--yyyymmdd     name     comment
--********************************************************************--
set @busi_date = DATE_FORMAT('${busi_date}', '%Y-%m-%d') ;
set oneservice.allow.full.scan = true;
SET query_timeout = 1800; 

DELETE from dws_pump_retention_di where base_dt = '${busi_date}';

INSERT into dws_pump_retention_di
WITH
-- 今日（base_dt）活跃用户集合
today_users AS (
  SELECT DISTINCT uid
  FROM dws_pump_session_df
  WHERE evt_dt = @busi_date
),
-- 今日活跃设备集合（pump_device_id）
today_devices AS (
  SELECT DISTINCT pump_device_id
  FROM dws_pump_session_df
  WHERE evt_dt = @busi_date AND pump_device_id IS NOT NULL
),
-- 昨日（base_dt-1）活跃用户集合（D1 留存分母）
base_users AS (
  SELECT DISTINCT uid
  FROM dws_pump_session_df
  WHERE evt_dt = DATE_SUB(@busi_date, INTERVAL 1 DAY)
),
-- 昨日活跃设备集合（pump_device_id）
base_devices AS (
  SELECT DISTINCT pump_device_id
  FROM dws_pump_session_df
  WHERE evt_dt = DATE_SUB(@busi_date, INTERVAL 1 DAY) AND pump_device_id IS NOT NULL
),
-- 7天前活跃用户集合
d7_base_users AS (
  SELECT DISTINCT uid
  FROM dws_pump_session_df
  WHERE evt_dt = DATE_SUB(@busi_date, INTERVAL 7 DAY)
),
-- 14天前活跃用户集合
d14_base_users AS (
  SELECT DISTINCT uid
  FROM dws_pump_session_df
  WHERE evt_dt = DATE_SUB(@busi_date, INTERVAL 14 DAY)
),
-- 7天前活跃设备集合
d7_base_devices AS (
  SELECT DISTINCT pump_device_id
  FROM dws_pump_session_df
  WHERE evt_dt = DATE_SUB(@busi_date, INTERVAL 7 DAY) AND pump_device_id IS NOT NULL
),
-- 14天前活跃设备集合
d14_base_devices AS (
  SELECT DISTINCT pump_device_id
  FROM dws_pump_session_df
  WHERE evt_dt = DATE_SUB(@busi_date, INTERVAL 14 DAY) AND pump_device_id IS NOT NULL
),
-- 今日新增用户（历史首次 evt_dt = base_dt）
new_users AS (
  SELECT uid
  FROM (
    SELECT uid, MIN(evt_dt) AS first_evt_dt
    FROM dws_pump_session_df
    GROUP BY uid
  ) t
  WHERE first_evt_dt = @busi_date
),
-- 新用户同期留存到达日（向未来看）
cohort_d1_users  AS (SELECT DISTINCT uid FROM dws_pump_session_df WHERE evt_dt = DATE_ADD(@busi_date, INTERVAL  1 DAY)),
cohort_d7_users  AS (SELECT DISTINCT uid FROM dws_pump_session_df WHERE evt_dt = DATE_ADD(@busi_date, INTERVAL  7 DAY)),
cohort_d14_users AS (SELECT DISTINCT uid FROM dws_pump_session_df WHERE evt_dt = DATE_ADD(@busi_date, INTERVAL 14 DAY))

SELECT
  @busi_date                                                            AS base_dt,
  'ALL'                                                                  AS deviceCode,

  -- 用户留存
  (SELECT COUNT(*) FROM base_users)                                     AS base_users,
  (SELECT COUNT(*) FROM base_users b JOIN today_users t ON b.uid = t.uid) AS d1_retained_users,
  (SELECT COUNT(*) FROM d7_base_users d7 JOIN today_users t ON d7.uid = t.uid) AS d7_retained_users,
  (SELECT COUNT(*) FROM d14_base_users d14 JOIN today_users t ON d14.uid = t.uid) AS d14_retained_users,
  ROUND((SELECT COUNT(*) FROM base_users b JOIN today_users t ON b.uid = t.uid) * 1.0
        / NULLIF((SELECT COUNT(*) FROM base_users), 0), 5)              AS d1_user_ret,
  ROUND((SELECT COUNT(*) FROM d7_base_users d7 JOIN today_users t ON d7.uid = t.uid) * 1.0
        / NULLIF((SELECT COUNT(*) FROM d7_base_users), 0), 5)           AS d7_user_ret,
  ROUND((SELECT COUNT(*) FROM d14_base_users d14 JOIN today_users t ON d14.uid = t.uid) * 1.0
        / NULLIF((SELECT COUNT(*) FROM d14_base_users), 0), 5)          AS d14_user_ret,

  -- 设备留存（pump_device_id，非 deviceCode 型号）
  (SELECT COUNT(*) FROM base_devices)                                   AS base_devices,
  (SELECT COUNT(*) FROM base_devices b JOIN today_devices t ON b.pump_device_id = t.pump_device_id) AS d1_retained_devices,
  (SELECT COUNT(*) FROM d7_base_devices d7 JOIN today_devices t ON d7.pump_device_id = t.pump_device_id) AS d7_retained_devices,
  (SELECT COUNT(*) FROM d14_base_devices d14 JOIN today_devices t ON d14.pump_device_id = t.pump_device_id) AS d14_retained_devices,
  ROUND((SELECT COUNT(*) FROM base_devices b JOIN today_devices t ON b.pump_device_id = t.pump_device_id) * 1.0
        / NULLIF((SELECT COUNT(*) FROM base_devices), 0), 5)            AS d1_device_ret,
  ROUND((SELECT COUNT(*) FROM d7_base_devices d7 JOIN today_devices t ON d7.pump_device_id = t.pump_device_id) * 1.0
        / NULLIF((SELECT COUNT(*) FROM d7_base_devices), 0), 5)         AS d7_device_ret,
  ROUND((SELECT COUNT(*) FROM d14_base_devices d14 JOIN today_devices t ON d14.pump_device_id = t.pump_device_id) * 1.0
        / NULLIF((SELECT COUNT(*) FROM d14_base_devices), 0), 5)        AS d14_device_ret,

  -- 新用户同期留存
  (SELECT COUNT(*) FROM new_users)                                      AS new_users_base,
  ROUND((SELECT COUNT(*) FROM new_users n JOIN cohort_d1_users c ON n.uid = c.uid) * 1.0
        / NULLIF((SELECT COUNT(*) FROM new_users), 0), 5)               AS cohort_d1_ret,
  ROUND((SELECT COUNT(*) FROM new_users n JOIN cohort_d7_users c ON n.uid = c.uid) * 1.0
        / NULLIF((SELECT COUNT(*) FROM new_users), 0), 5)               AS cohort_d7_ret,
  ROUND((SELECT COUNT(*) FROM new_users n JOIN cohort_d14_users c ON n.uid = c.uid) * 1.0
        / NULLIF((SELECT COUNT(*) FROM new_users), 0), 5)               AS cohort_d14_ret
;