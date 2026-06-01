# 吸奶器看板数据核对文档

> 更新时间：2026-05-29  
> 核对区间：2026-04-29 ~ 2026-05-28（近30天）  
> 数据源：`lute_app_dw`（美东 StarRocks，经 MCP → Superset SQL Lab）  
> deviceCode 过滤：全部型号（无过滤）  
> 缓存版本：20260529v7

---

## 数据表说明

| 常量 | 完整表名 | 说明 |
|------|----------|------|
| `DWD`   | `lute_app_dw.dwd_tp_app_breast_pump_log_di` | 事件明细层，字段全小写 |
| `SESS`  | `lute_app_dw.dws_pump_session_df`           | session 级汇总，混合大小写字段 |
| `DAILY` | `lute_app_dw.dws_pump_daily_df`             | 日粒度汇总，无全品类行（SUM all deviceCodes） |
| `MODE`  | `lute_app_dw.dws_pump_session_mode_df`      | session × 模式级明细 |
| `RET`   | `lute_app_dw.dws_pump_retention_di`         | 留存率表，`deviceCode='ALL'` 为全品类汇总行 |

---

## 一、总览（overview）

### 1.1 累计汇总 KPI 卡片（上方第一行）

**看板位置**：总览 → 累计总览区  
**卡片**：累计活跃用户数 / 累计活跃设备数 / 总吸奶次数 / 总吸奶时长 / 次留率(D1) / 有效进程率

**SQL**（`query_kpi01`）
```sql
SELECT
    MAX(cumulative_users)    AS total_users,
    MAX(cumulative_devices)  AS total_devices,
    SUM(total_sessions)      AS total_sessions,
    ROUND(SUM(total_sessions) / COUNT(DISTINCT evt_dt), 2) AS avg_sessions_per_user,
    ROUND(SUM(valid_sessions) / NULLIF(SUM(total_sessions), 0), 5) AS valid_session_rate_pct,
    ROUND(SUM(total_duration_h), 2) AS total_duration_hours,
    ROUND(SUM(avg_duration_min * total_sessions) / NULLIF(SUM(total_sessions), 0), 2) AS avg_duration_min,
    ROUND(MAX(cumulative_devices) / NULLIF(MAX(cumulative_users), 0), 4) AS devices_per_user
FROM lute_app_dw.dws_pump_daily_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
```

**当前结果**

| 指标 | 数值 | 看板显示 |
|------|------|---------|
| 累计活跃用户数 | 3,908 人 | 累计活跃用户数 |
| 累计活跃设备数 | 6,035 台 | 累计活跃设备数 |
| 总吸奶次数 | 242,977 次 | 总吸奶次数 |
| 有效进程率 | 0.8959 → 89.6% | 有效进程率（时长>10分钟） |
| 总吸奶时长 | 134,039 h → **134.0 kh** | 总吸奶时长 |
| 次均时长 | 33.1 分钟 | 次均 33.1 分钟（副标签） |
| 人均设备数 | 1.54 台/人 | 人均 X 台（副标签） |

> `devices_per_user` 来自本表；`d1_retention_pct` 另由 `query_d1_ret(end)` 从 `RET` 表取最新行

**D1留存率 SQL**（`query_d1_ret`）
```sql
SELECT d1_user_ret FROM lute_app_dw.dws_pump_retention_di
WHERE deviceCode = 'ALL' ORDER BY base_dt DESC LIMIT 1
```
**结果**：0.79932 → **79.9%**

---

### 1.2 昨日 KPI 卡片（下方第二行）

**看板位置**：总览 → 昨日概览区  
**卡片**：昨日 DAU / 昨日活跃设备 / 昨日吸奶次数 / 昨日吸奶时长 / 次留率(D1) / 有效进程率  
（每卡显示"较前1日"和"较前7日均值"环比）

**SQL**（`query_kpi_yesterday`，快照取 `2026-05-28`）
```sql
-- 当日快照
SELECT evt_dt, SUM(dau) AS dau, SUM(active_devices) AS active_devices,
    SUM(total_sessions) AS sessions,
    ROUND(SUM(total_duration_h), 2) AS duration_hours,
    ROUND(SUM(avg_duration_min * total_sessions)/NULLIF(SUM(total_sessions),0), 2) AS avg_dur_min,
    ROUND(SUM(valid_sessions)/NULLIF(SUM(total_sessions),0), 5) AS valid_rate
FROM lute_app_dw.dws_pump_daily_df
WHERE evt_dt = '2026-05-28'

-- 前1日快照：evt_dt = '2026-05-27'
-- 前7日均值：evt_dt BETWEEN '2026-05-21' AND '2026-05-27'（7日 AVG）
```

**当前结果**

