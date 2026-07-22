"""Loopback-only, read-only HelloDev Control Center."""
from __future__ import annotations
import contextlib,hashlib,hmac,json,mimetypes,os,secrets,subprocess,sys,threading,time,urllib.parse,urllib.request
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from . import __version__,capabilities,checkpoints,components,context_runtime,contracts,drift,efficiency_cycles,gates,host_bridge,integrations,lifecycle,optimization,policy_evolution,receipts,repository_tools,resume,sagas,transactions
from .governance import usage_status
from .command_rendering import rewrite_commands
from .project import ProjectError,ProjectPaths,list_tasks,load_config,utc_now,write_json

HOST="127.0.0.1"; DEFAULT_PORT=8242; ASSETS=Path(__file__).with_name("dashboard_assets"); COOKIE="hellodev_control"; MAX_ASSET=512*1024; SNAPSHOT_TTL=.75
def _paths(root:Path):
 d=ProjectPaths(root).state_dir/"dashboard";return d,d/"state.json",d/"control.token"
def _read_state(root:Path):
 _,p,_=_paths(root)
 if not p.is_file() or p.is_symlink():return None
 try:v=json.loads(p.read_text(encoding="utf-8"))
 except Exception:return None
 return v if isinstance(v,dict) else None
def _request(url:str,method="GET",headers=None,data=None,timeout=2):
 body=None if data is None else json.dumps(data).encode();req=urllib.request.Request(url,method=method,headers=headers or {},data=body)
 try:
  with urllib.request.urlopen(req,timeout=timeout) as r:return r.status,json.loads(r.read().decode())
 except Exception:return 0,{}
def dashboard_status(root:Path):
 state=_read_state(root)
 if not state:return {"status":"stopped","running":False}
 code,value=_request(f"http://{HOST}:{state.get('port')}/api/health")
 running=code==200 and value.get("instanceId")==state.get("instanceId")
 return {"status":"running" if running else "stale","running":running,"url":f"http://{HOST}:{state.get('port')}/","instanceId":state.get("instanceId")}
