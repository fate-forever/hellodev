"""Generate deterministic dependency notices, license copies, locks, and SPDX SBOM."""

from __future__ import annotations

import argparse
import email
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]+", "-", value).strip("-") or "package"


def declared_license(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()[:256]
    return "NOASSERTION"


def copy_license_files(source: Path, destination: Path) -> int:
    candidates = []
    for path in source.iterdir():
        if path.is_file() and path.name.casefold().startswith(("license", "licence", "copying", "notice")):
            candidates.append(path)
    licenses = source / "licenses"
    if licenses.is_dir():
        candidates.extend(path for path in licenses.rglob("*") if path.is_file())
    count = 0
    for path in sorted(candidates, key=lambda item: item.relative_to(source).as_posix().casefold()):
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        count += 1
    return count


def python_packages(stage: Path) -> list[dict[str, Any]]:
    site = stage / "runtime" / "python" / "Lib" / "site-packages"
    packages: list[dict[str, Any]] = []
    for dist in sorted(site.glob("*.dist-info"), key=lambda item: item.name.casefold()):
        metadata_path = dist / "METADATA"
        if not metadata_path.is_file():
            continue
        metadata = email.message_from_string(metadata_path.read_text(encoding="utf-8", errors="replace"))
        name = metadata.get("Name", dist.name)
        version = metadata.get("Version", "unknown")
        license_value = metadata.get("License-Expression") or metadata.get("License")
        destination = stage / "licenses" / "python-packages" / f"{safe_name(name)}-{safe_name(version)}"
        license_files = copy_license_files(dist, destination)
        packages.append(
            {
                "ecosystem": "pypi",
                "name": name,
                "version": version,
                "license": declared_license(license_value),
                "licenseFiles": license_files,
            }
        )
    return packages


def npm_packages(stage: Path) -> list[dict[str, Any]]:
    modules = stage / "components" / "trellis" / "node_modules"
    packages: list[dict[str, Any]] = []
    for manifest in sorted(modules.rglob("package.json"), key=lambda item: item.as_posix().casefold()):
        package_dir = manifest.parent
        parts = package_dir.relative_to(modules).parts
        boundary = max((index for index, part in enumerate(parts) if part == "node_modules"), default=-1)
        suffix = parts[boundary + 1 :]
        if not (len(suffix) == 1 or (len(suffix) == 2 and suffix[0].startswith("@"))):
            continue
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict) or not isinstance(value.get("name"), str) or not isinstance(value.get("version"), str):
            continue
        name, version = value["name"], value["version"]
        relative = package_dir.relative_to(modules)
        destination = stage / "licenses" / "npm-packages" / relative
        license_files = copy_license_files(package_dir, destination)
        packages.append(
            {
                "ecosystem": "npm",
                "name": name,
                "version": version,
                "license": declared_license(value.get("license")),
                "licenseFiles": license_files,
            }
        )
    return packages


def wheel_lock(wheelhouse: Path) -> list[dict[str, str]]:
    records = []
    for wheel in sorted(wheelhouse.glob("*.whl"), key=lambda item: item.name.casefold()):
        with zipfile.ZipFile(wheel) as archive:
            metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata_names) != 1:
                raise ValueError(f"wheel has no unique METADATA: {wheel}")
            metadata = email.message_from_bytes(archive.read(metadata_names[0]))
        records.append(
            {
                "name": metadata.get("Name", wheel.stem),
                "version": metadata.get("Version", "unknown"),
                "filename": wheel.name,
                "sha256": sha256(wheel),
            }
        )
    return records


def spdx_id(index: int, package: dict[str, Any]) -> str:
    return f"SPDXRef-Package-{index:04d}-{safe_name(package['name'])}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True)
    parser.add_argument("--wheelhouse", required=True)
    parser.add_argument("--runtime-input", action="append", default=[], metavar="NAME=PATH")
    args = parser.parse_args()
    stage = Path(args.stage).resolve()
    wheelhouse = Path(args.wheelhouse).resolve()
    packages = python_packages(stage) + npm_packages(stage)
    packages.sort(key=lambda item: (item["ecosystem"], item["name"].casefold(), item["version"]))

    wheel_records = wheel_lock(wheelhouse)
    runtime_inputs = []
    for raw in args.runtime_input:
        name, separator, path_value = raw.partition("=")
        if not separator or not name:
            raise ValueError("--runtime-input must be NAME=PATH")
        path = Path(path_value).resolve()
        runtime_inputs.append({"name": name, "filename": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    inputs = {"schemaVersion": 1, "wheelLocks": wheel_records, "runtimeInputs": sorted(runtime_inputs, key=lambda item: item["name"])}
    sources = stage / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    (sources / "runtime-input-lock.json").write_text(json.dumps(inputs, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    spdx_packages = []
    relationships = []
    for index, package in enumerate(packages, start=1):
        identifier = spdx_id(index, package)
        declared = package["license"] if re.fullmatch(r"[A-Za-z0-9.+()-]+", package["license"]) else "NOASSERTION"
        spdx_packages.append(
            {
                "SPDXID": identifier,
                "name": package["name"],
                "versionInfo": package["version"],
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": declared,
                "supplier": "NOASSERTION",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": f"pkg:{package['ecosystem']}/{package['name']}@{package['version']}",
                    }
                ],
            }
        )
        relationships.append(
            {"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES", "relatedSpdxElement": identifier}
        )
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "HelloDev-0.14.3-windows-x86_64",
        "documentNamespace": "https://github.com/fate-forever/hellodev/sbom/0.14.3/windows-x86_64",
        "creationInfo": {"created": "2026-07-20T00:00:00Z", "creators": ["Tool: hellodev-generate-bundle-metadata"]},
        "packages": spdx_packages,
        "relationships": relationships,
    }
    (stage / "SBOM.spdx.json").write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# HelloDev 0.14.3 third-party notices",
        "",
        "This Windows archive redistributes independently launched components and runtimes.",
        "The declarations below are inventory metadata, not legal advice or a substitute for the exact license files under `licenses/`.",
        "Manifest hashes prove only local byte equality with the included manifest; they are not signatures or provenance attestations.",
        "",
        "| Ecosystem | Package | Version | Declared license | License files |",
        "|---|---|---:|---|---:|",
    ]
    for package in packages:
        lines.append(
            f"| {package['ecosystem']} | {package['name'].replace('|', '/')} | {package['version']} | "
            f"{package['license'].replace('|', '/')} | {package['licenseFiles']} |"
        )
    lines.extend(
        [
            "",
            "Component summary: HelloDev Core (MIT), Trellis 0.6.7 (AGPL-3.0-only), "
            "Nocturne snapshot 2.5.4 at revision 15930e0 (MIT), Node.js and CPython under their included licenses.",
            "Process separation is an architecture boundary, not a license-isolation conclusion.",
            "",
        ]
    )
    (stage / "THIRD_PARTY_NOTICES.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"packages": len(packages), "wheels": len(wheel_records), "runtimeInputs": len(runtime_inputs)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