| 指标 | 昨日值 | 较前1日 | 较前7日均值 |
|------|--------|---------|------------|
| DAU | 1,407 | ↓ 4.9% | ↓ 11.4% |
| 活跃设备 | 2,230 | ↓ 5.0% | ↓ 10.9% |
| 吸奶次数 | 6,133 | ↓ 9.5% | ↓ 13.4% |
| 吸奶时长 | 3,440 h | ↑ 0.8% | ↓ 8.0% |
| 次留率D1 | 79.9% | ↑ 3.6pp | — |
| 有效进程率 | 92.3% | ↑ 2.6pp | ↑ 3.3pp |

---

### 1.3 日活/活跃设备趋势（折线图 chart01）

**看板位置**：总览 → 日活跃用户与设备趋势

**SQL**（`query_chart01`）
```sql
SELECT evt_dt AS dt, SUM(dau) AS dau, SUM(active_devices) AS active_devices
FROM lute_app_dw.dws_pump_daily_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
GROUP BY evt_dt ORDER BY evt_dt
```

**结果摘要**：共30行，首日 dau=192/active_devices=245，末日(05-28) dau=1,407/active_devices=2,230

---

### 1.4 每日吸奶次数趋势（折线图 chart02）

**看板位置**：总览 → 每日吸奶次数趋势

**SQL**（`query_chart02`）
```sql
SELECT evt_dt AS dt, SUM(total_sessions) AS session_count
FROM lute_app_dw.dws_pump_daily_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
GROUP BY evt_dt ORDER BY evt_dt
```

**结果摘要**：共30行，首日352次，末日6,133次

---

### 1.5 最终模式分布（饼图 chart03）

**看板位置**：总览 → 最终使用模式分布

**SQL**（`query_chart03`）
```sql
SELECT finalModeType AS mode_type,
    COUNT(DISTINCT useSessionId) AS session_count,
    ROUND(COUNT(DISTINCT useSessionId) / SUM(COUNT(DISTINCT useSessionId)) OVER(), 5) AS pct
FROM lute_app_dw.dws_pump_session_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
  AND finalModeType IS NOT NULL
GROUP BY mode_type ORDER BY session_count DESC
```

**当前结果**

| 模式 | 次数 | 占比 |
|------|------|------|
| 泌乳(expression) | 150,840 | 62.8% |
| 混合(massage) | 64,103 | 26.7% |
| 刺激(stimulation) | 25,398 | 10.6% |

---

### 1.6 最终档位分布（柱图 chart04）

**看板位置**：总览 → 最终档位分布

**SQL**（`query_chart04`）
```sql
SELECT CASE WHEN CAST(finalSuctionLevel AS INT) BETWEEN 1 AND 3 THEN '1–3档' ...END AS level_bucket,
    COUNT(DISTINCT useSessionId) AS session_count,
    ROUND(...) AS pct
FROM lute_app_dw.dws_pump_session_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
  AND finalSuctionLevel IS NOT NULL AND finalSuctionLevel != '0'
GROUP BY level_bucket ORDER BY bucket_order
```

**当前结果**

| 档位段 | 次数 | 占比 |
|--------|------|------|
| 1–3档 | 91,406 | 38.0% |
| 4–6档 | 93,197 | 38.8% |
| 7–9档 | 55,738 | 23.2% |

---

### 1.7 高频时段 TOP6（横向柱图 chart05）

**看板位置**：总览 → 常用吸奶时段 TOP6

**SQL**（`query_chart05`）
```sql
SELECT local_hour, COUNT(DISTINCT useSessionId) AS session_count,
    ROUND(COUNT(DISTINCT useSessionId) / SUM(COUNT(DISTINCT useSessionId)) OVER(), 5) AS pct
FROM lute_app_dw.dws_pump_session_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
  AND local_hour IS NOT NULL
GROUP BY local_hour ORDER BY session_count DESC LIMIT 6
```

**当前结果**

| 时段 | 次数 | 占比 |
|------|------|------|
| 9时 | 53,925 | 22.3% |
| 10时 | 45,442 | 18.8% |
| 16时 | 31,745 | 13.1% |
| 15时 | 31,622 | 13.1% |
| 8时 | 25,279 | 10.4% |
| 7时 | 22,191 | 9.2% |

---

## 二、活跃与留存（retention）

### 2.1 留存汇总 KPI 卡片

**看板位置**：活跃与留存 → KPI 行  
**卡片**：昨日DAU / D1用户留存 / D1设备留存 / D7用户留存 / D7设备留存 / 新增用户数 / 新增设备数

