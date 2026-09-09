# Cross-Component Verification

This directory owns tests involving more than one MemoTrace component. It contains
no test runner or executable scenarios yet. Add a local dependency manifest and
documented commands with the first tests; do not depend on an undeclared developer
environment or a root-level server import.

Planned scenarios include interrupted/repeated transfers, checksum failures,
durable archive acknowledgments before phone cleanup, and query/evidence exchange
across the declared supported contract and client/server versions.

Use public protocols and declared test services. Tests of one component's private
functions or its own database belong in that component instead. Device-specific
Android tests stay in `android/`, with explicit hardware prerequisites.

`tests/` reserves system scenarios. `fixtures/` may hold small synthetic or
explicitly redistributable samples only. Never commit personal recordings,
document scans, real device identifiers, credentials, or private OCR text.
