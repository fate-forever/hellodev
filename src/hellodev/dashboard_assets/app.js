const $ = (id) => document.getElementById(id);
const PAGE_SIZE = 10;
let currentData = null;
let statusEtag = null;
let lessonFilter = "all";
let lessonPage = 0;
let pollTimer = null;

const clear = (id) => { $(id).replaceChildren(); };
const text = (value, fallback = "—") => value === null || value === undefined ? fallback : String(value);
const toast = (message) => {
  $("toast").textContent = message;
  $("toast").classList.add("show");
  setTimeout(() => $("toast").classList.remove("show"), 1500);
};
const copyCommand = async (command) => {
  try {
    await navigator.clipboard.writeText(command);
    toast("命令已复制；页面没有执行它");
  } catch {
    toast("无法访问剪贴板，请手动复制");
  }
};
const row = (title, detail, badge = "info") => {
  const element = document.createElement("div");
  element.className = "row";
  const body = document.createElement("div");
  const strong = document.createElement("strong");
  const small = document.createElement("small");
  const tag = document.createElement("span");
  strong.textContent = title;
  small.textContent = detail;
  tag.className = `pill state-${badge}`;
  tag.textContent = badge;
  body.append(strong, small);
  element.append(body, tag);
  return element;
};
const empty = (message) => row("暂无", message, "empty");
const action = (label, command, detail = "仅复制命令") => {
  const element = row(label, detail, "copy");
  element.classList.add("command-row");
  element.querySelector(".pill").remove();
  const code = document.createElement("code");
  code.textContent = command;
  const button = document.createElement("button");
  button.className = "copy";
  button.type = "button";
  button.textContent = "复制";
  button.addEventListener("click", () => copyCommand(command));
  element.append(code, button);
  return element;
};
const metric = (label, value) => {
  const article = document.createElement("article");
  const span = document.createElement("span");
  const strong = document.createElement("strong");
  span.textContent = label;
  strong.textContent = text(value);
  article.append(span, strong);
  return article;
};

document.querySelectorAll("#tabs button").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll("#tabs button, .panel").forEach((element) => element.classList.remove("active"));
  button.classList.add("active");
  $(button.dataset.tab).classList.add("active");
}));

const renderLessons = () => {
  clear("lessons");
  const proposals = currentData.continuity.lessonProposals.filter((item) => lessonFilter === "all" || item.effectiveReviewState === lessonFilter);
  const pageCount = Math.max(1, Math.ceil(proposals.length / PAGE_SIZE));
  lessonPage = Math.min(lessonPage, pageCount - 1);
  proposals.slice(lessonPage * PAGE_SIZE, (lessonPage + 1) * PAGE_SIZE).forEach((item) => $("lessons").append(row(
    `${item.id} · ${item.destination}`,
    `scope=${item.scope} · evidence=${item.evidenceReceiptCount} · expires=${item.expiresAt || "none"} · reason=${item.reviewReasonCode || "none"}`,
    item.effectiveReviewState,
  ), action("查看审核元数据", item.reviewCommand, "只读 lesson show")));
  if (!proposals.length) $("lessons").append(empty("当前筛选没有 LessonProposal"));
  $("lesson-page").textContent = `${lessonPage + 1} / ${pageCount} · ${proposals.length} items`;
  $("lesson-prev").disabled = lessonPage === 0;
  $("lesson-next").disabled = lessonPage >= pageCount - 1;
};