**SQL**（`query_retention_summary`）
```sql
-- 区间平均留存率（来自 RET 表）
SELECT ROUND(AVG(d1_user_ret),5), ROUND(AVG(d7_user_ret),5),
       ROUND(AVG(d1_device_ret),5), ROUND(AVG(d7_device_ret),5)
FROM lute_app_dw.dws_pump_retention_di
WHERE deviceCode = 'ALL' AND base_dt BETWEEN '2026-04-29' AND '2026-05-28'

-- 昨日新增（来自 DAILY 表，取最大 evt_dt）
SELECT SUM(new_users), SUM(new_devices)
FROM lute_app_dw.dws_pump_daily_df
WHERE evt_dt = (SELECT MAX(evt_dt) FROM ... WHERE evt_dt <= '2026-05-28')

-- D1/D7留存环比：取 RET 最新行 vs 前1日行 vs 近7日 AVG
```

**当前结果**

| 指标 | 值 | 较前1日 | 较前7日均值 |
|------|-----|---------|------------|
| 昨日DAU | 1,847（区间均值） | ↓ 4.9% | ↓ 11.4% |
| D1 用户留存 | 80.5%（区间均值） | ↑ 3.6pp | ↓ 0.2pp |
| D1 设备留存 | 80.8%（区间均值） | ↑ 2.2pp | ↓ 0.4pp |
| D7 用户留存 | 59.4%（区间均值） | ↑ 1.1pp | ↓ 3.6pp |
| D7 设备留存 | 60.2%（区间均值） | ↑ 0.6pp | ↓ 2.8pp |
| 新增用户（昨） | 4 | ↓ 4.9% | ↓ 11.4% |
| 新增设备（昨） | 7 | ↓ 5.0% | ↓ 10.9% |

---

### 2.2 用户留存率趋势（chart06_user）/ 设备留存率趋势（chart06_device）

**看板位置**：活跃与留存 → 用户留存率趋势 / 设备留存率趋势

**SQL**（`query_chart06_user`）
```sql
SELECT base_dt AS base_date, d1_user_ret AS d1_user_retention_pct,
       d7_user_ret AS d7_user_retention_pct
FROM lute_app_dw.dws_pump_retention_di
WHERE deviceCode='ALL' ORDER BY base_dt
```

**结果摘要**：16行（有数据的日期），首行 2026-05-01，D1用户=79.8%，D7用户=29.0%

---

### 2.3 每日新增用户/设备（折线图 newUserDev）

**看板位置**：活跃与留存 → 每日新增用户/设备趋势

**SQL**（`query_new_user_dev`）
```sql
SELECT evt_dt AS dt, SUM(new_users) AS new_users, SUM(new_devices) AS new_devices
FROM lute_app_dw.dws_pump_daily_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
GROUP BY evt_dt ORDER BY evt_dt
```

**结果摘要**：共30行，首日 new_users=85/new_devices=125，末日 new_users=4/new_devices=7

---

### 2.4 连续活跃天数分布（柱图 chart07）

**看板位置**：活跃与留存 → 连续活跃天数分布  
**标签格式**：绝对值 + 百分比（两行）

**SQL**（`query_chart07`）
```sql
WITH user_active AS (
    SELECT uid, evt_dt FROM lute_app_dw.dws_pump_session_df
    WHERE uid IS NOT NULL AND evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
    GROUP BY uid, evt_dt
),
streaks AS (
    SELECT uid, evt_dt,
        DATE_SUB(evt_dt, INTERVAL ROW_NUMBER() OVER (PARTITION BY uid ORDER BY evt_dt) DAY) AS grp
    FROM user_active
),
user_max_streak AS (
    SELECT uid, MAX(cnt) AS max_streak
    FROM (SELECT uid, grp, COUNT(*) AS cnt FROM streaks GROUP BY uid, grp) t
    GROUP BY uid
)
SELECT CASE WHEN max_streak = 1 THEN '1天' WHEN max_streak <= 3 THEN '2–3天'
       WHEN max_streak <= 7 THEN '4–7天' WHEN max_streak <= 14 THEN '8–14天'
       WHEN max_streak <= 30 THEN '15–30天' ELSE '30+天' END AS streak_bucket,
    ... AS bucket_order, COUNT(DISTINCT uid) AS user_count
FROM user_max_streak GROUP BY streak_bucket ORDER BY bucket_order
```

**当前结果**（总用户 3,908）

| 区间 | 用户数 | 占比 |
|------|--------|------|
| 1天 | 572 | 14.6% |
| 2–3天 | 796 | 20.4% |
| 4–7天 | 884 | 22.6% |
| 8–14天 | 577 | 14.8% |
| 15–30天 | 1,077 | 27.6% |
| 30+天 | 2 | 0.1% |

---

### 2.5 留存率分组详情（cohort 表 table01）

**看板位置**：活跃与留存 → 留存率分组详情表  
**说明**：按用户首次激活周分组，展示各周 D1/D3/D7/D14 留存率；"激活日期段"显示为 `周一 ~ 周日` 格式；受顶部日期筛选器控制（过滤激活日期范围）；分页展示，每页10行

