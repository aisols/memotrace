# Bounded object-search experiment

This is a runnable **experimental image-query diagnostic**, separate from the
production worker/index identity and generic retrieval evaluator. It uses the
existing verified **SigLIP2 Base224** full-image letterbox baseline, an exact fixed
semantic shortlist, actual **YOLOS-Tiny** proposals, and independent **DINOv2-small
CLS384** query/proposal descriptors. Scores from the two spaces are never blended.
It does not establish same-instance retrieval quality or persistent object identity.

## Run with separately acquired artifacts

Run from `server/` in the existing locked Python 3.12 CPU ML environment. All paths
below denote operator-selected **existing absolute external paths**, outside Git.
Set these shell variables to your actual paths; the runner has no acquisition mode.
The output parent must already exist; the output file must not exist (even with
identical contents). Models, images and output reject symlinks and writable/untrusted
artifact ancestry according to the existing artifact I/O policy.

```sh
uv run --locked --project ml python -m scripts.object_search_experiment manifest \
  --model-dir "$SIGLIP_BASE224_ROOT" --vision-root "$VISION_ROOT" \
  --manifest "$INPUT_MANIFEST" --output "$NEW_REPORT_JSON" \
  --threads 4 --batch-size 2 --top-k 20 \
  --max-detector-frames 100 --max-budget-ms 3600000
```

`--model-dir` must pass the existing pinned SigLIP verifier and identify
`google/siglip2-base-patch16-224`. `--vision-root` must pass
`scripts.object_search_vision.verify_models`, containing its separately acquired
`yolos-tiny/` and `dinov2-small/` sealed inventories. Loading uses explicit
`SiglipModel`, `YolosForObjectDetection`, `Dinov2Model`, `YolosImageProcessor` and
`BitImageProcessor`, local files only, safetensors, float32 CPU/eager/eval. There is
no tokenizer or remote-code model dispatch in the image-only runner.

The semantic identity is independently named
`object-experiment-siglip2-base224-image-only-v2`. It binds the verified model
manifest, this runner's source bytes, the complete packaged helper source inventory,
and `numerical_runtime_identity`: verified installed distribution RECORD content,
Python/ABI/libc/CPU features and Torch build information. Effective Torch/BLAS thread
settings, matmul/determinism flags, batch size, CPU float32/eager/eval execution,
letterbox preprocessing and normalization constants are included. Changing runtime
content without changing its version still changes the fingerprint. Source/model
root paths and mtimes are not part of this identity, so relocation preserves it.
Loaded semantic identities are detached snapshots; source, effective settings,
policy and execution-mode changes are checked around inference and before output.
Installed runtime content is verified at load rather than rehashed per image.
This uses the existing Base224 image computation without claiming the production
`SiglipEncoder` identity.

### Public Open Images adapter (up to 100 existing images, six image queries)

```sh
uv run --locked --project ml python -m scripts.object_search_experiment openimages \
  --model-dir "$SIGLIP_BASE224_ROOT" --vision-root "$VISION_ROOT" \
  --data-root "$VERIFIED_OPENIMAGES_V3_ROOT" --output "$NEW_REPORT_JSON" \
  --max-queries 6 --top-k 20 --threads 4 --batch-size 2 \
  --max-detector-frames 100 --max-budget-ms 3600000
```

The adapter requires the existing completed Open Images v3 acquisition, including
its original metadata/attribution/selection receipts. It calls the existing offline
`verified_acquisition` and verifies image bytes on every read. It neither downloads
nor repairs data. The input acquisition supports 48–100 source images; a verified
100-image root contributes all 100 sources before content deduplication.
`--max-queries` is 1–6, default 6.

The public query cohort follows `memotrace_ml.benchmark` image-source selection,
restricted to its **primary both-polarities group**:

1. Visit classes in the existing fixed class-profile order. Require at least two
   unique positive-content examples and at least one negative-content example.
2. Select the lexicographically first `image_id` with a positive raw judgment and
   a declared GT box, independent of acquisition order. A source may serve several
   class queries, as in the benchmark. Unboxed/ineligible classes do not consume
   the query limit.
3. Select its largest declared GT query box using the benchmark's float64 area
   calculation and stable annotation-order ties. The selected coordinates remain
   exact through validation and rasterization.
4. If that frozen query raster is below 32px on either axis, **fail explicitly**.
   Do not replace it with another source or box. Take the first `max_queries`
   eligible primary classes; report excluded classes and reasons.

The adapter calls the existing `content_corpus` and `content_judgments` helpers:
deduplicate exact SHA-256 content before class counts, indexing and metrics; use
the smallest-ID representative; merge known alias judgments; reject conflicting
positive/negative judgments for identical content. Query source content and all its
aliases are excluded. Alias counts and excluded source alias IDs are reported, so
duplicate images never add extra votes or ranking slots.

