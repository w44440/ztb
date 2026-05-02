# ZTB Agent Session Rules

这个文件定义本 agent 在会话中的初始化规则、工具调用顺序和任务处理方式。

## Session Initialization

进入新会话后，默认先识别用户问题属于哪一类：

- 单日盘面概况
- 趋势/情绪变化
- 热点/题材分析
- 个股明细追问
- 抓取失败排查
- 报告生成需求

## Command Order

### 咨询类问题

优先顺序：

1. `uv run ztb agent context --date YYYYMMDD --days 5`
2. 必要时再运行：
   - `uv run ztb query --date YYYYMMDD --source ths`
   - `uv run ztb query --date YYYYMMDD --source jygs`

### 数据更新类问题

优先顺序：

1. `uv run ztb agent fetch --date YYYYMMDD`
2. 抓取成功后，再运行：
   - `uv run ztb agent context --date YYYYMMDD --days 5`

### 抓取异常排查

优先顺序：

1. `uv run ztb fetch --date YYYYMMDD`
2. `cat /data/ops-data/ztb/last_run.json`

只在用户明确要求排查自动化抓取异常时，才优先使用顶层 `ztb fetch`。

### 图片报告需求

优先顺序：

1. `uv run ztb agent report --date YYYYMMDD`
2. 如用户还需要文字解读，再运行：
   - `uv run ztb agent context --date YYYYMMDD --days 5`

## Output Contract

回答默认结构：

1. 一句结论
2. 2 到 5 条关键依据
3. 若数据不完整，补一条缺口说明

不要：

- 直接粘贴完整 JSON
- 只报数字不解释含义
- 在没有数据支持时给强判断

## Date Handling

- 对“今天/昨天/最近”这类问题，始终转换成具体日期后再查询
- 如果用户没有给日期，且问题明显是单日盘面问题，默认先用当前交易相关日期查询
- 如果查询结果显示非交易日，要明确说明

## Escalation Rules

- `data_quality` 提示缺失时，先说明缺口，再决定是否建议抓取
- `ztb agent fetch` 返回 `error` 时，直接说明失败来源和原因
- `ztb fetch` 的 `last_run.json` 里若 `failed_stage` 存在，必须显式解释这个字段
