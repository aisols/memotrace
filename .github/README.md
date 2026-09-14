# Repository Automation

## Android

`workflows/android.yml` executes the Android component's JVM coverage/tests, app
unit tests, lint, formatting and application/instrumentation APK builds. Pinned
action commits orchestrate the commands documented in `android/README.md`.
Hardware tests remain a separate main-agent step, not a hosted-CI claim.

## Ingestion contracts and server

`workflows/ingestion.yml` runs one coordinated job for changes to either component,
repository automation, or shared policies/docs. A contracts-only change therefore
also runs Go conformance/regressions and server-owned Python ML checks. `server/**`
already includes `server/ml/**`. Pull requests and pushes to `main`
use the same path filters; manual dispatch is available. The Ubuntu 24.04 job has
a 30-minute timeout, `contents: read` permission, and no persisted Git credentials.

Toolchain: **Go 1.26.4**, **Python 3.12**, **uv 0.11.3**, and runner-provided Docker.
The Python baseline and uv requirement match both `contracts/` and `server/ml/`;
`--locked` verifies each project's own `uv.lock` consistency. The shared setup-uv
step runs at the repository root; verification selects each component explicitly.
Go automatic toolchain switching and uv Python downloads are disabled so checks
use the explicitly installed toolchains.

Commands run in order:

1. From `contracts/`: `uv run --locked python -m tools.verify`.
2. From `server/`, the read-only **assembly** parity check:

   ```sh
   python3 scripts/refresh-contract.py --check --source ../contracts \
     --source-base 5f5ac49e03b25f805f5a89f791727d0c3bd18642 \
     --provenance unreleased-revision
   ```

3. From `server/`: `uv run --locked --project ml python -m memotrace_ml.verify`.
4. From `server/`, the external generic blind/staged evaluator gate:

   ```sh
   uv run --locked --project ml python scripts/verify_retrieval_eval.py
   ```

5. From `server/`, the separate object-search experiment gate:

   ```sh
   uv run --locked --project ml python scripts/verify_object_search.py
   ```

6. From `server/`, the external smoke helper gate:

   ```sh
   uv run --locked --project ml ruff check --config ml/pyproject.toml scripts/retrieval-smoke.py scripts/test_retrieval_smoke.py
   uv run --locked --project ml ruff format --check --config ml/pyproject.toml scripts/retrieval-smoke.py scripts/test_retrieval_smoke.py
   uv run --locked --project ml pytest -c ml/pyproject.toml scripts/test_retrieval_smoke.py
   ```

7. From `server/`:
   `MEMOTRACE_TEST_ML_PYTHON="$PWD/ml/.venv/bin/python" bash scripts/verify.sh`.
8. From `server/`: `docker build -t memotrace-server:local .`.

The server verifier owns formatting checks (no gofmt mutation), module verification,
vet, build, snapshot conformance, required PostgreSQL/race/fault tests and the
independently approved **>=85% statement-coverage gates for `internal/protocol`
and `internal/retrieval`, enforced separately**. It creates and cleans up its own
uniquely named, digest-pinned PostgreSQL-15 container with an ephemeral loopback
port. No workflow-global PostgreSQL service or operator database is used. See
[server quality](../server/docs/quality.md) and
[contract quality](../contracts/docs/quality.md) for the exact checks and review gates.

