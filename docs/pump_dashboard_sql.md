# 吸奶器看板 — SQL 数据接口文档

> **引擎**：StarRocks（数据库：`lute_app_dw`）  
> **时间约定**：DWS 表按 `evt_dt`（硬件事件日期）分区，查询时用 `evt_dt` 过滤；DWD 表按 `dt`（上报日期）分区。两个字段对离线补报数据会不同，分析请统一用 `evt_dt`。  
> **设备 ID**：`pump_device_id = uid + SUBSTRING(payload, 9, 4)`，已在 ETL 中预计算，直接使用字段名，无需在查询中重复拼接。  
> ⚠️ **占比约定**：所有占比 / 率字段均保留小数形式（范围 0–1），**前端负责乘以 100 显示为百分比**，SQL 中不做 `* 100` 处理。

---

## 数据层说明

| 表名 | 粒度 | 主键 | 主要用途 |
|------|------|------|----------|
| `dwd_tp_app_breast_pump_log_di` | 原始事件行 | `id + dt` | 行为明细，字段全小写；仅在 DWS 无对应聚合时直接查询 |
| `dws_pump_session_df` | 每次吸奶 session | `evt_dt + useSessionId` | session 维度分析：时长、完整率、模式、档位、操作行为 |
| `dws_pump_session_mode_df` | session × 模式 | `evt_dt + useSessionId + modeType` | 各模式使用时长 / 次数占比 |
| `dws_pump_daily_df` | 日 × 设备型号 | `evt_dt + deviceCode` | 日粒度汇总：DAU、次数、时长、转化率、累计指标 |
| `dws_pump_retention_di` | 日 × 设备型号 | `base_dt + deviceCode` | 用户 & 设备 D1/D7/D14 留存率，新用户同期留存 |

**全型号查询**：`dws_pump_daily_df` 无全型号汇总行（`deviceCode` NOT NULL），全型号指标需 `GROUP BY evt_dt` 对所有 `deviceCode` 求和。`dws_pump_retention_di` 中 `deviceCode = 'ALL'` 的行为全型号汇总行。  
**字段大小写**：DWD 表字段全小写（`eventname`, `usesessionid`, `adjustfrom`, `adjustto`, `evttype`, `evtsource`）；DWS session 表字段混合大小写（`useSessionId`, `finalModeType`, `finalSuctionLevel`, `usedModeCount`）。  
**日期参数**：统一用 `${start_dt}` / `${end_dt}`（格式 `YYYY-MM-DD`），DWS 表过滤 `evt_dt`，DWD 表过滤 `evt_dt`（也已预计算）。

---

## 对应关系索引

