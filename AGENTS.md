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
- The current scaffold has no application build/test commands or executable CI.
  Mark those checks honestly not applicable; do not invent commands, placeholder
  configuration, or green builds. Add reproducible component-local commands and
  real CI checks with working implementation targets.
