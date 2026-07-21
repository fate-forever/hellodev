from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import capabilities, contracts, dashboard, drift, efficiency_cycles, governance, host_bridge, lifecycle, optimization, policy_evolution, receipts, sagas
from hellodev.project import ProjectPaths, init_project


class F2DashboardTests(unittest.TestCase):
    def _root(self, directory: str) -> Path:
        root = Path(directory)
        init_project(root)
        lifecycle.start(root)
        capabilities.refresh(root)
        return root

    def _state_files(self, root: Path) -> dict[str, bytes]:
        state_dir = ProjectPaths(root).state_dir
        return {
            path.relative_to(state_dir).as_posix(): path.read_bytes()
            for path in state_dir.rglob("*")
            if path.is_file() and not path.is_symlink()
        }

    def test_snapshot_projects_f2_continuity_without_adapter_calls_or_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            task = root / ".trellis" / "tasks" / "07-16-dashboard"
            task.mkdir(parents=True)
            (task / "prd.md").write_text("Dashboard pointer body must stay external", encoding="utf-8")
            capabilities.refresh(root)
            work = contracts.create_work_item(root, "trellis", task.name)
            evidence = receipts.record(
                root,
                "trellis",
                "intent/task-validate",
                "read",
                {"private": "request"},
                {"private": "result"},
                True,
                kind="gate",
                evidence_binding=contracts.evidence_binding(root),
            )
            receipts.record_verification(root, evidence["id"], "operator-only evidence")
            contracts.reconcile_evidence(root, evidence["id"])
            saga = sagas.create(root, "Recover hash-only lesson")
            private_lesson = "Never expose this lesson in the dashboard projection"
            proposal = contracts.create_lesson_proposal(
                root,
                private_lesson,
                "cross-project",
                "nocturne",
                evidence_receipt_id=evidence["id"],
                saga_id=saga["id"],
                state="saga-active",
            )
            before = self._state_files(root)

            with patch(
                "hellodev.adapters.trellis.discover",
                side_effect=AssertionError("Trellis adapter called"),
            ), patch(
                "hellodev.adapters.trellis.run",
                side_effect=AssertionError("Trellis adapter executed"),
            ), patch(
                "hellodev.adapters.nocturne.status",
                side_effect=AssertionError("Nocturne adapter called"),
            ), patch(
                "hellodev.adapters.nocturne.call",
                side_effect=AssertionError("Nocturne adapter executed"),
            ):
                value = dashboard.snapshot(root, "instance", "2026-07-16T00:00:00Z")

            self.assertEqual(value["schemaVersion"], 9)
            self.assertTrue(value["readOnly"])
            continuity = value["continuity"]
            self.assertTrue(continuity["readOnly"])
            self.assertFalse(continuity["executionPerformed"])
            self.assertEqual(continuity["currentWorkItem"]["id"], work["id"])
            self.assertEqual(continuity["gate"]["state"], "aligned")
            self.assertFalse(continuity["gate"]["trellisMutationPerformed"])
            self.assertEqual(continuity["incompleteSagas"][0]["id"], saga["id"])
            self.assertEqual(
                continuity["incompleteSagas"][0]["nextCommand"],
                "hellodev do validate --task 07-16-dashboard",
            )
            self.assertEqual(continuity["lessonProposals"][0]["id"], proposal["id"])
            self.assertEqual(continuity["lessonProposals"][0]["lessonSha256"], proposal["lessonSha256"])
            self.assertEqual(value["audit"]["workItems"], 1)
            self.assertEqual(value["audit"]["lessonProposals"], 1)
            self.assertEqual(value["audit"]["evidenceLinks"], 1)
            self.assertEqual(value["audit"]["incompleteSagas"], 1)
            self.assertNotIn(private_lesson, json.dumps(value, ensure_ascii=False))
            self.assertNotIn("operator-only evidence", json.dumps(value, ensure_ascii=False))
            self.assertEqual(self._state_files(root), before)

    def test_snapshot_is_nondestructive_for_08_state_without_f2_stores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            paths = ProjectPaths(root)
            value = dashboard.snapshot(root, "instance", "2026-07-16T00:00:00Z")
            continuity = value["continuity"]
            self.assertIsNone(continuity["currentWorkItem"])
            self.assertEqual(continuity["incompleteSagas"], [])
            self.assertEqual(continuity["lessonProposals"], [])
            self.assertEqual(continuity["gate"]["state"], "no-current-work")
            self.assertFalse((paths.state_dir / "work-items.json").exists())
            self.assertFalse((paths.state_dir / "lesson-proposals.json").exists())
            self.assertFalse((paths.state_dir / "evidence-links.json").exists())
            self.assertFalse(paths.optimization_file.exists())
            self.assertEqual(value["optimization"]["state"], "insufficient-data")
            self.assertEqual(value["optimization"]["traceCount"], 0)
            self.assertEqual(value["optimization"]["reportCount"], 0)
            self.assertEqual(value["optimization"]["proposalCount"], 0)
            self.assertIsNone(value["optimization"]["latestUsageEnvelope"])
            self.assertIsNone(value["optimization"]["latestReflection"])
            self.assertFalse(paths.host_completions_file.exists())
            self.assertFalse(paths.evolution_policy_file.exists())
            self.assertEqual(value["advanced"]["host"]["state"], "unavailable")
            self.assertEqual(value["advanced"]["host"]["completionCount"], 0)
            self.assertEqual(value["advanced"]["policy"]["eventCount"], 0)
            self.assertEqual(value["advanced"]["drift"]["state"], "unavailable")
            self.assertEqual(value["advanced"]["drift"]["findingCount"], 0)

    def test_optimization_projection_is_numeric_private_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            private_query = "RAW-QUERY-CANARY"
            private_lesson = "RAW-LESSON-CANARY"
            private_task = "RAW-TASK-CANARY"
            private_context = "RAW-CONTEXT-CANARY"
            usage = governance.record_usage(
                root,
                20_000,
                12_000,
                2,
                f"{private_query}:{private_lesson}",
                f"{private_task}:{private_context}",
            )
            for retries in (2, 3, 4):
                optimization.reflect(
                    root,
                    "code",
                    "L1",
                    "partial",
                    usage_id=usage["id"],
                    total_token_ceiling=8_000,
                    subagent_token_ceiling=4_000,
                    max_subagents=2,
                    delegation_mode="executed",
                    retry_count=retries,
                )
            before = self._state_files(root)

            with patch(
                "hellodev.adapters.trellis.discover",
                side_effect=AssertionError("Trellis adapter called"),
            ), patch(
                "hellodev.adapters.trellis.run",
                side_effect=AssertionError("Trellis adapter executed"),
            ), patch(
                "hellodev.adapters.nocturne.status",
                side_effect=AssertionError("Nocturne adapter called"),
            ), patch(
                "hellodev.adapters.nocturne.call",
                side_effect=AssertionError("Nocturne adapter executed"),
            ), patch(
                "hellodev.optimization.reflect",
                side_effect=AssertionError("reflection executed"),
            ), patch(
                "hellodev.optimization.plan",
                side_effect=AssertionError("optimization plan executed"),
            ), patch(
                "hellodev.optimization.write_json",
                side_effect=AssertionError("optimization state written"),
            ):
                value = dashboard.snapshot(root, "instance", "2026-07-16T00:00:00Z")

            projected = value["optimization"]
            self.assertEqual(projected["state"], "review-due")
            self.assertEqual(projected["traceCount"], 3)
            self.assertEqual(projected["reportCount"], 3)
            self.assertEqual(projected["proposalCount"], 2)
            self.assertEqual(projected["staleProposalCount"], 0)
            self.assertEqual(projected["nextCommand"], "hellodev optimize proposals")
            self.assertFalse(projected["applyAllowed"])
            self.assertTrue(projected["readOnly"])
            self.assertFalse(projected["executionPerformed"])
            self.assertFalse(projected["persistencePerformed"])
            self.assertEqual(projected["adapterCallCount"], 0)
            self.assertEqual(projected["modelCallCount"], 0)
            self.assertEqual(
                set(projected["latestUsageEnvelope"]),
                {"budgetState", "plan", "actual"},
            )
            self.assertEqual(
                set(projected["latestUsageEnvelope"]["actual"]),
                {
                    "totalTokens",
                    "rootTokens",
                    "subagentTokens",
                    "subagentCount",
                    "sourceKind",
                    "sourceTrust",
                    "accuracy",
                },
            )
            self.assertEqual(projected["latestUsageEnvelope"]["actual"]["totalTokens"], 20_000)
            self.assertEqual(projected["latestUsageEnvelope"]["actual"]["sourceTrust"], "asserted")
            self.assertEqual(value["usage"]["displayBasis"], "latest-operator-report")
            self.assertEqual(
                set(projected["latestReflection"]),
                {
                    "findingCount",
                    "recommendationCount",
                    "deepReflectionState",
                    "deepReflectionTokenCeiling",
                    "anomaly",
                    "sampleSize",
                    "usageAvailableCount",
                    "averageReportedTokens",
                },
            )
            self.assertEqual(projected["latestReflection"]["sampleSize"], 3)
            self.assertEqual(projected["latestReflection"]["usageAvailableCount"], 3)
            self.assertEqual(projected["latestReflection"]["averageReportedTokens"], 20_000)
            self.assertEqual(
                set(value["usage"]["latest"]),
                {
                    "state",
                    "completedAt",
                    "totalTokens",
                    "rootTokens",
                    "subagentTokens",
                    "subagentCount",
                    "sourceKind",
                    "sourceTrust",
                    "measurement",
                    "attestation",
                    "accuracy",
                    "breakdown",
                },
            )
            serialized = json.dumps(value, ensure_ascii=False)
            for canary in (private_query, private_lesson, private_task, private_context):
                self.assertNotIn(canary, serialized)
            self.assertNotIn("recommendations", projected["latestReflection"])
            self.assertNotIn("sourceSha256", serialized)
            self.assertNotIn("scopeSha256", serialized)
            self.assertEqual(self._state_files(root), before)

    def test_efficiency_cycle_projection_is_filtered_read_only_and_copy_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            for number in range(20):
                governance.record_runtime_usage(
                    root,
                    input_tokens=1_000,
                    cached_input_tokens=100,
                    output_tokens=100,
                    reasoning_output_tokens=10,
                    subagent_tokens=0,
                    subagent_count=0,
                    completed_at=f"2026-07-17T00:00:{number:02d}Z",
                    source_sha256="a" * 64,
                    scope_sha256=f"{number + 1:064x}",
                    source_kind="codex-runtime",
                    source_trust="runtime-observed",
                )
            efficiency_cycles.reconcile(root)
            before = self._state_files(root)
            value = dashboard.snapshot(root, "instance", "2026-07-17T00:01:00Z")

            projected = value["efficiencyCycle"]
            self.assertEqual(value["schemaVersion"], 9)
            self.assertTrue(projected["readOnly"])
            self.assertEqual(projected["windowSize"], 20)
            self.assertEqual(projected["cycleCount"], 1)
            self.assertEqual(projected["pendingReceiptCount"], 0)
            self.assertEqual(projected["remainingUntilNextCycle"], 20)
            self.assertEqual(
                set(projected["latest"]),
                {
                    "id", "receiptCount", "firstCompletedAt", "lastCompletedAt",
                    "metrics", "signals", "recommendation", "policyEffect",
                },
            )
            self.assertEqual(projected["latest"]["recommendation"]["code"], "increase-context-reuse")
            self.assertFalse(projected["latest"]["policyEffect"]["applyAllowed"])
            serialized = json.dumps(projected, ensure_ascii=False)
            self.assertNotIn("windowSha256", serialized)
            self.assertNotIn("cycleSha256", serialized)
            self.assertNotIn("sourceSha256", serialized)
            self.assertNotIn("scopeSha256", serialized)
            self.assertEqual(self._state_files(root), before)

    def test_advanced_projection_filters_host_policy_and_drift_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            private_envelope = "RAW-HOST-ENVELOPE-CANARY"
            private_context = "RAW-HOST-CONTEXT-CANARY"
            private_patch = "RAW-POLICY-PATCH-CANARY"
            private_receipt = "RAW-RECEIPT-CANARY"
            host_value = {
                "schemaVersion": 1,
                "state": "ready",
                "completionCount": 4,
                "pendingEnvelopeCount": 2,
                "expiredPendingEnvelopeCount": 1,
                "lateCount": 1,
                "budgetExceededCount": 2,
                "usageTrustCounts": {"host-asserted": 3, "unavailable": 1},
                "latest": {
                    "id": private_envelope,
                    "outcome": "partial",
                    "budgetState": "exceeded",
                    "usageTrust": "host-asserted",
                    "late": True,
                    "recordedAt": private_context,
                },
                "trustContract": private_receipt,
                "executionPerformed": False,
                "persistencePerformed": False,
                "adapterCalls": [],
                "modelCalls": [],
            }
            policy_value = {
                "schemaVersion": 1,
                "state": "canary-active",
                "committedPolicy": {"private": private_patch},
                "effectivePolicy": {"private": private_patch},
                "eventCount": 5,
                "ledgerHead": {"eventSha256": private_receipt},
                "activeProposalId": "evolution-private",
                "activeCanary": {
                    "proposalId": "evolution-private",
                    "turnLimit": 3,
                    "startedAt": private_context,
                    "expiresAt": private_context,
                    "expired": False,
                },
                "integrity": {"state": "structurally-valid", "guarantee": private_context},
                "executionPerformed": False,
                "persistencePerformed": False,
                "adapterCalls": [],
                "modelCalls": [],
            }
            drift_value = {
                "schemaVersion": 1,
                "state": "detected",
                "reasonCode": "policy-or-binding-drift",
                "integrityState": "structurally-valid",
                "runtimeState": "observed",
                "policyState": "canary-active",
                "ledgerHeadSha256": private_receipt,
                "expectedHeadMatched": None,
                "findings": [
                    {"code": "private-warning", "severity": "warning", "raw": private_context},
                    {"code": "private-info", "severity": "info", "raw": private_envelope},
                ],
                "counts": {
                    "currentCompletions": 3,
                    "historicalCompletions": 1,
                    "violations": 2,
                    "assertedUsage": 2,
                    "unavailableUsage": 1,
                },
                "trustContract": private_receipt,
                "integrityGuarantee": private_context,
                "repairCommand": "hellodev policy revert",
                "executionPerformed": False,
                "persistencePerformed": False,
                "adapterCalls": [],
                "modelCalls": [],
            }
            before = self._state_files(root)
            mutation_patches = (
                patch("hellodev.host_bridge.prepare", side_effect=AssertionError("host prepare called")),
                patch("hellodev.host_bridge.complete", side_effect=AssertionError("host complete called")),
                patch("hellodev.policy_evolution.stage", side_effect=AssertionError("policy stage called")),
                patch("hellodev.policy_evolution.start_canary", side_effect=AssertionError("canary called")),
                patch("hellodev.policy_evolution.commit", side_effect=AssertionError("commit called")),
                patch("hellodev.policy_evolution.revert", side_effect=AssertionError("revert called")),
            )
            with patch("hellodev.host_bridge.status", return_value=host_value), patch(
                "hellodev.policy_evolution.status", return_value=policy_value
            ), patch("hellodev.drift.status", return_value=drift_value), mutation_patches[0], mutation_patches[1], mutation_patches[2], mutation_patches[3], mutation_patches[4], mutation_patches[5]:
                value = dashboard.snapshot(root, "instance", "2026-07-16T00:00:00Z")

            advanced = value["advanced"]
            self.assertEqual(value["schemaVersion"], 9)
            self.assertEqual(advanced["host"]["completionCount"], 4)
            self.assertEqual(
                set(advanced["host"]["latest"]),
                {"outcome", "budgetState", "usageTrust", "late"},
            )
            self.assertEqual(advanced["policy"]["eventCount"], 5)
            self.assertTrue(advanced["policy"]["activeProposal"])
            self.assertTrue(advanced["policy"]["canaryActive"])
            self.assertEqual(advanced["drift"]["findingCount"], 2)
            self.assertEqual(advanced["drift"]["warningCount"], 1)
            self.assertEqual(advanced["drift"]["infoCount"], 1)
            self.assertEqual(
                {
                    advanced["host"]["command"],
                    advanced["policy"]["command"],
                    advanced["drift"]["command"],
                    advanced["transactions"]["command"],
                    advanced["checkpoint"]["command"],
                },
                {
                    "hellodev host status", "hellodev policy status", "hellodev drift status",
                    "hellodev transaction status", "hellodev policy checkpoint status",
                },
            )
            self.assertEqual(
                advanced["uiCapabilities"],
                {
                    "copyOnly": True,
                    "applyAllowed": False,
                    "commitAllowed": False,
                    "revertAllowed": False,
                    "actionApiAvailable": False,
                },
            )
            serialized = json.dumps(value, ensure_ascii=False)
            for canary in (private_envelope, private_context, private_patch, private_receipt):
                self.assertNotIn(canary, serialized)
            self.assertNotIn("committedPolicy", serialized)
            self.assertNotIn("effectivePolicy", serialized)
            self.assertNotIn("repairCommand", serialized)
            self.assertEqual(self._state_files(root), before)

    def test_tampered_advanced_stores_report_invalid_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            paths = ProjectPaths(root)
            paths.host_completions_file.write_text('{"schemaVersion":1,"completions":"bad"}', encoding="utf-8")
            paths.evolution_policy_file.write_text('{"schemaVersion":1,"events":[]}', encoding="utf-8")
            before = self._state_files(root)
            value = dashboard.snapshot(root, "instance", "2026-07-16T00:00:00Z")
            self.assertEqual(value["advanced"]["host"]["state"], "invalid")
            self.assertEqual(value["advanced"]["policy"]["state"], "invalid")
            self.assertEqual(value["advanced"]["drift"]["state"], "invalid")
            self.assertFalse(value["advanced"]["uiCapabilities"]["applyAllowed"])
            self.assertFalse(value["advanced"]["uiCapabilities"]["commitAllowed"])
            self.assertFalse(value["advanced"]["uiCapabilities"]["revertAllowed"])
            self.assertEqual(self._state_files(root), before)

    def test_assets_only_fetch_status_and_offer_copy_only_commands(self) -> None:
        assets = PACKAGE_ROOT / "src" / "hellodev" / "dashboard_assets"
        script = (assets / "app.js").read_text(encoding="utf-8")
        markup = (assets / "index.html").read_text(encoding="utf-8")
        self.assertIn('fetch("/api/status", { cache: "no-store" })', script)
        self.assertNotIn("/api/action", script)
        self.assertNotIn("method:", script)
        self.assertNotIn("innerHTML", script)
        self.assertIn("navigator.clipboard.writeText", script)
        self.assertNotIn("knowledge-query", script)
        self.assertNotIn("build-search", script)
        self.assertNotIn("knowledge-query", markup)
        self.assertNotIn("build-search", markup)
        self.assertIn("只读控制中心", markup)
        self.assertIn("LessonProposal", markup)
        self.assertIn('data-tab="optimization"', markup)
        self.assertIn("最近 Usage Envelope", markup)
        self.assertIn("Reflection 摘要", markup)
        self.assertIn("optimizationCommands", script)
        self.assertIn('data-tab="advanced"', markup)
        self.assertIn("Host Bridge", markup)
        self.assertIn("Policy Ledger", markup)
        self.assertIn("advancedCommands", script)
        self.assertIn("efficiencyCycle", script)
        self.assertIn("20-turn efficiency cycle", markup)
        advanced_block = script.split("const advancedCommands = new Set([", 1)[1].split("]);", 1)[0]
        expected_advanced_commands = {
            "hellodev host status",
            "hellodev policy status",
            "hellodev drift status",
            "hellodev transaction status",
            "hellodev policy checkpoint status",
        }
        self.assertEqual(set(re.findall(r'"(hellodev [^"]+)"', advanced_block)), expected_advanced_commands)
        for command in expected_advanced_commands:
            self.assertIn(command, script)
        for forbidden in (
            "hellodev host complete",
            "hellodev policy stage",
            "hellodev policy canary",
            "hellodev policy commit",
            "hellodev policy revert",
        ):
            self.assertNotIn(forbidden, script)
            self.assertNotIn(forbidden, markup)
        self.assertNotIn("<input", markup)
        self.assertIn("Canary Evaluation v2", markup)
        self.assertIn("Portable checkpoint", markup)
        self.assertIn("HELLODEV 0.14.3", markup)


if __name__ == "__main__":
    unittest.main()