| SQL ID | 所在 Tab | 图表/组件 | 数据来源 |
|--------|----------|-----------|----------|
| KPI-01 | 总览 | 顶部 KPI 卡片 | `dws_pump_daily_df` |
| CHART-01 | 总览 | DAU & 活跃设备趋势折线图 | `dws_pump_daily_df` |
| CHART-02 | 总览 | 每日吸奶次数趋势柱状图 | `dws_pump_daily_df` |
| CHART-03 | 总览 | 最常用结束模式水平条形 | `dws_pump_session_df` |
| CHART-04 | 总览 | 常用档位分布环形图 | `dws_pump_session_df` |
| CHART-05 | 总览 | 吸奶高峰时段 Top6 | `dws_pump_session_df` |
| CHART-06 | 留存 | 用户留存率趋势折线图 | `dws_pump_retention_di` |
| CHART-06b | 留存 | 设备留存率趋势折线图 | `dws_pump_retention_di` |
| CHART-07 | 留存 | 连续活跃天数分布柱状图 | `dws_pump_session_df` |
| TABLE-01 | 留存 | 新用户同期留存队列表 | `dws_pump_session_df` |
| newUserDev | 留存 | 每日新增用户 & 设备趋势 | `dws_pump_daily_df` |
| chart_sess_daily_trend | 次数 | 每日吸奶次数趋势折线图 | `dws_pump_daily_df` |
| chart_sess_avg_per_user | 次数 | 人均每日吸奶次数趋势 | `dws_pump_daily_df` |
| CHART-08 | 次数 | 每日次数离散分布柱状图 | `dws_pump_session_df` |
| CHART-09 | 次数 | 各次数区间按日趋势堆积图 | `dws_pump_session_df` |
| CHART-10 | 次数 | 用户粒度累计次数分布环形图 | `dws_pump_session_df` |
| CHART-11 | 次数 | 设备粒度累计次数分布环形图 | `dws_pump_session_df` |
| chart_mode_sess_dist | 次数 | 各模式吸奶次数占比环形图 | `dws_pump_session_mode_df` |
| chart_mode_sess_trend | 次数 | 各模式吸奶次数趋势堆积图 | `dws_pump_session_mode_df` |
| chart_dur_daily_trend | 时长 | 每日吸奶总时长趋势折线图 | `dws_pump_daily_df` |
| chart_dur_avg_per_user | 时长 | 人均每日吸奶时长趋势折线图 | `dws_pump_daily_df` |
| CHART-12 | 时长 | 吸奶时长分布柱状图 | `dws_pump_session_df` |
| CHART-13 | 时长 | 次均时长趋势折线图 | `dws_pump_daily_df` |
| CHART-14 | 时长 | 每日时长 & 累计时长折线图 | `dws_pump_daily_df` |
| chart_mode_dur_dist | 时长 | 各模式吸奶时长占比环形图 | `dws_pump_session_mode_df` |
| chart_mode_dur_trend | 时长 | 各模式吸奶时长趋势堆积图 | `dws_pump_session_mode_df` |
| CHART-15 | 习惯 | 吸奶时段热力图（工作日/周末） | `dws_pump_session_df` |
| TABLE-02 | 习惯 | 结束模式 × 结束档位交叉表 | `dws_pump_session_df` |
| CHART-16 | 习惯 | 混合模式使用分布条形 | `dws_pump_session_df` |
| CHART-17 | 习惯 | 模式调节路径 Top6 | `dwd_tp_app_breast_pump_log_di` |
| CHART-18 | 习惯 | 档位调节方向环形图 | `dws_pump_session_df` |
| CHART-19 | 习惯 | 每次吸奶调节次数分布柱状图 | `dws_pump_session_df` |
| KPI-02 | 有效进程 | 漏斗 4 个 KPI 卡片 | `dws_pump_daily_df` |
| CHART-20 | 有效进程 | 漏斗各阶段每日趋势折线图 | `dws_pump_daily_df` |
| CHART-21 | 有效进程 | 完整率 & 有效率趋势折线图 | `dws_pump_daily_df` |

---

## 返回格式约定

- 时间序列类：按 `evt_dt`（前端收到字段名为 `dt`）升序返回
- 分布类：按 `bucket_order` 升序，保证区间顺序正确
- **占比字段均为小数（0–1），前端 `(pct * 100).toFixed(1)` 显示为百分比**
- 字段名即前端 JS 映射键名

---

## 总览 Tab

### KPI-01 · 全局汇总 KPI

**对应**：`kpi01` + `kpi01_extra`  
**数据来源**：`dws_pump_daily_df`（SUM 所有 deviceCode，无全型号行）+ `dws_pump_retention_di`

```sql
-- kpi01
SELECT
    MAX(cumulative_users)    AS total_users,
    MAX(cumulative_devices)  AS total_devices,
    SUM(total_sessions)      AS total_sessions,
    ROUND(SUM(total_sessions) / NULLIF(SUM(dau), 0), 2) AS avg_sessions_per_user,
    ROUND(SUM(valid_sessions) / NULLIF(SUM(total_sessions), 0), 5) AS valid_session_rate_pct,
    ROUND(SUM(total_duration_h), 2) AS total_duration_hours,
    ROUND(SUM(total_duration_sec) / 60.0 / NULLIF(SUM(total_sessions), 0), 2) AS avg_duration_min,
    ROUND(MAX(cumulative_devices) / NULLIF(MAX(cumulative_users), 0), 4) AS devices_per_user
FROM dws_pump_daily_df
WHERE evt_dt BETWEEN '${start_dt}' AND '${end_dt}';

-- d1_retention_pct (最近一天)
SELECT d1_user_ret
FROM dws_pump_retention_di
WHERE deviceCode = 'ALL'
ORDER BY base_dt DESC
LIMIT 1;
```

### CHART-01 · DAU & 活跃设备趋势

**返回字段**：`dt`, `dau`, `active_devices`

```sql
SELECT evt_dt AS dt,
    SUM(dau)            AS dau,
    SUM(active_devices) AS active_devices
FROM dws_pump_daily_df
WHERE evt_dt BETWEEN '${start_dt}' AND '${end_dt}'
GROUP BY evt_dt ORDER BY evt_dt;
```

### CHART-02 · 每日吸奶次数趋势

**返回字段**：`dt`, `session_count`

