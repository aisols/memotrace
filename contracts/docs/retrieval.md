# Retrieval protocol 0.2.0 — normative development contract

**Unreleased.** This document supplements `schemas/retrieval.schema.json` and
`openapi/retrieval.json`. Bundle `0.2.0` contains retrieval wire `0.2.0` and the
byte-identical ingestion wire `0.1.0`. Existing health, invitation, pairing,
manifest and receipt responses continue to emit `0.1.0`, with their original
fields and meanings. See [versions and snapshots](releases.md).

MUST/SHALL statements are conformance requirements, not evidence of completed
server, model, dataset, deployment, or Android verification. All examples here
are synthetic. No measured retrieval quality or benchmark is claimed.

## HTTP surface and shared rules

| Method and path | Request | Success |
| --- | --- | --- |
| `POST /v1/archives/{archive_id}/search` | `SearchRequest` | `200 SearchResponse` |
| `POST /v1/archives/{archive_id}/history` | `HistoryRequest` | `200 HistoryResponse` |
| `GET /v1/archives/{archive_id}/search/assets/{asset_id}/original` | No body | `200 image/jpeg` exact original |

Reuse ingestion's [transport, lossless JSON and authorization](protocol.md)
requirements: HTTPS/TLS >=1.2, UTF-8 `application/json`, every response carrying
`Cache-Control: no-store` and `X-Content-Type-Options: nosniff`. Both POSTs have
a **1,048,576-byte** received-body limit, independent of declared Content-Length.
Originals remain **1..16,777,216 bytes**; success requires `Content-Length` equal
to the verified returned byte count. Preserve the exact JPEG, including EXIF;
do not return the matching crop in place of the original.

All three routes require the same archive-scoped device credential. The HTTP
authentication scheme is **case-insensitive** (`Bearer`, `bearer`, `BEARER`, mixed
case); the token is **case-sensitive** and retains the exact ingestion token
length, unpadded base64url alphabet and zero-pad-bit rules. Every 401 MUST emit:

```http
WWW-Authenticate: Bearer realm="memotrace"
```

Header names are case-insensitive; emit the challenge value as shown. Query
assets, index coverage, evidence, and original reads MUST be scoped to the
authenticated owner and archive, including when the caller supplies a valid
UUID or hash. Invalid/revoked credentials are 401. Unknown and out-of-scope
archives/query assets/originals are indistinguishable 404 `not_found`. Reauthorize
each new request. An already-authorized in-flight download may finish after
revocation. No public owner field, local path, or alternate external source URL
can bypass that scope.

The `Error` and `ErrorDetail` definitions are the **unchanged ingestion schema
definitions**. Their existing status/retryability mapping applies:

| Status | Code | retryable | Retrieval meaning |
| --- | --- | --- | --- |
| 400 | `invalid_request` | false | Malformed JSON/text, unknown/wrong fields, invalid geometry/timeline/cutoff, explicitly unsupported query text |
| 401 | `unauthorized` | false | Missing/invalid/revoked credential; required Bearer challenge |
| 404 | `not_found` | false | Unknown/out-of-scope archive or asset |
| 405 | `invalid_request` | false | Wrong method |
| 409 | `integrity_error` | false | Original missing/corrupt; refuse before serving JPEG bytes |
| 413 | `payload_too_large` | false | POST body exceeds received-byte limit |
| 415 | `unsupported_media_type` | false | POST body is not `application/json` |
| 503 | `unavailable` | true | Model/search disabled or unavailable, unknown/unready generation, no indexed assets, excessive exact-search scope, or service/resource failure |

Unknown routes may use 404 `invalid_request`, as in ingestion. OpenAPI's exact
operation status inventories and `x-error-codes`/`x-error-statuses` are normative.
409 applies to original reads; a query whose source cannot be embedded because
its stored bytes are unusable cannot succeed and returns 503. Errors MUST be
generic: no query echo, tokens, other-owner identifiers, SQL, filesystem paths,
source URLs, or worker diagnostics. Retry uses bounded backoff; 503 may require
operator model/index provisioning. It never permits fake vectors or an empty
successful response standing in for an unavailable index.

## Requests, numbers and text

All objects are closed, including query variants, timeline, provenance, nested
hits and errors. Unknown properties, duplicates (including escape-equivalent
names), trailing JSON data, invalid UTF-8, and unpaired surrogate escapes in
**values or property names** are invalid. Reject before database/inference access,
without replacement, trimming, normalization, or silent query truncation.