**SQL**（`query_table01`）
```sql
WITH user_first AS (
    SELECT uid, MIN(evt_dt) AS install_date FROM lute_app_dw.dws_pump_session_df
    WHERE uid IS NOT NULL GROUP BY uid
),
week_base AS (
    SELECT uid, install_date,
        CAST(date_trunc('week', install_date) AS DATE) AS install_week
    FROM user_first WHERE install_date BETWEEN '2026-04-29' AND '2026-05-28'
)
SELECT w.install_week,
    COUNT(DISTINCT w.uid) AS new_users,
    ROUND(COUNT(DISTINCT CASE WHEN a.active_date = DATE_ADD(w.install_date, INTERVAL 1 DAY) THEN w.uid END)
        / NULLIF(COUNT(DISTINCT w.uid), 0), 4) AS d1_pct,
    ... d3_pct, d7_pct, d14_pct
FROM week_base w LEFT JOIN user_active a ON w.uid = a.uid
GROUP BY w.install_week ORDER BY w.install_week
```

---

## 三、吸奶次数（sessions）

### 3.1 次数汇总 KPI 卡片

**看板位置**：吸奶次数 → KPI 行  
**卡片**：总吸奶次数 / 日均次数 / 1次/天占比 / 单日最高次数

**SQL**（`query_sessions_summary`）
```sql
-- 总次数/日均：来自 kpi01（DAILY 表 SUM）
-- 1次/天占比：DAILY+SESS 联合统计 user×day 维度
-- 单日最高：MAX per uid per day from SESS
```

**当前结果**

| 指标 | 值 |
|------|----|
| 总吸奶次数 | 242,977 |
| 1次/天占比 | 18.2%（较前1日 —，较前7日均值 —） |
| 单日最高次数（单用户） | 27次 |

---

### 3.2 每日次数趋势（chart_sess_daily_trend）

同 chart02，SQL 相同。末日(05-28)=6,133次。

---

### 3.3 日均次/人趋势（chart_sess_avg_per_user）

**SQL**（`query_chart_sess_avg_per_user`）
```sql
SELECT evt_dt AS dt,
    ROUND(SUM(total_sessions) / NULLIF(SUM(dau), 0), 2) AS avg_sessions
FROM lute_app_dw.dws_pump_daily_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
GROUP BY evt_dt ORDER BY evt_dt
```

**结果摘要**：末日(05-28) avg_sessions=4.36次/人

---

### 3.4 日均次数分布（柱图 chart08）

**看板位置**：吸奶次数 → 每日次数分布

**SQL**（`query_chart08`）
```sql
-- 先统计每 uid 每天的 session 数，再按桶分布
WITH ud AS (
    SELECT evt_dt, uid, COUNT(DISTINCT useSessionId) AS pump_sessions
    FROM lute_app_dw.dws_pump_session_df
    WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
    GROUP BY evt_dt, uid
)
SELECT CASE WHEN pump_sessions=1 THEN '1次' WHEN pump_sessions=2 THEN '2次'
       ... WHEN pump_sessions>=21 THEN '21+次' END AS session_bucket,
    COUNT(*) AS user_day_count,
    ROUND(COUNT(*) / SUM(COUNT(*)) OVER(), 5) AS pct
FROM ud GROUP BY session_bucket ORDER BY bucket_order
```

**当前结果**

| 区间 | 用户-天数 | 占比 |
|------|----------|------|
| 1次 | 10,066 | 18.2% |
| 2次 | 12,870 | 23.2% |
| 3次 | 4,790 | 8.7% |
| 4次 | 8,078 | 14.6% |
| 5次 | 2,643 | 4.8% |
| 6–10次 | 13,585 | 24.5% |
| 11–20次 | 3,346 | 6.0% |
| 21+次 | 28 | 0.1% |

---

### 3.5 每日次数区间用户数趋势（堆积柱图 chart09）

**看板位置**：吸奶次数 → 各次数区间用户趋势（可切换数值/百分比堆积）

**SQL**（`query_chart09`）：与 chart08 同源，按 evt_dt 分组展开

**结果摘要**：共150行（30天 × 5个桶）

---

### 3.6 累计次数分布 - 用户维度（chart10）/ 设备维度（chart11）

**看板位置**：吸奶次数 → 人均/设备累计次数分布

**SQL**（`query_chart10`）
```sql
WITH user_total AS (
    SELECT uid, COUNT(DISTINCT useSessionId) AS total_sessions
    FROM lute_app_dw.dws_pump_session_df
    WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
    GROUP BY uid
)
SELECT CASE WHEN total_sessions=1 THEN '1次' WHEN total_sessions<=5 THEN '2–5次' ... END AS cumulative_bucket,
    COUNT(DISTINCT uid) AS user_count, ROUND(...) AS pct
FROM user_total GROUP BY cumulative_bucket ORDER BY bucket_order
```

