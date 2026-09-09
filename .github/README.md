# Repository Automation

## Android

`workflows/android.yml` executes the Android component's JVM coverage/tests, app
unit tests, lint, formatting and application/instrumentation APK builds. Pinned
action commits orchestrate the commands documented in `android/README.md`.
Hardware tests remain a separate main-agent step, not a hosted-CI claim.

## Ingestion contracts and server

`workflows/ingestion.yml` runs one coordinated job for changes to either component,
repository automation, or shared policies/docs. A contracts-only change therefore
also runs server conformance/regression checks. Pull requests and pushes to `main`
use the same path filters; manual dispatch is available. The Ubuntu 24.04 job has
a 30-minute timeout, `contents: read` permission, and no persisted Git credentials.

Toolchain: **Go 1.26.4**, **Python 3.12**, **uv 0.11.3**, and runner-provided Docker.
The Python baseline and uv requirement match the contracts component's
`.python-version` and `pyproject.toml`; `--locked` verifies `uv.lock` consistency.
Go automatic toolchain switching and uv Python downloads are disabled so checks
use the explicitly installed toolchains.

Commands run in order:

1. From `contracts/`: `uv run --locked python -m tools.verify`.
2. From `server/`, the read-only **assembly** parity check:

   ```sh
   python3 scripts/refresh-contract.py --check --source ../contracts \
     --source-base f4e53f8 --provenance unreleased-working-tree
   ```

3. From `server/`: `bash scripts/verify.sh`.
4. From `server/`: `docker build -t memotrace-server:local .`.

The server verifier owns formatting checks (no gofmt mutation), module verification,
vet, build, snapshot conformance, required PostgreSQL/race/fault tests and the **85%
`internal/protocol` statement-coverage gate**. It creates and cleans up its own
uniquely named, digest-pinned PostgreSQL-15 container with an ephemeral loopback
port. No workflow-global PostgreSQL service or operator database is used. See
[server quality](../server/docs/quality.md) and
[contract quality](../contracts/docs/quality.md) for the exact checks and review gates.

The parity step deliberately reads the selected canonical sibling source; ordinary
component verification and the `server/` Docker build context remain autonomous.
A mismatch fails CI rather than refreshing generated files. Coordinate canonical
and consumer snapshot changes in the same reviewed PR using the
[explicit refresh procedure](../server/docs/quality.md#controlled-canonical-snapshot).
The base revision `f4e53f8` identifies the first unreleased working-tree snapshot's
provenance, not a release containing those bytes; hashes identify the actual content.
Update the parity arguments with the next reviewed provenance change.

Action tag-to-commit pins were checked against the upstream GitHub API:

| Action | Tag | Pinned commit |
| --- | --- | --- |
| `actions/checkout` | v5.0.0 | [08c6903cd8c0fde910a37f88322edcfb5dd907a8](https://github.com/actions/checkout/commit/08c6903cd8c0fde910a37f88322edcfb5dd907a8) |
| `actions/setup-python` | v6.0.0 | [e797f83bcb11b83ae66e0230d6156d7c80228e7c](https://github.com/actions/setup-python/commit/e797f83bcb11b83ae66e0230d6156d7c80228e7c) |
| `astral-sh/setup-uv` | v7.0.0 | [eb1897b8dc4b5d5bfe39a428a8f2304605e0983c](https://github.com/astral-sh/setup-uv/commit/eb1897b8dc4b5d5bfe39a428a8f2304605e0983c) |
| `actions/setup-go` | v6.0.0 | [44694675825211faa026b3c33043df3e48a5fa00](https://github.com/actions/setup-go/commit/44694675825211faa026b3c33043df3e48a5fa00) |

This wiring is not a claim of a passed hosted run. Independent review, main-agent
verification at the final revision, and applicable hosted CI remain merge gates.
Linux synthetic/fault tests do not establish physical power-loss, restored-backup,
Android synchronization, or production shared-service readiness.

## Ownership

Workflows should orchestrate component-local commands and cross-component tests.
They must not become the sole implementation of build or test logic. Verify
components without sibling sources or parent configuration, and run affected
contract/consumer checks when public formats change. Never require personal
recordings or production credentials in CI. Add checks only with working targets;
no green placeholder builds.
