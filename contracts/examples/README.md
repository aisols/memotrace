# Synthetic schema fixtures

`valid.json` maps each canonical `$defs` name to one accepted instance.
`invalid.json` contains complete rejected instances, the target definition, and
the expected JSON Schema **keyword and instance path**. Every entry is exercised
by the quality command; a failure for an unrelated reason does not satisfy an
invalid expectation. Boundary matrices in `tests/test_contract.py` add limits,
missing/null/type cases, nested validation, and state/retryable relationships.

`raw-json.json` preserves raw numeric lexemes and JSON string/document literals
inside ordinary JSON strings. Its number cases expect exact integer acceptance
or a specific schema keyword; text cases explicitly distinguish `parse_error`,
`schema_error` (with keyword), and lossless `valid` values. Tests embed each raw
text literal in the applicable request/profile fields. Malformed surrogate
escapes remain escaped fixture text until a lossless parser rejects them; fixture
loading and diagnostics never try to UTF-8 encode illegal surrogate values.
Direct in-memory schema cases separately prove NUL/surrogate pattern rejection.
Valid surrogate pairs decode to one astral scalar and genuine U+FFFD is preserved.

All values are hand-authored synthetic MemoTrace fixtures, `AGPL-3.0-only`.
Reserved `.example` hosts, repeated UUIDs, zero/all-one byte tokens, and dummy
digests represent no person, credential, deployment, certificate, or image. No
third-party data, phone content, images, or model weights are included. The dummy
hash and byte count are schema illustrations; there is no corresponding JPEG.
Consumers generate their own synthetic JPEG and compute its actual hash/length
for runtime tests. In particular these illustrative tokens are **not random**;
production issuance must generate 32 cryptographically random bytes.

`ManifestRequest` demonstrates both absent legacy optionals and explicit nulls.
`ManifestResponse` demonstrates a committed and pending result in matching order.
Examples prove schema acceptance/rejection only; the normative scenario table in
`docs/protocol.md` defines the expectations that consumer integration tests must
exercise against actual runtime behavior.
