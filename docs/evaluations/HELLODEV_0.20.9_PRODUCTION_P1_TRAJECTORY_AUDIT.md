# HelloDev 0.20.9 production P1 Agent trajectory audit

Date: 2026-08-03

## 记录范围

本文记录同一份生产式 P1「周目标与共同复盘」需求的两次有效实验：

- Direct Agent：`/root/p1_0209_direct_r2`，Agent nickname `Kierkegaard`
- HelloDev 0.20.9 + Trellis：`/root/p1_0209_hellodev`，Agent nickname `Chandrasekhar`

第一次被中断的 Direct 样本不属于本对比。它在执行
`finish-run.ps1` 前被 Codex 中断，计时器混入停机时间，因此只保留物理目录，
不进入耗时、操作轨迹或 Token 对比。

本文所称「思考」是从 Agent 对用户可见的状态消息、工具调用、文件读取顺序、
patch 顺序、测试结果和持久化状态重建出的**可观察决策摘要**。本文不复制模型
内部隐藏 reasoning，也不声称可以恢复逐字的私有 chain-of-thought。

完整的逐调用可观察记录分别位于：

- `raw/hellodev-0209-production-p1-direct-r2-observable-trajectory.json`
- `raw/hellodev-0209-production-p1-treatment-observable-trajectory.json`

公开仓库使用路径脱敏但调用内容等价的副本：

- `public/hellodev-0209-production-p1-direct-r2-observable-trajectory.json`
- `public/hellodev-0209-production-p1-treatment-observable-trajectory.json`

每条记录包含序号、UTC 时间、工具类型、完整 shell 命令或 patch 目标文件、
原始输入 SHA-256、输出 SHA-256、退出码和工具耗时。原始 rollout 的 SHA-256
和本地路径也保存在记录中，因而可以核对记录是否来自同一物理会话。
原始 rollout 对 Direct 的 3 条读取调用和 Treatment 的 4 条读取调用没有保存配对的
`custom_tool_call_output`；这些调用仍保留完整命令并明确标记
`outputState=missing-in-source-rollout`，其余 130 条具有输出哈希。记录不会把缺失回执
伪装成成功或失败。

## 实验身份与结果

| 指标 | Direct R2 | HelloDev 0.20.9 + Trellis |
|---|---:|---:|
| 单调时钟总耗时 | 28:01.293 | **25:08.398** |
| 相对 Direct | 基线 | **快 2:52.896 / 10.28%** |
| 工具调用 | 51 | 86 |
| shell / patch | 26 / 25 | 59 / 27 |
| 工具等待时间 | 143.74 s | 210.38 s |
| 非工具/模型时间 | 1,537.55 s | **1,298.02 s** |
| 首次 gate 前 patch | 5 | 18 |
| 首次 gate 后 patch | 20 | 9 |
| 单元/组件测试 | 66 | 66 |
| 集成测试 | 29 | 32 |
| 外部 E2E | 14/16 | **16/16** |
| 固定 judge 强制 gate | 4/4 | 4/4 |
| 静态发现信号 | 10/10 | 10/10 |

HelloDev 组多花约 66.64 秒执行工具和治理流程，但非工具/模型阶段少花约
239.53 秒，最终净省约 172.90 秒。该分解是运行轨迹的物理观察，不等于
HelloDev 已被单样本因果证明为提速来源。

## 共同任务输入

两组收到相同的 23 行自然语言 `TASK.md`，要求自行完成需求分析、设计、实现和
验证，没有给目标文件、函数名、数据结构、固定 patch 或 judge rubric。需求包括：

- 学习者创建周目标，并亲自确认关联日程；
- 根据精力和实际用时给出过载提示；
- 周末汇总计划、实际专注、完成和延期；
- 未完成事项由学习者一键调整到下周；
- 支持者只能看到授权后的汇总，不得获得实时监控；
- 支持者可提出三类建议并发送两种固定温和回应；
- 阶段目标完成后，支持者只能进行一次轻量回应。

Direct 从产品基线 `997117c` 启动。Treatment 从相同产品树加项目本地 Trellis
状态和 `AGENTS.md` 工作流说明的 `d3a281c` 启动。依赖物化在计时前完成。

## Direct Agent 完成内容

Direct 最终完成了以下跨层实现：

