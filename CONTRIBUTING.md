# Contributing to MemoTrace

MemoTrace is currently a design-stage project. Discuss substantial changes to
behavior, component boundaries, public formats, or dependencies before building
them. Do not treat a proposed design as a tested device capability.

## Component Ownership

- Put Android implementation and tests under `android/`.
- Put server implementation, migrations, and component tests under `server/`.
- Put public wire formats and their validation under `contracts/`.
- Put tests requiring multiple components under `integration/`.
- Put system assembly under `deploy/`; keep component build logic local.
- Use `tools/` only for work that genuinely coordinates the repository.

Follow the [architecture rules](docs/architecture/README.md). Do not introduce
imports, build configuration, or mandatory dependency paths into a sibling
component. A repository split must not require application changes.

## Changes and Verification

Keep changes focused and include the relevant tests and documentation. State
which checks ran and which could not run. There are no application build or test
commands yet; add reproducible commands to the component README when its first
implementation is introduced.

Contract changes need examples and validation. Once consumers exist, check the
declared supported client/server combinations, not only a simultaneously updated
checkout. Preserve compatibility where released clients or persisted data need
it; do not accumulate speculative compatibility code.

Record significant architecture decisions in `docs/decisions/`. Component
details belong with the component. Do not silently rewrite accepted decisions;
supersede them and explain the reason.

## Data and Dependencies

Never attach personal archive material, unredacted logs, secrets, or private
documents to a pull request or issue. Public test fixtures must be synthetic or
have explicit redistribution permission and documented provenance.

Before adding a library, model, or dataset, record its source, version, license,
and relevant redistribution restrictions. Model weights and datasets are not
automatically licensed like their inference library. See [licensing](docs/licensing.md)
and [security](SECURITY.md).

## Contribution License

By submitting original material for inclusion, you agree to license that
contribution under `AGPL-3.0-only`, unless an explicit, compatible exception has
been agreed and recorded. You must have the right to submit the material and
must preserve third-party notices.

Contributors retain their copyrights. Contribution alone does not assign
copyright or grant a blanket right to issue proprietary licenses for their work.
No contributor license agreement or copyright-assignment process is in place.
Any future alternative licensing arrangement must secure the necessary rights
from the affected copyright holders before it is offered.
