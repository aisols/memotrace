# Main verification: object retrieval — 2026-09-09

> **SUPERSEDED HISTORICAL EVIDENCE.** This body is preserved as recorded for its
> Base224-era source and artifacts. The
> [2026-09-10 main verification](retrieval-main-verification-2026-09-10.md) is also
> historical pre-hardening evidence; as documented there, current-source live evidence
> is pending and unavailable. Do not treat the identities, counts or authority claims
> below as current. Current model fingerprints and generations are unavailable pending
> fresh v3 acquisition and a live run on the hardened source.

**At that time, Main completed all required local checks on the then-checked source.**
Independent Go/security, ML/data and contract/API reviewers returned final **PASS**,
with all findings resolved and the new component-local coverage gates independently
approved.
Branch: `feat/object-search-history`; base/HEAD:
`0ebc2a87752e533f1fa50fd138b15b68546b4fcc`, with uncommitted implementation changes.
`origin/main` advanced separately with Android work; no merge, rebase or push occurred.
This was the authoritative local record at that time; earlier builder/pilot records
were already historical.

## Toolchain and component gates

Main used Linux, **Go 1.26.4**, **Python 3.12.3**, **uv 0.11.3**. From `contracts/`:

```sh
uv run --locked python -m tools.verify
```

**PASS: 2090 tests, including the unchanged 977-test legacy corpus.** Bundle/retrieval
remain **0.2.0** and ingestion wire **0.1.0**. From `server/`:

```sh
python3 scripts/refresh-contract.py --source ../contracts \
  --source-base 0ebc2a87752e533f1fa50fd138b15b68546b4fcc \
  --provenance unreleased-working-tree --check
uv run --locked --project ml python -m memotrace_ml.verify
MEMOTRACE_TEST_ML_PYTHON="$PWD/ml/.venv/bin/python" bash scripts/verify.sh
```

**PASS:** read-only canonical parity for both document pairs and VERSION (five files).
ML: **117 tests**, Ruff lint/format across 22 files, strict mypy across 22 files.
Go: formatting, module verification, vet, build and required disposable-PG15/race
tests covering CLI/API, lease fencing, populated-v1 migration, faults, RLS, open-stdin
cancellation, cutoffs, null history and decimal queries. Genuine Pillow decoder/
exact-rasterizer integration passed with a test encoder; unit gates loaded no weights.

| Independently approved gate | Main result | Required |
| --- | --- | --- |
| `internal/protocol` statements | 238/252, **94.4%** | >=85% |
| `internal/retrieval` statements | 259/282, **91.8%** | >=85% |
| `memotrace_ml.images` statements | 103/103, **100%** | >=95% |

Images branch coverage was **34/34, 100%**, reported separately from its statement gate.

## Genuine model smoke and measured benchmark

From `server/`, using the pre-acquired local model and public dataset:

```sh
uv run --locked --project ml python -m memotrace_ml.smoke \
  --model-dir /tmp/opencode/memotrace-search-models/siglip2-base-patch16-224
uv run --locked --project ml python -m memotrace_ml.benchmark \
  --model-dir /tmp/opencode/memotrace-search-models/siglip2-base-patch16-224 \
  --data-dir /tmp/opencode/memotrace-openimages \
  --output /tmp/opencode/memotrace-openimages/report-main-2026-09-09.json \
  --threads 4 --batch-size 2 --image-queries --gt-query-crop
```

Smoke **PASS: 13 actual-model JSONL requests, zero stderr bytes**. Main ran the
benchmark after the other checks, without concurrent model jobs. The command above
records the completed run; use a fresh output filename for each no-clobber rerun.
Genuine SigLIP2: approximately 375M parameters, **768 dimensions**, CPU, 4 threads / batch 2.
There were **48 distinct images, zero SHA aliases**; all dataset clocks remain null.

| Measurement | Full | Full + overlap |
| --- | ---: | ---: |
| Indexed vectors | 48 | 322 |
| Image-pipeline time, seconds | 8.181652918 | 48.689717340 |
| Primary English mean AP | 0.8808468888 | 0.9230339105 |
| Primary Russian mean AP | 0.8766577256 | 0.8780692792 |
| Primary image-query proxy mean AP | 0.8034499107 | 0.8090261101 |

