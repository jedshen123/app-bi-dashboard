--STARROCKS_SQL
--********************************************************************--
--所属主题: 数据属于哪个数据域或业务场景下---如交易域、运营数据报表
--功能描述: 数据记录的描述，如数据是什么、统计粒度等
--创建者: 沈健
--创建日期: 2026-03-09 17:04:35
--修改日期     修改人     修改内容
--yyyymmdd     name     comment
--********************************************************************--

set @busi_date = DATE_FORMAT('${busi_date}', '%Y-%m-%d') ;
set oneservice.allow.full.scan = true;
SET query_timeout = 1800;    

CREATE TABLE dwd_tp_app_breast_pump_log_di (

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
  `content`       varchar(65533)  NULL     COMMENT "事件详情（原始 JSON，含 extradata）",
  `createtime`    bigint(20)      NOT NULL COMMENT "创建时间（毫秒）",
  `data_source`   varchar(32)     NULL     COMMENT "数据来源",

  -- ── 从 content 展开的一级字段 ────────────────────────────
  `extradata`     varchar(65533)  NULL     COMMENT "content.extradata 原始 JSON，吸奶器操作扩展信息",
  `eventname`     varchar(128)    NULL     COMMENT "吸奶器事件名称（extradata.eventname）",
  `evttimestamp`  bigint(20)      NULL     COMMENT "硬件记录的事件发生时间戳（毫秒，UTC 0 时区），业务分析的正确时间基准",
  `usesessionid`  varchar(64)     NULL     COMMENT "吸奶过程唯一标识，统计吸奶次数的 key",

  -- ── 从 extradata 进一步展开的字段 ────────────────────────
  `eventsessionid`      varchar(64)     NULL COMMENT "吸奶过程子流程 ID（content.eventsessionid），每次暂停后重启会更新",
  `devicecode`          varchar(32)     NULL COMMENT "吸奶器设备型号（extradata.devicecode），如 TP-A1；同一型号可有多台设备，仅用于看板全局筛选，不代表唯一设备",
  `deviceid`            varchar(64)     NULL COMMENT "手机设备 ID（content.deviceid），非吸奶器设备 ID",
  `os`                  varchar(16)     NULL COMMENT "手机操作系统（content.os），如 iOS / Android",
  `timezoneoffset`      varchar(16)     NULL COMMENT "用户时区（content.timezoneoffset），如 GMT+8 / GMT+2",
  `evttype`             varchar(32)     NULL COMMENT "细分事件类型（extradata.evttype）：suction_level=调节档位 / pump_mode=调节模式 / pause / start 等",
  `evtsource`           varchar(16)     NULL COMMENT "事件来源（extradata.evtsource）：remote_app=APP 操作，manual=硬件按键操作",
  `adjustfrom`          varchar(32)     NULL COMMENT "调节前的值（extradata.adjustfrom）；pump_mode 时为数字（0=刺激/1=泌乳/2=混合/3=自定义），suction_level 时为档位数字",
  `adjustto`            varchar(32)     NULL COMMENT "调节后的值（extradata.adjustto），同 adjustfrom 说明",
  `finalmodetype`       varchar(32)     NULL COMMENT "吸奶过程结束时使用的模式（extradata.finalmodetype），pump_session_end 事件有值",
  `finalsuctionlevel`   varchar(8)      NULL COMMENT "吸奶过程结束时使用的档位（extradata.finalsuctionlevel），pump_session_end 事件有值",
  `modeduration`        varchar(65533)  NULL COMMENT "各模式使用时长列表（extradata.modeduration）pump_session_end 事件有值",
  `payload`             varchar(128)    NULL COMMENT "硬件编码（extradata.payload）；pump_device_id = uid + substring(payload,9,4)",
  `usedmodecount`       int(11)         NULL COMMENT "整个吸奶过程使用过的模式数量（extradata.usedmodecount），pump_session_end 事件有值",
  `endreason`           varchar(32)     NULL COMMENT "结束原因（extradata.endreason），pump_session_end 事件有值",

  -- ── ETL 衍生字段 ─────────────────────────────────────────
  `writetime_dt`        datetime        NULL COMMENT "writetime 毫秒转可读时间",
  `createtime_dt`       datetime        NULL COMMENT "createtime 毫秒转可读时间",
  `evttimestamp_dt`     datetime        NULL COMMENT "evttimestamp 毫秒转 UTC 可读时间",
  `evt_dt`              date            NULL COMMENT "evttimestamp 对应的 UTC 日期（业务分析用分区键）；离线补报时与 dt 不同，DWS 各表按此字段分区",
  `evttimestamp_local`  datetime        NULL COMMENT "evttimestamp 结合 timezoneoffset 还原的用户本地时间",
  `local_hour`          bigint(20)      NULL COMMENT "用户本地操作小时 0-23（取自 evttimestamp_local）",
  `is_weekday`          bigint(20)      NULL COMMENT "是否工作日：1=工作日，0=周末（基于 evttimestamp_local）",
  `adjust_direction`    varchar(8)      NULL COMMENT "档位调节方向：up=上调 / down=下调 / same=不变（evttype=suction_level 时计算）",
  `total_duration_sec`  bigint(20)      NULL COMMENT "吸奶总时长（秒），从 modeduration 列表中所有 durationsec 加总（pump_session_end 事件有值）",
  `pump_device_id`      varchar(128)    NULL COMMENT "吸奶器唯一设备 ID，ETL 衍生：uid + substring(payload,9,4)；用于统计活跃设备数、新增设备数、设备留存"

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

set @busi_date = DATE_FORMAT('${busi_date}', '%Y-%m-%d') ;
set oneservice.allow.full.scan = true;
SET query_timeout = 1800;    

DELETE from dwd_tp_app_breast_pump_log_di where dt = '${busi_date}';

INSERT INTO dwd_tp_app_breast_pump_log_di
WITH log_info AS (
  SELECT
    *,
    get_json_string(content, '$.extraData') AS extradata_raw,
    get_json_string(get_json_string(content, '$.extraData'), '$.modeDuration') as modeduration
  FROM dwd_tp_app_log_di
  WHERE eventname = 'Pump Log'
    AND dt = @busi_date
),
sum_info as (
  SELECT
    t.id,
    SUM(get_json_int(j.value, '$.durationSec')) AS total_duration_sec
FROM log_info t,
     json_each(modeduration) j
WHERE t.extradata_raw IS NOT NULL
GROUP BY t.id
)
SELECT
  -- ── 原始基础字段 ──────────────────────────────────────────
  t1.id,
  dt,
  app,
  appid,
  writetime,
  url,
  traceid,
  uid,
  eventtype,
  content,
  createtime,
  data_source,

  -- ── content 一级展开 ──────────────────────────────────────
  extradata_raw                                                         AS extradata,
  get_json_string(extradata_raw, '$.eventName')                         AS eventname,
  CAST(get_json_string(extradata_raw, '$.evtTimestamp') AS bigint)      AS evttimestamp,
  get_json_string(extradata_raw, '$.useSessionId')                      AS usesessionid,

  -- ── extradata 进一步展开 ──────────────────────────────────
  get_json_string(content,      '$.eventSessionId')                     AS eventsessionid,
  get_json_string(extradata_raw,'$.deviceCode')                         AS devicecode,
  get_json_string(content,      '$.deviceId')                           AS deviceid,
  get_json_string(content,      '$.os')                                 AS os,
  get_json_string(content,      '$.timezoneOffset')                     AS timezoneoffset,
  get_json_string(extradata_raw,'$.evtType')                            AS evttype,
  get_json_string(extradata_raw,'$.evtSource')                          AS evtsource,
  get_json_string(extradata_raw,'$.adjustFrom')                         AS adjustfrom,
  get_json_string(extradata_raw,'$.adjustTo')                           AS adjustto,
  get_json_string(extradata_raw,'$.finalModeType')                      AS finalmodetype,
  get_json_string(extradata_raw,'$.finalSuctionLevel')                  AS finalsuctionlevel,
  get_json_string(extradata_raw,'$.modeDuration')                       AS modeduration,
  get_json_string(extradata_raw,'$.payload')                            AS payload,
  CAST(get_json_string(extradata_raw,'$.usedModeCount') AS int)         AS usedmodecount,
  get_json_string(extradata_raw,'$.endReason')                          AS endreason,

  -- ── ETL 衍生字段 ──────────────────────────────────────────
  from_unixtime(CAST(writetime   / 1000 AS bigint))                     AS writetime_dt,
  from_unixtime(CAST(createtime  / 1000 AS bigint))                     AS createtime_dt,

  from_unixtime(CAST(get_json_string(extradata_raw,'$.evtTimestamp') AS bigint))
                                                                        AS evttimestamp_dt,

  -- evt_dt：evttimestamp 对应的 UTC 日期，DWS 分区键
  DATE(from_unixtime(CAST(get_json_string(extradata_raw,'$.evtTimestamp') AS bigint)))
                                                                        AS evt_dt,

  -- 用户本地时间（timezoneoffset 格式如 "GMT+8"）
  from_unixtime(
    CAST(get_json_string(extradata_raw,'$.evtTimestamp') AS bigint)
    + CAST(
        regexp_extract(get_json_string(content,'$.timezoneOffset'), 'GMT([+-]\\d+)', 1)
      AS int) * 3600
  )                                                                     AS evttimestamp_local,

  hour(
    from_unixtime(
      CAST(get_json_string(extradata_raw,'$.evtTimestamp') / 1000 AS bigint)
      + CAST(
          regexp_extract(get_json_string(content,'$.timezoneOffset'), 'GMT([+-]\\d+)', 1)
        AS int) * 3600
    )
  )                                                                     AS local_hour,

  IF(
    dayofweek(
      from_unixtime(
        CAST(get_json_string(extradata_raw,'$.evtTimestamp') / 1000 AS bigint)
        + CAST(
            regexp_extract(get_json_string(content,'$.timezoneOffset'), 'GMT([+-]\\d+)', 1)
          AS int) * 3600
      )
    ) BETWEEN 2 AND 6,
    1, 0
  )                                                                     AS is_weekday,

  CASE
    WHEN get_json_string(extradata_raw,'$.evtType') = 'suction_level'
      AND CAST(get_json_string(extradata_raw,'$.adjustTo')   AS int)
        > CAST(get_json_string(extradata_raw,'$.adjustFrom') AS int) THEN 'up'
    WHEN get_json_string(extradata_raw,'$.evtType') = 'suction_level'
      AND CAST(get_json_string(extradata_raw,'$.adjustTo')   AS int)
        < CAST(get_json_string(extradata_raw,'$.adjustFrom') AS int) THEN 'down'
    WHEN get_json_string(extradata_raw,'$.evtType') = 'suction_level' THEN 'same'
    ELSE NULL
  END                                                                   AS adjust_direction,

  -- 吸奶总时长（秒）：从 modeduration JSON 数组中加总所有 durationSec
  t2.total_duration_sec as total_duration_sec,

  -- 吸奶器唯一设备 ID：uid + payload 第 9–12 位字符
  -- payload 为空或 uid 为空时返回 NULL
  IF(
    uid IS NOT NULL AND get_json_string(extradata_raw,'$.payload') IS NOT NULL
      AND LENGTH(get_json_string(extradata_raw,'$.payload')) >= 12,
    CONCAT(uid, SUBSTRING(get_json_string(extradata_raw,'$.payload'), 9, 4)),
    NULL
  )                                                                     AS pump_device_id
FROM log_info t1
left join sum_info t2
on t1.id = t2.id
WHERE t1.extradata_raw IS NOT NULL 
         


