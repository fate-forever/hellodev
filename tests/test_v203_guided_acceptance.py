from __future__ import annotations

import tempfile
import unittest
import sys
import json
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import acceptance, verification
from hellodev.application import ProjectClient
from hellodev.project import ProjectError, ProjectPaths
from tests.test_v201_acceptance_continuity import _project_contract, _satisfy


GOOD_SOURCE = """\
class BaseResponse:
    def __init__(self, x_security_headers=False):
        self.x_security_headers = x_security_headers

Response = BaseResponse

class HTTPResponse(Response):
    def __init__(self, **more_headers):
        super().__init__(**more_headers)
"""

BROKEN_SOURCE = """\
class BaseResponse:
    def __init__(self, x_security_headers=False):
        self.x_security_headers = x_security_headers

Response = BaseResponse

class HTTPResponse(Response):
    def __init__(self, x_security_headers=False, **more_headers):
        super().__init__(**more_headers)
"""

FIXED_SOURCE = """\
class BaseResponse:
    def __init__(self, x_security_headers=False):
        self.x_security_headers = x_security_headers

Response = BaseResponse

class HTTPResponse(Response):
    def __init__(self, x_security_headers=False, **more_headers):
        super().__init__(x_security_headers=x_security_headers, **more_headers)
"""


class V203GuidedAcceptanceTests(unittest.TestCase):
    def test_docs_only_goal_uses_lite_mode_without_code_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _project_contract(root)
            readme = root / "README.md"
            readme.write_text("Initial notes\n", encoding="utf-8")
            client = ProjectClient(root)
            client.open()
            client.do("begin", {"goal": "Update README documentation", "acceptance": "docs reviewed"})
            client.do("work")
            readme.write_text("Updated notes\n", encoding="utf-8")

            guided = acceptance.evidence(root)["guidedAcceptance"]
            self.assertEqual(guided["mode"], "lite")
            self.assertTrue(guided["satisfied"])
            self.assertNotIn("feature-code-change-missing", guided["blockers"])

    def test_unforwarded_override_parameter_blocks_check_until_fixed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _project_contract(root)
            source = root / "responses.py"
            source.write_text(GOOD_SOURCE, encoding="utf-8")
            client = ProjectClient(root)
            client.open()
            client.do(
                "begin",
                {
                    "goal": "Implement security headers",
                    "acceptance": "python -m unittest discover",
                },
            )
            client.do("work")
            source.write_text(BROKEN_SOURCE, encoding="utf-8")
            _satisfy(client, root)

            evidence = acceptance.evidence(root)
            guided = evidence["guidedAcceptance"]
            self.assertEqual(guided["mode"], "strict")
            self.assertEqual(guided["state"], "blocked")
            self.assertEqual(guided["overrideForwarding"]["issueCount"], 1)
            self.assertIn("python-override-parameter-not-forwarded", guided["blockers"])
            with self.assertRaisesRegex(ProjectError, "guided-blocked"):
                client.do("check")

            source.write_text(FIXED_SOURCE, encoding="utf-8")
            _satisfy(client, root)
            repaired = acceptance.evidence(root)
            self.assertTrue(repaired["satisfied"])
            self.assertEqual(repaired["guidedAcceptance"]["overrideForwarding"]["state"], "clear")
            quality = repaired["guidedAcceptance"]["verificationQuality"]
            self.assertEqual(quality["distinctCommandCount"], 1)
            self.assertEqual(quality["distinctSnapshotCount"], 2)
            self.assertEqual(quality["repeatedCommandCount"], 1)
            client.do("check")
            self.assertEqual(client.do("finish")["lifecycle"]["phase"], "finished")

    def test_forwarding_issue_blocks_finish_after_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _project_contract(root)
            source = root / "responses.py"
            source.write_text(GOOD_SOURCE, encoding="utf-8")
            client = ProjectClient(root)
            client.open()
            client.do(
                "begin",
                {"goal": "Implement security headers", "acceptance": "python -m unittest discover"},
            )
            client.do("work")
            source.write_text(FIXED_SOURCE, encoding="utf-8")
            _satisfy(client, root)
            client.do("check")
            source.write_text(BROKEN_SOURCE, encoding="utf-8")
            _satisfy(client, root)

            self.assertEqual(client.next()["reasonCode"], "guided-acceptance-blocked")
            with self.assertRaisesRegex(ProjectError, "guided-blocked"):
                client.do("finish")

    def test_feature_with_no_code_change_is_not_allowed_to_finish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _project_contract(root)
            client = ProjectClient(root)
            client.open()
            client.do("begin", {"goal": "Add health endpoint", "acceptance": "tests pass"})
            client.do("work")
            _satisfy(client, root)
            evidence = acceptance.evidence(root)
            self.assertIn("feature-code-change-missing", evidence["guidedAcceptance"]["blockers"])
            decision = client.next()
            self.assertEqual(decision["reasonCode"], "guided-acceptance-blocked")
            self.assertEqual(decision["command"], "hellodev status --verbose")
            opened = client.open()
            self.assertEqual(set(opened), {"task", "phase", "blockers", "acceptance", "next", "approval"})
            self.assertEqual(opened["acceptance"]["mode"], "guided")
            self.assertIn(
                "guided acceptance: feature-code-change-missing", opened["blockers"]
            )

    def test_verification_summary_reports_evidence_diversity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _project_contract(root)
            client = ProjectClient(root)
            client.open()
            client.do("begin", {"goal": "Compatibility check", "acceptance": "tests pass"})
            client.do("work")
            _satisfy(client, root)
            first = verification.summary(root)
            self.assertEqual(first["distinctCommandCount"], 1)
            self.assertEqual(first["distinctSnapshotCount"], 1)
            self.assertEqual(first["repeatedCommandCount"], 0)

    def test_preexisting_forwarding_issue_does_not_block_unrelated_edit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _project_contract(root)
            source = root / "responses.py"
            source.write_text(BROKEN_SOURCE, encoding="utf-8")
            client = ProjectClient(root)
            client.open()
            client.do("begin", {"goal": "Change response documentation", "acceptance": "tests pass"})
            client.do("work")
            source.write_text(BROKEN_SOURCE + "\n# clarified behavior\n", encoding="utf-8")
            _satisfy(client, root)

            guided = acceptance.evidence(root)["guidedAcceptance"]
            self.assertEqual(guided["overrideForwarding"]["baselineState"], "ready")
            self.assertEqual(guided["overrideForwarding"]["issueCount"], 0)
            self.assertTrue(guided["satisfied"])

    def test_legacy_changeset_is_readable_and_forwarding_check_is_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _project_contract(root)
            source = root / "responses.py"
            source.write_text(BROKEN_SOURCE, encoding="utf-8")
            client = ProjectClient(root)
            client.open()
            client.do("begin", {"goal": "Change response behavior", "acceptance": "tests pass"})
            client.do("work")
            path = ProjectPaths(root).changeset_file
            stored = json.loads(path.read_text(encoding="utf-8"))
            stored["schemaVersion"] = 1
            stored.pop("qualityBaseline")
            path.write_text(json.dumps(stored), encoding="utf-8")
            source.write_text(BROKEN_SOURCE + "\nVALUE = 1\n", encoding="utf-8")

            guided = acceptance.evidence(root)["guidedAcceptance"]
            self.assertEqual(
                guided["overrideForwarding"]["state"], "advisory-baseline-unavailable"
            )
            self.assertEqual(guided["overrideForwarding"]["issueCount"], 0)
            self.assertTrue(guided["satisfied"])

    def test_imported_base_alias_forwarding_issue_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _project_contract(root)
            (root / "base.py").write_text(
                "class BaseResponse:\n"
                "    def __init__(self, x_security_headers=False):\n"
                "        self.x_security_headers = x_security_headers\n",
                encoding="utf-8",
            )
            child = root / "response.py"
            child.write_text(
                "from base import BaseResponse as Response\n\n"
                "class HTTPResponse(Response):\n"
                "    def __init__(self, **more_headers):\n"
                "        super().__init__(**more_headers)\n",
                encoding="utf-8",
            )
            client = ProjectClient(root)
            client.open()
            client.do("begin", {"goal": "Implement security headers", "acceptance": "tests pass"})
            client.do("work")
            child.write_text(
                "from base import BaseResponse as Response\n\n"
                "class HTTPResponse(Response):\n"
                "    def __init__(self, x_security_headers=False, **more_headers):\n"
                "        super().__init__(**more_headers)\n",
                encoding="utf-8",
            )

            guided = acceptance.evidence(root)["guidedAcceptance"]
            self.assertEqual(guided["overrideForwarding"]["issueCount"], 1)
            self.assertIn("python-override-parameter-not-forwarded", guided["blockers"])


if __name__ == "__main__":
    unittest.main()
