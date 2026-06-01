CREATE TABLE `dws_pump_session_mode_df` (

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

set oneservice.allow.full.scan = true;
SET query_timeout = 1800;  

truncate table dws_pump_session_mode_df;

-- ------------------------------------------------------------
-- ETL-3：dws_pump_session_mode_di
-- 调度参数：@busi_date、@late_days
-- ------------------------------------------------------------
INSERT into dws_pump_session_mode_df
WITH log_info AS (
  SELECT
    *
  FROM dwd_tp_app_breast_pump_log_di
  where modeduration IS NOT NULL
),
duration_info as (
  SELECT
    t.id,
    get_json_string(j.value, '$.modeType') AS modeType,
    get_json_int(j.value, '$.durationSec') AS durationSec
FROM log_info t,
     json_each(modeduration) j
)
select evt_dt,
    useSessionId,
    t2.modeType,
    uid,
    pump_device_id,
    deviceCode,
    t2.durationSec,
    ROUND(CAST(t2.durationSec AS int) / 60.0, 2)  
from log_info t1 
left join duration_info t2 
on t1.id = t2.id
where t2.modeType is not null
and t2.durationSec is not null
and useSessionId is not null
and evt_dt is not null
