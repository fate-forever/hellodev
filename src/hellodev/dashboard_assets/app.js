const $ = (id) => document.getElementById(id);

const toast = (message) => {
  const element = $("toast");
  element.textContent = message;
  element.classList.add("show");
  setTimeout(() => element.classList.remove("show"), 1500);
};

const copyCommand = async (command) => {
  try {
    await navigator.clipboard.writeText(command);
    toast("命令已复制，不会在页面中执行");
  } catch {
    toast("无法访问剪贴板，请手动复制");
  }
};

document.querySelectorAll("#tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("#tabs button, .panel").forEach((element) => element.classList.remove("active"));
    button.classList.add("active");
    $(button.dataset.tab).classList.add("active");
  });
});

const row = (title, detail, badge) => {
  const element = document.createElement("div");
  element.className = "row";
  const text = document.createElement("div");
  const strong = document.createElement("div");
  const small = document.createElement("small");
  const tag = document.createElement("span");
  strong.textContent = title;
  small.textContent = detail;
  tag.className = "pill";
  tag.textContent = badge;
  text.append(strong, small);
  element.append(text, tag);
  return element;
};

const empty = (message) => row("暂无", message, "local");

const action = (label, command, detail = "仅复制命令") => {
  const element = row(label, detail, "copy");
  element.classList.add("command-row");
  element.querySelector(".pill").remove();
  const commandText = document.createElement("code");
  commandText.textContent = command;
  const button = document.createElement("button");
  button.className = "copy";
  button.textContent = "复制命令";
  button.addEventListener("click", () => copyCommand(command));
  element.append(commandText, button);
  return element;
};

const compactHash = (value) => value ? `${value.slice(0, 12)}…` : "none";
const optimizationCommands = new Set([
  "hellodev optimize plan --intent code",
  "hellodev optimize proposals",
]);
const advancedCommands = new Set([
  "hellodev host status",
  "hellodev policy status",
  "hellodev drift status",
  "hellodev transaction status",
  "hellodev policy checkpoint status",
]);