1. `src/domain/weeklyGoals.ts` 和测试：周目标校验、周日期计算、过载提示、
   目标、支持者建议和阶段回应模型。
2. `src/domain/types.ts`：扩展 `AppBackend` 的周目标和协作契约。
3. `src/lib/localBackend.ts`：本地目标、进度、日程确认、顺延、建议和回应持久化。
4. `src/lib/supabaseBackend.ts`、`src/lib/database.types.ts`：Supabase 实现与类型。
5. `src/app/PlanningFeatures.tsx`：学习者目标创建、日程确认、复盘、顺延，
   以及支持者汇总、建议和回应入口。
6. `supabase/migrations/202608030001_weekly_goals.sql`：数据表、约束和权限迁移。
7. `src/lib/weeklyGoals.local.test.ts`：本地工作流与隐私边界测试。

一次性里程碑回应在本地后端通过重复检查实现，数据库使用
`(goal_id, supporter_id)` 主键约束。Direct 的本地测试验证了首次回应，但没有像
Treatment 那样显式断言第二次回应被拒绝。

## Direct Agent 操作轨迹

### 1. 启动与架构定位，02:41:42-02:44:30

- 第 1 次调用先运行 `start-run.ps1`，防偷跑检查为 `passed-zero-diff`。
- 第 2-6 次调用读取 `TASK.md`、全仓文件清单、`package.json`、领域类型、
  planning/support 模块、local backend、Supabase backend 和主要 UI 区间。
- 可观察决策：把需求拆成领域模型、backend contract、本地实现、远端实现和 UI
  五个改动面，并优先寻找现有 support/planning 模式复用。

### 2. 领域与后端骨架，02:44:30-02:48:44

- 第 7 次 patch 同时创建领域实现、领域测试并扩展 backend 类型。
- 第 8、10、11 次 patch 逐步建立 local backend 存储和行为。
- 第 12 次 patch 开始接入 Supabase backend。
- 经过 5 次 patch 后，第 13 次调用首次尝试 `npm run typecheck`；Windows launcher
  不匹配后，第 14 次改用 `npm.cmd run typecheck`。
- 可观察决策：尽早用类型系统检验领域和 backend 骨架，但此时 UI、数据库类型、
  完整迁移和集成测试尚未收拢。

### 3. 第一轮 UI、测试与迁移，02:50:04-02:55:26

- 连续读取并 patch `PlanningFeatures.tsx`，加入学习者和支持者流程入口。
- 新增本地周目标测试与 Supabase migration。
- 第 24 次调用一次运行 typecheck、unit、lint 和 build。
- gate 后紧接一个跨 5 个文件的大 patch，说明第一次 gate 暴露或促使 Agent
  重新校准领域、UI、两个 backend 和迁移的一致性。

### 4. 第二轮跨层补齐，02:56:47-03:07:19

- 再次扩展 backend contract、local/Supabase backend 和 UI。
- 读取并修改 `database.types.ts`，补齐远端表类型和关系。
- 多次回看 migration 与现有 task/support 表结构，修正外键和契约。
- 回到领域逻辑和本地测试补边界，再次修改 UI 与 Supabase backend。
- 第一次 gate 后共有 20 次 patch，占 Direct 全部 patch 的 80%。
- 可观察决策：Direct 选择先形成可类型检查的纵向切片，再通过后半程反复补齐
  产品要求在 UI、持久化和 schema 之间的遗漏。

### 5. 验证与结束，03:06:26-03:09:44

- 两次运行完整 unit suite，随后运行 integration suite。
- 最后运行 `finish-run.ps1`，物理状态记录 `completed`、`codeModified=true`，
  `.hellodev` 不存在。
- 外部固定 judge 后续确认 4/4 gate、10/10 发现信号、66 单元/组件测试和
  29 集成测试通过。
- 外部 E2E 为 14/16；两个失败来自同一个既有 Monday boundary 场景，测试在
  周一仍尝试点击当前周之前的星期日。

## HelloDev Agent 完成内容

Treatment 完成了同一产品能力，并额外留下更强的测试和治理证据：

