# HelloDev 0.20.9 快速上手

## 0.20.9 exact-requirements path

For a multi-part production brief, first save the original text unchanged in a
project-relative UTF-8 file, then bind it at begin:

```powershell
hellodev --root . do begin `
  --goal "Implement weekly goals" `
  --acceptance "npm test and npm run typecheck pass" `
  --requirements-file "USER_REQUIREMENTS.md"
```

HelloDev stores a bounded exact copy and digest in
`.hellodev/acceptance-sources.json`. Do not replace the original brief with an
Agent-authored summary. Strict changes spanning more than ten files require
this source before closure. `hellodev do finish` also verifies the active
Trellis task, task-complete receipt, mergeable quality evidence and the final
WorkItem projection; direct lifecycle completion cannot bypass these checks.

## 0.20.8 shortest closure path

After `do begin`, inspect `closurePlan.requiredSteps` before editing. The plan
discloses the conservative maximum level and scope; the final requirements may
tighten after the repository changes.

Execute the returned `hostCommand` values in the project cwd. On Windows this
is normally `npm.cmd ...`; do not substitute a shell chain. After all checks
finish, record their bounded results in one CLI call:

```powershell
hellodev do verify `
  --result T2 project succeeded 1200 "npm.cmd test" `
  --result T2 project succeeded 800 "npm.cmd run typecheck"
```

Repeated `--result-json` remains available for hosts that preserve JSON argv
bytes. Windows PowerShell users should prefer `--result`, whose five fields are
`LEVEL SCOPE OUTCOME DURATION_MS COMMAND`; use `-` for an unavailable duration.

Each item is validated before the batch is written; one invalid item rejects
the whole batch. HelloDev records hashes and bounded metadata, not command
output. A conservative `T2/project` result can cover a later narrower step only
for the same command, WorkItem and complete repository snapshot. Let `do
finish` write HelloDev evidence to
`.gates/hellodev-quality.json`; do not have parallel agents overwrite a shared
Trellis `quality.json`.

HelloDev 是本地开发编排层，不替代 Agent、Trellis 或项目测试运行器。0.20.8 保持六个 MCP 工具、默认六字段 `open`、一次性授权和只读 Dashboard。

## 复制给 Codex / Cursor / Antigravity Agent

请在项目内完成 `open -> next -> do`，先检查项目规则与现有安装；git clone 只含 HelloDev Core。不要虚构 bootstrap.ps1、Release 资产或全局组件。

## 安装与接入

### 手工安装参考

当前 bundle 目标平台为 Windows x86_64。使用 bundle 前运行 `hellodev components verify` 并核对 SHA-256；没有可信 bundle 时使用隔离虚拟环境安装源码。

先确认当前环境：

```powershell
hellodev --version
hellodev --root . onboard --host <codex|cursor|antigravity>
hellodev --root . integrate check --host <codex|cursor|antigravity>
hellodev --root . open
```

预期版本为 `hellodev 0.20.9`。本文不宣称 HelloDev 0.20.9 已发布到 PyPI；源码安装、wheel、自包含 bundle 是不同交付形态，不能互相冒充。

## 日常流程

```powershell
hellodev --root . do begin --goal "<目标>" --acceptance "<验收条件>"
hellodev --root . next
```

0.20.8 保留 Intent-first Bootstrap、Strong Closure 和 Manifest-first Verification Plan，并增加提前 closure plan 与批量回执：

- 首次 `open` 的 `next.action.kind` 是 `begin-work`；直接执行它给出的 `do begin --goal/--acceptance` 模板，不要替换成 `do plan` 或原生 Trellis 初始化。
- `plan/work/verify/check/finish` 会检查 WorkItem 与 AcceptanceContract；缺失时必须先按唯一 action 修复绑定。
- Trellis 项目的 `do begin` 可在一次授权下创建/启动/绑定任务；出现多个歧义候选时只选择一个 `candidateAction`，不要自行批量绑定。
- `finish` 只有在当前 WorkItem、AcceptanceContract 与验收证据全部满足时才允许执行。

- 有效 `package.json` test script 优先于名字叫 `tests` 的目录。
- Python 需要 `pyproject.toml`、pytest 配置或有界 `.py` 测试证据。
- `npm test and npm run typecheck pass` 会拆成两个有序步骤，每次只返回一个 `next.action`，不拼接 shell 命令。
- 宿主执行 `hostCommand` 后，调用对应的 `recordSuccessCommand` 或 `recordFailureCommand`。
- 当前源码快照变化后，旧步骤证据不再覆盖新快照。
- 未变化的失败会进入诊断状态，不再返回可机械重试的 action。

HelloDev 不执行项目测试，不保存原始输出；verification 仍标记为 `host-asserted`。Trellis context validate 是上下文证据，不是测试质量证据。

## Trellis 与 Nocturne

仓库存在 `.trellis/` 时，先遵守其 `workflow.md`、spec 和 task 状态。HelloDev 绑定原生任务，但 Trellis 仍是任务与 gate 权威。Nocturne recall 只在本地上下文不足时建议一次有界读取，外部操作仍需授权。

## Dashboard

Control Center 3.3 / Dashboard schema 23 保持 GET/copy-only。它显示当前任务、绑定完整性、验收计划、阻塞、唯一下一步 action、Trellis 漂移、verification 与 memory 状态，不在浏览器内执行命令或接收 approval token。

## Context Plane：不用另装 FastCtx

原生 Context Plane 是默认实现；FastCtx 仅是 optional accelerator，不会自动接管仓库工具。
