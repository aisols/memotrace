# Server Benchmarks

An executable **Open Images image-ranking pilot** now compares genuine CPU SigLIP2
full-frame letterboxing with full-frame plus overlapping crops. Runners belong to
the autonomous server Python package in [`../ml/`](../ml/README.md). Downloaded
models, JPEGs, annotation contents, attribution and machine reports remain outside
Git. All committed test images are generated synthetic fixtures.

The [historical everyday-object evaluation](everyday-object-evaluation-2026-09-10.md)
consolidates pre-hardening thread, checkpoint and 100-image Base384 data/language
measurements. The [dated main verification](../docs/retrieval-main-verification-2026-09-10.md)
records matching pre-hardening local gates and genuine Go/PostgreSQL/CLI/TLS evidence.
Current live evidence requires fresh v3 acquisition and a model/data rerun. The
[2026-09-09 main report](../docs/retrieval-main-verification-2026-09-09.md) is
historical evidence for its exact Base224-era source and identities.

The benchmark allowlist is closed to these pinned candidates:

| Checkpoint | Revision | Letterbox | Dimension | Parameters |
| --- | --- | --- | --- | --- |
| `google/siglip2-base-patch16-224` | `75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2` | 224×224 | 768 | 375,187,970 |
| `google/siglip2-base-patch16-384` | `f775b65a79762255128c981547af89addcfe0f88` | 384×384 | 768 | 375,479,810 |
| `google/siglip2-so400m-patch16-384` | `dd658faac399427308559e2c3ac1e99cbe43845d` | 384×384 | 1,152 | 1,136,039,602 |

Every selected full image, overlap region, and image-query crop is edge-preserving
letterboxed to that checkpoint's resolution. Base224 behavior remains 224×224;
384 processes about 2.94 times as many input pixels and is not a center crop. The
resolution-specific preprocessing version and exact manifest enter model identity.
Each checkpoint therefore needs separate model fingerprints, full/overlap generations,
indexes, and report names; never compare or combine their vectors as one generation.
SO400M has a 4,544,267,488-byte float32 weight file and needs substantial additional
runtime memory plus more CPU for 384-pixel crops. Measure it only on a separately
provisioned host with explicit memory monitoring.

## Repeat the public-data experiment

From **`server/`**, with Python 3.12 and uv 0.11.3:

```bash
uv sync --locked --project ml
uv run --locked --project ml python -m memotrace_ml.acquire \
  --model-dir /tmp/opencode/memotrace-search-models/siglip2-base-patch16-224
uv run --locked --project ml python -m memotrace_ml.openimages \
  --data-dir /tmp/opencode/memotrace-openimages-everyday-v3 --count 100
uv run --locked --project ml python -m memotrace_ml.benchmark \
  --model-dir /tmp/opencode/memotrace-search-models/siglip2-base-patch16-224 \
  --data-dir /tmp/opencode/memotrace-openimages-everyday-v3 \
  --output /tmp/opencode/memotrace-openimages-everyday-v3/report-base224-repeat.json \
  --threads 4 --batch-size 2 --image-queries --gt-query-crop
uv run --locked --project ml python -m memotrace_ml.summary \
  --report /tmp/opencode/memotrace-openimages-everyday-v3/report-base224-repeat.json
```

The command without `--model-id` intentionally retains the Base224 default. Acquire
the other approved checkpoints into distinct roots before running the same benchmark
with the corresponding `--model-dir` and a fresh output filename:

```bash
uv run --locked --project ml python -m memotrace_ml.acquire \
  --model-id google/siglip2-base-patch16-384 \
  --model-dir /tmp/opencode/memotrace-search-models/siglip2-base-patch16-384

uv run --locked --project ml python -m memotrace_ml.acquire \
  --model-id google/siglip2-so400m-patch16-384 \
  --model-dir /tmp/opencode/memotrace-search-models/siglip2-so400m-patch16-384
```