```sql
SELECT evt_dt AS dt, SUM(total_sessions) AS session_count
FROM dws_pump_daily_df
WHERE evt_dt BETWEEN '${start_dt}' AND '${end_dt}'
GROUP BY evt_dt ORDER BY evt_dt;
```

### CHART-03 · 最常用结束模式

**返回字段**：`mode_type`, `session_count`, `pct`（0–1）

```sql
SELECT finalModeType AS mode_type,
    COUNT(DISTINCT useSessionId) AS session_count,
    ROUND(COUNT(DISTINCT useSessionId)
        / SUM(COUNT(DISTINCT useSessionId)) OVER(), 5) AS pct
FROM dws_pump_session_df
WHERE evt_dt BETWEEN '${start_dt}' AND '${end_dt}'
  AND finalModeType IS NOT NULL
GROUP BY mode_type
ORDER BY session_count DESC;
```

### CHART-04 · 常用档位分布

**返回字段**：`level_bucket`, `bucket_order`, `session_count`, `pct`（0–1）

```sql
SELECT
    CASE
        WHEN CAST(finalSuctionLevel AS INT) BETWEEN 1 AND 3 THEN '1–3档'
        WHEN CAST(finalSuctionLevel AS INT) BETWEEN 4 AND 6 THEN '4–6档'
        WHEN CAST(finalSuctionLevel AS INT) BETWEEN 7 AND 9 THEN '7–9档'
        ELSE '9+档'
    END AS level_bucket,
    ...bucket_order...
    ROUND(.../ SUM(...) OVER(), 5) AS pct
FROM dws_pump_session_df
WHERE evt_dt BETWEEN '${start_dt}' AND '${end_dt}'
  AND finalSuctionLevel IS NOT NULL
GROUP BY level_bucket, bucket_order ORDER BY bucket_order;
```

### CHART-05 · 吸奶高峰时段 Top6

**返回字段**：`local_hour`, `session_count`, `pct`（0–1）

```sql
SELECT local_hour,
    COUNT(DISTINCT useSessionId) AS session_count,
    ROUND(COUNT(DISTINCT useSessionId) / SUM(COUNT(DISTINCT useSessionId)) OVER(), 5) AS pct
FROM dws_pump_session_df
WHERE evt_dt BETWEEN '${start_dt}' AND '${end_dt}'
  AND local_hour IS NOT NULL
GROUP BY local_hour
ORDER BY session_count DESC LIMIT 6;
```

---

## 留存 Tab

### CHART-06 · 用户留存率趋势

**返回字段**：`base_date`, `d1_user_retention_pct`, `d7_user_retention_pct`（均为 0–1 小数）

```sql
SELECT base_dt AS base_date,
    d1_user_ret AS d1_user_retention_pct,
    d7_user_ret AS d7_user_retention_pct
FROM dws_pump_retention_di
WHERE deviceCode = 'ALL'
  AND base_dt BETWEEN '${start_dt}' AND '${end_dt}'
ORDER BY base_dt;
```

### CHART-06b · 设备留存率趋势

**返回字段**：`base_date`, `d1_device_retention_pct`（0–1）

```sql
SELECT base_dt AS base_date, d1_device_ret AS d1_device_retention_pct
FROM dws_pump_retention_di
WHERE deviceCode = 'ALL'
  AND base_dt BETWEEN '${start_dt}' AND '${end_dt}'
ORDER BY base_dt;
```

### newUserDev · 每日新增用户 & 设备

**返回字段**：`dt`, `new_users`, `new_devices`

```sql
SELECT evt_dt AS dt, SUM(new_users) AS new_users, SUM(new_devices) AS new_devices
FROM dws_pump_daily_df
WHERE evt_dt BETWEEN '${start_dt}' AND '${end_dt}'
GROUP BY evt_dt ORDER BY evt_dt;
```

### CHART-07 · 连续活跃天数分布

**返回字段**：`streak_bucket`, `bucket_order`, `user_count`, `pct`（0–1）  
**来源**：`dws_pump_session_df`，计算每个用户历史最长连续活跃天数

