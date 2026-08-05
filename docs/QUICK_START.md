# HelloDev 0.21.3 快速上手

HelloDev 是 Codex、Cursor、Antigravity 等编码 Agent 的本地开发编排层。它负责把任务、验收、授权、验证、恢复和审计串成一条可继续执行的路径，但不替代 Agent 写代码，也不替代项目自己的测试工具。

```text
用户提出需求
  -> Agent 读取项目规则
  -> HelloDev onboard / open / do begin
  -> Agent 修改代码并运行项目测试
  -> HelloDev 记录有界验证证据
  -> check / finish 受控收尾
```

## 1. 复制给 Codex / Cursor / Antigravity Agent

项目完成一次 `onboard` 并重新加载宿主后，日常只需发送：

```text
用 HelloDev 完成：<任务>。
验收：<测试、行为或交付物>。
```

0.21.3 的 `onboard` 会同时安装一个项目级 HelloDev Agent Skill：Cursor 使用 `.cursor/skills/hellodev/`，Codex 和 Antigravity 使用 `.agents/skills/hellodev/`。Skill、宿主规则和 HelloDev MCP instructions 会向 Agent 提供 `open -> next -> do`、项目规则、验收、授权、恢复与收尾协议；Codex 还会读取仓库现有的 `AGENTS.md`。Agent 应完成普通 CLI 操作，用户只负责明确需求、验收标准，以及确认真正有风险的外部写入。

Skill 采用渐进披露：日常路径保持简短；同一 `reasonCode` 连续出现两次时，Agent 才读取 `references/recovery.md`，停止继续修改并收集有界诊断。它不会全局安装，也不会替代 Core 的 AcceptanceContract、verification、approval 和 finish 门禁。

这属于宿主自动加载的项目规则，不是操作系统级强制沙箱。HelloDev 能对受管 lifecycle、AcceptanceContract、验证证据和 `finish` 执行硬门禁，但不能阻止宿主绕开 MCP 后直接修改文件或运行其他 CLI。

首次尚未接入时继续阅读下一节。git clone 只含 HelloDev Core；不要虚构 bootstrap.ps1、Release 资产或 PyPI 包。

## 2. 安装与接入

### 手工安装参考：源码/Core

Git clone 只获得 HelloDev Core，不包含 Trellis、Nocturne、Python、Node.js 或自包含运行时。

```powershell
git clone https://github.com/fate-forever/hellodev.git C:\Tools\hellodev
cd C:\Tools\hellodev
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[mcp]"
.\.venv\Scripts\hellodev.exe --version
```

预期输出为 `hellodev 0.21.3`。Python 3.10 至 3.12 受源码测试矩阵覆盖。只使用 CLI 时可以安装 `.`；Codex、Cursor 或 Antigravity 通过 stdio MCP 接入时使用 `.[mcp]`。

macOS/Linux 使用同样的 Python 包，虚拟环境命令位于 `.venv/bin/`。

### Wheel 或平台 bundle

- Wheel 仍然只是 HelloDev Core，不会附带可选组件或运行时。
- 当前 bundle 目标平台为 Windows x86_64；其他平台不能复用或改名使用该资产。
- 平台 bundle 只有在同版本 Release 资产真实存在、平台匹配且 SHA-256 核对通过时才可使用。
- 不要把源码仓库、旧版本 archive 或临时构建改名冒充 0.21.3 bundle。
- bundle 解压后先运行 `hellodev components verify`，再运行其 `setup`；组件哈希验证不等于数字签名或来源证明。

本文不宣称 HelloDev 0.21.3 已发布到 PyPI。

## 3. 项目接入

以下命令以 PATH 中已有 `hellodev` 为例；源码安装可以替换为虚拟环境中的完整可执行文件路径。

```powershell
cd C:\path\to\your-project
hellodev --root . onboard --host <codex|cursor|antigravity>
hellodev --root . integrate check --host <codex|cursor|antigravity>
hellodev --root . open
```

