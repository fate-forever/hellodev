from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import acceptance, knowledge_flows
from hellodev.application import ProjectClient
from hellodev.dashboard import snapshot
from hellodev.project import configure_nocturne, create_task, init_project
from tests.test_v201_acceptance_continuity import _project_contract, _satisfy, _trellis_task, _validate_context


FAKE_MCP_SERVER = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"


class V202AcceptanceFlowTests(unittest.TestCase):
    def test_open_is_daily_only_and_verbose_preserves_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)
            daily = client.open()
            verbose = client.open(verbose=True)
            self.assertEqual(
                set(daily), {"task", "phase", "blockers", "acceptance", "next", "approval"}
            )
            self.assertIn("usageSync", verbose)
            self.assertIn("resume", verbose)
            self.assertLess(len(json.dumps(daily)), len(json.dumps(verbose)) * 0.3)

    def test_acceptance_evidence_routes_host_then_trellis_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _project_contract(root)
            task_id = _trellis_task(root)
            client = ProjectClient(root)
            client.open()
            client.do(
                "begin",
                {"goal": "Acceptance-driven delivery", "acceptance": "project tests pass", "task": task_id},
            )
            client.do("work")
            before = acceptance.evidence(root)
            self.assertEqual(before["state"], "verification-required")
            self.assertEqual(before["hostTest"]["runtime"]["executor"], "host")
            self.assertEqual(before["hostTest"]["runtime"]["cwd"], str(root.resolve()))
            self.assertEqual(before["hostTest"]["runtime"]["environmentHint"], "project-runtime")

            _satisfy(client, root)
            context_required = acceptance.evidence(root)
            self.assertEqual(context_required["state"], "context-validation-required")
            self.assertEqual(context_required["coverage"], {"satisfied": 1, "required": 2, "ratio": 0.5})
            self.assertEqual(client.next()["command"], context_required["trellisContextGate"]["next"])

            _validate_context(client, task_id)
            completed = acceptance.evidence(root)
            self.assertTrue(completed["satisfied"])
            self.assertEqual(completed["coverage"], {"satisfied": 2, "required": 2, "ratio": 1.0})
            self.assertFalse(completed["trellisContextGate"]["qualityGateSatisfied"])
            self.assertTrue(completed["finishDecision"]["allowed"])
            self.assertEqual(client.next()["command"], "hellodev do check")

    def test_external_trellis_context_validation_persists_digest_bound_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _project_contract(root)
            task_id = _trellis_task(root)
            scripts = root / ".trellis" / "scripts"
            scripts.mkdir()
            (scripts / "task.py").write_text(
                "import sys\nprint('context valid')\nraise SystemExit(0)\n", encoding="utf-8"
            )
            client = ProjectClient(root)
            client.open()
            client.do("begin", {"goal": "Legacy compatibility", "acceptance": "tests pass", "task": task_id})
            client.do("work")
            _satisfy(client, root)
            prepared = client.do("validate", {"task": task_id})
            client.do("validate", {"task": task_id, "approve": prepared["approval"]})
            evidence = acceptance.evidence(root)
            self.assertTrue(evidence["trellisContextGate"]["satisfied"])
            self.assertEqual(evidence["trellisContextGate"]["source"], "legacy-task-script")
            self.assertTrue((root / ".hellodev" / "acceptance-evidence.json").is_file())

    def test_recall_derives_narrow_scope_only_after_local_miss(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            (root / "pyproject.toml").write_text(
                "[project]\nname = 'Study Companion'\nversion = '1.0.0'\n", encoding="utf-8"
            )
            configure_nocturne(root, sys.executable, [str(FAKE_MCP_SERVER)], root)
            planned = knowledge_flows.recall_plan(root, "missing handoff preference", None, None, None)
            self.assertEqual(planned["state"], "memory-plan-required")
            self.assertEqual(
                planned["nocturne"]["parameters"],
                {"query": "missing handoff preference", "domain": "core", "limit": 3},
            )
            self.assertEqual(planned["nocturne"]["namespaceScope"], "project-study-companion")
            self.assertEqual(planned["scopeDerivation"]["state"], "derived")

            task = create_task(root, "Local convention")
            task_path = Path(task["path"])
            task_path.write_text(
                task_path.read_text(encoding="utf-8") + "\nUse local-first evidence for this project.\n",
                encoding="utf-8",
            )
            local = knowledge_flows.recall_plan(root, "local-first evidence", None, None, None)
            self.assertEqual(local["state"], "local-sufficient")
            self.assertEqual(local["nocturne"], "not-planned")
            self.assertNotIn("scopeDerivation", local)

    def test_dashboard_combines_acceptance_drift_verification_and_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)
            client.open()
            client.do("begin", {"goal": "Dashboard flow", "acceptance": "tests pass"})
            value = snapshot(root, "instance", "2026-07-29T00:00:00Z")
            self.assertEqual(value["schemaVersion"], 23)
            flow = value["acceptanceFlow"]
            self.assertEqual(flow["coverage"]["required"], 1)
            self.assertEqual(flow["quality"]["mode"], "guided")
            self.assertIn("overrideForwarding", flow["guided"])
            self.assertIn("verificationQuality", flow["guided"])
            self.assertIn("lifecycleDrift", flow)
            self.assertIn("pendingVerification", flow)
            self.assertFalse(flow["memory"]["externalReadAutomatic"])
            self.assertTrue(flow["readOnly"])


if __name__ == "__main__":
    unittest.main()
