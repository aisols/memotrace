# Main verification: object retrieval, 2026-09-10

**Historical pre-hardening local verification and genuine-model integration
evidence.** Detailed performance, checkpoint, language and dataset measurements are
in the
[everyday-object evaluation record](../benchmarks/everyday-object-evaluation-2026-09-10.md).
This superseded the [2026-09-09 main record](retrieval-main-verification-2026-09-09.md)
at the recorded source without changing that record's historical body. It does not
verify the subsequently hardened source: current evaluation requires fresh v3
acquisition, and a live model/data rerun remains pending.

## Source and host

The historically verified source was the dirty, uncommitted
`feat/object-search-history` working tree at HEAD/base
`0ebc2a87752e533f1fa50fd138b15b68546b4fcc`. `origin/main` was
`407a5855fb9628dcc2d2f2ce88e90b2611d7d824`. No rebase, commit or push occurred.
Hosted CI, PR review, merge and deployment remain pending.

The host was a Ryzen 9 5950X with 16 physical/32 logical CPUs and 62 GiB RAM.
Toolchain: Go 1.26.4, Python 3.12.3, uv 0.11.3 and Docker 29.1.3.

## Historical local gates

From `contracts/`:

```sh
uv run --locked python -m tools.verify
```

**PASS:** 2090 tests.

From `server/`:

```sh
uv run --locked --project ml python -m memotrace_ml.verify
MEMOTRACE_TEST_ML_PYTHON="$PWD/ml/.venv/bin/python" bash scripts/verify.sh
docker build -t memotrace-server:local .
git diff --check
```

| Gate | Result |
| --- | --- |
| ML lint/format/type | Ruff lint and format plus strict mypy passed |
| ML tests | 185 passed |
| `memotrace_ml.images` statements | 114/114, 100%; required >=95% |
| `memotrace_ml.images` branches | 36/36, 100%; reported separately |
| Full server verifier | PostgreSQL-15, race, fault and genuine Pillow bridge checks passed |
| `internal/protocol` statements | 238/252, 94.4%; required >=85% |
| `internal/retrieval` statements | 259/282, 91.8%; required >=85% |
| Standalone Go-only Docker build | passed; image ID `sha256:20bee18ac4720f976d5c73b50f8157ee9681239f8b246c806ba6bfd9ac40a9a5` |
| Worktree whitespace | `git diff --check` passed |

The full server verifier used its owned disposable PostgreSQL-15 instance and
included required race/fault scenarios. Supplying
`MEMOTRACE_TEST_ML_PYTHON="$PWD/ml/.venv/bin/python"` exercised the genuine Pillow
decode/exact-query-pixel bridge with a test-only encoder and no model download.

At the recorded pre-hardening source, independent review reproduced all 60 final
query-mode records, exact RRF scores, timings, macros and exclusions, all 100 selected IDs/class
counts/candidate universes, 100/668 vectors, attribution receipts, the model
fingerprint, both generations and that implementation digest. Those digest,
dataset and source measurements are historical only and do not close verification
of the changed source.

## Historical real Go/PostgreSQL/CLI/TLS evidence

The external runner used the selected Base384 model, final everyday-object v2
100-image manifest and explicit 16-thread/batch-4 runtime:

```sh
python3 scripts/retrieval-smoke.py \
  --model-dir /tmp/opencode/memotrace-search-models/siglip2-base-patch16-384 \
  --manifest /tmp/opencode/memotrace-openimages-everyday-v2-100-2026-09-10/manifest.json \
  --output-dir /tmp/opencode/memotrace-go-search-smoke \
  --threads 16 --batch-size 4
MEMOTRACE_RETRIEVAL_EVIDENCE_DIR=/tmp/opencode/memotrace-go-search-smoke/go-smoke-f5820d8b9b3e150ae208719d \
  go test -count=1 ./internal/contract -run '^TestExternalGenuineRetrievalEvidence$' -v
```

Output directory:
`/tmp/opencode/memotrace-go-search-smoke/go-smoke-f5820d8b9b3e150ae208719d`.
Full and overlap indexing each completed 100/100 assets with zero failures and
respectively 100/668 regions. English and Russian CLI searches passed. HTTPS
pairing, search, history and exact-original retrieval passed. History correctly
reported unavailable for Open Images, without fabricated timestamps. The embedded
evidence test passed.

| Smoke artifact | SHA-256 |
| --- | --- |
| `summary.json` | `b8c72f7e7fc3ee7bc31d292d711194103873924d522ca68a259ce5d47a5bcd72` |
| `index-full.json` | `8b6a52810b5916b2276e0128d4cf60d5e4cc6bf5b7893fdb7cec44c5efc7a100` |
| `index-overlap.json` | `6b0486849051cc7a2b8bbad56e599976f2dc5842684d932d68d8eaf32ade86e1` |

The final benchmark established Base384 loading only for its recorded pre-hardening
model/implementation/generation identities. Earlier Base384 and SO400M 13-request
smokes passed before later benchmark-only implementation changes; their old
fingerprints must not be presented as current. See the linked benchmark record for
the final report hash, generations, timing and metrics.

## Scope and delivery

The standalone Docker image remains Go-only; the genuine Python worker ran through
separate host provisioning. This is not sustained-load, production deployment or
an OS sandbox claim. Open Images is class-level evidence with unknown times, sparse
judgments and six primary-eligible classes; it is not same-instance or chronological
history evidence. No automatic translator was tested. Ego4D remains pending, and no
official Ego4D metric is claimed. Current live evidence requires a fresh v3 dataset
acquisition and rerun; the v2 paths and hashes above remain unmodified historical facts.

Private encrypted deployment, Android sync/device behavior, physical power-loss and
restored-backup evidence remain separate. At the recorded source, the working tree
was uncommitted and dirty; hosted CI, PR/merge, deployment and release evidence did
not yet exist.