`onboard` 只创建或合并项目级接入文件，并安装对应宿主的项目级 HelloDev Skill。已有 MCP server、规则或同名 Skill 发生冲突时会在项目状态写入前 fail closed，不应通过覆盖用户级配置来绕过。由 HelloDev 管理且内容未被修改的旧 Skill 可以原地升级；用户修改过、缺文件或所有权不明确的 Skill 必须先人工审阅。使用 `--host none` 时不安装 Skill。

重新加载宿主后可使用六个固定的 HelloDev MCP 工具：

```text
hellodev_open      hellodev_next       hellodev_do
hellodev_status    hellodev_context    hellodev_resume
```

CLI、SDK 和不同 Agent 宿主使用相同的核心状态与权限边界。

## 4. 开始任务

### 简单、明确的任务

```powershell
hellodev --root . do begin `
  --goal "修复登录超时" `
  --acceptance "相关测试通过且登录行为不回归"
```

首次 `open` 的 `next.action.kind` 通常是 `begin-work`。优先执行它给出的精确命令，不要改成 `do plan`，也不要自行转去初始化原生 Trellis。

### 多条或生产式需求

把用户原始需求不删减地保存为项目相对路径下的 UTF-8 文件，例如 `USER_REQUIREMENTS.md`：

```powershell
hellodev --root . do begin `
  --goal "实现周目标与共同复盘" `
  --acceptance "单元测试、集成测试和类型检查通过" `
  --requirements-file "USER_REQUIREMENTS.md"
```

HelloDev 会在 `.hellodev/acceptance-sources.json` 保存有界原文、SHA-256、字节数和行数。它不会读取宿主的私有聊天记录，因此 Agent 不能用自己压缩后的摘要替代权威需求。

以下情况会阻止收尾：

- 绑定后的需求文件缺失、变化或被替换；
- 使用绝对路径、符号链接或项目外文件；
- strict 变更超过十个文件，却只提供了摘要验收条件；
- 当前 WorkItem、cycle 与 AcceptanceContract 不一致。

### 0.21.0 可执行验收提案

精确绑定 `--requirements-file` 后，`next` 会先要求 Agent 提交一份可审核的测试或 invariant 提案：

```powershell
hellodev --root . acceptance propose `
  --mode red `
  --path "src/domain/weekly-goals.test.ts" `
  --command "npm test" `
  --summary "覆盖学习者确认、隐私边界和一次性阶段回应"

hellodev --root . acceptance review acceptance-proposal-0001 `
  --decision approve `
  --reason "覆盖原始需求的关键不变量"
