# Bounded object retrieval and candidate history

**Unreleased experiment.** Go stores owner/archive-scoped assets and PostgreSQL
`real[]` vectors, then streams a complete bounded generation for **exact cosine**.
There is no pgvector/ANN implementation or full-archive throughput claim. The
optional [pinned offline SigLIP2 worker](../ml/README.md) supports the approved
candidate set. Open Images acquisition/evaluation support is implemented, but no
author-machine model or dataset path is assumed available. The
[2026-09-14 evidence record](../benchmarks/object-search-experiment-2026-09-14.md)
documents a passing 100-image genuine-model Go CLI/TLS smoke with independent exact-
query matching, plus the first usable [offline object-search experiment](object-search-experiment.md)
and public/private diagnostics. Actual source hashes bind uncommitted experiment
work over `39b24e3`. Production remains **Base224 full**; the separate proposal/
descriptor runner adds no history endpoint, database object association or user
confirmation. Its narrow PTS scan leaves canonical content/frame-zero and whole-
cohort timing unestablished; official VQ2D evaluation was not run. Server-source
extraction passed with provisioned dependencies; hosted delivery/deployment and
production gates remain pending.
Encryption deployment is deferred only for public/synthetic experiments.

## Operating commands

Run from `server/`, after the [database setup](../README.md#database-provisioning)
and migration. `MEMOTRACE_ADMIN_DSN` is used only by `migrate`, `create-archive`,
`invite` and `revoke-device`. `MEMOTRACE_DSN` selects the separate nonowner runtime
role for **dataset-import, index, search, history and serve**. Never use an admin
DSN as the runtime DSN: startup validates role privileges and all eight RLS tables.
Local retrieval commands select an archive using the existing scoped-recovery
capability, then ordinary transaction-local RLS. They are trusted operator commands,
not a device authorization interface. HTTP uses archive-scoped device credentials.

**Stop serving before local import/index/search/history.** All these commands and
`serve` acquire the same exclusive data-root flock. Use one data root per database.
The operator pre-creates an absolute private 0700 data directory. Dependencies and
verified model files are installed before invoking the offline worker:

```sh
mkdir -p .build
go build -trimpath -o .build/memotrace ./cmd/memotrace
uv sync --locked --project ml
```

Acquire and verify a selected approved model using the
[model instructions](../ml/README.md#explicit-model-acquisition-and-live-smoke), and
acquire a fresh everyday-object v3 root using the
[public-data instructions](../benchmarks/README.md#repeat-the-public-data-experiment).
Set operator-owned absolute paths before continuing:

```sh
: "${MODEL_DIR:?set MODEL_DIR to an absolute verified model directory}"
: "${MANIFEST:?set MANIFEST to an absolute verified v3 manifest.json}"
WORKER=$(python3 -c 'import json,sys; print(json.dumps(["uv","run","--locked","--project","ml","python","-m","memotrace_ml.worker","--model-dir",sys.argv[1]]))' "$MODEL_DIR")
```

The argv array is a trusted local CLI setting. Shell operators, command strings,
public request fields and arbitrary remote commands are not interpreted. For other
working directories use absolute project/model paths. After securely provisioning
the operator DSNs, and selecting `ARCHIVE_ID` from `create-archive` JSON and the
private `DATA_ROOT`:

```sh
.build/memotrace migrate
.build/memotrace create-archive
.build/memotrace dataset-import --archive "$ARCHIVE_ID" --data-root "$DATA_ROOT" \
  --manifest "$MANIFEST"
.build/memotrace index --archive "$ARCHIVE_ID" --data-root "$DATA_ROOT" \
  --mode full --worker-argv "$WORKER"
INDEX_REPORT=$(mktemp /tmp/opencode/memotrace-index-overlap.XXXXXX.json)
.build/memotrace index --archive "$ARCHIVE_ID" --data-root "$DATA_ROOT" \
  --mode overlap --worker-argv "$WORKER" > "$INDEX_REPORT"
```

Import emits `archive_id`, `manifest_sha256`, and ordered `items` mapping each
`item_id` to its persistent `asset_id` and `sha256`. Index emits `generation_id`,
`mode`, `completed`, `failed_attempts` and coverage. **Use the emitted generation**:
Go obtains dimensions/policies from `describe`, rather than assuming 768 or a
fixed generation across runtime changes. Full/overlap have independent generations.
Index `--max-jobs` is a claim-attempt budget, 1..15000, default 15000. A repeat
queues newly available assets and resumes pending/expired work, preserving completed
results and terminal failures. An index containing failed assets emits its report
and exits nonzero. Terminal failures require operator investigation; the CLI does
not silently reset attempts or discard generation state.

Search/history read request JSON from stdin or `--request /absolute/request.json`.
Input must complete with EOF within30s. SIGINT/SIGTERM cancels and closes the pollable
input descriptor promptly; input validation finishes **before** acquiring the
data-root lock or opening PostgreSQL. Named request files must be regular files;
use stdin for a pipe/terminal stream. FIFOs/devices/directories supplied as request
file paths are rejected without a blocking open or archive lock.

```sh
.build/memotrace search --archive "$ARCHIVE_ID" --data-root "$DATA_ROOT" \
  --worker-argv "$WORKER" --request /absolute/search.json
.build/memotrace history --archive "$ARCHIVE_ID" --data-root "$DATA_ROOT" \
  --worker-argv "$WORKER" --request /absolute/history.json
```

Generate a request from the actual saved index report instead of assuming an old
model/generation fingerprint (implementation/preprocessing changes create new ones):

```sh
python3 -c 'import json,sys; r=json.load(sys.stdin); print(json.dumps({"generation_id":r["generation_id"],"query":{"text":"отвёртка"},"limit":20,"min_score":0.1},ensure_ascii=False))' < "$INDEX_REPORT" |
  .build/memotrace search --archive "$ARCHIVE_ID" --data-root "$DATA_ROOT" --worker-argv "$WORKER"
```

The same shape is a valid history request because `min_score` is explicit. Image
query replaces `query` with an imported `asset_id` and optional `box:[0.1,0,0.9,1]`;
omit `box` for the full image. No source path, original base64 or annotation enters
the public request. Selected region coordinates follow the worker's EXIF-oriented
display geometry. Query original bytes are read and verified from private storage.

To serve queries using the already populated index, with **only the runtime DSN**
in the service environment:

```sh
.build/memotrace serve --data-root "$DATA_ROOT" \
  --cert "$TLS_DIR/cert.pem" --key "$TLS_DIR/key.pem" --worker-argv "$WORKER"
```

Without `--worker-argv`, ingestion works and search/history return authenticated
503 `unavailable`. Asset originals remain available without inference. There is
no automatic online indexing scheduler: stop service and run `index` to process
new committed frames. Health/pair/invitation/receipt remain wire 0.1.0. Retrieval
responses are wire 0.2.0 with the exact routes and fields in the embedded
[schema](../internal/contract/snapshot/schemas/retrieval.schema.json) and
[OpenAPI](../internal/contract/snapshot/openapi/retrieval.json).

## One-command genuine-model CLI/TLS smoke

This explicit experiment provisions **its own uniquely labelled disposable PG15**,
random passwords and ephemeral loopback port. It does not read/use an operator DSN.
It creates an owner/archive, imports exact JPEGs, indexes both policies, searches
English/Russian through the CLI, checks image-source exclusions/null history, starts
TLS, issues/redeems a verified invitation, and queries/reads originals over HTTP.
The worker is the real offline Python model, with no synthetic production fallback.
It downloads no dataset or model and calculates no retrieval-quality metrics. Use
the operator-defined, pre-acquired and verified `$MODEL_DIR` and `$MANIFEST` paths
from the setup above. The [latest smoke evidence](../benchmarks/object-search-experiment-2026-09-14.md#genuine-model-go-clitls-smoke)
records 100 images, 100/668 full/overlap vectors, zero failures, passing CLI/HTTPS
operations and 7/7 response schemas. Independent recomputation used the exact smoke
texts, which differ from the historical benchmark. Raw evidence remains external;
single-sample timings do not establish warm p95 or deployment readiness.

```sh
mkdir -m 700 /tmp/opencode/memotrace-go-search-smoke
python3 scripts/retrieval-smoke.py \
  --model-dir "$MODEL_DIR" \
  --manifest "$MANIFEST" \
  --output-dir /tmp/opencode/memotrace-go-search-smoke \
  --threads 16 --batch-size 4
```

Create the output parent once; subsequent runs use a new random subdirectory.
Requirements: built `.build/memotrace`, Docker, Python 3, OpenSSL, uv and installed
ML dependencies/model. The script preserves private experiment originals, public
result JSON and the ephemeral TLS key under that external output; its own PG
container/database is removed in `finally`, after terminating its own server.
It never deletes an operator database/root. This runner is specifically for the
Open-Images unknown-time manifest; it fails if temporal history is fabricated.

Validate the actual saved CLI/TLS response bodies using the genuine embedded
JSON Schema 2020-12 validator (substitute the emitted run directory):

```sh
MEMOTRACE_RETRIEVAL_EVIDENCE_DIR=/absolute/go-smoke-RUN \
  go test ./internal/contract -run '^TestExternalGenuineRetrievalEvidence$' -v
```

## Bounded scope, ranking and time meanings

- Entire authorized archive: **at most 5000 assets**; requested generation: **at
  most 50000 stored regions**, with <=64 regions/image and dimension 1..4096.
  Above either limit return 503 **before query filtering/ranking**. No silent
  top-N pre-scan or partial corpus presented as complete. Coverage is counted
  before source/cutoff/score filtering.
- Stream every stored region in a repeatable-read snapshot; exact cosine, maximum
  per asset; score descending then UUID ascending, tied regions prefer full then
  lexicographic box. Many tiles cannot occupy multiple Top-K asset places.
- Exclude the image-query asset **and all identical-SHA aliases**, including all
  their full/crop regions, before ranking. Text matches are semantic candidates;
  image queries do not prove the same physical object.
- `min_score` is an inclusive **cosine threshold**, not confidence/probability.
  The threshold remains an exact decimal, normalized once per search; `1e-400`
  excludes a zero-score hit instead of rounding onto zero. Query box endpoints remain raw JSON
  numbers through private IPC: exact ordering/ranges are checked with work bounded
  by input length, including enormous exponents, and Python rasterizes floor/ceil
  on those decimals before float conversion. Positive-area boxes such as
  `[0,0,1e-400,1]` and `[0.5,0,0.50000000000000001,1]` preserve touched pixels rather
  than collapsing to zero area. Returned candidate-region boxes remain float64.
  Duplicate/case-aliased/unknown members, invalid Unicode, null nonnullable fields,
  nonfinite values, invalid normalized geometry and fractional integer fields fail.
  Ingestion's old mathematical-integer normalization remains separate and intact.
- Explicit `timeline:{kind:"wall"}` selects actual request wall time for frames or
  manifest wall time for datasets. `timeline:{kind:"sequence",sequence_id:"..."}`
  selects only that sequence. A non-null `before_ms` requires a timeline and
  excludes unknown/other-clock time as well as timestamps at/after the cutoff.
  Filtering occurs before cosine scoring, asset aggregation and history grouping.
- History groups qualified observations by chronological gap in exactly one clock.
  **First/last and each group's bounds/max score come from all qualified indexed
  observations**, before the response evidence budget. `limit` (default20,max100)
  is a total hit budget selected by score across groups/unsequenced hits. Groups
  lacking selected evidence are omitted; included group evidence is chronological.
  `truncated=true` means evidence was omitted or indexing coverage is incomplete.
- No timeline or no matching clock: `history_available=false`, empty observations,
  null first/last, ranked `unsequenced_hits`. Other-clock hits without a cutoff are
  unsequenced, never merged with the selected clock. Open Images supplies no wall
  or sequence clock and cannot acquire fabricated chronology. Legacy sessionless
  elapsed time is never promoted into a shared sequence.

## Persistence and worker boundary

The append-only `migration_v2.sql` backfills committed frame assets and installs an
invoker trigger for newly committed frames; originals/metadata/v1 SQL are unchanged.
Every asset has a server-generated UUID distinct from its optional legacy frame ID.
Client-chosen frame UUIDs therefore cannot collide with dataset asset identities.
Dataset assets are independent records, never fabricated Android captures.
Dataset manifest paths are relative to the manifest directory, bounded by `os.Root`,
validated against traversal and final symlinks. Exact SHA/length/header validation
precedes durable publication under `asset-ARCHIVE_UUID_ASSET_UUID.jpg` (0600).
Manifest metadata/path/hash are private provenance; labels/annotations never enter
model input. Manifests are <=4MiB, <=5000 items and <=512MiB declared JPEG bytes.
Each dataset name, version and item ID remains limited to 256 Unicode scalars, and
their combined UTF-8 encoding is additionally limited to 1024 bytes. The same
bound is a database CHECK, keeping the non-hashed unique identity safely below
PostgreSQL B-tree tuple limits.
An idempotent repeated manifest returns the same assets. Metadata conflicts fail;
import SQL is atomic. A failed transaction may leave an unreferenced durable JPEG,
preserved for operator inspection, never acknowledged as a committed dataset asset.

Generations pin the exact description/dimension/model/policy identity. Index jobs
have at most three persistent attempts and 10-minute leases with random UUID tokens.
The lease gives the supported 5-minute worker request an explicit 5-minute margin
for archive reads, result validation, database writes and commit.
Claim uses `FOR UPDATE SKIP LOCKED`; expired final attempts become failed. A result
must match generation, dimensions, finite unit norm, geometry, kinds and region
budget. Lease/token/revocation are rechecked in the transaction writing all regions
and completing the job. Malformed inference consumes a persistent attempt. Stale
claims cannot finish or fail a replacement claim. A SQL COMMIT failure cannot expose
partial vectors/completion. Existing ingestion pending jobs keep their old meaning.

One serialized worker, no waiting request queue; busy is 503. JSONL input <=24MiB,
output <=2MiB, retained stderr <=8KiB, default per-call timeout75s (configurable
positive through5m), outer HTTP90s. Child death, malformed output, wrong IDs/model/
policy/dimensions/norms or cancellation discard/kill its process group; the next
request spawns a new worker. Request rejection is generic400 for unsupported text;
valid image queries whose stored JPEG fails full decode/inference are generic503,
even when ingestion's SHA/length/header checks previously passed. Service/model
failure is generic503. No child diagnostics reach public errors.
The child gets a fixed offline environment and fresh temporary HOME, **no inherited
DB/admin/AWS/device secrets, PYTHONPATH or loader configuration**. uv must use the
already installed project environment; downloads/sync are disabled for inference.
This is a trusted same-UID local subprocess, **not an OS filesystem/network sandbox**.
It has no SQL/job API or DB orchestration; OS-level filesystem/egress isolation is
a deployment concern and is not claimed by this experiment.