def start_dashboard(root:Path,port:int):
 load_config(root)
 if not 1024<=port<=65535:raise ProjectError("dashboard port must be 1024-65535")
 current=dashboard_status(root)
 if current["running"]:return current
 directory,state_path,control_path=_paths(root);directory.mkdir(parents=True,exist_ok=True)
 if directory.is_symlink():raise ProjectError("refusing symlinked dashboard state")
 browser=secrets.token_urlsafe(32);control=secrets.token_urlsafe(32);instance=secrets.token_hex(16);started=utc_now()
 env=os.environ.copy();env["HELLODEV_DASHBOARD_TOKEN"]=browser;env["HELLODEV_DASHBOARD_CONTROL"]=control
 package_src=str(Path(__file__).resolve().parents[1]);env["PYTHONPATH"]=package_src+(os.pathsep+env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
 args=[sys.executable,"-m","hellodev.dashboard","serve","--root",str(root),"--port",str(port),"--instance",instance,"--started",started]
 kwargs={"cwd":str(root),"env":env,"stdin":subprocess.DEVNULL,"stdout":subprocess.DEVNULL,"stderr":subprocess.DEVNULL,"close_fds":True}
 if os.name=="nt":kwargs["creationflags"]=getattr(subprocess,"CREATE_NO_WINDOW",0)
 proc=subprocess.Popen(args,**kwargs);control_path.write_text(control,encoding="utf-8");write_json(state_path,{"schemaVersion":1,"pid":proc.pid,"port":port,"instanceId":instance,"startedAt":started,"root":str(root)})
 deadline=time.monotonic()+6
 while time.monotonic()<deadline:
  if dashboard_status(root)["running"]:return {"status":"running","running":True,"url":f"http://{HOST}:{port}/?token={browser}","instanceId":instance}
  if proc.poll() is not None:raise ProjectError(f"dashboard process exited before readiness (code {proc.returncode})")
  time.sleep(.05)
 raise ProjectError("dashboard failed readiness check")
def stop_dashboard(root:Path):
 state=_read_state(root)
 if not state:return {"status":"stopped","running":False}
 directory,state_path,control_path=_paths(root)
 if not control_path.is_file() or control_path.is_symlink():raise ProjectError("dashboard control token unavailable")
 control=control_path.read_text(encoding="utf-8").strip();origin=f"http://{HOST}:{state['port']}"
 code,value=_request(origin+"/api/shutdown","POST",{"Origin":origin,"X-HelloDev-Control":control,"X-HelloDev-Instance":state["instanceId"]},{"instanceId":state["instanceId"]})
 if code!=200:raise ProjectError("dashboard rejected stop request")
 deadline=time.monotonic()+5
 while time.monotonic()<deadline and dashboard_status(root)["running"]:time.sleep(.05)
 pid=state.get("pid")
 if isinstance(pid,int):
  while time.monotonic()<deadline:
   try:os.kill(pid,0)
   except OSError:break
   time.sleep(.05)
 with contextlib.suppress(OSError):state_path.unlink();control_path.unlink()
 return {"status":"stopped","running":False,"instanceId":value.get("instanceId")}
def _continuity_snapshot(root:Path):
 try:
  projection=resume.build(root);gate=gates.status(root);saga_states=sagas.list_sagas(root)
 except ProjectError:
  return {
   "schemaVersion":1,"state":"invalid","readOnly":True,"executionPerformed":False,
   "resume":{"lifecyclePhase":None,"capabilityState":"invalid","next":None},
   "currentWorkItem":None,
   "gate":{"state":"invalid","finishPolicy":"unavailable","capabilityState":"invalid","validEvidenceCount":0,"staleEvidenceCount":0,"lifecycleConsistency":None,"trellisMutationPerformed":False},
   "incompleteSagas":[],"lessonProposals":[],"recoveryCenter":[],
   "auditSummary":{"workItems":0,"lessonProposals":0,"evidenceLinks":0,"incompleteSagas":0},
  }
 incomplete=[]
 for state in saga_states:
  if state["phase"] in resume.INCOMPLETE_SAGA_PHASES:
   decision=sagas.next_step(root,state["id"])
   incomplete.append({"id":state["id"],"phase":state["phase"],"updatedAt":state.get("updatedAt"),"nextCommand":decision["command"],"reasonCode":decision["reasonCode"],"requiresInput":decision["requiresInput"]})
   if len(incomplete)>=20:break
 lessons=[]
 for proposal in sorted(contracts.list_lesson_review_projections(root),key=lambda item:(item["updatedAt"],item["id"]),reverse=True):
  lessons.append({
   "id":proposal["id"],"lessonSha256":proposal["lessonSha256"],"scope":proposal["scope"],"destination":proposal["destination"],
   "evidenceReceiptId":proposal["evidenceReceiptId"],"evidenceReceiptCount":len(proposal["evidenceReceiptIds"]),"sagaId":proposal["sagaId"],
   "state":proposal["state"],"reviewState":proposal["reviewState"],"effectiveReviewState":proposal["effectiveReviewState"],
   "reviewReasonCode":proposal["reviewReasonCode"],"expiresAt":proposal["expiresAt"],"supersededBy":proposal["supersededBy"],
   "reviewRequired":proposal["reviewRequired"],"reviewCommand":proposal["reviewCommand"],"updatedAt":proposal["updatedAt"],
  })
  if len(lessons)>=50:break
 recovery=[]
 def recover(kind,title,state,command,priority,detail):
  recovery.append({"kind":kind,"title":title,"state":state,"command":command,"priority":priority,"detail":detail})
 pending_transaction=projection.get("pendingTransaction")
 if pending_transaction:
  recover("transaction",pending_transaction["id"],pending_transaction["state"],pending_transaction["recoveryCommand"],1,"Authorized WAL recovery; no new approval is required.")
 pending_envelope=projection.get("pendingHostEnvelope")
 if pending_envelope:
  recover("host-envelope",pending_envelope["id"],"pending",pending_envelope["recoveryCommand"],2,"A HostEnvelope has no completion receipt.")
 for item in incomplete:
  recover("saga",item["id"],item["phase"],item["nextCommand"],3,item["reasonCode"])
 work=projection.get("currentWorkItem")
 if work and not work["fingerprintCurrent"]:
  recover("work-item",work["id"],"stale",f"hellodev work refresh {work['id']}",4,"The pointer predates the current project fingerprint.")
 if projection.get("lifecyclePhase")=="checking" and gate.get("state") not in {"ready","passed","satisfied"}:
  decision=projection["next"]
  recover("gate","finish gate",gate["state"],decision["command"],5,decision["reasonCode"])
 active_canary=projection.get("activeCanary")
 if active_canary and (active_canary.get("expired") or active_canary.get("exhausted")):
  recover("canary",active_canary["proposalId"],"evaluation-required",f"hellodev policy evaluate --proposal {active_canary['proposalId']}",6,"The bounded canary window is complete.")
 pending_lesson=projection.get("pendingLessonReview")
 if pending_lesson:
  recover("lesson",pending_lesson["id"],pending_lesson["effectiveReviewState"],f"hellodev lesson show {pending_lesson['id']}",7,"Review metadata and evidence before any persistence decision.")
 efficiency=projection.get("next",{}).get("efficiency")
 if efficiency and isinstance(efficiency.get("command"),str):
  recover("efficiency","efficiency hint","advisory",efficiency["command"],8,efficiency.get("reasonCode","efficiency-advice"))
 recovery.sort(key=lambda item:(item["priority"],item["title"]))
 return {
  "schemaVersion":1,
  "readOnly":True,
  "executionPerformed":False,
  "resume":{"lifecyclePhase":projection["lifecyclePhase"],"capabilityState":projection["capabilityState"],"next":projection["next"]},
  "currentWorkItem":projection["currentWorkItem"],
  "gate":{"state":gate["state"],"finishPolicy":gate["finishPolicy"],"capabilityState":gate["capabilityState"],"validEvidenceCount":len(gate["validEvidence"]),"staleEvidenceCount":gate["staleEvidenceCount"],"lifecycleConsistency":gate["lifecycleConsistency"],"trellisMutationPerformed":False},
  "incompleteSagas":incomplete,
  "lessonProposals":lessons,
  "recoveryCenter":recovery,
  "auditSummary":{"workItems":len(contracts.list_work_items(root)),"lessonProposals":len(lessons),"evidenceLinks":len(contracts.list_evidence_links(root)),"incompleteSagas":len(incomplete)},
 }

def _recall_snapshot(root:Path):
 history=[]
 for item in reversed(receipts.list_receipts(root)):
  if item.get("operation")!="search_memory":continue
  history.append({"receiptId":item["id"],"outcome":item["outcome"],"recordedAt":item["recordedAt"],"risk":item["risk"],"acceptedCount":None,"quarantinedCount":None,"deduplicated":True,"detailState":"not-persisted"})
  if len(history)>=10:break
 return {"state":"observed" if history else "no-history","history":history,"historyLimit":10,"source":"Long-term memory","authority":"advisory-only","freshness":"unavailable","instructionAuthority":"none","conflictPolicy":"repository-and-trellis-facts-win","quarantinePolicy":"instruction-like-memory-quarantined","rawResultExposed":False,"resultDetailsPersisted":False,"readOnly":True}

def _diagnostics_snapshot(root:Path,caps:dict,adapters:dict,repository_tool_state:dict):
 try:distribution=components.availability()
 except (components.ComponentError,ProjectError,OSError) as error:distribution={"state":"invalid","reason":str(error)}
 host_checks={}
 for host in ("codex","cursor"):
  try:value=integrations.check(root,host);host_checks[host]={"state":value["state"],"checks":[{"name":item["name"],"state":item["state"]} for item in value["checks"]]}
  except (components.ComponentError,ProjectError,OSError,ImportError) as error:host_checks[host]={"state":"invalid","checks":[],"reason":str(error)}
 fixes=[]
 if caps.get("state")!="fresh":fixes.append({"label":"Refresh capabilities","command":"hellodev capabilities refresh"})
 if adapters["trellis"]["state"] not in {"ready","available"}:fixes.append({"label":"Inspect Trellis","command":"hellodev doctor --fix-hints"})
 if adapters["nocturne"]["state"] not in {"ready","available"}:fixes.append({"label":"Inspect Nocturne","command":"hellodev doctor --fix-hints"})
 for host,value in host_checks.items():
  if value["state"]!="ready":fixes.append({"label":f"Check {host.title()} MCP","command":f"hellodev integrate check --host {host}"})
 unique=[];seen=set()
 for fix in fixes:
  if fix["command"] not in seen:seen.add(fix["command"]);unique.append(fix)
 return {"core":{"version":__version__,"mode":"bundle" if distribution.get("state") in {"ready","available"} else "core","distributionState":distribution.get("state","unknown")},"components":{"trellis":adapters["trellis"],"nocturne":adapters["nocturne"]},"repositoryTools":repository_tool_state,"hosts":host_checks,"fixes":unique[:6],"readOnly":True}
def _usage_snapshot(root:Path):
 value=usage_status(root);latest=value.get("preferredDetails")
 basis=("unavailable" if latest is None else
  "previous-completed-runtime-turn" if latest["sourceTrust"]=="runtime-observed" else
  "previous-completed-caller-selected-runtime-metadata" if latest["sourceTrust"]=="asserted-runtime" else
  "latest-operator-report")
 return {
  "state":value["state"],
  "records":value["records"],
  "totalTokens":None if latest is None else latest["totalTokens"],
  "subagentTokens":None if latest is None else latest["subagentTokens"],
  "rootTokens":None if latest is None else latest["rootTokens"],
  "ledgerTotalTokens":value["totalTokens"],
  "displayBasis":basis,
  "latest":None if latest is None else {key:latest[key] for key in ("state","completedAt","totalTokens","rootTokens","subagentTokens","subagentCount","sourceKind","sourceTrust","measurement","attestation","accuracy","breakdown")},
  "trustCounts":value["trustCounts"],
  "accuracy":value["accuracy"],
 }
def _optimization_snapshot(root:Path):
 try:value=optimization.status(root)
 except ProjectError:
  return {"schemaVersion":1,"state":"invalid","reasonCode":"optimization-state-invalid","usageState":"unavailable","traceCount":0,"reportCount":0,"proposalCount":0,"staleProposalCount":0,"latestUsageEnvelope":None,"latestReflection":None,"nextCommand":None,"applyAllowed":False,"readOnly":True,"executionPerformed":False,"persistencePerformed":False,"adapterCallCount":0,"modelCallCount":0}
 envelope=value.get("latestUsageEnvelope");reflection=value.get("latestReflection")
 usage_envelope=None
 if envelope is not None:
  plan=envelope["plan"];actual=envelope["actual"]
  usage_envelope={
   "budgetState":envelope["budgetState"],
   "plan":{key:plan[key] for key in ("contextTokenCeiling","totalTokenCeiling","subagentTokenCeiling","maxSubagents")},
   "actual":None if actual is None else {key:actual[key] for key in ("totalTokens","rootTokens","subagentTokens","subagentCount","sourceKind","sourceTrust","accuracy")},
  }
 reflection_summary=None
 if reflection is not None:
  deep=reflection["deepReflection"]
  trend=reflection["trend"]
  reflection_summary={"findingCount":reflection["findingCount"],"recommendationCount":len(reflection["recommendations"]),"deepReflectionState":deep["state"],"deepReflectionTokenCeiling":deep["tokenCeiling"],"anomaly":deep["anomaly"],"sampleSize":trend["sampleSize"],"usageAvailableCount":trend["usageAvailableCount"],"averageReportedTokens":trend["averageReportedTokens"]}
 next_command="hellodev optimize proposals" if value["proposalCount"] else "hellodev optimize plan --intent code"
 return {
  "schemaVersion":1,
  "state":value["state"],
  "reasonCode":value["reasonCode"],
  "usageState":value["usageState"],
  "traceCount":value["traceCount"],
  "reportCount":value["reportCount"],
  "proposalCount":value["proposalCount"],
  "staleProposalCount":value["staleProposalCount"],
  "latestUsageEnvelope":usage_envelope,
  "latestReflection":reflection_summary,
  "nextCommand":next_command,
  "applyAllowed":False,
  "readOnly":True,
  "executionPerformed":False,
  "persistencePerformed":False,
  "adapterCallCount":0,
  "modelCallCount":0,
 }
def _efficiency_cycle_snapshot(root:Path):
 try:value=efficiency_cycles.status(root)
 except ProjectError:
  return {"state":"invalid","windowSize":20,"cycleCount":0,"pendingReceiptCount":0,"remainingUntilNextCycle":None,"latest":None,"readOnly":True}
 latest=value["latest"]
 return {
  "state":value["state"],
  "windowSize":value["windowSize"],
  "cycleCount":value["cycleCount"],
  "pendingReceiptCount":value["pendingReceiptCount"],
  "remainingUntilNextCycle":value["remainingUntilNextCycle"],
  "latest":None if latest is None else {
   "id":latest["id"],
   "receiptCount":latest["receiptCount"],
   "firstCompletedAt":latest["firstCompletedAt"],
   "lastCompletedAt":latest["lastCompletedAt"],
   "metrics":latest["metrics"],
   "signals":latest["signals"],
   "recommendation":latest["recommendation"],
   "policyEffect":latest["policyEffect"],
  },
  "readOnly":True,
 }
def _advanced_snapshot(root:Path):
 try:
  host_value=host_bridge.status(root)
  host={
   "state":host_value["state"],
   "completionCount":host_value["completionCount"],
   "pendingEnvelopeCount":host_value["pendingEnvelopeCount"],
   "expiredPendingEnvelopeCount":host_value["expiredPendingEnvelopeCount"],
   "lateCount":host_value["lateCount"],
   "budgetExceededCount":host_value["budgetExceededCount"],
   "usageTrustCounts":{"hostAsserted":host_value["usageTrustCounts"]["host-asserted"],"unavailable":host_value["usageTrustCounts"]["unavailable"]},
   "latest":None if host_value["latest"] is None else {key:host_value["latest"][key] for key in ("outcome","budgetState","usageTrust","late")},
   "command":"hellodev host status",
  }
 except ProjectError:
  host={"state":"invalid","completionCount":0,"pendingEnvelopeCount":0,"expiredPendingEnvelopeCount":0,"lateCount":0,"budgetExceededCount":0,"usageTrustCounts":{"hostAsserted":0,"unavailable":0},"latest":None,"command":"hellodev host status"}
 try:
  policy_value=policy_evolution.status(root)
  active=policy_value["activeCanary"]
  policy={
   "state":policy_value["state"],
   "eventCount":policy_value["eventCount"],
   "activeProposal":policy_value["activeProposalId"] is not None,
   "canaryActive":active is not None,
   "canaryExpired":bool(active and active.get("expired",False)),
   "integrityState":policy_value["integrity"]["state"],
   "command":"hellodev policy status",
  }
 except ProjectError:
  policy={"state":"invalid","eventCount":0,"activeProposal":False,"canaryActive":False,"canaryExpired":False,"integrityState":"invalid","command":"hellodev policy status"}
 try:
  transaction_value=transactions.status(root)
  transaction={"state":transaction_value["state"],"pendingCount":transaction_value["pendingCount"],"command":"hellodev transaction status"}
 except ProjectError:
  transaction={"state":"invalid","pendingCount":0,"command":"hellodev transaction status"}
 try:
  checkpoint_value=checkpoints.status(root)
  checkpoint={"state":checkpoint_value["state"],"matched":checkpoint_value["matched"],"portableCopyRequired":checkpoint_value["portableCopyRequired"],"command":"hellodev policy checkpoint status"}
 except ProjectError:
  checkpoint={"state":"invalid","matched":None,"portableCopyRequired":True,"command":"hellodev policy checkpoint status"}
 experiment=None
 if policy.get("canaryActive"):
  try:
   policy_full=policy_evolution.status(root);active=policy_full["activeCanary"]
   evaluation=policy_evolution.evaluate(root,active["proposalId"])
   experiment={
    "evaluationVersion":evaluation["evaluationVersion"],"state":evaluation["state"],"reasonCode":evaluation["reasonCode"],
    "evidenceSufficient":evaluation["evidenceSufficient"],"commitEligible":evaluation["commitEligible"],
    "missingBaseline":evaluation["missingBaselineCompletions"],"missingCanary":evaluation["missingCanaryCompletions"],
    "baselineObserved":evaluation["observedBaselineCompletions"],
    "canaryObserved":evaluation["observedCompletions"],"required":evaluation["requiredCompletions"],
    "regressionCount":len(evaluation["regressions"]),
    "comparison":{key:value for key,value in evaluation["comparison"].items() if key!="averageTokenDelta"},
   }
  except ProjectError:
    experiment={"evaluationVersion":2,"state":"invalid","reasonCode":"canary-evaluation-invalid","evidenceSufficient":False,"commitEligible":False,"missingBaseline":0,"missingCanary":0,"baselineObserved":0,"canaryObserved":0,"required":0,"regressionCount":0,"comparison":{"tokenTrust":"unavailable"}}
 try:
  drift_value=drift.status(root);counts=drift_value["counts"];findings=drift_value["findings"]
  drift_projection={
   "state":drift_value["state"],
   "reasonCode":drift_value["reasonCode"],
   "integrityState":drift_value["integrityState"],
   "runtimeState":drift_value["runtimeState"],
   "findingCount":len(findings),
   "warningCount":sum(1 for item in findings if item.get("severity")=="warning"),
   "infoCount":sum(1 for item in findings if item.get("severity")=="info"),
   "counts":{key:counts[key] for key in ("currentCompletions","historicalCompletions","violations","assertedUsage","unavailableUsage")},
   "command":"hellodev drift status",
  }
 except ProjectError:
  drift_projection={"state":"invalid","reasonCode":"drift-state-invalid","integrityState":"invalid","runtimeState":"unavailable","findingCount":0,"warningCount":0,"infoCount":0,"counts":{"currentCompletions":0,"historicalCompletions":0,"violations":0,"assertedUsage":0,"unavailableUsage":0},"command":"hellodev drift status"}
 return {
  "schemaVersion":1,
  "host":host,
  "policy":policy,
  "transactions":transaction,
  "checkpoint":checkpoint,
  "canaryEvaluation":experiment,
  "hostProtocol":{"selectedVersion":host_bridge.HOST_PROTOCOL_VERSION,"supportedVersions":list(host_bridge.SUPPORTED_PROTOCOL_VERSIONS)},
  "drift":drift_projection,
  "uiCapabilities":{"copyOnly":True,"applyAllowed":False,"commitAllowed":False,"revertAllowed":False,"actionApiAvailable":False},
  "readOnly":True,
  "executionPerformed":False,
  "persistencePerformed":False,
  "adapterCallCount":0,
  "modelCallCount":0,
 }
def _legacy_snapshot(root:Path,instance:str,started:str):
 caps=capabilities.status(root);ad=caps.get("capabilities") or {};life=lifecycle.status(root);usage=_usage_snapshot(root);paths=ProjectPaths(root);continuity=_continuity_snapshot(root);optimize=_optimization_snapshot(root);advanced=_advanced_snapshot(root)
 brief_items=[]
 for p in sorted(paths.briefs_dir.glob("*.json")):
  if p.is_file() and not p.is_symlink():brief_items.append({"name":p.stem,"state":"cached","updated":time.strftime("%Y-%m-%d %H:%M",time.localtime(p.stat().st_mtime))})
 saga_count=sum(1 for p in paths.sagas_dir.glob("saga-*.json") if p.is_file() and not p.is_symlink())
 def adapt(name):
  v=ad.get(name,{"state":"cache-missing"});return {"state":v.get("state","unknown"),"detail":v.get("reason",v.get("execution","ready"))}
 return rewrite_commands({"schemaVersion":9,"generatedAt":utc_now(),"instanceId":instance,"startedAt":started,"readOnly":True,"lifecycle":{"phase":life["phase"],"cycleId":life["cycleId"],"completedCycleCount":len(life["completedCycles"])},"tasks":{"localCount":len(list_tasks(root)),"trellisActiveCount":len(contracts.list_trellis_tasks(root)),"linkedWorkItemCount":len(contracts.list_work_items(root))},"capabilities":{"state":caps["state"]},"adapters":{"trellis":adapt("trellis"),"nocturne":adapt("nocturne")},"briefs":brief_items,"usage":usage,"efficiencyCycle":_efficiency_cycle_snapshot(root),"continuity":continuity,"optimization":optimize,"advanced":advanced,"audit":{"receipts":len(receipts.list_receipts(root)),"sagas":saga_count,"optimizationTraces":optimize["traceCount"],"reflectionReports":optimize["reportCount"],"evolutionProposals":optimize["proposalCount"],"hostCompletions":advanced["host"]["completionCount"],"pendingTransactions":advanced["transactions"]["pendingCount"],"pendingHostEnvelopes":advanced["host"]["pendingEnvelopeCount"],"policyEvents":advanced["policy"]["eventCount"],"driftFindings":advanced["drift"]["findingCount"],**continuity["auditSummary"]},"actions":[{"label":"刷新能力","command":"hellodev capabilities refresh"},{"label":"构建 L0 brief","command":"hellodev brief build --level L0"},{"label":"进入计划阶段","command":"hellodev lifecycle plan"},{"label":"进入工作阶段","command":"hellodev lifecycle work"}]})
def snapshot(root:Path,instance:str,started:str):
 value=_legacy_snapshot(root,instance,started)
 value["schemaVersion"]=12
 cached=capabilities.status(root).get("capabilities") or {}
 value["repositoryTools"]=cached.get("repositoryTools") if isinstance(cached.get("repositoryTools"),dict) else repository_tools.discover()
 value["contextPlane"]=context_runtime.status(root)
 continuity=value["continuity"];next_step=continuity["resume"].get("next") or {"command":"hellodev doctor --fix-hints","reason":"Project state is invalid; inspect deterministic fix hints.","reasonCode":"project-state-invalid","suggestedLevel":"L0"}
 value["briefs"]=value["briefs"][-20:]
 value["now"]={
  "phase":value["lifecycle"]["phase"],"cycleId":value["lifecycle"]["cycleId"],
  "workItem":continuity["currentWorkItem"],
  "blocker":continuity["recoveryCenter"][0] if continuity["recoveryCenter"] else None,
  "next":{"command":next_step["command"],"reason":next_step["reason"],"reasonCode":next_step["reasonCode"],"suggestedLevel":next_step["suggestedLevel"]},
  "health":{"capabilities":value["capabilities"]["state"],"trellis":value["adapters"]["trellis"]["state"],"nocturne":value["adapters"]["nocturne"]["state"],"repositoryTools":value["repositoryTools"].get("state","unknown"),"contextPlane":value["contextPlane"].get("state","unknown")},
 }
 value["recallInspector"]=_recall_snapshot(root)
 value["diagnostics"]=_diagnostics_snapshot(root,value["capabilities"],value["adapters"],value["repositoryTools"])
 return rewrite_commands(value)

class Server(ThreadingHTTPServer):
 daemon_threads=True
 def __init__(self,address,root,token,control,instance,started):self.root=root;self.token=token;self.control=control;self.instance=instance;self.started=started;self.snapshot_cache=None;self.snapshot_lock=threading.Lock();super().__init__(address,Handler)
 def status_payload(self):
  now=time.monotonic()
  with self.snapshot_lock:
   if self.snapshot_cache is None or now-self.snapshot_cache[0]>SNAPSHOT_TTL:
    value=snapshot(self.root,self.instance,self.started);semantic={key:item for key,item in value.items() if key!="generatedAt"};digest=hashlib.sha256(json.dumps(semantic,ensure_ascii=False,separators=(",",":"),sort_keys=True).encode()).hexdigest()
    if self.snapshot_cache is not None and self.snapshot_cache[3]==digest:self.snapshot_cache=(now,self.snapshot_cache[1],self.snapshot_cache[2],digest)
    else:
     body=json.dumps(value,ensure_ascii=False,separators=(",",":")).encode();etag='"'+digest+'"';self.snapshot_cache=(now,body,etag,digest)
   return self.snapshot_cache[1],self.snapshot_cache[2]
class Handler(BaseHTTPRequestHandler):
 server:Server
 def log_message(self,*_):pass
 def _headers(self,status,kind,length,extra=None):
  self.send_response(status);headers={"Content-Type":kind,"Content-Length":str(length),"Cache-Control":"no-store","Content-Security-Policy":"default-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'","Referrer-Policy":"no-referrer","X-Content-Type-Options":"nosniff","X-Frame-Options":"DENY"};headers.update(extra or {})
  for k,v in headers.items():self.send_header(k,v)
  self.end_headers()
 def _send(self,status,value):body=json.dumps(value,ensure_ascii=False).encode();self._headers(status,"application/json; charset=utf-8",len(body));self.wfile.write(body)
 def _host(self):return hmac.compare_digest(self.headers.get("Host",""),f"{HOST}:{self.server.server_port}")
 def _auth(self):
  c=SimpleCookie();c.load(self.headers.get("Cookie",""));m=c.get(COOKIE);return m is not None and hmac.compare_digest(m.value,self.server.token)
 def do_GET(self):
  if not self._host():return self._send(403,{"status":"forbidden"})
  parsed=urllib.parse.urlsplit(self.path)
  if parsed.path=="/api/health":return self._send(200,{"status":"running","instanceId":self.server.instance})
  query=urllib.parse.parse_qs(parsed.query)
  if query.get("token") and hmac.compare_digest(query["token"][0],self.server.token):
   self._headers(303,"text/plain",0,{"Location":"/","Set-Cookie":f"{COOKIE}={self.server.token}; Path=/; HttpOnly; SameSite=Strict"});return
  if not self._auth():return self._send(401,{"status":"unauthorized"})
  if parsed.path=="/api/status":
   body,etag=self.server.status_payload()
   if hmac.compare_digest(self.headers.get("If-None-Match",""),etag):return self._headers(304,"application/json; charset=utf-8",0,{"ETag":etag,"Cache-Control":"private, no-cache"})
   self._headers(200,"application/json; charset=utf-8",len(body),{"ETag":etag,"Cache-Control":"private, no-cache"});self.wfile.write(body);return
  names={"/":"index.html","/index.html":"index.html","/styles.css":"styles.css","/app.js":"app.js"};name=names.get(parsed.path)
  if not name:return self._send(404,{"status":"not-found"})
  p=ASSETS/name
  if p.is_symlink() or not p.is_file() or p.stat().st_size>MAX_ASSET:return self._send(404,{"status":"not-found"})
  body=p.read_bytes();kind=mimetypes.guess_type(name)[0] or "application/octet-stream";etag='"'+hashlib.sha256(body).hexdigest()+'"'
  if hmac.compare_digest(self.headers.get("If-None-Match",""),etag):return self._headers(304,kind,0,{"ETag":etag,"Cache-Control":"private, max-age=300"})
  self._headers(200,kind,len(body),{"ETag":etag,"Cache-Control":"private, max-age=300"});self.wfile.write(body)
 def do_POST(self):
  origin=f"http://{HOST}:{self.server.server_port}"
  if not self._host() or not hmac.compare_digest(self.headers.get("Origin",""),origin):return self._send(403,{"status":"forbidden"})
  if self.path=="/api/shutdown":
   if not hmac.compare_digest(self.headers.get("X-HelloDev-Control",""),self.server.control) or not hmac.compare_digest(self.headers.get("X-HelloDev-Instance",""),self.server.instance):return self._send(401,{"status":"unauthorized"})
   self._send(200,{"status":"stopping","instanceId":self.server.instance});import threading;threading.Thread(target=self.server.shutdown,daemon=True).start();return
  return self._send(405,{"status":"method-not-allowed"})
 def do_PUT(self):self._send(405,{"status":"method-not-allowed"})
 do_PATCH=do_PUT;do_DELETE=do_PUT;do_OPTIONS=do_PUT
def serve(root:Path,port:int,instance:str,started:str):
 token=os.environ.get("HELLODEV_DASHBOARD_TOKEN","");control=os.environ.get("HELLODEV_DASHBOARD_CONTROL","")
 if len(token)<40 or len(control)<40:return 2
 server=Server((HOST,port),root.resolve(),token,control,instance,started)
 try:server.serve_forever(.1)
 finally:server.server_close()
 return 0
def main():
 import argparse;p=argparse.ArgumentParser();s=p.add_subparsers(dest="cmd",required=True);serve_p=s.add_parser("serve");serve_p.add_argument("--root",required=True);serve_p.add_argument("--port",type=int,required=True);serve_p.add_argument("--instance",required=True);serve_p.add_argument("--started",required=True);a=p.parse_args();return serve(Path(a.root),a.port,a.instance,a.started)
if __name__=="__main__":raise SystemExit(main())