```

`red` 适合新增行为，`characterization` 适合先锁定既有行为，`invariant` 适合安全、隐私或兼容性约束。HelloDev 只保存有界提案和审核状态；不会创建测试文件、运行命令，也不会把批准动作算作 verification success。仅使用一句 `--acceptance` 的简单任务不强制增加此步骤。

### 0.21.1 门禁计划与 Trellis preflight

精确需求绑定成功后，`do begin`、`do work` 与 executable-acceptance 响应会附带 `acceptanceGatePlan` / `gatePlan`。它把原始需求投影为有编号的 criterion，并列出按项目 manifest 发现的测试、集成、类型检查与构建门禁。该计划只帮助 Agent 尽早看见完整验收面，不能证明自然语言语义已被测试完整覆盖。

Trellis 任务还会返回 `trellisPreflight`。复杂任务缺少 `prd.md`、`design.md`、`implement.md` 或非 seed `implement.jsonl` / `check.jsonl` 时，Agent 应先补齐本地规划和上下文清单；`state=ready` 仍不等于 Trellis 原生 validation 或项目测试通过。

每个成功的 `do` 响应都包含规范化 `nextAction` 和非持久化 `operationMetrics`。前者优先保留待审批的精确 `resumeCommand`，后者只测量当前 Core 调用的本地 monotonic 耗时。它们都不会执行 host command、消费 approval token、统计 Agent 总耗时或估算 token。

### 0.21.2 收尾恢复与渐进提示

`do finish` 只有在 lifecycle 已为 `checking` 时才会准备 Trellis 写操作。若 Agent 提前 finish，响应会返回 `state=check-required`、一个权威 `nextAction` 和 `agentGuidance.disclosureLevel=repair`；此时没有 approval，也没有 Trellis mutation。

Trellis 完成后若宿主进程中断，`.hellodev/closure-transactions.json` 会保留 `native-completed` 状态。重新进入项目后只执行 `open` / `next` 返回的恢复动作；HelloDev 会复用已验证的 operation 与 receipt，不再次完成 task。

## 5. 按唯一下一步执行

```powershell
hellodev --root . next
```

日常情况下只处理返回的 `next.action`：

1. `hostCommand`：在返回的项目 `cwd` 中执行测试、类型检查或其他宿主命令。
2. `recordSuccessCommand`：仅在真实退出码成功时执行。
3. `recordFailureCommand`：失败时执行，并先诊断问题；不要机械重跑未变化的失败命令。
4. `resumeCommand`：仅在获得所需授权后原样执行。

开始实现前可查看 `closurePlan.requiredSteps`。它是保守的最大验证范围；代码发生变化后，最终 level/scope 可以收紧，但不能因为旧证据而放宽。

HelloDev 不运行项目测试，也不保存原始测试输出。verification 始终标记为 `executor=host` / `host-asserted`，只保存命令哈希、退出结论、耗时和快照等有界证据。

同一 WorkItem、规范化命令和仓库快照已经失败后，不要原样重试。第二次未改变输入的尝试会触发 deterministic strict escalation；此时按 `next` 返回的命令记录根因与不同策略。账本只持久化诊断摘要的哈希，不保存原文，不自动创建 subagent。修改受影响文件后仓库快照变化，旧升阶自动失效。

## 6. 批量记录验证结果

Agent 正常跟随 `next` 即可逐步记录。已由宿主完成多个独立检查时，可以在一个 CLI 调用中原子提交：

```powershell
hellodev --root . do verify `
  --result T2 project succeeded 1200 "npm.cmd test" `
  --result T2 project succeeded 800 "npm.cmd run typecheck"