All user strings contain Unicode scalar values and exclude U+0000. Astral text
counts as one scalar, valid escaped surrogate pairs equal literal scalars, genuine
U+FFFD is preserved, and combining sequences remain unchanged. Other JSON-escaped
scalar controls are not prohibited. `text` is **1..2048** scalars; dataset `name`,
`version`, `item_id` are each **1..512**; `sequence_id` is **1..256**. These are
opaque values, not case-folded identifiers. English and Russian text share the
same policy. Model token limits must produce explicit `400 invalid_request` for
unsupported input, never silently truncate a schema-valid query.

UUID and SHA-256 use the original canonical lower-case hexadecimal rules, with
no UUID version/variant restriction. Milliseconds and counters are integers
**0..9007199254740991**. Validate JSON numeric values exactly before range/integer
checks; `1.0` is an integer, `1.00000000000000001` is not. Scores and coordinates
are finite JSON numbers: reject NaN/Infinity, including internal non-finite values
before serialization. `score`/`min_score` are **[-1,1]** cosine values, not
probabilities. Out-of-range decimals must not round into accepted bounds.

`SearchRequest` requires `generation_id` (SHA-256) and `query`, exactly one of:

```json
{"text":"красная отвёртка / red screwdriver"}
```

```json
{"asset_id":"44444444-4444-4444-4444-444444444444","box":[0,0.25,0.75,1]}
```

Image `box` is optional but cannot be null. Missing selects the full image. Text
and image fields cannot coexist; no text `box`, image URL, base64, local path,
dataset annotations or owner identity is accepted. Resolve image sources only
inside the authorized archive. **Exclude the source asset and all derived
candidates before ranking**, including its full/crop regions and identical-byte
aliases in the archive. Source metadata and dataset text/ground truth MUST NOT
be used as semantic model input. Provenance is for attribution/identification.

Optional search fields:

| Field | Meaning |
| --- | --- |
| `limit` | Integer 1..100, default 20; non-null |
| `min_score` | Inclusive score threshold [-1,1], default -1; non-null |
| `timeline` | Absent/null (default): no time claim; otherwise exactly `{"kind":"wall"}` or `{"kind":"sequence","sequence_id":STRING}` |
| `before_ms` | Absent/null: no cutoff; a non-null safe integer requires an explicit non-null timeline and means **strictly earlier than**, never inclusive |

`HistoryRequest` has the same fields but **requires `min_score`** to make the
threshold explicit, and adds optional non-null `gap_ms`, integer **0..3600000**,
default **30000**. Search rejects `gap_ms`. Defaults are server behavior; JSON
Schema's `default` keyword is an annotation, not an input mutation operation.

### Geometry is a required semantic check

`Box` is exactly four finite numbers `[x0,y0,x1,y1]` normalized to the source image
coordinate system used by the pinned preprocessing generation. MUST satisfy:

```text
0 <= x0 < x1 <= 1
0 <= y0 < y1 <= 1
```

Zero-area or reversed boxes are invalid. JSON Schema checks cardinality/type/range
but cannot compare elements. `tools.retrieval.validate` adds those comparisons;
the Go request decoder/domain validator and worker-result validation MUST enforce
them too. Preserve exact decimal coordinates through positive-area checks and
pixel-covering rounding (floor lower edges, ceil upper edges). Both
`[0,0,1e-400,1]` and `[0.5,0,0.50000000000000001,1]` have positive exact width and
are valid: binary64 underflow or endpoint collapse must not narrow the public
acceptance domain or turn them into rejected zero-width selections. Conversely,
rounding must not make an exactly reversed or out-of-range box acceptable.
A `full` region has exactly `[0,0,1,1]`; `crop` is a coarse selected
window, **not a predicted object-instance detection or tracking box**. Overlap
covers image area under a pinned policy; it does not guarantee every object is
detected. Schema conformance cannot prove EXIF, padding or preprocessing behavior.

## Hits, ranking, coverage and originals

`Hit` has exactly the fields listed in the schema:

- `asset_id`, `sha256`, finite `score`, and `region: {kind,box}`;
- `source_kind`: `frame` or `dataset`;
- nullable `frame_id` and `dataset`: frame requires non-null frame ID/null dataset;
  dataset requires null frame ID/non-null `{name,version,item_id}`;
- nullable `observed_at_ms`, `sequence_id`, `sequence_position_ms`; the two sequence
  fields are both null or both non-null;
- `original_path`: exactly the origin-relative asset-original API path above,
  containing the enclosing response's archive UUID and this hit's asset UUID.

`original_path` is **109 characters**, with no scheme/host, encoding, query,
fragment, traversal, trailing slash or filesystem content. Resolve on the trusted
authenticated server origin. It conveys no authorization or perpetual file
availability. Verify stored length/SHA-256 before original-read success.
`source_uri`, labels, annotations, filenames and private dataset manifests are
not public fields. An imported dataset item is not a mobile capture: do not
invent `request_wall_ms=0` or a legacy `FrameMetadata` to represent unknown time.