Each selected query reports its benchmark-compatible `<class>:image` ID and exact
signature `{class, source_id, source_sha256, box}`, plus signature/cohort hashes.
These identify queries that can be paired with an existing public benchmark report.
**Only the selected query crop** enters inference; candidate annotation boxes and
labels never enter semantic scoring, detection or descriptor computation. Candidate
relevance judgments are joined only after all blind runs. This is a declared
class-proxy diagnostic, not label-free query sampling or same-instance evaluation.

AP uses the complete judged ranking; primary mAP, mean Hit@K and mean Recall@K
include only queries retaining **both a positive and a negative after source-content
exclusion**. Eligible counts and exclusion reasons are reported separately for
baseline and reranked results. Hit@K and Recall@K use the first K entries of that
judged ranking. Unknown judgments are removed **only for metric calculation**;
`unknown@K` counts unknowns in the original, unfiltered top K. No-positive metrics
are null. Source-ID and exact-source-byte-hash matches are excluded before ranking,
and are therefore also excluded from metric denominators. These are class-level
metrics, not same-instance metrics; labels do not validate detector classes/boxes.
Open Images timestamps and detector temporal coverage are explicitly unknown.
Both baseline and reranked results are freshly computed in this run using the
same frozen queries and deduplicated candidates. Historical metric values are not
imported or presented as current evidence. The baseline uses the core's full-vector
cosine scorer; pairing signatures does not assert bitwise score identity with the
older benchmark's float32 dot-product scorer.

## Dataset-neutral schema 1

The manifest is one JSON object with exactly these fields:

| Field | Required value |
|---|---|
| `schema` | Integer `1` |
| `kind` | `frames` or `images` |
| `candidates` | Ordered array of 1–100 image records |
| `queries` | Exactly one query for `frames`; 1–6 for `images` |
| `coverage_gaps` | Explicit array, possibly empty, at most 100 gaps |

Every image record, including the query source, has exactly these fields:

| Field | Meaning |
|---|---|
| `id` | Unique candidate ID, 1–256 characters; no controls |
| `path` | Canonical relative `.jpg`, `.jpeg` or `.png` path under the manifest parent |
| `sha256` | Declared 64-character lowercase SHA-256 of the exact original bytes |
| `byte_length` | Exact integer byte length, 1–16 MiB |
| `stream` | Explicit stream ID |
| `timestamp_ms` | Exact nonnegative millisecond timestamp for `frames`; explicit null for `images` |
| `sequence_id` | Explicit episode/sequence ID; associations cannot cross it |

Use timestamps from an actual source clock. No FPS or timestamps are inferred from
array position or filenames. Candidate order must be strictly increasing within
each stream; streams may be interleaved. All frame timestamps must be known or
frame-mode parsing fails. The query source can be separate from the gallery. If its
ID exists in the gallery, its complete declared record must match that candidate.
Byte-identical gallery aliases are excluded even when their IDs differ.

Every query has exactly:

- `id`: unique query ID.
- `image`: the complete source image record above.
- `crop`: null for the whole declared query image, or normalized display-oriented
  `[x0, y0, x1, y1]`, rasterized floor-start/ceil-end using existing query crop code.
  JSON decimal/scientific coordinates are parsed exactly and retained as exact
  coordinates through validation and rasterization, without a float conversion.
  The resulting query must be at least 32px on each axis.
- `cutoffs`: for frames, a map from **every candidate stream** to its explicit
  exclusive cutoff timestamp; for images, null.
- `tracking_window`: null, or an explicitly ordered array of candidate IDs in a
  separately bounded chronological window. Each participating stream must be a
  consecutive slice of the supplied manifest, with at most 64 frames before cutoff
  filtering. The complete window has at most 100 frames. Only frame mode supports it.

For example, on a 64px-wide image, `[0.499999999999999999999,0,1,1]`
starts at pixel 31 and produces a 33px-wide crop. `5e-1` instead starts at pixel 32.
Coordinates such as `-1e-1000` or `1.000000000000000000001` are rejected before
underflow/rounding can make them appear valid. Reports serialize exact coordinates
as JSON numbers using the existing canonical serializer; equivalent scientific
notation may be normalized, but the coordinate value is retained. Integer-only
fields (`schema`, byte lengths, timestamps, cutoffs and gap endpoints) still require
JSON integer tokens; decimal/scientific tokens such as `1.0` and `1e0` are rejected.

Each coverage gap has exactly `stream`, `start_ms`, `end_ms`. It denotes an unknown
open interval; endpoints may be observed. Gaps must be positive, nonoverlapping,
and contain no supplied observation strictly inside. Gaps are clipped at the query
cutoff in reports. An empty gap list declares no additional known missing intervals;
it does not establish continuous visibility between observations.

Images decode only as single-image JPEG/PNG, with EXIF orientation applied and ICC
ignored. Source geometry is checked **before full decode**: 32–2048px edges and
at most 4,000,000 pixels. Animated/multi-frame sources fail. All inference uses those
display-oriented RGB pixels. Candidate GT boxes are not part of this schema.