**当前结果（用户）**

| 区间 | 用户数 | 占比 |
|------|--------|------|
| 1次 | 138 | 3.6% |
| 2–5次 | 501 | 12.9% |
| 6–10次 | 398 | 10.3% |
| 11–20次 | 547 | 14.1% |
| 21–50次 | 840 | 21.7% |
| 51–100次 | 605 | 15.6% |
| 100+次 | 839 | 21.7% |

---

### 3.7 各模式次数分布（饼图 chart_mode_sess_dist）

**看板位置**：吸奶次数 → 各模式次数分布

**SQL**（`query_chart_mode_sess_dist`，来自 MODE 表）
```sql
SELECT modeType AS mode_type, COUNT(DISTINCT useSessionId) AS cnt
FROM lute_app_dw.dws_pump_session_mode_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
GROUP BY modeType ORDER BY cnt DESC
```

**当前结果**

| 模式 | 次数（含切换重复计） |
|------|---------------------|
| 泌乳(expression) | 190,771 |
| 刺激(stimulation) | 132,968 |
| 混合(massage) | 122,964 |

> 注：MODE 表按 session×modeType 展开，同一 session 切换多次会重复计数，数值与 SESS 表 finalModeType 的 150,840 不同

---

### 3.8 各模式次数趋势（堆积柱图 chart_mode_sess_trend）

**看板位置**：吸奶次数 → 各模式吸奶次数趋势（可切换数值/百分比堆积）

**SQL**（`query_chart_mode_sess_trend`）
```sql
SELECT evt_dt AS dt, modeType AS mode_type,
    COUNT(DISTINCT useSessionId) AS cnt,
    ROUND(COUNT(DISTINCT useSessionId)
        / SUM(COUNT(DISTINCT useSessionId)) OVER (PARTITION BY evt_dt), 5) AS pct
FROM lute_app_dw.dws_pump_session_mode_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
GROUP BY evt_dt, modeType ORDER BY evt_dt
```

**结果摘要**：共90行（30天 × 3种模式）。首日(04-29)：expression=43.8%，massage=32.7%，stimulation=23.5%

---

## 四、吸奶时长（duration）

### 4.1 时长汇总 KPI 卡片

**看板位置**：吸奶时长 → KPI 行  
**卡片**：总吸奶时长 / 次均时长 / 每人每日平均时长 / 有效进程率

**SQL**（`query_duration_summary`，来自 DAILY 表）
```sql
SELECT
    ROUND(SUM(total_duration_h), 2) AS total_duration_hours,
    ROUND(SUM(avg_duration_min * total_sessions) / NULLIF(SUM(total_sessions), 0), 2) AS avg_duration_min,
    ROUND(SUM(total_duration_h) * 60 / NULLIF(SUM(dau) * COUNT(DISTINCT evt_dt), 0), 2) AS daily_min_per_user,
    ROUND(SUM(valid_sessions) / NULLIF(SUM(total_sessions), 0), 5) AS valid_session_rate_pct
FROM lute_app_dw.dws_pump_daily_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
```

**当前结果**

| 指标 | 值 |
|------|----|
| 总吸奶时长 | 134,039 h → **134.0 kh** |
| 次均时长 | 33.1 分钟 |
| 人均每日时长 | 4.84 分钟/人·日 |
| 有效进程率 | 89.6% |

---

### 4.2 昨日时长 KPI 卡片

**看板位置**：吸奶时长 → 昨日 KPI 行

**SQL**（`query_duration_kpi_yesterday`，取 `2026-05-28`）

**当前结果**

| 指标 | 昨日值 |
|------|--------|
| 总时长 | 3,440 h |
| 次均时长 | 33.66 分钟 |
| 人均日时长 | 146.71 分钟 |
| 有效进程率 | 92.3% |

---

### 4.3 每日时长趋势（chart_dur_daily_trend）

**SQL**
```sql
SELECT evt_dt AS dt, SUM(total_duration_h) AS total_hours
FROM lute_app_dw.dws_pump_daily_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
GROUP BY evt_dt ORDER BY evt_dt
```
**结果摘要**：末日(05-28) total_hours=3,440.41 h

---

### 4.4 时长分布（柱图 chart12）

**看板位置**：吸奶时长 → 每次吸奶时长分布（5分钟分桶，45min+合并）

**SQL**（`query_chart12`，来自 SESS 表）
```sql
SELECT CASE WHEN total_duration_sec < 300 THEN '0–5min'
            WHEN total_duration_sec < 600 THEN '5–10min'
            ... WHEN total_duration_sec < 2700 THEN '40–45min'
            ELSE '45min+' END AS duration_bucket,
    COUNT(DISTINCT useSessionId) AS session_count,
    ROUND(COUNT(DISTINCT useSessionId) / SUM(COUNT(DISTINCT useSessionId)) OVER(), 5) AS pct
FROM lute_app_dw.dws_pump_session_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
GROUP BY duration_bucket ORDER BY bucket_order
```

