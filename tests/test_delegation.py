from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import delegation
from hellodev.project import ProjectError


def proposal() -> dict:
    return {
        "task": "Implement and independently review the continuity layer",
        "intent": "code",
        "parallelizable": True,
        "sharedContext": "Repository rules and frozen interface contract.",
        "candidates": [
            {
                "role": "implement",
                "objective": "Implement the bounded contract",
                "contextDelta": "Edit the implementation module only.",
            },
            {
                "role": "review",
                "objective": "Review safety and deterministic behavior",
                "contextDelta": "Return findings without editing source.",
            },
            {
                "role": "test",
                "objective": "Exercise contract boundaries",
                "contextDelta": "Focus on malformed and oversized payloads.",
            },
        ],
        "limits": {
            "maxAgents": 2,
            "sharedBytes": 2_000,
            "perAgentBytes": 4_000,
            "totalReportedTokenBudget": 2_000,
        },
    }


class DelegationTests(unittest.TestCase):
    def test_plan_selects_bounded_roles_without_side_effect_claims(self) -> None:
        value = proposal()
        first = delegation.plan(value)
        second = delegation.plan(copy.deepcopy(value))
        self.assertEqual(first, second)
        self.assertEqual(first["decision"], "delegate")
        self.assertEqual(first["selectedRoles"], ["implement", "review"])
        self.assertEqual(first["budgets"]["roleReportedTokenBudgets"], {"implement": 1000, "review": 1000})
        self.assertEqual(len(first["sharedEnvelope"]["sha256"]), 64)
        self.assertFalse(first["sharedEnvelope"]["contentIncluded"])
        self.assertFalse(first["executionPerformed"])
        self.assertFalse(first["persistencePerformed"])
        self.assertEqual(first["adapterCalls"], [])
        self.assertEqual(first["modelCalls"], [])

    def test_plan_rejects_unneeded_or_authority_sensitive_delegation(self) -> None:
        value = proposal()
        value["parallelizable"] = False
        result = delegation.plan(value)
        self.assertEqual(result["decision"], "main-only")
        self.assertIn("task-not-parallelizable", result["reasonCodes"])
        self.assertEqual(result["selectedRoles"], [])

        value = proposal()
        value["intent"] = "nocturne-write"
        result = delegation.plan(value)
        self.assertEqual(result["decision"], "main-only")
        self.assertIn("serialized-or-authority-sensitive-intent", result["reasonCodes"])

    def test_plan_requires_two_candidates_and_budget_for_each(self) -> None:
        value = proposal()
        value["candidates"] = value["candidates"][:1]
        result = delegation.plan(value)
        self.assertEqual(result["decision"], "main-only")
        self.assertIn("insufficient-independent-candidates", result["reasonCodes"])

        value = proposal()
        value["limits"]["totalReportedTokenBudget"] = 255
        result = delegation.plan(value)
        self.assertEqual(result["decision"], "main-only")
        self.assertIn("reported-token-budget-too-small", result["reasonCodes"])

    def test_contract_rejects_unknown_missing_and_wrong_typed_fields(self) -> None:
        for mutate in (
            lambda value: value.update({"extra": True}),
            lambda value: value.pop("intent"),
            lambda value: value.update({"parallelizable": 1}),
            lambda value: value.update({"candidates": "review"}),
            lambda value: value["limits"].update({"extra": 1}),
        ):
            value = proposal()
            mutate(value)
            with self.subTest(value=value), self.assertRaises(ProjectError):
                delegation.plan(value)

    def test_contract_rejects_duplicate_roles_and_multiline_objectives(self) -> None:
        value = proposal()
        value["candidates"][1]["role"] = "implement"
        with self.assertRaisesRegex(ProjectError, "roles must be unique"):
            delegation.plan(value)

        value = proposal()
        value["candidates"][0]["objective"] = "Implement\nthen inspect"
        with self.assertRaisesRegex(ProjectError, "single line"):
            delegation.plan(value)

    def test_contract_rejects_oversized_content_and_candidate_count(self) -> None:
        value = proposal()
        value["sharedContext"] = "x" * 2_001
        with self.assertRaisesRegex(ProjectError, "limits.sharedBytes"):
            delegation.plan(value)

        value = proposal()
        value["candidates"][0]["contextDelta"] = "x" * 4_001
        with self.assertRaisesRegex(ProjectError, "limits.perAgentBytes"):
            delegation.plan(value)

        value = proposal()
        value["candidates"] = [
            {"role": f"role-{index}", "objective": "Review", "contextDelta": "Delta"}
            for index in range(delegation.MAX_CANDIDATES + 1)
        ]
        with self.assertRaisesRegex(ProjectError, "cannot exceed"):
            delegation.plan(value)

    def test_pack_contains_shared_context_once_and_only_selected_role_delta(self) -> None:
        value = proposal()
        result = delegation.pack(value, "implement", 600)
        self.assertEqual(result["role"], "implement")
        self.assertEqual(result["byteCap"], 600)
        self.assertLessEqual(result["byteCount"], result["byteCap"])
        self.assertIn("exact tokens depend", result["budgetContract"])
        self.assertEqual(result["text"].count(value["sharedContext"]), 1)
        self.assertIn(value["candidates"][0]["contextDelta"], result["text"])
        self.assertNotIn(value["candidates"][1]["contextDelta"], result["text"])
        self.assertFalse(result["executionPerformed"])

    def test_pack_rejects_unselected_role_and_budget_above_reported_ceiling(self) -> None:
        value = proposal()
        with self.assertRaisesRegex(ProjectError, "not selected"):
            delegation.pack(value, "test", 500)
        with self.assertRaisesRegex(ProjectError, "reported role ceiling"):
            delegation.pack(value, "implement", 1_001)

    def test_pack_is_utf8_bounded_and_does_not_claim_exact_tokens(self) -> None:
        value = proposal()
        value["sharedContext"] = "共享上下文" * 200
        value["limits"]["sharedBytes"] = 3_000
        value["limits"]["perAgentBytes"] = 700
        result = delegation.pack(value, "implement", 512)
        self.assertEqual(result["byteCap"], 512)
        self.assertLessEqual(len(result["text"].encode("utf-8")), 512)
        self.assertTrue(result["truncated"])
        self.assertIn("## Shared context", result["text"])
        self.assertIn("## Role context delta", result["text"])
        self.assertNotIn("exactToken", result)


if __name__ == "__main__":
    unittest.main()
