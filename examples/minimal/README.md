# Minimal zero-upstream demo

This demo exercises HelloDev without Trellis or Nocturne. It creates a
disposable local project and runs:

```text
open -> next -> do task create -> do plan -> do work -> do check -> do finish -> resume
```

After installing the wheel, run from the repository root:

```powershell
pwsh -File scripts/demo.ps1
```

The script prints the disposable project path and leaves it available for
inspection. It does not access the network, configure a host, or write outside
that temporary project.

For the typed integration surface, see
[`../host_sdk_minimal.py`](../host_sdk_minimal.py).
