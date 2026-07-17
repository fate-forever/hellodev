from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import context_policy
from hellodev.project import ProjectError


class ContextPolicyTests(unittest.TestCase):
    def test_canonical_intent_behavior_matrix(self) -> None:
        expected = {
            "status": "L0",
            "doctor": "L0",
            "lifecycle": "L1",
            "local-task": "L1",
            "code": "L1",
            "trellis-read": "L1",
            "trellis-write": "L2",
            "saga": "L2",
            "nocturne-write": "L2",
            "cross-project-retrieve": "L0",
            "recall": "L1",
            "remember": "L2",
        }
        for intent, level in expected.items():
            with self.subTest(intent=intent):
                result = context_policy.decide(intent)
                self.assertEqual(result["intent"], intent)
                self.assertEqual(result["level"], level)
                self.assertEqual(result["loading"], list(context_policy.LEVEL_LOADING[level]))
                self.assertEqual(result["tokenBudget"], context_policy.LEVEL_TOKEN_BUDGETS[level])
                self.assertEqual(result["selectionSource"], "intent")
                self.assertEqual(result["adapterCalls"], [])
                self.assertTrue(result["reasonCodes"])

    def test_cross_project_retrieval_is_narrow_without_loading_memory(self) -> None:
        result = context_policy.suggest("cross-project-retrieve")
        self.assertEqual(result["level"], "L0")
        self.assertTrue(result["narrowRetrieval"])
        self.assertIn("narrow-retrieval-required", result["reasonCodes"])
        self.assertNotIn("nocturne", " ".join(result["loading"]).lower())
        for intent in context_policy.INTENT_LEVELS:
            if intent != "cross-project-retrieve":
                self.assertFalse(context_policy.decide(intent)["narrowRetrieval"])

    def test_explicit_level_overrides_intent_and_reports_selection_source(self) -> None:
        self.assertEqual(context_policy.suggested_level("status"), "L0")
        self.assertEqual(context_policy.select_level("status", "L2"), "L2")
        self.assertEqual(context_policy.selection_source(None), "intent")
        self.assertEqual(context_policy.selection_source("L2"), "explicit")
        result = context_policy.decide("status", "L2")
        self.assertEqual(result["level"], "L2")
        self.assertEqual(result["selectionSource"], "explicit")
        self.assertEqual(result["tokenBudget"], 12_000)
        self.assertIn("explicit-level-override", result["reasonCodes"])

    def test_unknown_intents_and_invalid_levels_fail_closed(self) -> None:
        for intent in (None, "", "STATUS", " status", "external-write", "nocturne-read", 7):
            with self.subTest(intent=intent), self.assertRaises(ProjectError):
                context_policy.decide(intent)  # type: ignore[arg-type]
        for level in ("", "l0", "L3", " L1", 1):
            with self.subTest(level=level), self.assertRaises(ProjectError):
                context_policy.decide("status", level)  # type: ignore[arg-type]

    def test_decisions_are_deterministic_and_make_zero_adapter_calls(self) -> None:
        with (
            patch("hellodev.capabilities.status") as capability_status,
            patch("hellodev.capabilities.refresh") as capability_refresh,
            patch("hellodev.adapters.trellis.discover") as trellis_discover,
            patch("hellodev.adapters.nocturne.status") as nocturne_status,
        ):
            first = context_policy.decide("remember")
            second = context_policy.decide("remember")
        self.assertEqual(first, second)
        capability_status.assert_not_called()
        capability_refresh.assert_not_called()
        trellis_discover.assert_not_called()
        nocturne_status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
