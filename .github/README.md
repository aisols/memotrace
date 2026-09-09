# Repository Automation

`workflows/android.yml` executes the Android component's JVM coverage/tests, app
unit tests, lint, formatting and application/instrumentation APK builds. Pinned
action commits orchestrate the commands documented in `android/README.md`.
Hardware tests remain a separate main-agent step, not a hosted-CI claim.
Add other checks only with working targets; no green placeholder builds.

Workflows should orchestrate component-local commands and cross-component tests.
They must not become the sole implementation of build or test logic. Verify
components without sibling sources or parent configuration, and run affected
contract/consumer checks when public formats change. Never require personal
recordings or production credentials in CI.