## Ranking, history and work bounds

1. Cache one normalized 768-dimensional full-image semantic vector per candidate,
   shared by all queries. Query pixels use the same Base224 preprocessing.
2. Exclude source ID, source hash and frames at/after their stream cutoff. Rank all
   eligible full vectors by cosine; exact ties use the core's stream/frame keys.
3. Select exactly the first `min(top_k, eligible_count)` IDs. No labels, detector
   scores or descriptor scores alter this membership.
4. Run YOLOS only for these frames and any explicitly requested tracking window.
   Keep at most 20 proposals, score >0.20, excluding N/A classes, using the vision
   adapter's clipped half-open raster bounds and minimum 16px crop edges.
5. Encode query/proposals with DINO CLS384. The core currently permits a full-image
   DINO fallback **only when YOLOS returns zero proposals**. Fallbacks carry no
   detection/class observation. This is not an always-competing full-image row.
6. Rerank only the fixed prefix by max query/proposal DINO cosine. Stable instance
   ties retain semantic order; the original semantic tail remains unchanged.
7. Without an explicit tracking window, timed results contain query-supported
   singleton proposals and explicitly unknown chronological coverage. A sparse
   relevance shortlist is never presented as observed tracking.
8. With a window, process every eligible supplied frame in order, including frames
   where YOLOS returns no proposals. Source/hash-excluded frames remain explicit
   barriers without detector inference; future frames are removed before tracking.
   Associate only adjacent-frame, same-stream/same-episode proposals with the core's
   mutual unique-best class/appearance/geometry rules. Return only tracklets touching
   a shortlist query-winning proposal. Empty frames, recorded gaps, ambiguity and
   episode boundaries break links. No later episode is merged back into a tracklet.

The core's current conservative association rules are cosine >=0.85, IoU >=0.10,
gap <=1500ms, joint score `(cosine+IoU)/2`, and mutual best margin >=0.05. Thresholds
are uncalibrated; even linked frames have unknown visibility between timestamps.
For untimed image ranking, the core receives isolated one-record eligibility sets
with internal 0/1 sentinels; these are never emitted as acquisition times and never
passed to temporal association. All public timestamps remain null.

The baseline is fixed to threads4/batch2. Detector batch size is one. Semantic and
DINO batch size is at most two. The shared detector cache is bounded by
`--max-detector-frames` (1–100, default 100); exhaustion fails instead of silently
dropping shortlist members. Retained proposal descriptors are bounded above by
`100 * 21 * 384` float32 elements; actual fallback-only-on-empty uses fewer. Query
descriptor work adds at most six rows. Source rasters are not cached. Core vector,
observation, scoring and per-stream window budgets remain enforced independently.
The manifest limit is 1 MiB and output limit 16 MiB. `--max-budget-ms` is 1–3,600,000,
including verification/loading/publication; a Linux timer and stage checks abort
over-budget runs. Python signal delivery may wait for an active native inference
call to return; this is not a hard native-kernel preemption guarantee.

## Report and verification

`memotrace-object-search-experiment-v1` reports model artifact versions/hashes,
separate semantic/descriptor identities, implementation hashes, options, source
exclusions, original full rankings and reranked prefixes/tails, proposal geometry
and filtering counts, shared-cache work, stage timers, and temporal coverage.
Publication is atomic and exclusive. Immediately before publication it rechecks
model inventories/bytes, source identities, manifest/acquisition/query identities
and every input image hash/length. Keep roots stable during the run; same-UID
change-and-restore races are not a sandbox boundary.

```sh
uv run --locked --project ml python scripts/verify_object_search.py
```

The dedicated CI step checks all six new runner/core/vision source and test modules
plus the verifier with Ruff, format and strict mypy. Pytest runs synthetic
end-to-end real-core/fake-expensive-adapter tests and the existing vision/core
suites, including real tiny tensor/model computations without pretrained weights.
The verifier enforces **at least 95% statement coverage for
`scripts/object_search_core.py` individually**; branch counts are reported
separately and cannot compensate for missing statements. This per-file statement
gate has been independently approved in review. Regression tests cover exact crop
boundaries, scientific notation, underflow/overflow rejection, report round trips,
and preservation of integer-only manifest fields. Additional tests use synthetic
installed distribution RECORDs and a tiny genuine Torch feature computation to
exercise semantic runtime/source/settings fingerprints, relocation stability,
frozen primary query selection, unsupported-query failure and alias deduplication.
The generic evaluator's existing gates are unchanged.

Synthetic checks establish mechanics, not real-model quality or device evidence.
Main-agent verification must separately run the actual vision command above on
the verified 100-image public root, inspect the report at the latest revision, and
record runtime/results and these class-proxy limitations. No production ML package
files, weights, datasets or generated reports are added by this slice.
