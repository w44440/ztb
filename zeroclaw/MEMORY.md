# Long-Term Memory

## Project Facts

- 仓库根目录包含 `ztb` CLI 项目
- 项目核心命令分为两类：
  - `ztb fetch`：自动化入口，抓取、生成报告、尝试推送企业微信，并写入 `~/.ztb/data/last_run.json`
  - `ztb agent ...`：agent 入口，默认结构化、低副作用

## Important Commands

- `uv run ztb agent context --date YYYYMMDD --days 5`
- `uv run ztb agent fetch --date YYYYMMDD`
- `uv run ztb agent report --date YYYYMMDD`
- `uv run ztb query --date YYYYMMDD --source ths`
- `uv run ztb query --date YYYYMMDD --source jygs`
- `uv run ztb fetch --date YYYYMMDD`

## Status File Semantics

- `~/.ztb/data/last_run.json` 只描述最近一次顶层 `ztb fetch` 的结果
- 这个状态文件重点用于：
  - 判断抓取是否成功
  - 区分 `ok / partial / error / skipped`
  - 识别失败阶段和告警

## Preferred Query Strategy

- 咨询类问题先用 `ztb agent context`
- 数据缺口时再用 `ztb agent fetch`
- 抓取异常排查时才查看 `last_run.json`

## Stable Answering Heuristics

- 单日问题默认给：
  - 涨停总数
  - 最高连板
  - 连板结构
  - 热点题材
  - 代表个股
- 趋势问题默认至少看 5 天窗口
- 数据不完整时，一定说明结论可信度下降的原因
