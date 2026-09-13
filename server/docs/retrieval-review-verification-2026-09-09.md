# Go retrieval review-fix verification — 2026-09-09

> **HISTORICAL PRE-HARDENING BUILDER RECORD.** This follow-up applies only to its
> recorded source and does not supply current live model fingerprints or generations;
> those remain unavailable pending fresh v3 acquisition and a live hardened-source
> model/data run.

Builder follow-up to independent Go/contract review. Repository checkout: `<checkout>`,
branch `feat/object-search-history`, HEAD/base
`0ebc2a87752e533f1fa50fd138b15b68546b4fcc`. Changes are uncommitted; this is builder
evidence for main/reviewer re-verification, not a merge or new revision claim.

## Findings resolved in the Go-owned slice

1. **CLI cancellation:** read/validate search/history input before opening PG or
   locking the data root. Reopen stdin as a pollable nonblocking Linux descriptor,
   close it on context cancellation and impose a 30-second input deadline. Named request
   files must be regular; nonblocking open/stat rejects FIFOs/devices/directories.
   Actual CLI subprocess tests keep stdin open, signal SIGTERM and reacquire the
   root; additional tests cover input expiry and unsupported named streams.
2. **Stored JPEG failure:** operation-aware worker translation makes image-query
   decode/inference rejection `503`, including an older worker's `invalid_request`.
   Unsupported text remains `400`. Generic errors contain no child diagnostics.
3. **Exact decimals:** query `QueryBox` stores raw `json.Number` endpoints through
   JSONL. Numeric comparison uses normalized coefficient/exponent text, with work
   proportional to input bytes and no exponent-expanded rational allocation.
   Tiny/adjacent positive boxes remain valid and rasterize to touched pixels in
   the updated Python worker. The same precision issue for `min_score` is resolved:
   an exact threshold is prepared once per search and compared to the score's JSON
   decimal representation. A positive subnormal threshold cannot admit zero scores.
4. **Consumer oracle:** the conformance-only package checks coverage partitions and
   truncation, selected clocks, unsequenced membership, temporal/evidence bounds,
   chronological/nonoverlapping groups, complete extrema and original-path identity.
   Request-aware checking adds generation, limit, threshold, source, cutoff and gap.
   Structural-schema-valid counterexamples are explicitly rejected. A truncated
   response may retain temporal extrema while returning only unsequenced evidence.
   Production history assembly was not changed to accommodate the oracle.
5. **Provenance:** the explicit refresh pins the full 40-hex base above, both wire
   families and all five artifact hashes. Generator/embedded checks reject short
   provenance; the CI maintenance operation remains read-only `--check`.
6. **Coverage:** the independently approved >=85% retrieval statement gate is
   enforced alongside the existing >=85% protocol gate, separately. Missing either
   package's data fails; a rounded display percentage cannot conceal a failing gate.
7. **Generation evolution:** at this revision, Go derived generations dynamically
   from worker `describe`, with dimension/model/policy validation. Operator request
   examples were changed to consume the emitted index report rather than a previous
   hardcoded hash.

## Executed checks at this follow-up

From `server/`:

```sh
MEMOTRACE_TEST_ML_PYTHON="$PWD/ml/.venv/bin/python" bash scripts/verify.sh
python3 scripts/refresh-contract.py --source ../contracts \
  --source-base 0ebc2a87752e533f1fa50fd138b15b68546b4fcc \
  --provenance unreleased-working-tree --check
docker build -t memotrace-server:local .
git diff --check
```

All passed. The full verifier created/removed its own uniquely labelled PG15 and
ran formatting, module verification, vet, build, schema/oracle tests, CLI/HTTP/PG
regressions and race checks. The opt-in ML-interpreter test is **model-free**:
it uses the genuine Python JPEG decoder/query rasterizer and a test-only encoder.
It proves a header-valid, entropy-broken original fails before encoder invocation;
`[0,0,1e-400,1]` and `[0.5,0,0.50000000000000001,1]` each arrive as a 1×3 touched crop.
It neither loads weights nor measures retrieval quality. Ordinary Go checks need
no Python environment/model; their explicit JSONL fixtures are test-binary-only.

| Package gate | Covered statements | Coverage | Required |
| --- | ---: | ---: | ---: |
| `internal/protocol` | 238 / 252 | 94.4% | >=85% |
| `internal/retrieval` | 259 / 282 | 91.8% | >=85% |

Six separate gate probes passed: both passing, exact 85% passing, rounded 84.99%
failing, the original protocol gate failing independently, and either package's
coverage missing. Package-local IPC coverage was 82.0%, HTTP 88.5%, CLI 73.0% and
conformance 76.4%; these orchestration figures are reported, not substituted for the
two approved pure-package gates.

The full verifier also passed from the fresh isolated component copy
`/tmp/opencode/memotrace-review-final-4rvcSI`, without sibling components or an ML
virtual environment, with both identical gate results. Docker compiled the Go-only
image independently of Python/model artifacts; config ID:
`sha256:3473d3c9721750b5e3845e1afae0636bf1b34d51f4bafeac3ee67e1cb30ee726`.
The consumer snapshot's legacy/new document hashes and VERSION passed canonical
parity; the refresh changed provenance to the full base, not either wire family.

## Historical follow-up plan

No fresh genuine-model generation or Open Images benchmark was run in this
follow-up. At the time, this note assigned `scripts/retrieval-smoke.py` to Main after
the ML owner's final implementation-digest/preprocessing changes. The planned run
would index new generations from `describe` and record the emitted IDs; this record
does not claim that it completed. Earlier generation IDs are historical.
The child remains a trusted same-UID subprocess with sanitized offline environment,
not an OS sandbox; the Docker image remains Go-only. At the time, independent review
of these fixes and Main's later real CLI/TLS evidence remained separate gates.