1. 周目标领域、领域测试、共享 backend contract 和 local persistence。
2. Supabase backend/types 及带 RLS/RPC 的增量 migration。
3. 学习者创建、明确确认、过载提示、周末复盘和手动顺延 UI。
4. 支持者 aggregate-only 查看、三类需学习者同意的建议、两种固定温和回应。
5. 一次性里程碑回应，集成测试明确断言第一次成功、第二次返回“已经回应过”。
6. responsive styles、integration tests、migration-contract tests。
7. Monday E2E 周边界修复：测试需要时先切换到上一周，再选择星期日；没有放宽断言。
8. Trellis PRD、设计、实现、检查记录，以及可复用的隐私和 E2E 规范更新。
9. 完整 HelloDev closure：AcceptanceContract、4 条 host verification、quality gate、
   Trellis completed、WorkItem finished 和 lifecycle finished。

## HelloDev Agent 操作轨迹

### 1. 启动、规则发现与需求绑定，03:10:39-03:11:38

- 第 1 次调用运行 `start-run.ps1`，防偷跑检查为 `passed-zero-diff`。
- 第 2-3 次调用先发现并读取 `AGENTS.md`、`TASK.md`、`.trellis` workflow、spec 和 task。
- 第 4-5 次调用执行统一 begin 的准备/授权路径，以
  `--requirements-file TASK.md` 绑定原始需求。
- 第 6 次调用盘点仓库，第 7 次调用进入 `do work`。
- `TASK.md` 被持久化为 23 行、1,141 bytes，SHA-256 为
  `72c0d6914397de7e91cd51a5a94ffd76602c76d984977672d4b295ecc0c01d72`。
- 可观察决策：先锁定原始验收输入和工作流状态，再开始产品修改，避免用自行压缩的
  acceptance 丢掉“一次性回应”等长尾要求。

### 2. Trellis 设计与全层探索，03:11:52-03:13:29

- 第 8-12 次调用读取产品架构和相关实现面。
- 第 13 次 patch 先创建 Trellis PRD、design、implement、implement context 和
  check context 文件。
- 可观察决策：把隐私、学习者确认、aggregate-only sharing、一次性回应和验证范围
  先转化为持久化设计约束，再进入代码实现。

### 3. 前置跨层实现，03:14:28-03:22:12

- 创建领域模型和领域测试，同时扩展共享 backend contract。
- 完成 local backend，再读现有 Supabase/types 模式并实现远端 backend 和 migration。
- 连续实现 learner/supporter UI 与 responsive styles。
- 首次 typecheck 前共完成 18 次 patch；首个 gate 距启动约 11 分 31 秒。
- 可观察决策：不是先做最小纵向切片，而是先把领域、本地/远端持久化、迁移、
  两端 UI 和样式的大部分契约同时落地，再让类型系统统一检查。

### 4. 测试补强与产品修正，03:22:12-03:30:36

- 依次运行 typecheck 和 unit tests。
- 读取现有 integration 测试风格，新增 local-backend 和 migration-contract coverage。
- 显式加入一次性里程碑回应的第二次拒绝测试及数据库约束检查。
- 重跑 unit tests 和 build。
- 三次执行 E2E：第一次发现 Monday boundary，patch 导航逻辑；第二次进一步校正；
  第三次 16/16 通过。
- 运行 secrets、`git diff --check`、最终 unit 和 typecheck。
- 首次 gate 后只有 9 次 patch，明显少于 Direct 的 20 次。
- 可观察决策：后半程主要用于强化集成/迁移验证和修复一个真实日期边界，
  而不是大规模重新补产品主路径。

### 5. 验证下沉与 Trellis 收口，03:30:51-03:33:43

- 查询 verify 参数后，一次提交两条 T2/project host assertions。
- 多次执行 Trellis validate；初次校验暴露 task context 格式/覆盖不足。
- 读取 Trellis context 脚本和当前 task 文件，修正 implement/check context。
- 更新持久化 spec 中的隐私与 E2E 周边界规则。
- 再次运行 unit gate，并提交同一新 repository snapshot 的两条验证记录。
- 可观察决策：把本次发现的隐私和日期边界固化为后续任务可复用规则，并确保验证
  记录绑定当前 WorkItem 与当前仓库快照。

### 6. Check、授权与原子收尾，03:33:51-03:35:49

- `do check` 首次遇到能力状态需刷新，执行 `capabilities refresh` 后再次 check。
- `open` 确认唯一下一步，`do finish` 先生成一次性 write approval，再携带 approval 完成。
- 检查 receipts、component operations 和 `.gates/hellodev-quality.json`。
- 最后执行 `finish-run.ps1`。
- 生命周期物理历史为：
  `new -> started -> planned -> working -> checking -> finished`。
