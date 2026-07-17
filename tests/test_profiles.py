from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import approval, capabilities, profiles, receipts
from hellodev.project import ProjectError, ProjectPaths, init_project, load_config, write_json


class AuthorizationProfileTests(unittest.TestCase):
    def _root(self, directory: str) -> Path:
        root = Path(directory)
        init_project(root)
        return root

    def _apply(self, root: Path, policy: dict) -> dict:
        prepared = approval.prepare_policy_change(root, policy)
        self.assertTrue(prepared["approval"].startswith("APPROVE-POLICY:"))
        return approval.consume_policy_change(root, policy, prepared["approval"])

    def test_new_and_legacy_configs_default_to_strict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            config = load_config(root)
            self.assertEqual(config["authorizationProfile"], "strict")
            self.assertEqual(config["authorizationPolicy"]["leaseTtlSeconds"], 300)

            path = ProjectPaths(root).config_file
            legacy = json.loads(path.read_text(encoding="utf-8"))
            legacy.pop("authorizationProfile")
            legacy.pop("authorizationPolicy")
            write_json(path, legacy)
            migrated = load_config(root)
            self.assertEqual(migrated["authorizationProfile"], "strict")
            self.assertEqual(migrated["authorizationPolicy"]["memoryDomains"], [])
            self.assertNotIn("authorizationProfile", json.loads(path.read_text(encoding="utf-8")))

    def test_policy_validation_is_narrow_and_expiring(self) -> None:
        now = datetime(2026, 7, 16, 1, 0, 0, tzinfo=timezone.utc)
        expiry = (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        policy = profiles.build_policy(
            "autopilot-read",
            lease_ttl_seconds=60,
            memory_domains=["notes", "preferences"],
            memory_limit_ceiling=5,
            expires_at=expiry,
            now=now,
        )
        self.assertEqual(policy["memoryDomains"], ["notes", "preferences"])
        with self.assertRaisesRegex(ProjectError, "allowed memory domain"):
            profiles.build_policy(
                "autopilot-read",
                memory_domains=[],
                memory_limit_ceiling=5,
                expires_at=expiry,
                now=now,
            )
        with self.assertRaisesRegex(ProjectError, "24 hours"):
            profiles.build_policy(
                "autopilot-read",
                memory_domains=["notes"],
                memory_limit_ceiling=5,
                expires_at=(now + timedelta(days=2)).isoformat().replace("+00:00", "Z"),
                now=now,
            )
        with self.assertRaisesRegex(ProjectError, "cannot configure"):
            profiles.build_policy(
                "trusted-local",
                memory_domains=["notes"],
                memory_limit_ceiling=1,
            )

    def test_policy_change_uses_distinct_single_use_token_and_policy_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            policy = profiles.build_policy("trusted-local", lease_ttl_seconds=60)
            prepared = approval.prepare_policy_change(root, policy)
            self.assertTrue(prepared["approval"].startswith("APPROVE-POLICY:"))

            with self.assertRaisesRegex(ProjectError, "does not match"):
                approval.consume_policy_change(
                    root,
                    profiles.build_policy("strict"),
                    prepared["approval"],
                )
            self.assertEqual(load_config(root)["authorizationProfile"], "strict")

            changed = approval.consume_policy_change(root, policy, prepared["approval"])
            self.assertEqual(changed["policy"]["authorizationProfile"], "trusted-local")
            self.assertEqual(load_config(root)["authorizationProfile"], "trusted-local")
            receipt = changed["receipt"]
            self.assertEqual(receipt["kind"], "policy")
            self.assertEqual(receipt["adapter"], "hellodev")
            self.assertEqual(receipt["profileUsed"], "strict")
            self.assertEqual(receipt["authorizationMode"], "token-required")
            self.assertEqual(json.loads(ProjectPaths(root).receipts_file.read_text(encoding="utf-8"))["schemaVersion"], 3)
            with self.assertRaisesRegex(ProjectError, "already consumed"):
                approval.consume_policy_change(root, policy, prepared["approval"])

    def test_strict_and_all_profile_writes_always_require_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            strict_read = profiles.authorization_decision(
                root,
                adapter="trellis",
                risk="read",
                read_class="trellis-read",
            )
            self.assertEqual(strict_read["decision"], "token-required")
            for profile_name in ("trusted-local", "autopilot-read"):
                if profile_name == "trusted-local":
                    policy = profiles.build_policy(profile_name)
                else:
                    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                    policy = profiles.build_policy(
                        profile_name,
                        memory_domains=["notes"],
                        memory_limit_ceiling=3,
                        expires_at=expiry,
                    )
                self._apply(root, policy)
                for risk, read_class in (("write", "trellis-write"), ("policy", "policy-write")):
                    decision = profiles.authorization_decision(
                        root,
                        adapter="trellis" if risk == "write" else "hellodev",
                        risk=risk,
                        read_class=read_class,
                    )
                    self.assertEqual(decision["decision"], "token-required")

    def test_trusted_local_lease_is_fingerprint_bound_and_expires(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            self._apply(root, profiles.build_policy("trusted-local", lease_ttl_seconds=30))
            fingerprint = capabilities.fingerprint(root)
            executable = {"path": "C:/tools/python.exe", "sha256": "1" * 64}
            registry = {"task-list": {"risk": "read"}}
            created = datetime(2026, 7, 16, 2, 0, 0, tzinfo=timezone.utc)
            lease = profiles.grant_read_lease(
                root,
                capability_fingerprint=fingerprint,
                executable_identity=executable,
                intent_registry=registry,
                now=created,
            )
            allowed = profiles.authorization_decision(
                root,
                adapter="trellis",
                risk="read",
                read_class="trellis-read",
                capability_fingerprint=fingerprint,
                executable_identity=executable,
                intent_registry=registry,
                now=created + timedelta(seconds=15),
            )
            self.assertEqual(allowed["decision"], "lease-allowed")
            self.assertEqual(allowed["leaseSha256"], lease["leaseSha256"])
            self.assertNotIn("nonce", ProjectPaths(root).authorization_leases_file.read_text(encoding="utf-8"))

            expired = profiles.authorization_decision(
                root,
                adapter="trellis",
                risk="read",
                read_class="trellis-read",
                capability_fingerprint=fingerprint,
                executable_identity=executable,
                intent_registry=registry,
                now=created + timedelta(seconds=31),
            )
            self.assertEqual(expired["decision"], "token-required")
            changed_registry = profiles.authorization_decision(
                root,
                adapter="trellis",
                risk="read",
                read_class="trellis-read",
                capability_fingerprint=fingerprint,
                executable_identity=executable,
                intent_registry={"task-list": {"risk": "write"}},
                now=created + timedelta(seconds=15),
            )
            self.assertEqual(changed_registry["decision"], "token-required")
            (root / "AGENTS.md").write_text("changed authority\n", encoding="utf-8")
            stale_capability = profiles.authorization_decision(
                root,
                adapter="trellis",
                risk="read",
                read_class="trellis-read",
                capability_fingerprint=fingerprint,
                executable_identity=executable,
                intent_registry=registry,
                now=created + timedelta(seconds=15),
            )
            self.assertEqual(stale_capability["decision"], "token-required")

    def test_autopilot_allows_only_bound_trellis_and_narrow_allowlisted_search(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            now = datetime.now(timezone.utc).replace(microsecond=0)
            policy = profiles.build_policy(
                "autopilot-read",
                memory_domains=["notes"],
                memory_limit_ceiling=4,
                expires_at=(now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            )
            self._apply(root, policy)
            fingerprint = capabilities.fingerprint(root)
            identity = {"path": "tool", "sha256": "2" * 64}
            registry = {"task-list": "read", "search_memory": "read"}
            trellis = profiles.authorization_decision(
                root,
                adapter="trellis",
                risk="read",
                read_class="trellis-read",
                capability_fingerprint=fingerprint,
                executable_identity=identity,
                intent_registry=registry,
                now=now,
            )
            self.assertEqual(trellis["decision"], "profile-auto")
            search = profiles.authorization_decision(
                root,
                adapter="nocturne",
                risk="read",
                read_class="nocturne-search",
                capability_fingerprint=fingerprint,
                executable_identity=identity,
                intent_registry=registry,
                memory_domain="notes",
                memory_limit=4,
                now=now,
            )
            self.assertEqual(search["decision"], "profile-auto")
            for domain, limit in (("private", 4), ("notes", 5)):
                denied = profiles.authorization_decision(
                    root,
                    adapter="nocturne",
                    risk="read",
                    read_class="nocturne-search",
                    capability_fingerprint=fingerprint,
                    executable_identity=identity,
                    intent_registry=registry,
                    memory_domain=domain,
                    memory_limit=limit,
                    now=now,
                )
                self.assertEqual(denied["decision"], "token-required")
            other_read = profiles.authorization_decision(
                root,
                adapter="nocturne",
                risk="read",
                read_class="nocturne-read",
                capability_fingerprint=fingerprint,
                executable_identity=identity,
                intent_registry=registry,
                now=now,
            )
            self.assertEqual(other_read["decision"], "token-required")

    def test_lease_store_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = self._root(directory)
            self._apply(root, profiles.build_policy("trusted-local"))
            target = Path(outside) / "leases.json"
            target.write_text('{"schemaVersion":1,"leases":[]}', encoding="utf-8")
            path = ProjectPaths(root).authorization_leases_file
            try:
                os.symlink(target, path)
            except OSError as error:
                original_is_symlink = Path.is_symlink
                with patch.object(
                    Path,
                    "is_symlink",
                    lambda candidate: candidate == path or original_is_symlink(candidate),
                ):
                    with self.assertRaisesRegex(ProjectError, "symlinked"):
                        profiles.grant_read_lease(
                            root,
                            capability_fingerprint=capabilities.fingerprint(root),
                            executable_identity="tool",
                            intent_registry={},
                        )
                self.assertIsInstance(error, OSError)
            else:
                with self.assertRaisesRegex(ProjectError, "symlinked"):
                    profiles.grant_read_lease(
                        root,
                        capability_fingerprint=capabilities.fingerprint(root),
                        executable_identity="tool",
                        intent_registry={},
                    )


class ReceiptV3Tests(unittest.TestCase):
    def _root(self, directory: str) -> Path:
        root = Path(directory)
        init_project(root)
        return root

    def test_schema_v1_and_v2_migrate_to_v3_strict_audit_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            current = receipts.record(root, "trellis", "status", "read", {}, {}, True)
            path = ProjectPaths(root).receipts_file
            v2 = {
                key: value
                for key, value in current.items()
                if key not in {"profileUsed", "authorizationMode"}
            }
            write_json(path, {"schemaVersion": 2, "receipts": [v2]})
            migrated_v2 = receipts.list_receipts(root)
            self.assertEqual(migrated_v2[0]["profileUsed"], "strict")
            self.assertEqual(migrated_v2[0]["authorizationMode"], "token-required")

            v1 = {key: value for key, value in v2.items() if key != "kind"}
            write_json(path, {"schemaVersion": 1, "receipts": [v1]})
            migrated_v1 = receipts.list_receipts(root)
            self.assertEqual(migrated_v1[0]["kind"], "command")
            receipts.record(root, "trellis", "status", "read", {}, {}, True)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schemaVersion"], 3)

    def test_receipt_authorization_audit_is_strict_and_privacy_preserving(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            lease_sha256 = "a" * 64
            receipt = receipts.record(
                root,
                "trellis",
                "intent/task-list",
                "read",
                {"secret": "do not store"},
                {"private": "output"},
                True,
                profile_used="trusted-local",
                authorization_mode="lease-allowed",
                lease_sha256=lease_sha256,
            )
            self.assertEqual(receipt["leaseSha256"], lease_sha256)
            raw = ProjectPaths(root).receipts_file.read_text(encoding="utf-8")
            self.assertNotIn("do not store", raw)
            self.assertNotIn("output", raw)
            with self.assertRaisesRegex(ProjectError, "leaseSha256"):
                receipts.record(
                    root,
                    "trellis",
                    "intent/task-list",
                    "read",
                    {},
                    {},
                    True,
                    profile_used="trusted-local",
                    authorization_mode="lease-allowed",
                )
            with self.assertRaisesRegex(ProjectError, "profile-auto"):
                receipts.record(
                    root,
                    "trellis",
                    "intent/task-list",
                    "read",
                    {},
                    {},
                    True,
                    profile_used="strict",
                    authorization_mode="profile-auto",
                )


if __name__ == "__main__":
    unittest.main()
