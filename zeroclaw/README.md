# ZeroClaw Setup For `ztb`

这个目录提供一个面向 ZeroClaw 的 agent identity，用来让它通过本仓库的 `ztb` CLI 回答涨停板相关问题。

## Included Files

- `IDENTITY.md`: 角色定义，说明这个 agent 是谁、负责什么、优先使用哪些 CLI
- `SOUL.md`: 核心原则和不可违背的行为底线
- `AGENTS.md`: 会话初始化规则、命令调用顺序、输出约定
- `USER.md`: 当前用户的上下文和表达偏好
- `MEMORY.md`: 跨会话可复用的长期事实和经验

## Recommended Runtime Constraints

下面这些约束是基于 ZeroClaw 官方能力整理出来的接入建议。

已确认的 ZeroClaw 能力：

- 支持 markdown identity 文件和 JSON identity 文件
- 默认按工作区限制文件访问
- 支持命令 allowlist

建议把 ZeroClaw 的工作区指向本仓库根目录，并允许以下命令：

```text
uv
python
cat
rg
ls
```

如果你希望它只通过 `ztb` 工作，可以进一步收窄为：

```text
uv run ztb
cat
rg
ls
```

## Recommended Operating Pattern

1. 咨询类问题先运行：

```bash
uv run ztb agent context --date YYYYMMDD --days 5
```

2. 数据缺失或用户要求刷新时运行：

```bash
uv run ztb agent fetch --date YYYYMMDD
```

3. 用户要求查看抓取失败原因时运行：

```bash
uv run ztb fetch --date YYYYMMDD
cat /data/ops-data/ztb/last_run.json
```

4. 用户要求图片报告时运行：

```bash
uv run ztb agent report --date YYYYMMDD
```

## Notes

- `ztb fetch` 是自动化入口，会生成报告并尝试企业微信推送
- `ztb agent fetch` 是 agent 入口，只抓取和入库
- `ztb agent context` 是回答问题的首选接口，因为它输出结构化摘要
- 主运行数据默认位于 HDD `/data/ops-data/ztb`；最近一次顶层抓取状态位于 `/data/ops-data/ztb/last_run.json`
- JYGS 登录态默认使用 `/data/ops-data/ztb/auth/jygs_storage_state.json`，由 `ztb fetch` 内部自动下载和校验

## Suggested Injection Order

如果 ZeroClaw 支持多文件注入，建议顺序如下：

1. `SOUL.md`
2. `IDENTITY.md`
3. `AGENTS.md`
4. `USER.md`
5. `MEMORY.md`

这样能形成一个比较稳定的层次：

- `SOUL`: 原则
- `IDENTITY`: 角色
- `AGENTS`: 行动规则
- `USER`: 服务对象偏好
- `MEMORY`: 长期事实