async function load() {
  const response = await fetch("/api/status", { cache: "no-store" });
  if (!response.ok) throw new Error("status request failed");
  const data = await response.json();
  const continuity = data.continuity;
  const optimization = data.optimization;
  const efficiencyCycle = data.efficiencyCycle;
  const advanced = data.advanced;
  $("health-dot").style.background = "var(--accent)";
  $("health-text").textContent = "本机 · 只读";
  $("phase").textContent = data.lifecycle.phase;
  $("tasks").textContent = `L${data.tasks.localCount} / T${data.tasks.trellisActiveCount}`;
  $("cache").textContent = data.capabilities.state;
  $("tokens").textContent = data.usage.totalTokens ?? "未采集";

  $("adapters").append(
    row("Trellis", data.adapters.trellis.detail, data.adapters.trellis.state),
    row("Nocturne", data.adapters.nocturne.detail, data.adapters.nocturne.state),
  );
  $("next-action").append(action(
    continuity.resume.next.reason,
    continuity.resume.next.command,
    `${continuity.resume.next.reasonCode} · ${continuity.resume.next.suggestedLevel}`,
  ));
  data.actions.forEach((item) => $("actions").append(action(item.label, item.command)));

  const work = continuity.currentWorkItem;
  $("work-item").append(
    row("任务真相", `HelloDev 本地 ${data.tasks.localCount} · Trellis 活跃 ${data.tasks.trellisActiveCount}`, `${data.tasks.linkedWorkItemCount} WorkItem`),
    row("生命周期", `${data.lifecycle.cycleId} · 已完成 ${data.lifecycle.completedCycleCount} 周期`, data.lifecycle.phase),
  );
  if (work) {
    $("work-item").append(
      row(work.id, `${work.backend} · ${work.nativeRef}`, work.fingerprintCurrent ? "current" : "stale"),
      row("关联阶段", work.linkedPhase, "pointer-only"),
    );
  } else {
    $("work-item").append(empty("尚未选择本地或 Trellis 任务指针"));
  }

  const gate = continuity.gate;
  $("gate").append(
    row("对齐状态", `${gate.validEvidenceCount} 条当前证据，${gate.staleEvidenceCount} 条过期证据`, gate.state),
    row("Finish policy", "Gate 只读投影，不会修改 Trellis", gate.finishPolicy),
    row("Lifecycle consistency", gate.lifecycleConsistency.reasonCode, gate.lifecycleConsistency.state),
  );

  if (continuity.incompleteSagas.length) {
    continuity.incompleteSagas.forEach((saga) => $("sagas").append(action(
      `${saga.id} · ${saga.phase}`,
      saga.nextCommand,
      `${saga.reasonCode}${saga.requiresInput ? " · 需要人工输入" : ""}`,
    )));
  } else {
    $("sagas").append(empty("没有需要恢复的 Saga"));
  }

  $("optimization-traces").textContent = optimization.traceCount;
  $("optimization-reports").textContent = optimization.reportCount;
  $("optimization-proposals").textContent = optimization.proposalCount;
  $("optimization-stale").textContent = optimization.staleProposalCount;
  $("cycle-count").textContent = efficiencyCycle.cycleCount;
  $("cycle-progress").textContent = `${efficiencyCycle.pendingReceiptCount}/${efficiencyCycle.windowSize}`;
  $("cycle-remaining").textContent = efficiencyCycle.remainingUntilNextCycle ?? "unavailable";
  const latestCycle = efficiencyCycle.latest;
  if (latestCycle) {
    const metrics = latestCycle.metrics;
    $("efficiency-cycle").append(
      row("Average tokens", `${metrics.totalTokens} tokens across ${latestCycle.receiptCount} completed turns`, String(metrics.averageTokens)),
      row("Cache reuse", "Cached input share across the trusted twenty-turn window", `${(metrics.cacheShareBasisPoints / 100).toFixed(1)}%`),
      row("Subagent share", `${metrics.subagentCount} delegated runs in the window`, `${(metrics.subagentShareBasisPoints / 100).toFixed(1)}%`),
      action("Efficiency recommendation", latestCycle.recommendation.command, latestCycle.recommendation.reasonCode),
      row("Policy boundary", "Advice only; human review and tighten-only validation remain required", latestCycle.policyEffect.applyAllowed ? "apply" : "no auto-apply"),
    );
  } else {
    $("efficiency-cycle").append(empty(`Collect ${efficiencyCycle.remainingUntilNextCycle ?? efficiencyCycle.windowSize} more trusted completed turns for the first reflection cycle`));
  }
  $("optimization-status").append(
    row("状态", optimization.reasonCode, optimization.state),
    row("Usage", "只显示显式关联到 DecisionTrace 的用量；不会自动绑定最新收据", optimization.usageState),
    row("Apply", "0.10 不允许页面应用 Proposal", optimization.applyAllowed ? "allowed" : "disabled"),
  );

  const envelope = optimization.latestUsageEnvelope;
  if (envelope) {
    const plan = envelope.plan;
    const actual = envelope.actual;
    $("optimization-usage").append(
      row("Budget", `context=${plan.contextTokenCeiling} · total=${plan.totalTokenCeiling ?? "未计划"} · subagent=${plan.subagentTokenCeiling ?? "未计划"}`, envelope.budgetState),
      row("Agents", `上限 ${plan.maxSubagents}`, "planned"),
    );
    if (actual) {
      $("optimization-usage").append(
        row("实际 Token", `root=${actual.rootTokens} · subagent=${actual.subagentTokens}`, String(actual.totalTokens)),
        row("Subagents", "仅外部上报计数", String(actual.subagentCount)),
        row("Trust", `${actual.sourceKind} · ${actual.sourceTrust}`, actual.accuracy),
      );
    } else {
      $("optimization-usage").append(empty("没有可用的 usage 回执"));
    }
  } else {
    $("optimization-usage").append(empty("尚无 DecisionTrace usage envelope"));
  }

  const reflection = optimization.latestReflection;
  if (reflection) {
    $("optimization-reflection").append(
      row("Findings", "确定性规则命中数", String(reflection.findingCount)),
      row("Recommendations", "仅计数，不展示内容", String(reflection.recommendationCount)),
      row("Trend sample", `usage available=${reflection.usageAvailableCount}`, String(reflection.sampleSize)),
      row("Average reported", "仅外部上报的平均 Token", reflection.averageReportedTokens ?? "unavailable"),
      row("Deep reflection", `token ceiling=${reflection.deepReflectionTokenCeiling ?? "不可用"}`, reflection.deepReflectionState),
      row("Anomaly", "只读布尔投影", reflection.anomaly ? "yes" : "no"),
    );
  } else {
    $("optimization-reflection").append(empty("尚无 ReflectionReport"));
  }

  if (optimizationCommands.has(optimization.nextCommand)) {
    $("optimization-action").append(action(
      optimization.proposalCount ? "查看 EvolutionProposal" : "生成优化计划",
      optimization.nextCommand,
      "固定 allowlist 命令，仅复制",
    ));
  } else {
    $("optimization-action").append(empty("建议命令不在页面 allowlist"));
  }

  $("host-completions").textContent = advanced.host.completionCount;
  $("host-late").textContent = advanced.host.lateCount;
  $("policy-events").textContent = advanced.policy.eventCount;
  $("drift-findings").textContent = advanced.drift.findingCount;
  $("pending-transactions").textContent = advanced.transactions.pendingCount;
  $("pending-envelopes").textContent = advanced.host.pendingEnvelopeCount;
  $("checkpoint-state").textContent = advanced.checkpoint.state;
  $("host-protocol").textContent = advanced.hostProtocol.selectedVersion;
  $("host-status").append(
    row("状态", `${advanced.host.budgetExceededCount} 次预算超限`, advanced.host.state),
    row("Usage trust", `asserted=${advanced.host.usageTrustCounts.hostAsserted} · unavailable=${advanced.host.usageTrustCounts.unavailable}`, "counts"),
  );
  if (advanced.host.latest) {
    $("host-status").append(row(
      "最近完成",
      `budget=${advanced.host.latest.budgetState} · usage=${advanced.host.latest.usageTrust} · late=${advanced.host.latest.late}`,
      advanced.host.latest.outcome,
    ));
  }
  $("policy-status").append(
    row("状态", `${advanced.policy.eventCount} 个本地 ledger 事件`, advanced.policy.state),
    row("活动 Proposal", "仅布尔投影，不展示策略或 patch", advanced.policy.activeProposal ? "yes" : "no"),
    row("试运行窗口", `expired=${advanced.policy.canaryExpired}`, advanced.policy.canaryActive ? "active" : "inactive"),
    row("完整性", "只显示结构校验状态", advanced.policy.integrityState),
  );
  $("transaction-status").append(
    row("State", "Authorized policy mutations recover without a new approval token", advanced.transactions.state),
    row("Pending", "Only counts and one read-only status command are exposed", String(advanced.transactions.pendingCount)),
  );
  const experiment = advanced.canaryEvaluation;
  if (experiment) {
    $("canary-evaluation").append(
      row("State", experiment.reasonCode, experiment.state),
      row("Evidence", `baseline=${experiment.baselineObserved}/${experiment.required} · canary=${experiment.canaryObserved}/${experiment.required}`, experiment.evidenceSufficient ? "sufficient" : "insufficient"),
      row("Commit", `missing baseline=${experiment.missingBaseline} · canary=${experiment.missingCanary}`, experiment.commitEligible ? "eligible" : "blocked"),
      row("Regressions", "Success, retry, delegation and budget comparisons", String(experiment.regressionCount)),
      row("Token trust", "No exact/provider claim is made for Host assertions", experiment.comparison.tokenTrust),
    );
  } else {
    $("canary-evaluation").append(empty("No active Canary experiment"));
  }
  $("checkpoint-status").append(
    row("State", "External CI/Git/Host copies provide the durable comparison point", advanced.checkpoint.state),
    row("Matched", "A local saved copy alone is not tamper-proof", advanced.checkpoint.matched ?? "not-saved"),
  );
  const driftCounts = advanced.drift.counts;
  $("drift-status").append(
    row("状态", advanced.drift.reasonCode, advanced.drift.state),
    row("Findings", `warning=${advanced.drift.warningCount} · info=${advanced.drift.infoCount}`, String(advanced.drift.findingCount)),
    row("Completions", `current=${driftCounts.currentCompletions} · historical=${driftCounts.historicalCompletions}`, advanced.drift.runtimeState),
    row("Violations", `asserted=${driftCounts.assertedUsage} · unavailable=${driftCounts.unavailableUsage}`, String(driftCounts.violations)),
  );
  [
    ["检查 Host Bridge", advanced.host.command],
    ["检查 Policy Ledger", advanced.policy.command],
    ["检查 Drift", advanced.drift.command],
    ["检查 Transaction WAL", advanced.transactions.command],
    ["检查 Checkpoint", advanced.checkpoint.command],
  ].forEach(([label, command]) => {
    if (advancedCommands.has(command)) {
      $("advanced-actions").append(action(label, command, "固定只读命令，仅复制"));
    }
  });
  const ui = advanced.uiCapabilities;
  $("advanced-capabilities").append(
    row("Copy only", "页面不提交任何运行结果或策略变更", ui.copyOnly ? "enabled" : "disabled"),
    row("变更控制", `apply=${ui.applyAllowed} · commit=${ui.commitAllowed} · revert=${ui.revertAllowed}`, ui.actionApiAvailable ? "action-api" : "no-action-api"),
  );

  ["new", "started", "planned", "working", "checking", "finished"].forEach((phase) => {
    const element = document.createElement("span");
    element.textContent = phase;
    if (phase === data.lifecycle.phase) element.className = "current";
    $("timeline").append(element);
  });
  data.briefs.forEach((item) => $("briefs").append(row(item.name, item.updated, item.state)));
  if (!data.briefs.length) $("briefs").append(empty("还没有缓存 brief"));

  if (continuity.lessonProposals.length) {
    continuity.lessonProposals.forEach((proposal) => $("lessons").append(row(
      `${proposal.id} · ${proposal.destination}`,
      `scope=${proposal.scope} · evidence=${proposal.evidenceReceiptCount} · expires=${proposal.expiresAt} · sha256=${compactHash(proposal.lessonSha256)}`,
      `${proposal.state} / review=${proposal.effectiveReviewState}`,
    )));
  } else {
    $("lessons").append(empty("没有 hash-only LessonProposal"));
  }
  $("recall-template").append(action(
    "准备本地优先 Recall",
    'hellodev do recall --query "<query>"',
    "固定模板；在终端补充 query",
  ));

  $("audit").append(
    row("Receipts", "只显示计数", String(data.audit.receipts)),
    row("Sagas", "跨系统验证记录", String(data.audit.sagas)),
    row("未完成 Saga", "可恢复但不自动执行", String(data.audit.incompleteSagas)),
    row("WorkItems", "仅任务指针", String(data.audit.workItems)),
    row("LessonProposals", "仅摘要哈希与连续性链接", String(data.audit.lessonProposals)),
    row("EvidenceLinks", "绑定指纹的证据链接", String(data.audit.evidenceLinks)),
    row("DecisionTrace", "仅计数", String(data.audit.optimizationTraces)),
    row("ReflectionReport", "仅计数", String(data.audit.reflectionReports)),
    row("EvolutionProposal", "仅计数，不可应用", String(data.audit.evolutionProposals)),
    row("Host completions", "仅计数", String(data.audit.hostCompletions)),
    row("Policy events", "仅计数，不展示 patch", String(data.audit.policyEvents)),
    row("Drift findings", "仅计数", String(data.audit.driftFindings)),
    row("Usage receipts", `runtime=${data.usage.trustCounts["runtime-observed"]} · selected=${data.usage.trustCounts["asserted-runtime"]} · asserted=${data.usage.trustCounts.asserted}`, String(data.usage.records)),
    row("ReflectionCycle", `${efficiencyCycle.pendingReceiptCount}/${efficiencyCycle.windowSize} turns toward the next deterministic review`, String(efficiencyCycle.cycleCount)),
  );
}

load().catch(() => {
  $("health-text").textContent = "连接失败";
});
