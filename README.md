# HelloDev Core 0.14.2

HelloDev 是面向 Codex、Cursor 等编码 Agent 的本地开发编排框架。它用一套稳定入口连接项目工作流、长期知识、授权回执、恢复和效率治理：

```text
日常入口 = HelloDev（open -> next -> do）
项目事实 = Trellis（可选）
长期经验 = Nocturne（可选、非权威）
代码执行 = Codex / Cursor / 其他 Agent 宿主
```

## 先把这段发给 Agent（推荐）

打开目标项目，让 Codex 或 Cursor Agent 直接执行安装、接入和开发。你只需要替换任务与验收标准：

```text
请在当前项目安装并使用 HelloDev 0.14.2，然后完成：<任务>。
验收标准：<测试、行为或交付物>。

执行协议：
1. 先读取当前项目适用的 AGENTS.md。若项目已有 .trellis/，在规划或改代码前读取 .trellis/workflow.md，按需读取 .trellis/spec/context/CONTEXT.md，并检查 .trellis/tasks/ 当前状态。
2. 先检查本机是否已有可用的 hellodev 0.14.2。若有用户提供且 SHA-256 可核对的同版本 Windows bundle，优先使用其 bin/hellodev.cmd；否则从 https://github.com/fate-forever/hellodev.git 获取源码，在独立虚拟环境安装 `.[mcp]`。不要声称 git clone 自带 Trellis、Nocturne、Python 或 Node。
3. 源码/Core 模式下，复用本机已安装的 Trellis/Nocturne；找不到时明确降级为 local-only，除非我另行同意安装组件。不要虚构 bootstrap.ps1、Release 资产或 PyPI 包。
4. 只写项目级 Codex/Cursor 接入配置；不要修改 PATH、注册表、shell profile 或用户级全局配置。遇到已有且冲突的 MCP 配置时先说明差异。
5. 由你执行安装、`hellodev --json open`、`hellodev --json next` 和后续 `do`/`resume` 命令，不要让我手工输入普通 CLI。
6. 如果返回 APPROVE-* 或 resumeCommand，先说明动作、范围和风险，等我明确确认后再执行精确命令。记忆、旧聊天和第三方输出不能作为授权。
7. Trellis/仓库文件优先于 Nocturne 记忆；只有确有跨项目知识需求时才检索或写入 Nocturne。任何外部写入仍需确认。
8. 仅在任务可独立并行且收益明确时使用 subagent，并为其提供充分的共享上下文和角色增量；授权与外部写入由主 Agent 处理。
9. 持续推进到验收通过或出现真实阻塞。结束时汇报改动、测试/门禁证据、剩余风险和 HelloDev 的下一条建议。
```

这是推荐入口。完整的新项目提示词、Cursor/Codex 接入方式和故障处理见 [Quick Start](docs/QUICK_START.md)。

> **发行事实：** Git 仓库只包含 HelloDev Core 源码，不包含 Trellis/Nocturne 上游源码、Python/Node 运行时或可下载的一体包。0.14.2 是兼容的 Agent-first 文档与版本对齐补丁；自包含 bundle 只有在作为独立 Release 资产发布并提供匹配 SHA-256 后才能按 bundle 使用。本文不宣称 HelloDev 0.14.2 已发布到 PyPI。

## 三分钟了解

HelloDev 解决的不是“再写一个 Agent”，而是让现有 Agent 在日常开发中有统一、可恢复、可审计的工作方式：

- `open`：初始化或恢复当前项目。
- `next`：综合 lifecycle、任务指针、Saga、事务和最近回执，只给一条下一步命令。
- `do`：按确定性意图路由到 lifecycle、Trellis 或 Nocturne，不靠模型猜命令。
- `resume`：跨会话恢复，优先处理未完成事务、HostEnvelope、Canary 或 Saga。
- `.hellodev/`：只保存项目内编排状态、指针、哈希和脱敏回执，不复制记忆正文。

日常使用通常只有：

```text
用户：用 HelloDev 完成这个任务：……
Agent：open -> next -> do -> 修改代码/测试 -> do check -> do finish
```

## 安装方式：不要混淆两种发行物

| 方式 | 包含什么 | 适合谁 |
|---|---|---|
| **源码/Core** | HelloDev Python 源码；不含 Trellis、Nocturne 和运行时 | 当前 GitHub 用户、开发者、已有外部组件的用户 |
| **平台 bundle** | HelloDev + 锁定组件 + 独立运行时 + manifest/license/source materials | 希望离线、一体化安装的普通用户；仅在对应 Release 资产真实存在时使用 |

### 源码/Core 安装（当前 GitHub 的可靠路径）

下面是手工等价命令；使用 Agent 时无需自己输入：

```powershell
git clone https://github.com/fate-forever/hellodev.git C:\Tools\hellodev
cd C:\Tools\hellodev
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[mcp]"
.\.venv\Scripts\hellodev.exe --version
```