const render = (data) => {
  currentData = data;
  const now = data.now;
  $("health-dot").className = "ok";
  $("health-text").textContent = "本机 · 只读";
  $("updated-at").textContent = `更新 ${data.generatedAt}`;
  $("phase").textContent = now.phase;
  $("work-item-id").textContent = now.workItem?.id || "未绑定";
  $("task-counts").textContent = `${data.tasks.localCount} / ${data.tasks.trellisActiveCount} / ${data.tasks.linkedWorkItemCount}`;
  $("tokens").textContent = data.usage.totalTokens ?? "unavailable";
  clear("next-action");
  $("next-action").append(action(now.next.reason, now.next.command, `${now.next.reasonCode} · ${now.next.suggestedLevel}`));
  clear("blocker");
  $("blocker").append(now.blocker ? row(now.blocker.title, now.blocker.detail, now.blocker.kind) : empty("没有恢复阻塞；按唯一下一步继续"));
  clear("component-health");
  [["Capabilities", now.health.capabilities], ["Trellis", now.health.trellis], ["Nocturne", now.health.nocturne], ["Repository tools", now.health.repositoryTools]].forEach(([name, state]) => $("component-health").append(row(name, "当前只读探测状态", state)));
  $("component-health").append(row("Context Plane", "native bounded repository context", now.health.contextPlane));
  clear("actions");
  data.actions.forEach((item) => $("actions").append(action(item.label, item.command)));

  clear("recovery-list");
  data.continuity.recoveryCenter.forEach((item) => $("recovery-list").append(action(`${item.priority}. ${item.title}`, item.command, `${item.kind} · ${item.state} · ${item.detail}`)));
  if (!data.continuity.recoveryCenter.length) $("recovery-list").append(empty("没有待恢复事务；NOW 仍只给出一条日常下一步"));

  const states = ["pending", "verified", "persisted", "rejected", "expired", "superseded"];
  clear("lesson-summary");
  states.forEach((state) => $("lesson-summary").append(metric(state, data.continuity.lessonProposals.filter((item) => item.effectiveReviewState === state).length)));
  clear("lesson-filters");
  ["all", ...states].forEach((state) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = state === lessonFilter ? "filter active" : "filter";
    button.textContent = state;
    button.addEventListener("click", () => { lessonFilter = state; lessonPage = 0; render(data); });
    $("lesson-filters").append(button);
  });
  renderLessons();
  clear("recall-policy");
  const recall = data.recallInspector;
  $("recall-policy").append(
    row("Authority", `${recall.source}; instructionAuthority=${recall.instructionAuthority}`, recall.authority),
    row("Conflict", recall.conflictPolicy, recall.freshness),
    row("Privacy", `raw exposed=${recall.rawResultExposed}; result details persisted=${recall.resultDetailsPersisted}`, recall.quarantinePolicy),
  );
  clear("recall-history");
  recall.history.forEach((item) => $("recall-history").append(row(item.receiptId, `${item.recordedAt} · accepted/quarantined unavailable by design`, item.outcome)));
  if (!recall.history.length) $("recall-history").append(empty("尚无 Nocturne search_memory 回执"));
  clear("recall-template");
  $("recall-template").append(action("准备本地优先 Recall", 'hellodev do recall --query "<query>"', "在终端补充窄域 query"));

  clear("environment-core");
  const diagnostics = data.diagnostics;
  const contextLast = data.contextPlane.lastQuery;
  $("environment-core").append(metric("Core", diagnostics.core.version), metric("Mode", diagnostics.core.mode), metric("Distribution", diagnostics.core.distributionState), metric("Schema", data.schemaVersion), metric("Context backend", data.contextPlane.backend), metric("Last context", contextLast?.state || "none"), metric("Context files", contextLast?.metrics?.scannedFileCount ?? 0), metric("Context bytes", contextLast?.metrics?.returnedTextBytes ?? 0), metric("Optional accelerator", diagnostics.repositoryTools.suggestedProvider));
  [["codex", "codex-checks"], ["cursor", "cursor-checks"]].forEach(([host, target]) => {
    clear(target);
    diagnostics.hosts[host].checks.forEach((item) => $(target).append(row(item.name, "project-scoped compatibility check", item.state)));
    if (!diagnostics.hosts[host].checks.length) $(target).append(empty(diagnostics.hosts[host].reason || "未取得诊断"));
  });
  clear("diagnostic-fixes");
  diagnostics.fixes.forEach((item) => $("diagnostic-fixes").append(action(item.label, item.command)));
  if (!diagnostics.fixes.length) $("diagnostic-fixes").append(empty("当前没有确定性修复建议"));

  const cycle = data.efficiencyCycle;
  clear("efficiency-metrics");
  $("efficiency-metrics").append(metric("Cycles", cycle.cycleCount), metric("Progress", `${cycle.pendingReceiptCount}/${cycle.windowSize}`), metric("Remaining", cycle.remainingUntilNextCycle ?? "unavailable"), metric("Usage trust", data.usage.displayBasis));
  clear("efficiency-cycle");
  if (cycle.latest) {
    $("efficiency-cycle").append(row("Average tokens", `${cycle.latest.receiptCount} completed turns`, cycle.latest.metrics.averageTokens), action("Recommendation", cycle.latest.recommendation.command, cycle.latest.recommendation.reasonCode));
  } else $("efficiency-cycle").append(empty("等待可信的 completed-turn receipts"));
  clear("optimization-status");
  $("optimization-status").append(row("Optimize", data.optimization.reasonCode, data.optimization.state), row("Proposals", `stale=${data.optimization.staleProposalCount}`, data.optimization.proposalCount));
  clear("advanced-status");
  $("advanced-status").append(row("Transactions", "恢复无需重新授权", data.advanced.transactions.state), row("Host envelopes", `pending=${data.advanced.host.pendingEnvelopeCount}`, data.advanced.host.state), row("Policy / Drift", `${data.advanced.policy.state} / ${data.advanced.drift.state}`, data.advanced.checkpoint.state));

  clear("audit-grid");
  Object.entries(data.audit).forEach(([name, value]) => $("audit-grid").append(row(name, "bounded count", value)));
};

async function load(force = false) {
  const headers = {};
  if (statusEtag && !force) headers["If-None-Match"] = statusEtag;
  const response = await fetch("/api/status", { cache: "no-cache", headers });
  if (response.status === 304) return;
  if (!response.ok) throw new Error("status request failed");
  statusEtag = response.headers.get("ETag");
  render(await response.json());
}
const schedule = () => {
  clearTimeout(pollTimer);
  if (!document.hidden) pollTimer = setTimeout(async () => { try { await load(); } finally { schedule(); } }, 5000);
};
$("refresh").addEventListener("click", async () => { try { await load(true); toast("状态已刷新"); } catch { toast("刷新失败"); } });
$("lesson-prev").addEventListener("click", () => { lessonPage -= 1; renderLessons(); });
$("lesson-next").addEventListener("click", () => { lessonPage += 1; renderLessons(); });
document.addEventListener("visibilitychange", () => { if (!document.hidden) load().catch(() => {}); schedule(); });
load().then(schedule).catch(() => { $("health-text").textContent = "连接失败"; schedule(); });