Model load: **4.649800590 s**; total: **62.712025499 s**; peak RSS:
**1,399,076 KiB (~1.33 GiB)**. In-process image timings exclude JSONL, Go, SQL and queue
time; this fixed-order run is not cold-cache or sustained-throughput evidence.
Primary averages cover only the three both-polarity classes **Screwdriver, Knife,
Pen**. Scissors has no negative and Hammer no positive, so both are excluded.
Ranks are condensed to human-judged candidates: unknowns are omitted, not called
negative. These optimistic judged metrics are not full-corpus, multiyear or physical-
instance/history scores. Ground-truth boxes were used only for query crops, never indexing.
Full vectors preserve edges by letterboxing; default tiles use 0.75×minimum side,
25% overlap, anchored edges and a 64-region bound. Boxes are coarse crop matches,
not detections; area coverage does not guarantee recognition of every object.

## Recorded artifact and model identities

| Identity | SHA-256 |
| --- | --- |
| Main benchmark report | `26f4c362f2513cd54e7d8ff9b29907f6e4404980364d4eab89d4bde1eab0a2a2` |
| Dataset manifest | `5e80b91e992dbded88c2970c4b78f1c6bdfd488601bded9650cb5b389f10badd` |
| ML implementation | `1637853b5d1ecd6c4b1eed4ddc96f21e9e288f586cc0976427634812ca55f997` |
| Model fingerprint | `039ea1fc87576995648b814babe64be19b135d2a2428c98800fd92c9e099f9da` |
| Full generation | `faec3cb05e434b29d5b13840820045b6152fed64bac2ac4b97970e3334775ba2` |
| Overlap generation | `1c9c314934ad7992530ed328850ff317598d05679a70fa4b1df34d6f6634e21b` |

These identify this measured runtime/source, not constants for future installations;
continue to use dynamic `describe`/index output after implementation or runtime changes.

## Real Go/PostgreSQL/CLI/TLS evidence

```sh
python3 scripts/retrieval-smoke.py \
  --model-dir /tmp/opencode/memotrace-search-models/siglip2-base-patch16-224 \
  --manifest /tmp/opencode/memotrace-openimages/manifest.json \
  --output-dir /tmp/opencode/memotrace-go-search-smoke
MEMOTRACE_RETRIEVAL_EVIDENCE_DIR=/tmp/opencode/memotrace-go-search-smoke/go-smoke-53ad4b4e36f53f53638e7f4c \
  go test -count=1 ./internal/contract -run TestExternalGenuineRetrievalEvidence
```

**PASS:** both recorded generations completed 48 assets, zero failures, 48/322 regions.
English/Russian CLI queries, HTTPS pairing/search/history, exact-original reads and
source-SHA exclusion passed. Open Images returned `history_available:false`, null
first/last bounds and no fabricated chronology. **Seven saved actual CLI/HTTP
responses** passed genuine JSON Schema and semantic validation. Server/worker ran
on the native host, not in a Docker ML runtime. Artifacts were written to the external
run directory above; images, ground truth, attribution and credential files are not
in Git.

## Container, isolation and delivery status

```sh
docker build -t memotrace-server:retrieval-dev .
docker run --rm --read-only --network none memotrace-server:retrieval-dev serve --help
```

Both passed with server-only build context. Image config:
`sha256:3473d3c9721750b5e3845e1afae0636bf1b34d51f4bafeac3ee67e1cb30ee726`.
This is **Go-only**, without Python/models; the native worker is trusted same-UID,
with a sanitized offline environment, not an OS sandbox.
Main also used `python@sha256:ec948fa5f90f4f8907e89f4800cfd2d2e91e391a4bce4a6afa77ba265bc3a2fe`
with no network, read-only component sources and provisioned locked site-packages:
contracts-only mount **2090 passed**; server/ml-only mount **117 passed** with
`pytest -q -p no:cacheprovider`, no parent checkout/model. This proves isolated
execution with dependencies, not fresh offline installation; full ML typing/coverage
gates were verified natively. Actionlint, Bash syntax and `git diff --check` passed;
the memotrace Docker-container filter was empty after owned-container cleanup.
No hosted CI, new commit/PR/merge, device/private-archive, backup-restore, production
ANN-scale or Ego4D test is claimed. Real-video history quality remains unestablished.
