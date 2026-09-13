# Repository Workflow

These rules apply repository-wide to all features, fixes, documentation,
refactors, tests, and chores.

## Delivery and Agent Ownership

- Work in small, coherent slices on short-lived, descriptively named branches
  from `main`. Use prefixes such as `feat/`, `fix/`, `docs/`, `chore/`,
  `refactor/`, and `test/`: for example, `feat/adaptive-jpeg-capture`,
  `fix/capture-backpressure`, or `docs/recorder-verification`.
- Every change reaches `main` through a GitHub pull request independently
  reviewed and tested before merge. Never commit or push directly to `main`.
- The main agent owns coordination, authorized git/GitHub operations, and final
  verification. Delegate implementation/coding and review to separate general
  agents; explore agents may inspect. The builder must not be the sole reviewer.
  Use brief, scoped handoffs and findings to preserve context.
- PRs must explain rationale, checks and results, limitations, and resolution of
  review findings. The main agent verifies actual applicable build, CI, and device
  evidence at the latest PR revision before a reviewed merge to `main`.
- Perform git actions only when authorized. Amending or force-pushing requires
  explicit authorization. Never revert user work. Make all manual file edits
  through the `apply_patch` tool only.

## Architecture

- Keep `android/`, `server/`, and `contracts/` autonomous. `deploy/` owns assembly,
  `integration/` cross-component tests, `docs/` cross-cutting documentation, and
  `tools/` only genuine repository coordination.
- No sibling source imports or parent build dependencies. Consume explicit,
  pinned contract artifacts or controlled snapshots with provenance, version,
  and checksum; ordinary component builds must work independently.
- Start Android with cohesive capture, durable local state, synchronization,
  device interaction, speech, and accessible UI packages. Add Gradle modules
  only for justified isolation benefits. Keep pure capture/domain logic testable
  independently of Android side effects.
- Separate server inference from job orchestration and persistence; inference
  must not own transactions, retries, or archive deletion.
- The bounded retrieval baseline in ADR 0007 keeps optional offline Python inference
  in `server/ml/`. The standalone `server/` Docker image is Go-only; optional worker
  deployment must be provisioned separately. Preserve ingestion wire 0.1.0 when
  reviewing bundle/retrieval 0.2.0; bundle, wire-family and model/index versions
  have distinct meanings.

Follow the [architecture rules](docs/architecture/README.md) and accepted
[decisions](docs/README.md). Preserve `AGPL-3.0-only`, the full license, and
applicable notices. Never commit secrets or private data; use safe synthetic
fixtures or explicitly redistributable fixtures with documented provenance.

## Verification and Merge Gates

- Include relevant unit, integration, regression, contract, and device tests.
  Keep component tests local and cross-component scenarios in `integration/`.
- Document and independently review explicit component-local coverage gates for
  pure capture/domain logic with its first implementation; enforce them in CI
  when executable targets exist. Do not impose an arbitrary whole-app percentage.
- Existing applicable lint, style, build, tests, and CI must pass before merging
  to `main`. Never disable or skip tests or weaken gates merely to pass.
- Report failures, unavailable checks, and unsupported device behavior truthfully.
  Unresolved required checks block merge; design intent is not device evidence.
- Android now has executable recorder build/test targets and CI orchestration;
  run the commands and coverage gates in `android/README.md` and
  `android/docs/quality.md`. Device evidence is a separate main-agent gate.
- Server and contracts now have autonomous executable targets. From `contracts/`,
  run `uv run --locked python -m tools.verify` with Python 3.12 and uv 0.11.3;
  follow `contracts/README.md` and `contracts/docs/quality.md`. From `server/`, run
  `bash scripts/verify.sh` with Linux, Go 1.26.4, Python 3 and Docker, then
  `docker build -t memotrace-server:local .`; follow `server/README.md` and
  `server/docs/quality.md`. The full verifier owns disposable PostgreSQL-15 setup,
  required DB/race/fault tests and independently approved >=85% statement-coverage
  gates for `internal/protocol` and `internal/retrieval`, enforced separately.
  Neither package can offset the other's missing/failing coverage.
  `go test ./...` alone is not the full gate.
- The server-owned ML target is executable. From `server/`, run
  `uv run --locked --project ml python -m memotrace_ml.verify` with Linux x86-64,
  Python 3.12 and uv 0.11.3; follow `server/ml/README.md`. This runs unit tests,
  strict source/test typing, lint and format checks without models or datasets.
  Locked dependency installation uses CPU-only Torch wheels. The verifier enforces
  the independently approved >=95% statement-coverage gate for `memotrace_ml.images`;
  branch coverage is reported separately, without a branch threshold. Do not
  substitute a combined line/branch or whole-package percentage for this gate.
- Root ingestion CI runs contract and Go/ML checks for server or contract changes
  and checks canonical/snapshot parity with the explicit read-only maintenance
  command in `.github/README.md`. Install/test ML first, then from `server/` run
  `MEMOTRACE_TEST_ML_PYTHON="$PWD/ml/.venv/bin/python" bash scripts/verify.sh`.
  Root CI must exercise `TestHTTPPythonDecodeFailureAndExactQueryPixels` using the
  genuine Pillow decoder/query rasterizer and a test-only encoder, without weights
  or network. Standalone Go verification remains independent and may skip this
  opt-in decoder check when the interpreter variable is absent.
  Coordinate source, snapshot hashes/version/provenance and
  consumer regressions through review; never auto-refresh to conceal drift or add
  sibling imports to ordinary component builds. Verify component extraction too.
- Model acquisition, live-worker smoke, the public-data pilot and genuine-model
  CLI/TLS evidence are explicit external checks in `server/ml/README.md`,
  `server/benchmarks/README.md` and `server/docs/retrieval.md`, not ordinary CI
  downloads. Keep weights, downloaded datasets/annotations/attribution and raw
  reports outside Git. Record source/license checks, artifact hashes and actual
  model/policy fingerprints; apply `docs/licensing.md` to releases. Builder results
  need independent main-agent verification at the latest revision. Open Images
  has unknown times, not chronological or Ego4D evidence; candidates do not establish
  learned stable object identity/tracking or a final-best-model choice.
- Encryption deployment is deferred only for the user-directed public/synthetic
  experiments. Private capture still requires operator-provisioned encrypted
  storage/backups, protected keys and verified recovery as described in `SECURITY.md`.
- Do not invent commands, placeholder configuration or green builds. Physical
  power-loss, restored-backup, deployment and Android sync evidence remain separate
  from synthetic server/contract tests; report unavailable checks honestly.