**当前结果**

| 区间 | 次数 | 占比 |
|------|------|------|
| 0–5min | 8,333 | 3.4% |
| 5–10min | 16,319 | 6.7% |
| 10–15min | 28,224 | 11.6% |
| 15–20min | 42,249 | 17.4% |
| 20–25min | 49,976 | 20.6% |
| 25–30min | 66,702 | 27.5% |
| 30–35min | 27,295 | 11.3% |
| 35–40min | 230 | 0.1% |
| 40–45min | 87 | 0.04% |
| 45min+ | 3,080 | 1.3% |

---

### 4.5 次均时长趋势（chart13）

**SQL**（`query_chart13`，加权均值）
```sql
SELECT evt_dt AS dt,
    ROUND(SUM(avg_duration_min * total_sessions) / NULLIF(SUM(total_sessions), 0), 2) AS avg_duration_min
FROM lute_app_dw.dws_pump_daily_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
GROUP BY evt_dt ORDER BY evt_dt
```
**结果摘要**：末日(05-28) avg=33.66 min

---

### 4.6 每日时长 + 累计时长（折线+柱混合图 chart14）

**SQL**（`query_chart14`）
```sql
SELECT evt_dt AS dt,
    SUM(total_duration_h) AS daily_hours,
    ROUND(SUM(cumulative_duration_h) / 1000.0, 2) AS cumulative_hours_k
FROM lute_app_dw.dws_pump_daily_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
GROUP BY evt_dt ORDER BY evt_dt
```
**结果摘要**：首日 cumulative_hours_k=12.97k，末日=146.85k（即 146,850 h 累计）

---

### 4.7 各模式时长分布（饼图 chart_mode_dur_dist）

**SQL**（`query_chart_mode_dur_dist`，来自 MODE 表）
```sql
SELECT modeType AS mode_type, ROUND(SUM(duration_sec)/60.0, 2) AS duration_min
FROM lute_app_dw.dws_pump_session_mode_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
GROUP BY modeType ORDER BY duration_min DESC
```

**当前结果**

| 模式 | 累计时长(分钟) |
|------|---------------|
| 泌乳(expression) | 4,135,733 |
| 混合(massage) | 2,406,902 |
| 刺激(stimulation) | 2,001,833 |

---

### 4.8 各模式时长趋势（堆积柱图 chart_mode_dur_trend）

**SQL**（`query_chart_mode_dur_trend`）
```sql
SELECT evt_dt AS dt, modeType AS mode_type,
    ROUND(SUM(duration_sec)/60.0, 2) AS dur_min,
    ROUND(SUM(duration_sec) / NULLIF(SUM(SUM(duration_sec)) OVER (PARTITION BY evt_dt), 0), 5) AS pct
FROM lute_app_dw.dws_pump_session_mode_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
GROUP BY evt_dt, modeType ORDER BY evt_dt
```
**结果摘要**：共90行（30天 × 3模式）。首日(04-29)：expression=65.6%，stimulation=20.5%，massage=13.9%

---

## 五、用户习惯（habits）

### 5.1 习惯汇总 KPI 卡片

**看板位置**：用户习惯 → KPI 行  
**卡片**：调节过模式的进程占比 / 次均模式调节次数 / 调节过档位的进程占比 / 次均档位调节次数

**SQL**（`query_habits_summary`，来自 SESS 表）
```sql
SELECT
    COUNT(DISTINCT useSessionId) AS total_sessions,
    COUNT(DISTINCT CASE WHEN mode_adj_cnt > 0 THEN useSessionId END) AS mode_adj_sessions,
    COUNT(DISTINCT CASE WHEN level_adj_cnt > 0 THEN useSessionId END) AS level_adj_sessions,
    ROUND(SUM(mode_adj_cnt) / NULLIF(COUNT(DISTINCT useSessionId), 0), 2) AS avg_mode_adj,
    ROUND(SUM(level_adj_cnt) / NULLIF(COUNT(DISTINCT useSessionId), 0), 2) AS avg_level_adj
FROM lute_app_dw.dws_pump_session_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
```

**当前结果**

| 指标 | 值 |
|------|----|
| 调节过模式的进程占比 | 59.8% |
| 次均模式调节次数 | 2.08 次 |
| 调节过档位的进程占比 | 36.1% |
| 次均档位调节次数 | 2.05 次 |

---

### 5.2 吸奶时段分布（双柱图 chart15）

**看板位置**：用户习惯 → 吸奶时段分布（工作日 vs 周末对比）  
**说明**：`is_weekday` 字段在 DWS 表中存在数据质量问题（几乎全为1），改用 `DAYOFWEEK(evt_dt)` 计算；同时过滤 `evt_dt BETWEEN '2020-01-01' AND '2030-12-31'` 排除脏数据行