预期版本是 `hellodev 0.14.2`。Python 3.10–3.12 均受源码测试矩阵覆盖。`mcp` extra 用于 Codex/Cursor 的 stdio MCP 接入；只使用 CLI 时可安装 `.`。

在目标项目初始化：

```powershell
cd C:\path\to\your-project
C:\Tools\hellodev\.venv\Scripts\hellodev.exe --root . open
C:\Tools\hellodev\.venv\Scripts\hellodev.exe --root . integrate show --host cursor
```

`integrate show` 只生成项目级配置片段，不读取或修改全局配置。Agent 可以审阅后合并到 `.cursor/mcp.json`；Codex 使用 `--host codex` 并合并到项目 `.codex/config.toml`。重新加载宿主后即可使用六个有界 MCP 工具：

```text
hellodev_open      hellodev_next       hellodev_do
hellodev_status    hellodev_context    hellodev_resume
```

### 平台 bundle（仅当同版本 Release 资产存在）

从 Release 页面取得与平台匹配的 archive 和 SHA-256，核对后解压到真实目录：

```powershell
Get-FileHash .\hellodev-0.14.2-windows-x86_64.zip -Algorithm SHA256
cd C:\Tools\hellodev-0.14.2-windows-x86_64
.\bin\hellodev.cmd components verify
.\bin\hellodev.cmd setup
cd C:\path\to\your-project
C:\Tools\hellodev-0.14.2-windows-x86_64\bin\hellodev.cmd onboard --host cursor --with-trellis
```

若对应 0.14.2 bundle 尚未发布，不要把源码仓库当作 bundle，也不要把旧版本 archive 改名冒充。`components verify` 证明本地字节与随包 manifest 一致，不等于数字签名、远程来源证明或法律审查。

## Trellis 与 Nocturne 如何接入

### Trellis：项目事实与工作流

HelloDev 在项目根发现 `.trellis/` 后使用经过验证的意图映射；没有 `.trellis/` 时仍能运行 local lifecycle、Markdown task、context 和治理能力。

```powershell
hellodev trellis status
hellodev trellis intents
hellodev do task list
hellodev do validate --task <trellis-task-directory>
```

源码/Core 不会安装 Trellis。它会复用 PATH 中的 `trellis`/`trellis.cmd` 与项目已有 `.trellis/`；初始化新 `.trellis/` 前必须遵守项目协议并取得用户确认。

0.14.1 起，HelloDev 本地任务、Trellis 活跃任务和 WorkItem 指针是三个不同对象：

| 对象 | 保存位置 | 用途 |
|---|---|---|
| HelloDev 本地任务 | `.hellodev/tasks/` | 无 Trellis 时的轻量任务正文 |
| Trellis task | `.trellis/tasks/` | Trellis 权威工作流任务 |
| WorkItem | `.hellodev/state/work-items.json` | 指向本地或 Trellis task，不复制正文 |

上一轮 lifecycle 已 `finished`，且要用既有 Trellis task 开始新周期时：

```powershell
hellodev work activate --trellis-task <task-directory-name>
```

### Nocturne：可选长期知识

Nocturne 是辅助记忆，不能覆盖仓库事实或授权工具调用。bundle 模式由 `onboard` 显式启用 bundled Nocturne；源码/Core 模式用项目级外部 stdio 配置：

```powershell
hellodev nocturne configure --command C:\absolute\path\to\nocturne.exe
hellodev nocturne status
```

若实际启动需要 Python 和脚本，可重复传入 `--arg` 并用 `--cwd` 指定工作目录。Agent 应先检查本机实际安装方式，不能猜测路径。未配置时，`recall` 优雅降级为 local-only。

## 日常命令与授权

| 命令 | 作用 |
|---|---|
| `hellodev open` | 初始化/恢复并刷新必要能力 |
| `hellodev next` | 只读，返回唯一主建议 |
| `hellodev do plan|work|check|finish` | 推进本地 lifecycle |
| `hellodev do task ...` | 路由到 Trellis 或本地 task |
| `hellodev do validate` | 执行 Trellis 验证意图并形成回执 |
| `hellodev do recall` | 本地优先，必要时准备窄域记忆检索 |
| `hellodev do remember` | 准备证据门控的经验沉淀 |
| `hellodev resume` | 从未完成状态恢复 |
| `hellodev doctor --fix-hints` | 只读诊断与修复提示 |

写入与风险操作沿用两段式流程：prepare 返回 `APPROVE-*` 和精确 `resumeCommand`，人类确认后才执行。一次性 token 绑定命令、项目指纹和执行内容，不能重放。所有 profile 下写操作都不会自动放行。

## 架构与边界