For the requested generation, score **all eligible indexed regions** in the
bounded authorized scope, with one model/vector space and pinned crop policy.
Aggregate maximum cosine per asset before Top-K: multiple crops cannot occupy
multiple hit places. Order by score descending, then canonical asset ID ascending.
For equal-score regions of the same asset, prefer `full`, then lexicographic box
coordinates. Image-source exclusion and the exclusive cutoff occur before
ranking/grouping; `min_score` is inclusive. No silently truncated top-N pre-scan:
an excessive scope is 503, not a completeness claim.

`SearchResponse` has exactly `contract_version: "0.2.0"`, `archive_id`,
`generation_id`, `coverage`, `hits`, `truncated`. `hits` is a ranked list of at most
`limit` distinct assets. An available index with no qualifying matches may return
an empty list. Text and image results are semantic candidates, not proven physical
instance identity, ownership, presence duration, or acquisition.

`Coverage` is an authorized archive/generation snapshot **before query filters**:
`assets_total`, `assets_indexed`, `pending`, `failed`, `regions_indexed`, all safe
nonnegative integers. `assets_total = assets_indexed + pending + failed`.
Pending includes unattempted/in-flight/retry work; failed is failed indexing work.
Each indexed asset has at least one region; no indexed assets means no indexed
regions. The counters must describe one consistent generation snapshot, not mix
stale/partial writes. Pending=failed=0 and indexed=total is a **complete-indexing
hint only**; it does not establish complete scene detection or recording coverage.

`truncated` is true if qualified evidence is omitted by the response limit **or
index coverage is incomplete**. Inspect coverage to distinguish those conditions.
False means neither condition held at that snapshot, not that retrieval recall is
perfect or the archive captured every real-world observation.

## History without manufactured chronology

`HistoryResponse` has exactly the schema fields, including
`interpretation: "candidate_observations"`. This constant denies any inference
of guaranteed identity, continuous tracking, or when an object was acquired.

The response echoes the explicit timeline (absent request timeline becomes null).
No automatic wall-time selection occurs:

- `wall` uses `observed_at_ms` only. For a frame this is its approximate capture
  **request wall time**, not shutter/save/import/index time. Wall clocks can jump.
- `sequence` uses `sequence_position_ms` only for exactly the requested sequence
  ID. Sequence position needs actual documented source/PTS provenance; arbitrary
  elapsed times across device sessions cannot establish a common sequence.
- Null timeline means no time comparison. **Never merge clocks or sequence IDs**,
  reinterpret sequence position as Unix time, or synthesize dates from item IDs,
  array order, filenames, download/import time or model scores.

A non-null cutoff keeps only hits whose selected-clock timestamp is known and
`timestamp < before_ms`. Unknown/other-sequence times cannot satisfy a cutoff;
they are excluded, not silently included as earlier. Thus cutoff 0 yields no
qualifying timestamps. Without cutoff, hits lacking the selected clock remain
ordinary ranked `unsequenced_hits`; that ranking implies no observation order.

Determine temporal bounds and groups from **all qualified indexed assets after
source exclusion, threshold and cutoff, before response limit**. Sort timed hits
by timestamp ascending then asset ID. Adjacent timestamps with difference
`<= gap_ms` belong to one group (transitively); a larger difference starts another.
Gap 0 groups equal timestamps only. Each `Observation` is exactly
`{start_ms,end_ms,max_score,evidence}`: min/max time and max score of the **complete
group**, plus selected hit evidence. `start_ms <= end_ms` is mandatory.

`limit` is a **total evidence-hit budget** across all observation evidence and
unsequenced hits, selected by the ordinary ranked score order. Return only groups
with selected evidence, in chronological order; evidence within a group is time
ordered. Group boundaries/max score may refer to qualified hits omitted by limit.
`first_observed_ms`/`last_observed_ms` cover all qualified timed assets, including
groups entirely absent from the limited response. Do not derive them from Top-K.

`history_available` is true iff the complete qualified indexed set has at least
one timestamp in the explicitly selected clock. It can remain true with empty
returned observations if truncation selected only unsequenced evidence. If false,
observations MUST be empty and first/last MUST both be null. Null timeline always
means false, even when individual hits contain source timestamps. With no known
time, the output is ranked unsequenced candidates, not an invented history.

**Open Images items have all three source time fields null.** Therefore Open
Images alone cannot produce a chronological history, even if a caller requests
wall or sequence time. Its image-query matches are class-level proxies, not
same-instance/history evidence. Ego4D access and any future source-clock adapter
require separate real provenance/evidence; this contract does not claim access,
licensed downloads, or temporal model quality.

## Required consumer regression scenarios