The benchmark is offline and requires pre-acquired weights and a verified dataset.
It does not download missing inputs. Live acquisition/benchmark/smoke are separate
explicit commands, never part of `memotrace_ml.verify` or ordinary CI. Omit
`--gt-query-crop` for full-source-image queries; omit `--image-queries` for text only.
Each invocation independently builds both full and overlap indexes, including the
full vector in both, and measures their complete in-process image pipelines.
Reports are published without clobbering existing different files. Use a new report
filename for each independent repeat; historical reports retain their original hashes.
The command above is a new Base224 repeat and must use a fresh filename. The
[final P2 builder checks](final-p2-verification-2026-09-09.md) and earlier pilots are
retained as historical evidence for their recorded source revisions. The historical
2026-09-09 main run indexed 48 distinct images with zero aliases: 48 full vectors in
8.181652918 s and 322 overlap vectors in 48.689717340 s; see its record for judged
metrics, resources and limitations. Do not attribute those measurements or identities
to the current matrix.

### Official data and selection

Use the public [Open Images V5 validation annotations](https://storage.googleapis.com/openimages/web/download_v5.html)
and the [officially linked CVDF image mirror](https://github.com/cvdfoundation/open-images-dataset).
The runner downloads four bounded metadata CSVs from the official Google bucket:
class names, validation boxes, human image labels, and image/rotation/license
metadata. Source URLs and verified SHA-256 hashes are recorded in `selection.json`;
the known metadata hashes are pinned in `memotrace_ml/openimages.py`. It fetches
only individual selected JPEGs over public unsigned HTTPS, never a dataset archive.
Metadata is limited to 128 MiB/file, JPEGs to 16 MiB, with bounded streaming/retries
and timeouts. A partial acquisition records failures/missing counts and exits nonzero.
The downloader validates every redirect before following it, resolves and pins public
destination addresses, retains TLS verification, and uses a parent subprocess deadline
covering DNS/headers/trickled bodies. Directory/file symlinks cannot redirect writes;
exclusive random staging and atomic no-clobber publication replace fixed partial paths.
JPEG decode and identity-EXIF eligibility run against the owned staging body before
publication. Invalid or rotated candidates are recorded as failures without leaving
extra files among eligible images. Unexpected existing files still fail verification
and are never deleted to hide drift.

Candidate ordering is deterministic: fixed class order, positive then negative
buckets, sorted public IDs, round-robin with cross-bucket ID deduplication. Because
the attempt budget is bounded, transient download or validation failures can change
which later candidates fill the selected subset; ordering alone does not guarantee
an identical selection. `--count` is bounded to 48–100, and at most twice that number
of image candidates is attempted. The operative everyday-object v3 profile contains
exactly these classes in selection and query order:

| Class | Open Images MID |
| --- | --- |
| Screwdriver | `/m/01bms0` |
| Scissors | `/m/01lsmm` |
| Hammer | `/m/03l9g` |
| Knife | `/m/04ctx` |
| Pen | `/m/0k1tl` |
| Bottle | `/m/04dr76w` |
| Mug | `/m/02jvh9` |
| Mobile phone | `/m/050k8` |

Use a fresh acquisition root and `--count 100` for new or future checkpoint
comparisons. The recorded 2026-09-10 three-checkpoint comparison used the historical
48-image profile and remains provisional staged evidence; it was not rerun across all
models on the subsequently hardened implementation or everyday-object v3 data. This
broader eight-class profile supersedes the narrow five-class tools pilot for future work.
Selection evidence preserves every class's source, eligible, selected and unknown
counts. Expected/actual benchmark evidence must retain all eight classes: a class
without both judged polarities remains in per-query/source evidence and is named in
the aggregate `excluded_queries` with `no_positive` or `no_negative`, never silently
dropped to improve the macro result.

Only metadata-declared CC BY 2.0 images with known **zero dataset rotation** and
identity JPEG EXIF orientation enter this initial pilot. This explicitly scoped
filter preserves the published CVDF JPEG unchanged and maintains official box
coordinate agreement.
Open Images documents why dataset rotation and EXIF must not be conflated in its
[rotation announcement](https://storage.googleapis.com/openimages/web/2018-05-17-rotation-information.html).
The general worker handles all EXIF orientations; this dataset adapter does not
re-encode or pretend to recover unknown image orientation.

Open Images annotations are attributed to Google LLC under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); image licenses are
declared per source as [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/).
`attribution.json` retains declared license, author, author-profile, original and
landing URLs externally. Its `original_size` and `original_md5` fields are official
metadata for the original Flickr content; the nested `download` source, SHA-256 and
byte length identify the actual resized CVDF artifact. License status is based on the
official metadata, not a claim of a new live audit of every Flickr page.
Images/attribution are not redistributed in this repository. See the dataset's
[license statement](https://storage.googleapis.com/openimages/web/factsfigures_v7.html#licenses).

### Index input versus ground truth

The generated `manifest.json` is exactly the server-owned shared importer format:

```json
{
  "version": "1",
  "dataset": {"name": "...", "version": "...", "source": "...", "license": "..."},
  "items": [{
    "id": "public-source-id", "path": "images/public-source-id.jpg",
    "sha256": "64-lowercase-hex", "byte_length": 12345,
    "observed_at_ms": null, "sequence_id": null, "sequence_position_ms": null
  }]
}
```

`path` is relative to the manifest directory. The generated manifest has **no
labels, boxes, captions, author names or titles**. The Go importer must verify
bytes/hash/length and resolve paths under that directory. The Python verifier
also rejects path traversal, duplicate IDs, escaping symlinks and unsafe clocks.
Open Images always uses null for all three time fields: no calendar, sequence,
Android capture, `request_wall_ms=0`, or chronological history is fabricated.
The format can carry genuine future sequence IDs and safe-integer PTS milliseconds;
the adapter must supply documented source provenance before these count as evidence.

`ground-truth.json` holds per-class human judgments and boxes separately.
`selection.json` records source counts, eligibility losses, source checksums,
selection policy and selected IDs. `acquisition.json` records manifest/ground-truth
hashes and acquisition duration. The benchmark verifies every indexed JPEG and
records the dataset, selection and ground-truth hashes in its report.

Resume requires a **completed trusted local `acquisition.json` receipt** whose
manifest, ground-truth and selection hashes verify, followed by verification of
every manifest JPEG's actual CVDF SHA-256/length, the matching attribution download
record, and the pinned source metadata. Existing
unreceipted JPEGs, changed valid JPEGs, receipt/manifest drift, image-directory
symlinks and unrecognized extra images fail before metadata can be rewritten.
A successful completed resume reuses the existing files and receipt unchanged.
Incomplete/unreceipted directories are not automatically refreshed or blessed;
use a fresh acquisition root for a new acquisition. New receipts additionally pin
attribution. Completed roots must match the exact everyday-object v3 selection,
ground-truth, attribution and dataset profile. Earlier v2 and five-class pilot roots
fail before any JPEG reuse and remain historical evidence only. This is local
provenance validation, not a cryptographic signature against an operator able to
change the receipt itself.

### Ranking and metric definitions

For each class and each `full`/`overlap` spatial index, the benchmark emits three
text-evaluation groups. `ru` embeds the manually curated Russian query; `en` embeds
its manually curated equivalent English evaluation translation. Both independently
rank the same complete candidate set by maximum per-asset cosine. `fusion` combines
those two complete rankings with deterministic two-ranking Reciprocal Rank Fusion:
`score(id) = 1/(60 + rank_en(id)) + 1/(60 + rank_ru(id))`, using one-based ranks and
identity tie-breaking. Fusion output labels values as `rrf_score`, not cosine scores,
and rejects duplicate IDs or different component candidate sets.

The component `en` and `ru` query results remain in the report. Fusion metadata records
fixed `k=60`, method, component query IDs, reused component embedding/ranking durations,
and additional fusion duration, so reuse does not imply free embeddings. The English
phrases are curated benchmark inputs, not output from an automatic translation model.
These pairs test bilingual retrieval potential but do not measure any translator's
latency, quality, privacy, or production behavior. There is no translation dependency,
and the production worker/search API is unchanged.
New reports use `openimages-retrieval-pilot-v3`; the summary command retains the
both-polarities macro interpretation for historical v2 reports.

For each image query, deterministically choose the lexicographically first selected
boxed positive. With `--gt-query-crop`, use its largest official box **only as the
query crop**. Candidate indexing always uses the deterministic image policy and
never sees labels or ground-truth boxes. Exclude the source image and **all its
regions and SHA-256-identical aliases** before any scoring/ranking. A class needs
another distinct positive content hash for an image-query score.

An asset's score is the maximum cosine over its indexed regions. Rank unique
content candidates by descending score, breaking ties by ID. Verified SHA-256 bytes
define content identity; the lexicographically smallest ID represents identical
bytes, and aliases are deduplicated before indexing/scoring. Human judgments for
aliases merge known/unknown values, but conflicting positive/negative judgments
explicitly reject the benchmark. The external report retains
all corpus ranks and unknown counts in the original Top-K. A relevant asset means
the same **class**, not the same physical object.

Metrics use a **condensed per-class judged corpus**: remove unknown judgments from
the ranked list without marking them negative. A positive/negative is specifically
a `verification` or `crowdsource-verification` label with confidence 1/0. Missing
annotations and machine labels are not negatives. Let `P` be known positives in
the candidate corpus after source exclusion:

- `Hit@K = 1` if at least one positive is in the first K judged assets, otherwise 0.
- `Recall@K = known positives among first K judged assets / P` (a fraction).
- `AP = sum(precision at each positive's judged rank) / P`, over the entire judged list.
- With `P=0`, these metrics are null. **Primary macro averages require both known
  positive and known negative content candidates**, after query-source exclusion.
  They report query counts and exclusion reasons (`no_positive` / `no_negative`).
  Positive-only classes remain in per-query output and an explicitly labeled
  `secondary_positive_only_macro_averages` diagnostic, not the primary score.
  Nulls are not forced to zero or counted as successful queries.

This judged policy permits meaningful annotation-aware comparisons but can be
optimistic relative to deployment: unknowns can occupy real result slots, and a
class with no verified negatives yields a trivial judged ranking. Always read
judged/unknown counts alongside aggregate scores. These are neither official
Open Images detection scores nor **Ego4D VQ** scores, instance identity, or history
quality. The [historical 2026-09-10 evaluation](everyday-object-evaluation-2026-09-10.md)
documents these limits and the identities measured at its pre-hardening source.
The [2026-09-09 main report](../docs/retrieval-main-verification-2026-09-09.md) and
[preceding measured report](openimages-pilot-review-v2-2026-09-09.md) are historical.
The
[original pilot](openimages-pilot-2026-09-09.md) retains
its historical positive-only aggregate and original artifact hashes.

The report includes genuine model fingerprints, generation IDs, parameter count,
dimensions, configured threads/batches, model-load duration, image/region counts,
latencies, query/ranking durations, Linux peak RSS, and full query metrics. One
fixed-order small-subset run is not sustained throughput or an overnight-capacity
measurement. JSONL transport, Go persistence/search and DB time are separate gates.

## Deferred video/history research

[Ego4D access](https://ego4d-data.org/) is pending; no gated data, credentials,
licensed downloader or fabricated video API is implemented. Its
[visual queries task](https://ego4d-data.org/docs/benchmarks/episodic-memory/)
needs source-video/frame provenance and official task evaluation before any
Ego4D score claim. Future sampling must record source FPS/time base and actual
frame PTS, including any resampling, and apply the query cutoff before ranking.
Frame number divided by a guessed FPS is not evidence. Open Images provides no
temporal/cutoff or first/last-observed evidence for this deferred work.

The [generic blind/staged evaluator](../docs/retrieval-evaluation.md) now supplies only
model-free planning, ranking, and post-ranking metric primitives for a future licensed
runner. It contains no dataset parser or private fixture and does not change any access,
official-metric, tracking, or timestamp limitation above.
