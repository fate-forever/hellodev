"""Deterministic criterion and progressive-gate projection for exact requirements."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from . import acceptance, trellis_execution, verification
from .project import ProjectError, resolve_root


MAX_CRITERIA = 64
MAX_SUMMARY = 180

_LAYERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("privacy", ("privacy", "consent", "authoriz", "aggregate", "monitor", "隐私", "授权", "汇总", "监控")),
    ("persistence", ("database", "supabase", "migration", "persist", "local backend", "数据库", "迁移", "持久", "本地后端")),
    ("experience", ("ui", "view", "screen", "button", "learner", "supporter", "页面", "按钮", "学习者", "支持者")),
    ("quality", ("test", "typecheck", "build", "e2e", "测试", "构建", "验收")),
)


def _summary(value: str) -> str:
    selected = " ".join(value.split())
    return selected if len(selected) <= MAX_SUMMARY else selected[: MAX_SUMMARY - 3].rstrip() + "..."


def _criterion_lines(text: str) -> list[str]:
    values: list[str] = []
    section: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = line.lstrip("#").strip()
        if line.startswith("#") or line.endswith((":", "：")):
            section = heading.rstrip(":：").strip() or None
            continue
        selected = re.sub(r"^(?:[-*+]\s+|\d+[.)、]\s*)", "", line).strip()
        if not selected:
            continue
        value = f"{section}: {selected}" if section else selected
        values.append(_summary(value))
        if len(values) >= MAX_CRITERIA:
            break
    return values


def _layer(summary: str) -> str:
    lowered = summary.lower()
    return next((name for name, terms in _LAYERS if any(term in lowered for term in terms)), "domain")


def _stage(layer: str) -> str:
    return {
        "domain": "contract",
        "privacy": "contract",
        "persistence": "integration",
        "experience": "experience",
        "quality": "closure",
    }[layer]


def _criterion_ids_for_step(criteria: list[dict[str, Any]], kind: str) -> list[str]:
    allowed = {
        "typecheck": {"domain", "privacy", "persistence", "experience"},
        "test": {"domain", "privacy"},
        "integration": {"persistence", "privacy"},
        "build": {"experience", "quality"},
        "e2e": {"experience", "privacy"},
    }.get(kind, {item["layer"] for item in criteria})
    selected = [item["id"] for item in criteria if item["layer"] in allowed]
    return selected or [item["id"] for item in criteria]


def build(root: str | Path) -> dict[str, Any]:
    """Compile exact requirements into a bounded, read-only execution plan."""

    resolved = resolve_root(root)
    contract = acceptance.current(resolved)
    if contract is None or contract["requirementsSource"]["state"] != "bound":
        return {
            "schemaVersion": 1,
            "state": "not-applicable",
            "required": False,
            "criteria": [],
            "gates": [],
            "executionPerformed": False,
            "persistencePerformed": False,
        }
    try:
        text = acceptance.requirements_text(resolved)
    except ProjectError:
        return {
            "schemaVersion": 1,
            "state": "requirements-invalid",
            "required": True,
            "requirementsSha256": contract["requirementsSource"]["sha256"],
            "criteria": [],
            "gates": [],
            "criterionCount": 0,
            "gateCount": 0,
            "allCriteriaMapped": False,
            "sourceTrust": "requirements-integrity-failed",
            "executionPerformed": False,
            "persistencePerformed": False,
            "verificationEvidenceCreated": False,
        }
    summaries = _criterion_lines(text)
    criteria = []
    for index, summary in enumerate(summaries, start=1):
        layer = _layer(summary)
        criteria.append(
            {
                "id": f"AC-{index:03d}",
                "summary": summary,
                "summarySha256": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
                "layer": layer,
                "stage": _stage(layer),
            }
        )
    plan = trellis_execution.verification_plan(resolved, "strict", contract["acceptance"])
    gates = []
    for index, step in enumerate(plan["steps"], start=1):
        evidence = verification.inspect(resolved, step["level"], step["command"], step["scope"])
        gates.append(
            {
                "id": f"GATE-{index:02d}",
                "kind": step["kind"],
                "stage": {
                    "typecheck": "contract",
                    "test": "contract",
                    "integration": "integration",
                    "build": "closure",
                    "e2e": "closure",
                }.get(step["kind"], "closure"),
                "command": step["command"],
                "hostCommand": verification.executable_command(step["command"]),
                "level": step["level"],
                "scope": step["scope"],
                "criterionIds": _criterion_ids_for_step(criteria, step["kind"]),
                "verificationState": evidence["state"],
                "runRequired": evidence["runRequired"],
            }
        )
    identity = {
        "requirementsSha256": contract["requirementsSource"]["sha256"],
        "criteria": [{"id": item["id"], "summarySha256": item["summarySha256"], "layer": item["layer"]} for item in criteria],
        "gates": [{key: item[key] for key in ("id", "kind", "command", "level", "scope", "criterionIds")} for item in gates],
    }
    return {
        "schemaVersion": 1,
        "state": "ready" if criteria and gates else "incomplete",
        "required": True,
        "requirementsSha256": contract["requirementsSource"]["sha256"],
        "planSha256": hashlib.sha256(
            json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "criteria": criteria,
        "gates": gates,
        "criterionCount": len(criteria),
        "gateCount": len(gates),
        "allCriteriaMapped": bool(criteria) and all(
            any(item["id"] in gate["criterionIds"] for gate in gates) for item in criteria
        ),
        "sourceTrust": "requirements-bound-derived",
        "executionPerformed": False,
        "persistencePerformed": False,
        "verificationEvidenceCreated": False,
    }


__all__ = ["build"]
