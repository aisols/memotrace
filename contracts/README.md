# MemoTrace Contracts

Autonomous, language-neutral source of truth for the public protocol and persisted
exchange formats. **Protocol `0.1.0` is an implemented, unreleased development
contract**, with OpenAPI 3.1, JSON Schema 2020-12, and executable validation.
There is no published release or supported client/server combination yet. Schema
checks do not prove deployed server behavior, filesystem durability, or device sync.

The [normative protocol](docs/protocol.md) defines pairing, registration, exact
JPEG upload/read, stable historical receipts, errors, and content invariants.
The [design/status](docs/ingestion-design.md) separates this slice from future work.

## Layout

- `openapi/ingestion.json`: canonical public HTTP API definition (JSON).
- `schemas/ingestion.schema.json`: single canonical schema library; select `$defs`.
- `examples/`: synthetic valid/invalid examples with expected outcomes.
- `tests/`: schema validation and public-contract consistency checks.
- `tools/`: component-local validation entry point and offline reference registry.
- `VERSION`, `pyproject.toml`, `uv.lock`: wire version and pinned validation tools.

## Quality command

Prerequisites: Python 3.12+ and **uv 0.11.3**. `.python-version` selects Python 3.12
for the reproducible baseline. Run from `contracts/` or an isolated copy of it:

```sh
uv run --locked python -m tools.verify
```

The first run installs dependencies from `uv.lock`; subsequent validation is
offline, with no remote schema resolution. To require offline dependency use too,
after provisioning the lock's wheels and interpreter:

```sh
uv run --locked --offline python -m tools.verify
```

The command runs real `jsonschema` (including runtime date-time formats) and
`openapi-spec-validator`, all fixture expectations, reference/HTTP drift checks,
and boundary matrices, including exact raw-decimal and Unicode interoperability
regressions and the two operation-specific 401 challenges. It exits nonzero on
failures, skips, or an empty suite.
See [quality requirements](docs/quality.md) for coverage and limitations. No
sibling sources, cloud account, running server, database, or phone is needed.
`.venv` and tooling caches are ignored; `UV_CACHE_DIR` can point outside the tree.

Server ORM classes, SQL migrations, internal job payloads, and mobile UI models
do not belong here. Avoid defining speculative endpoint families before their
first implementation needs a contract.

## Consumption and Versions

Use contract-first development for the public API. Check the server's behavior
and exposed API against the canonical contract; do not maintain a second,
independently edited API definition in the server.

Consumers pin a release artifact or a controlled local snapshot with recorded
source version/revision and checksum. Snapshot refresh is an explicit operation;
consumers must not edit generated copies or require `../contracts` at build time.
Do not require a live server to generate clients during an ordinary build.

See the [controlled snapshot/release procedure and compatibility policy](docs/releases.md).
Protocol/schema versions are independent of client/server application versions.
Every object is closed in 0.1.0, including nested requests: unknown fields fail
validation. Even an additive field needs compatibility/version review; a patch
version is not permission to add fields. Test supported combinations once
consumers exist, including persisted recordings uploaded by older applications.

## License

Original contracts and examples are licensed under `AGPL-3.0-only`. There is no
separate permissive SDK or generated-code exception at present. Review generated
artifacts and their licensing before distributing them. The full license is in
the enclosing repository's top-level `LICENSE`; include a complete copy when
extracting or distributing this component independently.