**SQL**（`query_chart15`）
```sql
SELECT
    CASE WHEN DAYOFWEEK(evt_dt) IN (1,7) THEN '周末' ELSE '工作日' END AS day_type,
    local_hour,
    COUNT(DISTINCT useSessionId) AS session_count,
    ROUND(COUNT(DISTINCT useSessionId)
        / SUM(COUNT(DISTINCT useSessionId)) OVER (PARTITION BY day_type), 5) AS pct
FROM lute_app_dw.dws_pump_session_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
  AND local_hour IS NOT NULL AND evt_dt BETWEEN '2020-01-01' AND '2030-12-31'
GROUP BY day_type, local_hour ORDER BY day_type, local_hour
```

**结果摘要**：工作日22行，周末22行。峰值时段均在9–10时

---

### 5.3 模式×档位交叉表（table02）

**看板位置**：用户习惯 → 最终模式 × 档位偏好

**SQL**（`query_table02`）
```sql
SELECT finalModeType AS final_mode,
    CASE WHEN CAST(finalSuctionLevel AS INT) BETWEEN 1 AND 3 THEN '1–3档' ... END AS level_bucket,
    COUNT(DISTINCT useSessionId) AS session_count,
    ROUND(COUNT(DISTINCT useSessionId) / SUM(COUNT(DISTINCT useSessionId)) OVER (PARTITION BY finalModeType), 5) AS pct_within_mode
FROM lute_app_dw.dws_pump_session_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
  AND finalModeType IS NOT NULL AND finalSuctionLevel IS NOT NULL
GROUP BY final_mode, level_bucket
```

**当前结果（泌乳模式）**

| 模式 | 档位段 | 次数 | 模式内占比 |
|------|--------|------|-----------|
| 泌乳 | 1–3档 | 65,330 | 43.3% |
| 泌乳 | 4–6档 | 58,235 | 38.6% |
| 泌乳 | 7–9档 | 27,275 | 18.1% |
| 混合 | 1–3档 | 15,119 | 23.6% |
| 混合 | 4–6档 | 27,495 | 42.9% |
| 混合 | 7–9档 | 21,489 | 33.5% |

---

### 5.4 每次使用模式种数分布（柱图 chart16）

**看板位置**：用户习惯 → 每次吸奶使用模式数分布

**SQL**（`query_chart16`，来自 SESS 表 `usedModeCount`）

**当前结果**

| 类型 | 次数 | 占比 |
|------|------|------|
| 单一模式 | 104,946 | 43.7% |
| 混合 2 种 | 83,767 | 34.9% |
| 混合 3+ 种 | 51,628 | 21.5% |

---

### 5.5 模式调节方向（横向柱图 chart17）

**看板位置**：用户习惯 → 模式调节路径分布  
**数据来源**：`DWD` 事件明细表（`eventname='pump_manual_adjust_evt'`, `evttype='pump_mode'`）

**SQL**（`query_chart17`）
```sql
SELECT adjustfrom AS from_mode, adjustto AS to_mode,
    COUNT(*) AS adjust_count,
    ROUND(COUNT(*) / SUM(COUNT(*)) OVER(), 5) AS pct
FROM lute_app_dw.dwd_tp_app_breast_pump_log_di
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
  AND eventname = 'pump_manual_adjust_evt' AND evttype = 'pump_mode'
  AND adjustfrom IS NOT NULL AND adjustto IS NOT NULL AND adjustfrom != adjustto
GROUP BY adjustfrom, adjustto ORDER BY adjust_count DESC
```

**当前结果（TOP路径）**

| 路径 | 次数 | 占比 |
|------|------|------|
| 刺激→泌乳 | 194,655 | 31.4% |
| 泌乳→混合 | 155,694 | 25.1% |
| 混合→刺激 | 138,832 | 22.4% |
| 泌乳→刺激 | 74,804 | 12.1% |
| 混合→泌乳 | 36,445 | 5.9% |
| 刺激→混合 | 19,590 | 3.2% |

---

### 5.6 档位调节方向（chart18）

**看板位置**：用户习惯 → 档位调节方向（调高/调低/不变）

**SQL**（`query_chart18`，来自 SESS 表）
```sql
SELECT '调高档位' AS direction, SUM(level_up_cnt) AS adjust_count FROM ...
UNION ALL
SELECT '调低档位', SUM(level_down_cnt) FROM ...
UNION ALL
SELECT '不变', SUM(level_adj_cnt - level_up_cnt - level_down_cnt) FROM ...
```

**当前结果**

| 方向 | 次数 |
|------|------|
| 调高档位 | 251,684 |
| 调低档位 | 241,549 |
| 不变 | 0 |