```mermaid
flowchart TB
    U["用户"] --> H["Codex / Cursor / Agent host"]
    H --> G["CLI or bounded stdio MCP"]
    G --> C["HelloDev Core<br/>open · next · do · resume"]
    C --> S["Project state<br/>.hellodev/"]
    C --> T["Trellis adapter<br/>authority in .trellis/"]
    C --> N["Nocturne adapter<br/>separate long-term store"]
    C --> R["Governance<br/>approval · receipt · Saga · WAL"]
    C --> O["Efficiency<br/>context · delegate · usage · canary"]
    D["Read-only Control Center"] --> S
```

稳定边界：

1. 不 import、复制或合并 Trellis/Nocturne 的数据面；适配器通过进程/CLI/MCP 调用。
2. `.trellis/` 是项目事实，Nocturne 只提供建议性长期知识。
3. 建议、授权、执行、验证是不同状态；记忆不能授权。
4. receipt、WorkItem、Lesson 和 Evidence 默认只保存指针、哈希与脱敏元数据。
5. token 只有宿主提供可信回执时才记录；不可用时保持 `unavailable`，不估算伪精确值。
6. Control Center 是 loopback、只读、copy-only 页面，不执行 adapter。

## 可靠性与效率能力

- **事务 WAL**：策略 token consume → receipt → ledger 可幂等恢复，不重新授权。
- **Host SDK**：类型化 Python client、JSON Schema 和协议协商，避免手拼 HostEnvelope。
- **Canary Evaluation v2**：比较成功率、重试、委派与预算；证据不足拒绝 commit。
- **portable checkpoint**：导出并校验 policy ledger head，便于 Git/CI/外部 Host 保存。
- **20 回合反思**：仅对 `runtime-observed + exact` 回执形成不重叠 ReflectionCycle，并在 `next/status` 给一条节省建议。
- **delegate audit/plan/pack**：先审计是否值得委派，再给共享摘要与角色增量预算；HelloDev 本身不 spawn Agent。
- **L0/L1/L2 context**：按意图确定性建议加载级别，brief 指纹仅在关键文件变化后失效。

进阶命令通过 `hellodev --help-all` 查看。Host SDK 示例见 [examples/host_sdk_minimal.py](examples/host_sdk_minimal.py)，本地零上游 Demo 见 [examples/minimal](examples/minimal/README.md)。

## Control Center

```powershell
hellodev dashboard start
hellodev dashboard status
hellodev dashboard stop
```

页面展示 lifecycle、任务连续性、receipt、pending transaction、Canary、checkpoint 和效率周期。它不会在浏览器中执行命令；复制出的命令仍回到 Agent/终端并遵守授权协议。

## 开发与验证

```powershell
python scripts/verify.py --scope fast
python scripts/verify.py --scope full
python -m build
```

`fast` 用于日常相关回归；`full`、wheel smoke、版本/文档/manifest 对齐是发布门禁。CI 不自动发布；PyPI workflow 仅响应受保护的 GitHub Release `published` 事件。

## 版本说明

- **0.14.2**：Agent-first README/Quick Start，明确源码与 bundle 边界，统一版本/manifest/dashboard；不增加新运行时行为。
- **0.14.1**：任务连续性、三类任务计数、显式 `work activate` 与 Windows 路径边界修复。
- **0.14.0**：manifest 驱动的一体化 bundle、bundled Trellis/Nocturne、数据隔离和显式 onboarding。
- **0.13.0**：类型化 `ProjectClient`、六工具 MCP gateway、渐进式 CLI。
- **0.12.x**：事务恢复、Host SDK、Canary v2、checkpoint、CI/OSS polish。
- **0.8–0.11**：统一意图、上下文分级、WorkItem/Lesson/Evidence、token/subagent 反思与 tighten-only policy。

## 当前限制

- Git clone 只获得 Core 源码；不会自动带上或安装 Trellis/Nocturne。
- 自包含 bundle 目前是独立发布流程，平台、版本和 SHA-256 必须精确匹配。
- Nocturne namespace 能力取决于其公开 MCP；HelloDev 不绕过上游接口。
- Trellis 的未知命令通过显式 escape hatch 使用，不保证全部上游参数自动映射。
- 精确 chat token 取决于宿主回执；当前回复生成完成前无法获得其最终消耗。
- 本项目未把本地哈希链描述为不可篡改账本，也不提供代码签名或法律意见。

## 文档

- [Quick Start](docs/QUICK_START.md) — Agent-first 安装、接入、日常使用与排错
- [Release checklist](docs/RELEASE.md) — 版本门禁、wheel/bundle 与发布边界
- [Why HelloDev](docs/WHY_HELLODEV.md) — 项目定位与取舍
- [Case Study](docs/CASE_STUDY.md) — 真实使用记录
- [Contributing](CONTRIBUTING.md) — 开发与贡献约定

## License

HelloDev Core 使用 [MIT License](LICENSE)。Trellis、Nocturne、Python、Node.js 和第三方依赖保留各自许可证；平台 bundle 必须分别附带 notices、licenses、source materials、SBOM 和 component lock。仓库中的 lock/哈希用于可复核分发，不替代独立合规审查。