The [ML verifier](../server/ml/README.md#install-and-ordinary-verification) runs
Ruff lint/format checks, strict mypy over source and tests, and synthetic pytest
tests that prohibit network connections. It enforces the independently approved
**>=95% statement-coverage gate for `memotrace_ml.images`**; branch coverage is
reported separately without a branch threshold. Dependency installation can download
locked wheels, including **CPU-only Torch**; ordinary CI acquires **no model
weights or datasets**.

The [generic retrieval evaluator](../server/docs/retrieval-evaluation.md) is an external,
model-free diagnostic under `server/scripts`, not part of the packaged ML implementation
fingerprint or Go Docker image. Its gate uses only inline neutral synthetic cases, runs
strict typing and Ruff, and enforces **100% statement coverage separately** for the pure
planning/ranking core and post-ranking metrics module. Branch coverage is reported with
no threshold. It reads no model, dataset, private input, or network resource.

The [object-search experiment gate](../server/docs/quality.md#object-search-experiment-gate)
checks its core, vision adapter, runner, tests and verifier with Ruff and strict
mypy, plus synthetic tests without pretrained weights/data downloads. It enforces
the independently approved **>=95% statement coverage for
`scripts/object_search_core.py` alone**; branches are reported without a threshold.
It uses existing locked dependencies and leaves the production ML identity unchanged.

ML installation/verification precedes the Go verifier so the coordinated job can
supply its actual locked interpreter through `MEMOTRACE_TEST_ML_PYTHON`. This makes
`TestHTTPPythonDecodeFailureAndExactQueryPixels` required in root CI: genuine
Pillow decoding and exact-decimal query rasterization cross the HTTP/Go/JSONL/Python
boundary with a test-only encoder, without loading weights or using the network.
Ordinary standalone `bash scripts/verify.sh` remains autonomous and may skip this
opt-in decoder test when the environment variable is absent. Root CI supplies it
and must exercise the test; all PostgreSQL/race/fault and separate Go coverage gates
still run in the same full verifier.

The parity step deliberately reads the selected canonical sibling source; ordinary
component verification and the `server/` Docker build context remain autonomous.
A mismatch fails CI rather than refreshing generated files. Coordinate canonical
and consumer snapshot changes in the same reviewed PR using the
[explicit refresh procedure](../server/docs/quality.md#controlled-canonical-snapshot).
The [snapshot policy](../contracts/docs/releases.md#controlled-development-snapshot-consumer-owned)
pins full source revision `5f5ac49e03b25f805f5a89f791727d0c3bd18642`, explicitly
`unreleased-revision`: that commit contains the exact canonical bytes, but no
bundle 0.2.0 release exists. SHA-256 entries identify all five artifacts: `VERSION`
and the ingestion and retrieval schema/OpenAPI pairs. Bundle **0.2.0** contains frozen ingestion wire
**0.1.0** and retrieval wire **0.2.0**; a bundle bump must not relabel ingestion
responses. The consumer manifest now records the same full revision; the checker
compares manifest bytes too. Update source, snapshot, family versions, provenance and
parity arguments together through review, including strict-object compatibility
and consumer regressions.

The Docker step builds the standalone **Go-only** image from `server/`; it does not
package Python, ML dependencies or weights. An enabled worker needs separate trusted
runtime provisioning. Combined Python/model deployment is not built here.

## Explicit external retrieval experiments

Run the [model acquisition/live smoke commands](../server/ml/README.md#explicit-model-acquisition-and-live-smoke),
[Open Images pilot commands](../server/benchmarks/README.md#repeat-the-public-data-experiment),
and [genuine-model Go CLI/TLS smoke and response validation](../server/docs/retrieval.md#one-command-genuine-model-clitls-smoke)
separately from ordinary CI. The Go smoke uses pre-acquired inputs and its own
disposable database. Keep model/data artifacts and raw reports outside Git; use
the pinned
[model manifests](../server/ml/README.md#explicit-model-acquisition-and-live-smoke),
model licenses,
dataset provenance/attribution and actual model/policy fingerprints when recording
evidence. Apply the [release licensing checks](../docs/licensing.md#release-and-extraction-checklist)
to distributions. External pilot and CLI/HTTP results do not by themselves establish
hosted CI, main-agent delivery verification, a final-best-model decision, official
Ego4D quality, or temporal-history behavior.
The [historical pilot](../server/benchmarks/openimages-pilot-2026-09-09.md) and
[review-v2 builder rerun](../server/benchmarks/openimages-pilot-review-v2-2026-09-09.md)
retain their specific revision/fingerprint evidence. The latter's primary text
means use three classes with both positive and negative judgments; unknown labels
are not negatives. The historical
[everyday-object evaluation](../server/benchmarks/everyday-object-evaluation-2026-09-10.md)
records pre-hardening 100-image, six-primary-class data/language/model evidence. The
[dated main-verification report](../server/docs/retrieval-main-verification-2026-09-10.md)
records matching pre-hardening local component and genuine Base384 Go/PostgreSQL
CLI/TLS evidence. The
[2026-09-13 record](../server/benchmarks/everyday-object-evaluation-2026-09-13.md)
retains its historical v3 checkpoint/private diagnostic scope. The
[current 2026-09-14 record](../server/benchmarks/object-search-experiment-2026-09-14.md)
binds uncommitted source hashes over `39b24e3`, the first usable offline proposal/
descriptor experiment, public/private aggregates and a passing genuine-model
100-image Go CLI/TLS smoke with independent exact-query matching. It records local
gates and independent review, including the new 226-test core gate. A narrow private
PTS scan does not establish canonical content/frame-zero or whole-cohort timing.
Server-source extraction passed with provisioned dependencies; hosted CI, PR/merge,
release, deployment, official VQ2D, Android/device and production gates remain pending.

## Action pins and evidence

Action tag-to-commit pins were checked against the upstream GitHub API:

| Action | Tag | Pinned commit |
| --- | --- | --- |
| `actions/checkout` | v5.0.0 | [08c6903cd8c0fde910a37f88322edcfb5dd907a8](https://github.com/actions/checkout/commit/08c6903cd8c0fde910a37f88322edcfb5dd907a8) |
| `actions/setup-python` | v6.0.0 | [e797f83bcb11b83ae66e0230d6156d7c80228e7c](https://github.com/actions/setup-python/commit/e797f83bcb11b83ae66e0230d6156d7c80228e7c) |
| `astral-sh/setup-uv` | v7.0.0 | [eb1897b8dc4b5d5bfe39a428a8f2304605e0983c](https://github.com/astral-sh/setup-uv/commit/eb1897b8dc4b5d5bfe39a428a8f2304605e0983c) |
| `actions/setup-go` | v6.0.0 | [44694675825211faa026b3c33043df3e48a5fa00](https://github.com/actions/setup-go/commit/44694675825211faa026b3c33043df3e48a5fa00) |

Current source-local verification is recorded above; no hosted run or merge is claimed.
Subsequent implementation changes require applicable review and main-agent reruns;
hosted CI and authorized PR/merge gates remain pending.
Linux synthetic/fault tests do not establish physical power-loss, restored-backup,
Android synchronization, or production shared-service readiness.

## Ownership

Workflows should orchestrate component-local commands and cross-component tests.
They must not become the sole implementation of build or test logic. Verify
components without sibling sources or parent configuration, and run affected
contract/consumer checks when public formats change. Never require personal
recordings or production credentials in CI. Add checks only with working targets;
no green placeholder builds.