```sql
WITH user_dates AS (
    SELECT uid, evt_dt AS active_date FROM dws_pump_session_df
    WHERE uid IS NOT NULL GROUP BY uid, evt_dt
),
numbered AS (
    SELECT uid, active_date,
        ROW_NUMBER() OVER (PARTITION BY uid ORDER BY active_date) AS rn
    FROM user_dates
),
grouped AS (
    SELECT uid, DATE_SUB(active_date, INTERVAL rn DAY) AS grp_key FROM numbered
),
streak_len AS (
    SELECT uid, grp_key, COUNT(*) AS streak_days FROM grouped GROUP BY uid, grp_key
),
max_streak AS (SELECT uid, MAX(streak_days) AS max_consecutive_days FROM streak_len GROUP BY uid)
SELECT
    CASE WHEN max_consecutive_days = 1 THEN '1天' ... ELSE '30+天' END AS streak_bucket,
    ...bucket_order...,
    COUNT(uid) AS user_count,
    ROUND(COUNT(uid) / SUM(COUNT(uid)) OVER(), 4) AS pct
FROM max_streak GROUP BY streak_bucket, bucket_order ORDER BY bucket_order;
```

### TABLE-01 · 新用户同期留存队列表

**返回字段**：`install_week`, `new_users`, `d1_pct`, `d3_pct`, `d7_pct`, `d14_pct`（均 0–1）  
**来源**：`dws_pump_session_df`，以 `MIN(evt_dt)` 为安装日，按周分组

### 留存 summary

| 字段 | 含义 | 来源 |
|------|------|------|
| `avg_dau` | 区间内日均 DAU | `dws_pump_daily_df` AVG |
| `avg_devices` | 区间内日均活跃设备 | `dws_pump_daily_df` AVG |
| `d1_user_pct` | 区间内平均 D1 用户留存率 | `dws_pump_retention_di` AVG(`d1_user_ret`) |
| `d7_user_pct` | 区间内平均 D7 用户留存率 | `dws_pump_retention_di` AVG(`d7_user_ret`) |
| `d1_device_pct` | 区间内平均 D1 设备留存率 | `dws_pump_retention_di` AVG(`d1_device_ret`) |
| `d7_device_pct` | 区间内平均 D7 设备留存率 | `dws_pump_retention_di` AVG(`d7_device_ret`) |
| `new_users_yday` | 截止日当天新增用户数 | `dws_pump_daily_df` SUM(`new_users`) WHERE evt_dt = end |
| `new_devices_yday` | 截止日当天新增设备数 | `dws_pump_daily_df` SUM(`new_devices`) WHERE evt_dt = end |

---

## 次数 Tab

### chart_sess_daily_trend · 每日吸奶次数趋势

同 CHART-02，返回字段：`dt`, `session_count`

### chart_sess_avg_per_user · 人均每日吸奶次数趋势

**返回字段**：`dt`, `avg_sessions`

```sql
SELECT evt_dt AS dt,
    ROUND(SUM(total_sessions) / NULLIF(SUM(dau), 0), 2) AS avg_sessions
FROM dws_pump_daily_df
WHERE evt_dt BETWEEN '${start_dt}' AND '${end_dt}'
GROUP BY evt_dt ORDER BY evt_dt;
```

### CHART-08 · 每日次数离散分布

**返回字段**：`session_bucket`, `bucket_order`, `user_day_count`, `pct`（0–1）  
**来源**：`dws_pump_session_df`，按 `evt_dt + uid` 统计当日次数后分桶

### CHART-09 · 各次数区间按日趋势

**返回字段**：`dt`, `session_bucket`, `cnt_of_day`, `pct_of_day`（0–1）

### CHART-10 · 用户粒度累计次数分布

**返回字段**：`cumulative_bucket`, `bucket_order`, `user_count`, `pct`（0–1）  
**来源**：`dws_pump_session_df`，按 uid 统计区间内总次数

### CHART-11 · 设备粒度累计次数分布

同 CHART-10，按 `pump_device_id` 粒度，返回字段 `device_count`, `pct`

### chart_mode_sess_dist · 各模式吸奶次数分布

**返回字段**：`mode_type`, `cnt`

```sql
SELECT modeType AS mode_type, COUNT(DISTINCT useSessionId) AS cnt
FROM dws_pump_session_mode_df
WHERE evt_dt BETWEEN '${start_dt}' AND '${end_dt}'
GROUP BY modeType ORDER BY cnt DESC;
```

### chart_mode_sess_trend · 各模式吸奶次数趋势

**返回字段**：`dt`, `mode_type`, `cnt`, `pct`（0–1，各日内各模式占比）

```sql
SELECT evt_dt AS dt, modeType AS mode_type,
    COUNT(DISTINCT useSessionId) AS cnt,
    ROUND(COUNT(DISTINCT useSessionId)
        / SUM(COUNT(DISTINCT useSessionId)) OVER (PARTITION BY evt_dt), 5) AS pct
FROM dws_pump_session_mode_df
WHERE evt_dt BETWEEN '${start_dt}' AND '${end_dt}'
GROUP BY evt_dt, modeType ORDER BY evt_dt;
```

