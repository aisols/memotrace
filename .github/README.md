# Repository Automation

There are no executable workflows yet. Add checks when there are working targets
to verify; do not publish green placeholder application builds.

Workflows should orchestrate component-local commands and cross-component tests.
They must not become the sole implementation of build or test logic. Verify
components without sibling sources or parent configuration, and run affected
contract/consumer checks when public formats change. Never require personal
recordings or production credentials in CI.
