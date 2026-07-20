# HelloDev unified-distribution component notices

This Core wheel contains the component lock and distribution tooling, not the
Trellis or Nocturne payloads themselves. A platform bundle built from these
tools must include the exact third-party licenses and corresponding source
materials described below.

| Component | Locked revision | License | Required bundle material |
|---|---|---|---|
| Trellis 0.6.7 | `e7c5ead4d0dfd717d11a40b6bc0c80d8af94c49a` | AGPL-3.0-only | License, copyright notice, exact corresponding-source archive, build inputs and dependency notices |
| Nocturne 2.5.4-8-g15930e0 | `15930e09982d8349902af9032aeb6ff5d6994cdb` | MIT | MIT license and dependency notices |

HelloDev launches both components as separate processes and keeps their data
planes separate. This technical boundary is not a substitute for independent
license review. Manifest SHA-256 values prove only that local bytes match the
included manifest; they are not signatures or remote provenance.