---

## 时长 Tab

### chart_dur_daily_trend · 每日吸奶总时长趋势

**返回字段**：`dt`, `total_hours`

```sql
SELECT evt_dt AS dt, ROUND(SUM(total_duration_h), 2) AS total_hours
FROM dws_pump_daily_df
WHERE evt_dt BETWEEN '${start_dt}' AND '${end_dt}'
GROUP BY evt_dt ORDER BY evt_dt;
```

### chart_dur_avg_per_user · 人均每日吸奶时长趋势

**返回字段**：`dt`, `avg_min_per_user`

```sql
SELECT evt_dt AS dt,
    ROUND(SUM(total_duration_sec) / 60.0 / NULLIF(SUM(dau), 0), 2) AS avg_min_per_user
FROM dws_pump_daily_df
WHERE evt_dt BETWEEN '${start_dt}' AND '${end_dt}'
GROUP BY evt_dt ORDER BY evt_dt;
```

### CHART-12 · 吸奶时长分布

**返回字段**：`duration_bucket`, `bucket_order`, `session_count`, `pct`（0–1）  
**来源**：`dws_pump_session_df`，按 `total_duration_sec` 分桶，仅取 `is_complete=1`

### CHART-13 · 次均时长趋势

**返回字段**：`dt`, `avg_duration_min`  
**来源**：`dws_pump_daily_df`，加权平均 `avg_duration_min`

### CHART-14 · 每日时长 & 累计时长

**返回字段**：`dt`, `daily_hours`, `cumulative_hours_k`（累计小时数 ÷ 1000）

```sql
SELECT evt_dt AS dt,
    ROUND(SUM(total_duration_h), 2) AS daily_hours,
    ROUND(MAX(cumulative_duration_h) / 1000.0, 3) AS cumulative_hours_k
FROM dws_pump_daily_df
WHERE evt_dt BETWEEN '${start_dt}' AND '${end_dt}'
GROUP BY evt_dt ORDER BY evt_dt;
```

### chart_mode_dur_dist · 各模式吸奶时长分布

**返回字段**：`mode_type`, `duration_min`

```sql
SELECT modeType AS mode_type, ROUND(SUM(duration_sec) / 60.0, 2) AS duration_min
FROM dws_pump_session_mode_df
WHERE evt_dt BETWEEN '${start_dt}' AND '${end_dt}'
GROUP BY modeType ORDER BY duration_min DESC;
```

### chart_mode_dur_trend · 各模式吸奶时长趋势

**返回字段**：`dt`, `mode_type`, `dur_min`, `pct`（0–1，各日内各模式时长占比）

```sql
SELECT evt_dt AS dt, modeType AS mode_type,
    ROUND(SUM(duration_sec) / 60.0, 2) AS dur_min,
    ROUND(SUM(duration_sec)
        / NULLIF(SUM(SUM(duration_sec)) OVER (PARTITION BY evt_dt), 0), 5) AS pct
FROM dws_pump_session_mode_df
WHERE evt_dt BETWEEN '${start_dt}' AND '${end_dt}'
GROUP BY evt_dt, modeType ORDER BY evt_dt;
```

### 时长 summary

| 字段 | 含义 | 计算方式 |
|------|------|----------|
| `total_duration_hours` | 区间内总吸奶时长（小时） | `SUM(total_duration_h)` |
| `avg_duration_min` | 区间内次均时长（分钟） | 加权平均 `avg_duration_min` |
| `daily_min_per_user` | 区间内人均每日时长（分钟） | `总分钟 / 总用户数 / 天数` |
| `valid_session_rate_pct` | 有效进程率（0–1） | `SUM(valid_sessions) / SUM(total_sessions)` |

---

## 习惯 Tab

### CHART-15 · 时段热力图（工作日/周末）

**返回字段**：`day_type`（工作日/周末）, `local_hour`, `session_count`, `pct`（0–1，各 day_type 内占比）  
**来源**：`dws_pump_session_df`，`is_weekday` + `local_hour` 均已预计算

### TABLE-02 · 结束模式 × 结束档位交叉表

**返回字段**：`final_mode`, `level_bucket`, `session_count`, `pct_within_mode`（0–1）  
**来源**：`dws_pump_session_df`，`finalModeType` + `finalSuctionLevel`

