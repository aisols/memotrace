# Contract tooling dependencies

Original MemoTrace contract documents, fixtures, and tools are
`AGPL-3.0-only`. No third-party source, binary, JPEG, dataset, or model weight is
vendored here. `uv.lock` identifies the exact transitive dependency versions,
upstream PyPI artifact URLs, and SHA-256 checksums used by the validation tools.

Direct Python dependencies:

| Dependency | Version | Upstream | License |
| --- | --- | --- | --- |
| jsonschema (`format-nongpl` extra) | 4.25.1 | https://github.com/python-jsonschema/jsonschema | MIT |
| openapi-spec-validator | 0.7.2 | https://github.com/python-openapi/openapi-spec-validator | Apache-2.0 |

`jsonschema` is copyright Julian Berman and contributors (upstream distribution
retains its MIT notice). `openapi-spec-validator` is copyright its upstream
authors/contributors and distributed under Apache-2.0. Their original license
texts and notices are included by their distributions; these references do not
replace them. No MemoTrace license is applied to third-party packages.

uv **0.11.3** is an external execution prerequisite
(https://github.com/astral-sh/uv, MIT OR Apache-2.0), not a vendored dependency.
Python **3.12+** is an external runtime (PSF-2.0). Tests use standard-library
`unittest`. The `format-nongpl` extra selects jsonschema's non-GPL optional format
implementations; keep runtime date-time validation enabled when changing tools.

These packages are used as development validators, not embedded in the public
wire artifacts or server runtime. Their permissive licenses permit this use.
Before redistributing a bundled validation environment, include each installed
distribution's complete license/copyright/NOTICE material, including transitive
dependencies. The lock records their identities but is not a substitute for
their licenses. Standalone contract distribution must also include the complete
MemoTrace AGPL license as required by `docs/releases.md`.
