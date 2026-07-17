"""Typed Python SDK for the versioned HelloDev Host protocol."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Iterable, TypedDict, cast

from . import host_bridge
from .project import ProjectError, resolve_root


__all__ = [
    "HostClient",
    "HostRequest",
    "HostEnvelope",
    "HostResult",
    "HostPending",
    "HostReconciliation",
    "HostSdkError",
    "HostProtocolError",
    "HostEnvelopeError",
    "HostEnvelopeStaleError",
]


class HostSdkError(ProjectError):
    """Base error raised by the public typed Host SDK."""


class HostProtocolError(HostSdkError):
    """Raised when no compatible Host protocol can be negotiated."""


class HostEnvelopeError(HostSdkError):
    """Raised when HostEnvelope data is invalid or conflicts with local state."""


class HostEnvelopeStaleError(HostEnvelopeError):
    """Raised when a retained HostEnvelope no longer matches current bindings."""


class HostPending(TypedDict):
    schemaVersion: int
    id: str
    state: str
    intent: str
    workItemId: str | None
    protocolVersion: str
    createdAt: str
    expiresAt: str
    updatedAt: str
    completionId: str | None
    expired: bool
    externalHostContinuationRequired: bool
    inspectionCommand: str
    abandonCommand: str | None
    recoveryCommand: str | None
    contextPersisted: bool
    executionPerformed: bool
    persistencePerformed: bool


class HostReconciliation(TypedDict, total=False):
    schemaVersion: int
    state: str
    envelopeId: str
    completionId: str | None
    envelopeMatched: bool
    expired: bool
    externalHostContinuationRequired: bool
    abandonCommand: str | None
    persistencePerformed: bool


def _sdk_error(error: ProjectError, *, protocol: bool = False) -> HostSdkError:
    if protocol or "protocol" in str(error).lower() or "compatible" in str(error).lower():
        return HostProtocolError(str(error))
    if "stale" in str(error).lower() or "bindings" in str(error).lower():
        return HostEnvelopeStaleError(str(error))
    return HostEnvelopeError(str(error))


@dataclass(frozen=True)
class HostRequest:
    intent: str
    level: str | None = None
    total_token_ceiling: int | None = None
    subagent_token_ceiling: int | None = None
    max_subagents: int = 0
    work_item_id: str | None = None
    delegation_payload: dict[str, Any] | None = None
    ttl_seconds: int = 3_600
    allow_l2: bool = False


@dataclass(frozen=True)
class HostResult:
    outcome: str
    retry_count: int = 0
    retrieval_mode: str = "none"
    delegation_mode: str = "none"
    total_tokens: int | None = None
    subagent_tokens: int | None = None
    subagent_count: int = 0

    def to_wire(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "retryCount": self.retry_count,
            "retrievalMode": self.retrieval_mode,
            "delegationMode": self.delegation_mode,
            "totalTokens": self.total_tokens,
            "subagentTokens": self.subagent_tokens,
            "subagentCount": self.subagent_count,
        }


@dataclass(frozen=True)
class HostEnvelope:
    value: dict[str, Any]
    protocol_version: str

    @classmethod
    def from_wire(cls, value: dict[str, Any], protocol_version: str) -> "HostEnvelope":
        try:
            host_bridge.protocol_info([protocol_version])
            validated = host_bridge._validate_envelope(value)
        except ProjectError as error:
            raise _sdk_error(error) from error
        return cls(json.loads(json.dumps(validated)), protocol_version)

    @property
    def id(self) -> str:
        return self.value["id"]

    @property
    def sha256(self) -> str:
        return self.value["envelopeSha256"]

    def to_wire(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.value))


class HostClient:
    """In-process SDK; the host owns execution and HelloDev owns validation/state."""

    def __init__(self, root: str | Path, supported_versions: Iterable[str] = (host_bridge.HOST_PROTOCOL_VERSION,)) -> None:
        self.root = resolve_root(root)
        requested = list(supported_versions)
        try:
            self.protocol = host_bridge.protocol_info(requested)
        except ProjectError as error:
            raise _sdk_error(error, protocol=True) from error
        self.protocol_version = self.protocol["selectedVersion"]

    def prepare(self, request: HostRequest) -> HostEnvelope:
        if not isinstance(request, HostRequest):
            raise HostEnvelopeError("HostClient.prepare requires HostRequest")
        try:
            value = host_bridge.prepare(
                self.root,
                request.intent,
                request.level,
                request.total_token_ceiling,
                request.subagent_token_ceiling,
                request.max_subagents,
                request.work_item_id,
                request.delegation_payload,
                request.ttl_seconds,
                request.allow_l2,
            )
        except ProjectError as error:
            raise _sdk_error(error) from error
        return HostEnvelope.from_wire(value, self.protocol_version)

    def complete(self, envelope: HostEnvelope, result: HostResult) -> dict[str, Any]:
        if not isinstance(envelope, HostEnvelope) or not isinstance(result, HostResult):
            raise HostEnvelopeError("HostClient.complete requires HostEnvelope and HostResult")
        if envelope.protocol_version != self.protocol_version:
            raise HostProtocolError("HostEnvelope protocol version is incompatible with this HostClient")
        try:
            return host_bridge.complete(self.root, envelope.to_wire(), result.to_wire())
        except ProjectError as error:
            raise _sdk_error(error) from error

    def status(self) -> dict[str, Any]:
        return {**host_bridge.status(self.root), "protocol": self.protocol}

    def pending(self) -> list[HostPending]:
        try:
            return cast(list[HostPending], host_bridge.pending_envelopes(self.root))
        except ProjectError as error:
            raise _sdk_error(error) from error

    def pending_one(self, envelope_id: str) -> HostPending:
        try:
            return cast(HostPending, host_bridge.envelope_status(self.root, envelope_id))
        except ProjectError as error:
            raise _sdk_error(error) from error

    def reconcile(self, envelope: HostEnvelope) -> HostReconciliation:
        if not isinstance(envelope, HostEnvelope):
            raise HostEnvelopeError("HostClient.reconcile requires HostEnvelope")
        if envelope.protocol_version != self.protocol_version:
            raise HostProtocolError("HostEnvelope protocol version is incompatible with this HostClient")
        try:
            return cast(HostReconciliation, host_bridge.reconcile(self.root, envelope.to_wire()))
        except ProjectError as error:
            raise _sdk_error(error) from error

    def abandon(self, envelope_id: str) -> dict[str, Any]:
        try:
            return host_bridge.abandon(self.root, envelope_id)
        except ProjectError as error:
            raise _sdk_error(error) from error

    @staticmethod
    def schemas() -> dict[str, dict[str, Any]]:
        directory = files("hellodev").joinpath("schemas")
        names = {
            "hostEnvelope": "host-envelope-v1.schema.json",
            "hostResult": "host-result-v1.schema.json",
            "hostProtocol": "host-protocol-v1.schema.json",
        }
        return {key: json.loads(directory.joinpath(name).read_text(encoding="utf-8")) for key, name in names.items()}


def sdk_info() -> dict[str, Any]:
    schemas = HostClient.schemas()
    return {
        "schemaVersion": 1,
        "sdk": "hellodev.host_sdk.HostClient",
        "protocol": host_bridge.protocol_info(),
        "types": [HostRequest.__name__, HostEnvelope.__name__, HostResult.__name__, HostPending.__name__],
        "exceptions": [
            HostSdkError.__name__, HostProtocolError.__name__, HostEnvelopeError.__name__, HostEnvelopeStaleError.__name__,
        ],
        "jsonSchemas": {key: value["$id"] for key, value in schemas.items()},
        "pep561Typed": True,
        "recoveryMethods": ["pending", "pending_one", "reconcile", "abandon"],
        "manualEnvelopeJsonRequired": False,
        "executionPerformed": False,
    }