---

### 5.7 每次吸奶调节次数分布（柱图 chart19）

**看板位置**：用户习惯 → 每次吸奶调节次数分布（档位调节 / 模式调节，10次+合并）

**SQL**（`query_chart19`，来自 SESS 表 `level_adj_cnt` / `mode_adj_cnt`，10+合并）

**当前结果（档位调节）**

| 次数 | 进程数 | 占比 |
|------|--------|------|
| 0次 | 154,895 | 63.8% |
| 1次 | 18,400 | 7.6% |
| 2次 | 15,096 | 6.2% |
| 3–9次 | 合计33,073 | 13.6% |
| 10次+ | 15,513 | 6.4% |

**当前结果（模式调节）**

| 次数 | 进程数 | 占比 |
|------|--------|------|
| 0次 | 97,263 | 40.0% |
| 1次 | 9,761 | 4.0% |
| 2次 | 43,808 | 18.0% |
| 3次 | 47,053 | 19.4% |
| 10次+ | 2,821 | 1.2% |

---

## 六、有效进程（funnel）

### 6.1 漏斗汇总 KPI

**看板位置**：有效进程 → 漏斗概览  
**漏斗层级**：开机次数 → 开始吸奶次数 → 结束吸奶次数 → 有效进程次数（时长>10min）

**SQL**（`query_kpi02`，来自 DAILY 表）
```sql
SELECT
    SUM(power_on_cnt)      AS power_on_cnt,
    COUNT(DISTINCT ...)    AS devices_powered_on,
    SUM(total_sessions)    AS started_sessions,
    SUM(complete_sessions) AS ended_sessions,
    SUM(valid_sessions)    AS valid_sessions,
    COUNT(DISTINCT evt_dt) AS days
FROM lute_app_dw.dws_pump_daily_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
```

**当前结果**

| 漏斗层 | 数值 |
|--------|------|
| 开机次数 | 423,139 |
| 开始吸奶（started） | 242,977 |
| 结束吸奶（ended） | 242,495 |
| 有效进程（valid，>10min） | 217,682 |
| 结束率（ended/started） | 99.8% |
| 有效率（valid/ended） | 89.8% |

---

### 6.2 漏斗每日趋势（折线图 chart20）

**SQL**（`query_chart20`）
```sql
SELECT evt_dt AS dt,
    SUM(power_on_cnt) AS power_on_cnt,
    SUM(total_sessions) AS started_cnt,
    SUM(complete_sessions) AS ended_cnt,
    SUM(valid_sessions) AS valid_cnt
FROM lute_app_dw.dws_pump_daily_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
GROUP BY evt_dt ORDER BY evt_dt
```

**结果摘要**：末日(05-28) 开机8,856 / 开始6,133 / 结束6,108 / 有效5,661

---

### 6.3 完成率/有效率趋势（折线图 chart21）

**SQL**（`query_chart21`）
```sql
SELECT evt_dt AS dt,
    ROUND(SUM(complete_sessions) / NULLIF(SUM(total_sessions), 0) * 100, 2) AS completion_rate_pct,
    ROUND(SUM(valid_sessions) / NULLIF(SUM(complete_sessions), 0) * 100, 2) AS valid_rate_pct
FROM lute_app_dw.dws_pump_daily_df
WHERE evt_dt BETWEEN '2026-04-29' AND '2026-05-28'
GROUP BY evt_dt ORDER BY evt_dt
```

**结果摘要**：末日(05-28) completion_rate=99.59%，valid_rate=92.68%

---

## 附：deviceCode 过滤机制

所有 `DAILY`、`SESS`、`MODE` 表的查询，在用户选择具体型号时，会附加 `AND deviceCode = 'M5P0'`（`_dc_and()` 函数生成）。  
`RET` 表固定使用 `WHERE deviceCode='ALL'`，不受型号筛选影响（该表只有全品类汇总行）。

当前实际 deviceCode 列表（来自 DAILY 表）：**`['M5P0']`**

---

## 附：已知数据质量问题

| 问题 | 影响 | 处理方式 |
|------|------|---------|
| `dws_pump_session_df.is_weekday` 几乎全为1，周末行仅存在于2034–2094年脏数据中 | 时段分布周末图无数据 | 改用 `DAYOFWEEK(evt_dt) IN (1,7)` 计算，同时过滤 `evt_dt < '2031-01-01'` |
| `dws_pump_daily_df` 无全品类汇总行 | 全品类查询不能用 `WHERE deviceCode='ALL'` | 改为 SUM all deviceCodes（无 WHERE deviceCode 条件） |
| `dws_pump_retention_di` 只有 `deviceCode='ALL'` 行 | 留存率不支持按型号筛选 | 固定使用 `WHERE deviceCode='ALL'`，不拼接 `_dc_and()` |