```

`--result` 的五个字段依次为：

```text
LEVEL SCOPE OUTCOME DURATION_MS COMMAND
```

耗时不可用时使用 `-`。适合稳定传递 JSON argv 的宿主也可重复使用 `--result-json`。任一记录非法时，整个批次拒绝写入。

相同命令的 `T2/project` 成功证据只有在 WorkItem 和完整仓库快照不变时，才能覆盖更窄的后续步骤。源码变化会使旧快照证据失效。

## 7. 检查与收尾

继续执行 `next` 返回的动作，最终由 HelloDev 完成：

```powershell
hellodev --root . do check
hellodev --root . do finish
```

不要直接把底层 lifecycle 改成 `finished`。对于 Trellis-backed 任务，`do finish` 还会核对：

- 当前原生 Trellis task；
- 成功的 `intent/task-complete` receipt；
- Trellis task 的 `completed` 状态；
- WorkItem 绑定的 `.gates/hellodev-quality.json`；
- 最终 `linkedPhase=finished` 投影。

Trellis context validation 只证明 task/spec 上下文结构有效，不能替代项目测试或质量 gate。

## 8. Trellis 与 Nocturne

### Trellis：规范化项目推荐

[Trellis](https://github.com/mindfold-ai/trellis) 保存仓库级 workflow、spec、task 和 gate。获得用户明确同意后，可按其 [中文安装指南](https://docs.trytrellis.app/zh/start/install-and-first-task) 安装：

```powershell
npm install -g @mindfoldhq/trellis@latest
trellis --version
```

源码/Core 会复用 PATH 中的 `trellis`/`trellis.cmd` 和已有 `.trellis/`，不会自行安装、升级或初始化。HelloDev 负责日常入口与受控编排，Trellis 仍是项目事实和原生任务的权威。

### Nocturne：需要跨项目记忆时再安装

[Nocturne](https://github.com/Dataojitori/nocturne_memory) 是非权威的长期知识组件。具体依赖和启动方式以其 [官方 README](https://github.com/Dataojitori/nocturne_memory/blob/main/README_EN.md) 为准。完成安装后可配置项目级 stdio 命令：

```powershell
hellodev --root . nocturne configure --command C:\absolute\path\to\nocturne.exe
hellodev --root . nocturne status
```

本地上下文足够时不建议 recall。未配置 Nocturne 时会降级为 local-only；外部读取和写入仍受原有授权控制。仓库/Trellis 事实与长期记忆冲突时，项目事实优先。

## 9. 跨会话恢复

重新打开项目时先运行：

```powershell
hellodev --root . open
```

它默认只返回 `task / phase / blockers / acceptance / next / approval`。若存在未完成事务、Saga 或宿主回执，执行返回的唯一恢复动作；需要显式查看恢复投影时使用：

```powershell
hellodev --root . resume
hellodev --root . status --verbose
```

Agent 应按响应逐级处理故障：

1. 首次失败只执行返回的 `nextAction`，不要尝试猜测 `done`、`gate close` 等命令。
2. 进程中断或状态不明时执行 `resume`，不要直接编辑 `.hellodev/`。
3. 若同一 `reasonCode` 连续出现两次，停止修改和重复 finish，收集 `next`、`resume`、`status --verbose` 的有界输出并向用户说明阻塞。
4. approval 只能使用响应里的精确 `resumeCommand` 一次；不得复用 token，也不得直调 Trellis 绕过 HelloDev lifecycle。

普通响应只披露下一步；只有确认、修复或诊断场景才增加 `agentGuidance`。这是为了减少日常提示噪声，同时在真正卡住时给 Agent 足够的恢复信息。

不要把普通 lifecycle 恢复称为 Saga 恢复。只有实际存在中断事务或补偿记录时，Saga 指标才成立。

## 10. 常见问题

### 找不到 HelloDev

确认当前 shell 使用的是预期虚拟环境或完整可执行路径，并运行 `hellodev --version`。不要因为 PATH 中存在旧版命令就假定它对应当前源码。

### `open` 要求 begin-work

这是未绑定任务的正常入口。执行返回的 `do begin --goal ... --acceptance ...`；不要先探测内部 gate、receipt 或原生 Trellis 命令。

### 出现多个 Trellis 候选

只执行一个 `candidateAction`，明确选择任务。HelloDev 会在无法唯一对齐时 fail closed，不应批量绑定或猜测当前任务。

### 出现 `requirements-source-required`

当前变更已进入需要精确需求来源的 strict 范围。把原始需求保存为项目内 UTF-8 文件，并按返回动作升级 AcceptanceContract；不要临时缩小验收摘要来绕过。

### 验证成功后又要求重跑

检查代码、依赖清单或测试范围是否在验证后变化。HelloDev 按 WorkItem、命令和仓库快照绑定证据，旧快照不能证明新代码。

### 任务很小，流程反而更慢

几分钟可完成、无需恢复或审计的已知文件小改可以直接使用 Agent 原生工具。HelloDev 的主要收益在跨文件、长流程、严格验收、外部授权和跨会话任务中，不应强制覆盖所有微小修改。

## 11. Dashboard 与诊断

Control Center 3.3 / Dashboard schema 23 保持 GET/copy-only。它展示当前任务、绑定完整性、验收计划、阻塞、唯一下一步、Trellis 漂移、verification 与 memory 状态，但不会在浏览器中执行命令或接收 approval token。

需要集中检查环境时运行：

```powershell
hellodev --root . doctor
hellodev --root . status --verbose
```

## 12. Context Plane：不用另装 FastCtx

原生 Context Plane 已包含在 Core 中；FastCtx 只是可选加速器，不会自动接管仓库读取工具。已知文件或符号应优先使用宿主原生精确读取；陌生仓库和自然语言查询再使用有界 Context Plane。
