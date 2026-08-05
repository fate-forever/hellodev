from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataScriptTests(unittest.TestCase):
    def test_release_identity_is_supplied_by_the_caller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / "stage"
            wheelhouse = root / "wheelhouse"
            (stage / "runtime" / "python" / "Lib" / "site-packages").mkdir(parents=True)
            (stage / "components" / "trellis" / "node_modules").mkdir(parents=True)
            wheelhouse.mkdir()
            subprocess.run(
                [
                    sys.executable,
                    str(PACKAGE_ROOT / "scripts" / "generate_bundle_metadata.py"),
                    "--stage",
                    str(stage),
                    "--wheelhouse",
                    str(wheelhouse),
                    "--distribution-version",
                    "9.8.7",
                    "--created",
                    "2026-08-05T00:00:00Z",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            sbom = json.loads((stage / "SBOM.spdx.json").read_text(encoding="utf-8"))
            notices = (stage / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
            self.assertEqual(sbom["name"], "HelloDev-9.8.7-windows-x86_64")
            self.assertEqual(
                sbom["documentNamespace"],
                "https://github.com/fate-forever/hellodev/sbom/9.8.7/windows-x86_64",
            )
            self.assertEqual(sbom["creationInfo"]["created"], "2026-08-05T00:00:00Z")
            self.assertTrue(notices.startswith("# HelloDev 9.8.7 third-party notices\n"))


if __name__ == "__main__":
    unittest.main()