- 最终 WorkItem `work-0001 linkedPhase=finished`，Trellis task `completed`，
  `intent/task-complete` receipt 为 `receipt-0004`，quality gate present/passed。

## 两条决策路径的主要差异

Direct 的形状是「快速骨架 -> 早期 typecheck -> 大量第二轮补齐 -> 最终测试」。
Treatment 的形状是「需求绑定/设计约束 -> 较长的前置跨层实现 -> 集成和 E2E 强化
-> 状态收口」。

量化上：

- Direct 在首次 gate 前只做 5 个 patch，之后做 20 个；
- Treatment 在首次 gate 前做 18 个 patch，之后做 9 个；
- Treatment 比 Direct 多 35 次工具调用、多 66.64 秒工具时间；
- Treatment 却少 239.53 秒非工具/模型时间，最终净省 172.90 秒。

因此，本样本中 HelloDev 更快的最可信可观察机制不是 CLI 自身更快，而是
AcceptanceContract 和 Trellis 设计约束帮助 Agent 前置覆盖跨层要求，减少首次 gate
后的重新寻路和补线。这个解释仍有两个边界：单次随机 Agent 轨迹不能证明因果；
Treatment 第二个运行，可能享受依赖、文件系统或 OS cache 温度。

## Token 记录

| Token 指标 | Direct R2 | Treatment | Treatment 差值 |
|---|---:|---:|---:|
| input，含 cached | 6,777,928 | 14,680,729 | +7,902,801 |
| cached input | 6,557,952 | 14,456,576 | +7,898,624 |
| uncached input | 219,976 | 224,153 | +4,177 |
| output | 38,582 | 40,086 | +1,504 |
| total，含 cached input | 6,816,510 | 14,720,815 | +7,904,305 / +115.96% |
| uncached input + output | 258,558 | 264,239 | +5,681 / +2.20% |

Treatment 在本样本中节省了时间，但没有节省 Token。总 Token 翻倍主要来自缓存输入
重复计数；即使采用 `uncached input + output` 口径，Treatment 仍高 2.20%。这些数字是
Codex 本地 runtime 的精确观察值，没有 provider attestation，不能直接换算为账单成本。

## 完整性与复现

`benchmarks/production_p1_0209_ab/extract_observable_trajectory.ps1` 只读取 rollout 中的
`custom_tool_call`、`custom_tool_call_output` 和 token-count 事件，明确排除 assistant
message、agent reasoning 和 hidden chain-of-thought。它还处理了一条物理执行成功但
原始 JSONL 编码不严格的超大 UI patch，并把该条标记为
`recoveredFromMalformedJsonl=true`。
使用 `-RedactLocalPaths` 时，提取器把 workspace、Codex home 和 user profile 替换为
稳定占位符；调用顺序、命令其余内容、输入/输出哈希、状态和统计不变。公开副本因此
可复核实验轨迹，但不会披露本机用户名或绝对目录。

物理证据：

- Direct candidate：`benchmarks/production_p1_0209_ab/direct_r2`
- Treatment candidate：`benchmarks/production_p1_0209_ab/hellodev`
- 每组计时：candidate 内 `run_telemetry.json`
- 固定 judge：`benchmarks/production_p1_judge/judge.py` 与 `RUBRIC.md`
- Treatment acceptance：`.hellodev/acceptance.json`、`acceptance-sources.json`
- Treatment closure：`.hellodev/lifecycle.json`、`work-items.json`、`receipts.json`、
  `verification.json` 和 Trellis task 的 `.gates/hellodev-quality.json`
- 汇总数据：`hellodev-0.20.9-production-p1-trajectory-summary.json`

## 结论边界

这份记录可以回答「两个 Agent 实际做了什么、按什么顺序操作、哪些可观察证据支持
其决策路径、最后如何验证和结束」。它不能回答模型每个 token 在内部为什么产生，
也不应被用于公开模型私有思维链。

本次仍只是一组顺序 A/B。公开声称稳定提速前，需要 AB/BA 交叉顺序、至少三次重复、
多个任务尺寸和 provider-signed usage receipt。本文没有修改 HelloDev 产品源码、两个
候选项目、全局安装、用户配置、GitHub、Release 或插件状态。