The component suite validates real schemas/OpenAPI and synthetic instances.
`tools.retrieval.validate` additionally checks finite values, geometry, coverage
arithmetic, identity paths, duplicate evidence and locally derivable response
relationships:

- Pending or failed indexing requires `truncated: true` in either response family;
  complete indexing alone does not imply `truncated: false` because limits can omit
  evidence. The coverage partition remains indexed + pending + failed = total.
- Each observation hit must have a timestamp in exactly the selected clock and
  that timestamp must lie within its own observation's inclusive bounds. Wall time
  never falls back to sequence time; sequence selection requires exact sequence
  identity and never falls back to wall time. Unknown selected-clock times cannot
  justify temporal observations.
- Every unsequenced hit must lack the selected clock. A hit from another sequence
  may be unsequenced without cutoff, even if it has wall time; null timeline makes
  every hit unsequenced. Known selected-clock time cannot hide in unsequenced hits,
  regardless of `history_available`.
- Observation groups must be chronological and strictly non-overlapping, and
  evidence is ordered by selected time then asset ID. First/last enclose every
  returned group. With `truncated: false`, every qualifying hit is returned, so
  group bounds/max score and global first/last must equal their returned evidence
  and group extrema. With truncation, bounds may include omitted evidence/groups;
  the validator must not invent unseen timestamps or require selected evidence
  to establish complete extrema. Available history with only unsequenced selected
  evidence remains valid when truncated.

`validate("HistoryResponse", response, request=decoded_request)` (and the analogous
SearchResponse call) optionally validates the corresponding request and checks
generation, echoed timeline, evidence budget, inclusive threshold, source asset
exclusion and the **exclusive** cutoff against returned evidence and complete
history bounds. With cutoff, unknown/other-sequence hits cannot pass as unsequenced.
History request context also checks that distinct group bounds are separated by
more than `gap_ms`; only an untruncated group must demonstrate every within-group
gap through its returned evidence. Omitted hits may bridge a truncated group's
selected evidence when the gap is positive; `gap_ms: 0` always requires equal
group start/end because no omitted timestamp can bridge unequal times.
Without request context, the checker does not guess a cutoff,
threshold, limit or gap. Decode raw wire bytes with `tools.contract.parse_json`
first; these checks never coerce a missing/null/string timestamp into a date.

The supplement does **not** implement or certify retrieval, prove the truth of
supplied source timestamps, count actual DB rows, or inspect omitted evidence.
The approved retrieval-domain gate is owned by the server; see its
[quality requirements and evidence](../../server/docs/quality.md). Go/domain and
actual HTTP/DB integration tests must exercise:

| Scenario | Required result |
| --- | --- |
| Missing/revoked token, alternate scheme casing, token casing | Exact ingestion bearer grammar and 401 challenge; case-sensitive token |
| Other-owner archive/query asset/original | Non-disclosing 404 and no metadata/coverage leak |
| NUL/malformed scalar/duplicate JSON; unknown field; mixed query | 400 before storage/inference; valid astral/U+FFFD preserved |
| Non-finite/out-of-range score or coordinate; zero/reversed box | Reject; no truncated arrays or float-rounded acceptance of invalid bounds |
| Same asset has many crops; image query matches source/aliases | One max-score hit per asset; all query-source candidates excluded before Top-K |
| Tie scores / equal times / gap boundary | Deterministic rank and same-clock grouping; test 0, gap, gap+1 |
| Cutoff at exactly the observation; unknown or other-sequence time | Exclusive exclusion before rank/group; unknown time does not pass cutoff |
| First/last lower-ranked than returned Top-K; group omitted | Complete qualified indexed first/last and group boundaries retained |
| Open Images / null timeline / mixed sequences | No invented timeline; unsequenced rank is not chronology |
| Partial index / failed work / changing generations | Truthful consistent coverage and truncation; never mix spaces |
| Observation with unknown/wrong-clock evidence, misplaced timed hit, out-of-bound evidence | Reject response rather than certify fictional chronology |
| Overlapping/out-of-order groups; incompatible first/last or complete-group extrema | Reject locally contradictory response; allow omitted evidence only with truncation |
| Disabled/missing model, unindexed or excessive scope | Explicit 503, no fake vectors or silent pre-scan |
| Corrupt/missing original, incorrect path identities | Refuse original before JPEG bytes; no filesystem escape |
| Legacy ingestion on a retrieval-capable server | Byte-identical schema/OpenAPI; old fields, wire 0.1.0 and stable historical receipts |

Synthetic schema success cannot prove model effectiveness, overlap/edge coverage,
EXIF alignment, indexing/job fencing, actual temporal truth, authorization,
durability, deployment encryption or Android sync. Those are separate evidence
gates; benchmark measurements require real explicitly prepared data and models.