### CHART-16 · 混合模式使用分布

**返回字段**：`mode_mix_type`, `bucket_order`, `session_count`, `pct`（0–1）  
**来源**：`dws_pump_session_df`，`usedModeCount`（1=单一/2=混合2种/3+=混合3+种）

### CHART-17 · 模式调节路径 Top6

**来源**：`dwd_tp_app_breast_pump_log_di`（DWS 只存路径字符串，不便于重新聚合）  
**返回字段**：`from_mode`, `to_mode`, `adjust_path`, `adjust_count`, `pct`（0–1）

```sql
-- 注意：DWD 字段全小写
SELECT
    CASE adjustfrom WHEN '0' THEN '刺激' WHEN '1' THEN '泌乳'
        WHEN '2' THEN '混合' WHEN '3' THEN '自定义' ELSE adjustfrom END AS from_mode,
    CASE adjustto   WHEN '0' THEN '刺激' WHEN '1' THEN '泌乳'
        WHEN '2' THEN '混合' WHEN '3' THEN '自定义' ELSE adjustto   END AS to_mode,
    CONCAT(...) AS adjust_path,
    COUNT(*) AS adjust_count,
    ROUND(COUNT(*) / SUM(COUNT(*)) OVER(), 4) AS pct
FROM dwd_tp_app_breast_pump_log_di
WHERE evt_dt BETWEEN '${start_dt}' AND '${end_dt}'
  AND eventname = 'pump_manual_adjust_evt'
  AND evttype = 'pump_mode'
  AND adjustfrom IS NOT NULL AND adjustto IS NOT NULL
GROUP BY from_mode, to_mode, adjust_path
ORDER BY adjust_count DESC LIMIT 6;
```

### CHART-18 · 档位调节方向

**返回字段**：`direction`（调高档位/调低档位/不变）, `adjust_count`, `pct`（0–1）  
**来源**：`dws_pump_session_df`，`level_up_cnt` + `level_down_cnt` + `(level_adj_cnt - up - down)`

### CHART-19 · 每次吸奶调节次数分布

**返回**：`{level: [...], mode: [...]}` 两组  
**字段**：`adj_bucket`, `bucket_order`, `session_count`, `pct`（0–1）  
**来源**：`dws_pump_session_df`，`level_adj_cnt` / `mode_adj_cnt`（每 session 次数）

---

## 有效进程 Tab

### KPI-02 · 漏斗 KPI

**返回字段**：`power_on_cnt`, `devices_powered_on`, `started_sessions`, `ended_sessions`, `valid_sessions`

```sql
SELECT SUM(power_on_cnt) AS power_on_cnt, SUM(dau) AS devices_powered_on,
    SUM(total_sessions) AS started_sessions,
    SUM(complete_sessions) AS ended_sessions,
    SUM(valid_sessions) AS valid_sessions
FROM dws_pump_daily_df
WHERE evt_dt BETWEEN '${start_dt}' AND '${end_dt}';
```

### CHART-20 · 漏斗各阶段每日趋势

**返回字段**：`dt`, `power_on_cnt`, `started_cnt`, `ended_cnt`, `valid_cnt`

```sql
SELECT evt_dt AS dt,
    SUM(power_on_cnt) AS power_on_cnt, SUM(total_sessions) AS started_cnt,
    SUM(complete_sessions) AS ended_cnt, SUM(valid_sessions) AS valid_cnt
FROM dws_pump_daily_df
WHERE evt_dt BETWEEN '${start_dt}' AND '${end_dt}'
GROUP BY evt_dt ORDER BY evt_dt;
```

### CHART-21 · 完整率 & 有效率趋势

**返回字段**：`dt`, `completion_rate_pct`（×100 的百分数）, `valid_rate_pct`（×100 的百分数）  
注：此两字段前端直接显示为百分数，不需要再乘以 100

```sql
SELECT evt_dt AS dt,
    ROUND(SUM(complete_sessions) / NULLIF(SUM(total_sessions), 0) * 100, 2) AS completion_rate_pct,
    ROUND(SUM(valid_sessions) / NULLIF(SUM(complete_sessions), 0) * 100, 2) AS valid_rate_pct
FROM dws_pump_daily_df
WHERE evt_dt BETWEEN '${start_dt}' AND '${end_dt}'
GROUP BY evt_dt ORDER BY evt_dt;
```

---

*文档版本：20260528v1 — 对应 pump_data.py PUMP_SQL_VERSION*
