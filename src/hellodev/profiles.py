"""Authorization profiles, bounded read leases, and central decisions."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from .project import ProjectError, ProjectPaths, load_config, resolve_root, utc_now, write_json


AuthorizationProfile = Literal["strict", "trusted-local", "autopilot-read"]
AuthorizationMode = Literal["token-required", "lease-allowed", "profile-auto"]

PROFILES = {"strict", "trusted-local", "autopilot-read"}
AUTHORIZATION_MODES = {"token-required", "lease-allowed", "profile-auto"}
POLICY_FIELDS = {
    "authorizationProfile",
    "leaseTtlSeconds",
    "memoryDomains",
    "memoryLimitCeiling",
    "expiresAt",
}
LEASE_STORE_SCHEMA_VERSION = 1
LEASE_FIELDS = {
    "leaseSha256",
    "profile",
    "readClass",
    "rootSha256",
    "capabilityFingerprint",
    "executableSha256",
    "intentRegistrySha256",
    "createdAt",
    "expiresAt",
}
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DOMAIN_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DEFAULT_LEASE_TTL_SECONDS = 300
MIN_LEASE_TTL_SECONDS = 30
MAX_LEASE_TTL_SECONDS = 3600
MAX_AUTOPILOT_SECONDS = 24 * 60 * 60
MAX_MEMORY_DOMAINS = 16
MAX_MEMORY_LIMIT = 20


def _canonical_digest(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ProjectError("authorization identity must be JSON-serializable") from error
    return hashlib.sha256(encoded).hexdigest()


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ProjectError("authorization time must be timezone-aware")
    return current.astimezone(timezone.utc).replace(microsecond=0)


def _timestamp(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise ProjectError(f"{label} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProjectError(f"{label} must be a UTC timestamp") from error
    return parsed.astimezone(timezone.utc)


def default_policy() -> dict[str, Any]:
    return {
        "authorizationProfile": "strict",
        "leaseTtlSeconds": DEFAULT_LEASE_TTL_SECONDS,
        "memoryDomains": [],
        "memoryLimitCeiling": 0,
        "expiresAt": None,
    }


def normalize_policy(
    value: Any,
    *,
    require_active: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != POLICY_FIELDS:
        raise ProjectError("authorization policy has invalid fields")
    profile = value.get("authorizationProfile")
    if not isinstance(profile, str) or profile not in PROFILES:
        raise ProjectError("authorization profile must be strict, trusted-local, or autopilot-read")
    ttl = value.get("leaseTtlSeconds")
    if (
        type(ttl) is not int
        or not MIN_LEASE_TTL_SECONDS <= ttl <= MAX_LEASE_TTL_SECONDS
    ):
        raise ProjectError("authorization lease TTL must be between 30 and 3600 seconds")
    raw_domains = value.get("memoryDomains")
    if (
        not isinstance(raw_domains, list)
        or len(raw_domains) > MAX_MEMORY_DOMAINS
        or not all(isinstance(domain, str) and DOMAIN_PATTERN.fullmatch(domain) for domain in raw_domains)
    ):
        raise ProjectError("memory domains must be a bounded lowercase allowlist")
    if len(raw_domains) != len(set(raw_domains)):
        raise ProjectError("memory domain allowlist cannot contain duplicates")
    domains = sorted(raw_domains)
    limit = value.get("memoryLimitCeiling")
    if type(limit) is not int or not 0 <= limit <= MAX_MEMORY_LIMIT:
        raise ProjectError("memory limit ceiling must be between 0 and 20")
    expires_at = value.get("expiresAt")
    expiry: datetime | None = None
    if expires_at is not None:
        expiry = _parse_timestamp(expires_at, "authorization profile expiry")
    if profile in {"strict", "trusted-local"}:
        if domains or limit != 0 or expires_at is not None:
            raise ProjectError(f"{profile} cannot configure automatic memory reads or expiry")
    else:
        if not domains:
            raise ProjectError("autopilot-read requires at least one allowed memory domain")
        if limit < 1:
            raise ProjectError("autopilot-read requires a positive memory limit ceiling")
        if expiry is None:
            raise ProjectError("autopilot-read requires an explicit expiry")
        if require_active:
            current = _utc(now)
            if expiry <= current:
                raise ProjectError("autopilot-read expiry must be in the future")
            if expiry > current + timedelta(seconds=MAX_AUTOPILOT_SECONDS):
                raise ProjectError("autopilot-read expiry cannot exceed 24 hours")
    return {
        "authorizationProfile": profile,
        "leaseTtlSeconds": ttl,
        "memoryDomains": domains,
        "memoryLimitCeiling": limit,
        "expiresAt": expires_at,
    }


def build_policy(
    profile: AuthorizationProfile,
    *,
    lease_ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    memory_domains: list[str] | tuple[str, ...] = (),
    memory_limit_ceiling: int = 0,
    expires_at: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    return normalize_policy(
        {
            "authorizationProfile": profile,
            "leaseTtlSeconds": lease_ttl_seconds,
            "memoryDomains": list(memory_domains),
            "memoryLimitCeiling": memory_limit_ceiling,
            "expiresAt": expires_at,
        },
        require_active=profile == "autopilot-read",
        now=now,
    )


def policy_from_config(config: dict[str, Any]) -> dict[str, Any]:
    if "authorizationProfile" not in config and "authorizationPolicy" not in config:
        return default_policy()
    profile = config.get("authorizationProfile")
    raw_policy = config.get("authorizationPolicy")
    if not isinstance(raw_policy, dict):
        raise ProjectError("HelloDev config authorizationPolicy is invalid")
    return normalize_policy(
        {
            "authorizationProfile": profile,
            "leaseTtlSeconds": raw_policy.get("leaseTtlSeconds"),
            "memoryDomains": raw_policy.get("memoryDomains"),
            "memoryLimitCeiling": raw_policy.get("memoryLimitCeiling"),
            "expiresAt": raw_policy.get("expiresAt"),
        }
    )


def config_fields(policy: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_policy(policy)
    return {
        "authorizationProfile": normalized["authorizationProfile"],
        "authorizationPolicy": {
            "leaseTtlSeconds": normalized["leaseTtlSeconds"],
            "memoryDomains": normalized["memoryDomains"],
            "memoryLimitCeiling": normalized["memoryLimitCeiling"],
            "expiresAt": normalized["expiresAt"],
        },
    }


def current_policy(root: Path) -> dict[str, Any]:
    return policy_from_config(load_config(root))


def policy_change_payload(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    project_root = resolve_root(root)
    normalized = normalize_policy(policy, require_active=True)
    return {
        "operation": "authorization-policy.change",
        "rootSha256": _canonical_digest(str(project_root)),
        "currentPolicySha256": _canonical_digest(current_policy(project_root)),
        "proposedPolicy": normalized,
    }


def _apply_policy(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    project_root = resolve_root(root)
    normalized = normalize_policy(policy, require_active=True)
    config = load_config(project_root)
    _read_lease_store(project_root)
    config.update(config_fields(normalized))
    write_json(ProjectPaths(project_root).config_file, config)
    _clear_leases(project_root)
    return normalized


def _lease_path(root: Path) -> Path:
    return ProjectPaths(root).authorization_leases_file


def _validate_lease(lease: Any) -> dict[str, Any]:
    if not isinstance(lease, dict) or set(lease) != LEASE_FIELDS:
        raise ProjectError("invalid HelloDev authorization lease fields")
    for field in (
        "leaseSha256",
        "rootSha256",
        "capabilityFingerprint",
        "executableSha256",
        "intentRegistrySha256",
    ):
        digest = lease.get(field)
        if not isinstance(digest, str) or DIGEST_PATTERN.fullmatch(digest) is None:
            raise ProjectError(f"authorization lease {field} is invalid")
    if lease.get("profile") != "trusted-local" or lease.get("readClass") != "trellis-read":
        raise ProjectError("authorization lease profile or read class is invalid")
    created = _parse_timestamp(lease.get("createdAt"), "authorization lease createdAt")
    expires = _parse_timestamp(lease.get("expiresAt"), "authorization lease expiresAt")
    if expires <= created or expires > created + timedelta(seconds=MAX_LEASE_TTL_SECONDS):
        raise ProjectError("authorization lease lifetime is invalid")
    return lease


def _read_lease_store(root: Path) -> dict[str, Any]:
    load_config(root)
    path = _lease_path(root)
    if not path.exists():
        return {"schemaVersion": LEASE_STORE_SCHEMA_VERSION, "leases": []}
    if path.is_symlink():
        raise ProjectError("refusing symlinked HelloDev authorization lease store")
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid HelloDev authorization lease store: {error}") from error
    if (
        not isinstance(store, dict)
        or set(store) != {"schemaVersion", "leases"}
        or type(store.get("schemaVersion")) is not int
        or store["schemaVersion"] != LEASE_STORE_SCHEMA_VERSION
        or not isinstance(store.get("leases"), list)
    ):
        raise ProjectError("invalid HelloDev authorization lease store schema")
    leases = [_validate_lease(lease) for lease in store["leases"]]
    lease_ids = [lease["leaseSha256"] for lease in leases]
    if len(lease_ids) != len(set(lease_ids)):
        raise ProjectError("duplicate HelloDev authorization lease")
    return {"schemaVersion": LEASE_STORE_SCHEMA_VERSION, "leases": leases}


def _write_lease_store(root: Path, store: dict[str, Any]) -> None:
    path = _lease_path(root)
    if path.is_symlink():
        raise ProjectError("refusing symlinked HelloDev authorization lease store")
    write_json(path, store)


def _clear_leases(root: Path) -> None:
    path = _lease_path(root)
    if path.exists() and path.is_symlink():
        raise ProjectError("refusing symlinked HelloDev authorization lease store")
    if path.exists():
        _write_lease_store(root, {"schemaVersion": LEASE_STORE_SCHEMA_VERSION, "leases": []})


def _actual_capability_fingerprint(root: Path) -> str:
    from . import capabilities

    return capabilities.fingerprint(root)


def _binding(
    root: Path,
    capability_fingerprint: str,
    executable_identity: Any,
    intent_registry: Any,
    read_class: str,
) -> dict[str, str]:
    if read_class != "trellis-read":
        raise ProjectError("trusted-local leases support only the Trellis read class")
    return _profile_binding(
        root,
        capability_fingerprint,
        executable_identity,
        intent_registry,
        read_class,
    )


def _profile_binding(
    root: Path,
    capability_fingerprint: str,
    executable_identity: Any,
    intent_registry: Any,
    read_class: str,
) -> dict[str, str]:
    project_root = resolve_root(root)
    if not isinstance(capability_fingerprint, str) or DIGEST_PATTERN.fullmatch(capability_fingerprint) is None:
        raise ProjectError("capability fingerprint must be a lowercase SHA-256 digest")
    if capability_fingerprint != _actual_capability_fingerprint(project_root):
        raise ProjectError("capability fingerprint is stale or does not match this project")
    if executable_identity is None or intent_registry is None:
        raise ProjectError("read authorization requires executable and intent registry identities")
    return {
        "rootSha256": _canonical_digest(str(project_root)),
        "capabilityFingerprint": capability_fingerprint,
        "executableSha256": _canonical_digest(executable_identity),
        "intentRegistrySha256": _canonical_digest(intent_registry),
        "readClass": read_class,
    }


def grant_read_lease(
    root: Path,
    *,
    capability_fingerprint: str,
    executable_identity: Any,
    intent_registry: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    project_root = resolve_root(root)
    policy = current_policy(project_root)
    if policy["authorizationProfile"] != "trusted-local":
        raise ProjectError("read leases can be granted only under trusted-local")
    binding = _binding(
        project_root,
        capability_fingerprint,
        executable_identity,
        intent_registry,
        "trellis-read",
    )
    created = _utc(now)
    expires = created + timedelta(seconds=policy["leaseTtlSeconds"])
    lease_sha256 = _canonical_digest(
        {**binding, "createdAt": _timestamp(created), "nonce": secrets.token_hex(32)}
    )
    lease = {
        "leaseSha256": lease_sha256,
        "profile": "trusted-local",
        **binding,
        "createdAt": _timestamp(created),
        "expiresAt": _timestamp(expires),
    }
    _validate_lease(lease)
    store = _read_lease_store(project_root)
    store["leases"] = [*store["leases"][-127:], lease]
    _write_lease_store(project_root, store)
    return dict(lease)


def _matching_lease(
    root: Path,
    binding: dict[str, str],
    now: datetime,
) -> dict[str, Any] | None:
    for lease in reversed(_read_lease_store(root)["leases"]):
        if _parse_timestamp(lease["expiresAt"], "authorization lease expiresAt") <= now:
            continue
        if all(lease[field] == binding[field] for field in binding):
            return lease
    return None


def _decision(
    mode: AuthorizationMode,
    profile: str,
    reason: str,
    *,
    lease_sha256: str | None = None,
    binding_sha256: str | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "decision": mode,
        "authorizationMode": mode,
        "profileUsed": profile,
        "reason": reason,
    }
    if lease_sha256 is not None:
        value["leaseSha256"] = lease_sha256
    if binding_sha256 is not None:
        value["bindingSha256"] = binding_sha256
    return value


def authorization_decision(
    root: Path,
    *,
    adapter: str,
    risk: str,
    read_class: str,
    capability_fingerprint: str | None = None,
    executable_identity: Any = None,
    intent_registry: Any = None,
    memory_domain: str | None = None,
    memory_limit: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    project_root = resolve_root(root)
    policy = current_policy(project_root)
    profile = policy["authorizationProfile"]
    if risk not in {"read", "write", "policy"}:
        raise ProjectError("authorization risk must be read, write, or policy")
    if risk != "read" or read_class in {
        "trellis-write",
        "nocturne-write",
        "external-write",
        "policy-write",
    }:
        return _decision(
            "token-required",
            profile,
            "external and policy writes always require an exact one-time token",
        )
    if profile == "strict":
        return _decision("token-required", profile, "strict requires a token for every external read")
    current = _utc(now)
    if profile == "trusted-local":
        if adapter != "trellis" or read_class != "trellis-read":
            return _decision(
                "token-required",
                profile,
                "trusted-local relaxes only leased Trellis reads",
            )
        if capability_fingerprint is None or executable_identity is None or intent_registry is None:
            return _decision(
                "token-required",
                profile,
                "trusted-local requires a complete fingerprint binding and active lease",
            )
        try:
            binding = _binding(
                project_root,
                capability_fingerprint,
                executable_identity,
                intent_registry,
                read_class,
            )
        except ProjectError:
            return _decision(
                "token-required",
                profile,
                "trusted-local binding is incomplete or stale",
            )
        lease = _matching_lease(project_root, binding, current)
        if lease is None:
            return _decision("token-required", profile, "no matching active Trellis read lease")
        return _decision(
            "lease-allowed",
            profile,
            "matching fingerprint-bound Trellis read lease",
            lease_sha256=lease["leaseSha256"],
        )
    expiry = _parse_timestamp(policy["expiresAt"], "authorization profile expiry")
    if expiry <= current:
        return _decision("token-required", profile, "autopilot-read policy has expired")
    if expiry > current + timedelta(seconds=MAX_AUTOPILOT_SECONDS):
        return _decision("token-required", profile, "autopilot-read expiry exceeds the bounded window")
    if adapter == "trellis" and read_class == "trellis-read":
        if capability_fingerprint is None or executable_identity is None or intent_registry is None:
            return _decision(
                "token-required",
                profile,
                "autopilot Trellis reads require a complete current binding",
            )
        try:
            binding = _binding(
                project_root,
                capability_fingerprint,
                executable_identity,
                intent_registry,
                read_class,
            )
        except ProjectError:
            return _decision("token-required", profile, "autopilot Trellis binding is stale")
        return _decision(
            "profile-auto",
            profile,
            "active autopilot-read Trellis policy",
            binding_sha256=_canonical_digest(binding),
        )
    if adapter == "nocturne" and read_class == "nocturne-search":
        if not isinstance(memory_domain, str) or memory_domain not in policy["memoryDomains"]:
            return _decision("token-required", profile, "memory domain is not allowlisted")
        if type(memory_limit) is not int or not 1 <= memory_limit <= policy["memoryLimitCeiling"]:
            return _decision("token-required", profile, "memory result limit exceeds policy")
        if capability_fingerprint is None or executable_identity is None or intent_registry is None:
            return _decision("token-required", profile, "autopilot memory binding is incomplete")
        try:
            binding = _profile_binding(
                project_root,
                capability_fingerprint,
                executable_identity,
                intent_registry,
                read_class,
            )
        except ProjectError:
            return _decision("token-required", profile, "autopilot memory binding is stale")
        return _decision(
            "profile-auto",
            profile,
            "allowlisted narrow autopilot memory search",
            binding_sha256=_canonical_digest(binding),
        )
    return _decision("token-required", profile, "autopilot-read does not cover this read class")
