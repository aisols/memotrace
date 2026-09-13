# Generic blind and staged retrieval evaluation

`scripts/retrieval_eval_core.py` and `scripts/retrieval_eval_metrics.py` are offline,
model-free diagnostic helpers for future explicitly licensed video evaluations. They
are not a dataset adapter, runner, report writer, production API, or official task
implementation. The helpers perform no filesystem, subprocess, network, model, worker,
or JSON operations and contain no private inputs.

The files live in `server/scripts`, outside the packaged `memotrace_ml` source and its
model/policy implementation fingerprint. They are also outside the Go-only Docker
image: the Dockerfile copies only Go source and license material. Tests and the
verifier are tooling inputs only and do not enter either production identity.

## Structural blindness boundary

The core accepts only generic query IDs, stream IDs, exclusive frame cutoffs, cadence,
float32 query/gallery vectors, and normalized gallery-region boxes. It has no relevance
annotation type or metric import. A normal staged run is deliberately split:

1. `plan_blind_gallery` creates each query's own candidate cadence and the shared
   per-stream full-gallery unions.
2. `rank_full_plan` produces a complete deterministic full ranking for every query.
3. `plan_shortlists` selects exact full-ranking prefixes and shared overlap-work unions.
4. `complete_staged_run` retains the plan, immutable query embeddings, full galleries,
   shortlist plan, and overlap galleries; overlap-rescores only each query's own prefix;
   and returns an immutable `CompletedBlindRun`.
5. Only `evaluate_blind_run` in the one-way dependent metrics module can join explicit
   annotation frame rates and positive intervals to that completed value.

Before a completed run is accepted, `validate_completed_blind_run` recomputes full
max-region float32 scores/rankings, exact shortlists, and overlap prefix scores from the
retained evidence. It checks selected region indexes and region-object provenance, exact
score/order values, complete candidate membership, and unchanged full-tail object
identity and value. The metrics entry point always performs this validation first.

Changing annotation objects after step 4 cannot change candidates, shared work, scores,
shortlists, or rankings. This is a structural process-local separation, not cryptographic
authentication or proof that an external runner, dataset selection, operator, or human
process is blind. A caller controlling the Python process can replace whole objects or
construct a different internally consistent run; external immutable provenance and
independent review remain necessary.

## Planning and ranking semantics

- Inputs use exact Python types. In particular, booleans are not integers. IDs reject
  C0, DEL/C1, lone-surrogate, and Unicode `Cf` format controls while permitting ordinary
  Unicode. Collections, frame/rate values, vector dimensions, and work sizes are bounded.
- Vectors must be finite NumPy `float32` arrays with exact compatible dimensions.
  `QueryEmbedding` and `IndexedFrame` copy them into NumPy views backed by immutable
  `bytes`; callers cannot re-enable writes with `setflags(write=True)`. Validation rejects
  owning or mutable-backed substitutes. Normalized boxes are finite float tuples
  satisfying `0 <= x0 < x1 <= 1` and `0 <= y0 < y1 <= 1`. This protects the public array
  surface, not a hostile Python process capable of reflection or replacing objects.
- `map_evaluation_frame` computes `evaluation_frame * (source_fps / annotation_fps)`
  only when both rates are bounded positive exact `Fraction` values and their ratio is
  a positive integer. Nonintegral ratios and bounded-frame overflow fail. This arithmetic
  is not proof of constant-frame-rate media, frame identity, decode ordering, time base,
  presentation timestamps, or variable-frame-rate handling; a runner must establish
  those independently from the actual media.
- A query with cutoff `q` and stride `s` has exactly
  `tuple(range(0, q, s))`. The cutoff is always excluded. A stream's gallery work is
  the sorted union of those tuples, but ranking retains each query's own tuple.
- A frame's score is the maximum dot product over its regions. NumPy's first maximum
  selects the first region on a region-score tie. Complete frame rankings sort by
  descending score and then ascending frame number, with every candidate exactly once.
- Before any full or overlap dot product, the phase sums exact requested scalar vector
  elements across all queries: `region_count * vector_dimension` for every requested
  candidate frame. Python integer arithmetic is exact; a phase above the scoring-work
  cap fails before scoring. Shared galleries are validated once per collection and a
  private prevalidated path performs each query ranking without repeating gallery-wide
  finite scans.
- A shortlist is exactly `full[:min(K, n)]`. Shared overlap work is the sorted union of
  shortlists per stream, while each query is rescored only on its own shortlist.
- Staged output is the overlap-rescored prefix sorted by descending score and ascending
  frame number, followed by the original full-ranking tail objects unchanged. Prefix
  entries never compete with tail entries, so a lower prefix score intentionally remains
  ahead of a higher tail score.

### Practical allocation caps

The diagnostic rejects work before allocation-producing planner and output steps when
these exact caps would be exceeded:

| Scope | Cap |
| --- | ---: |
| Identifier length | 512 characters |
| Queries / distinct streams | 4,096 / 1,024 |
| Candidates per query / materialized candidates across queries | 100,000 / 500,000 |
| Query-vector dimension / bytes per query | 8,192 / 32,768 bytes |
| Regions per frame | 512 |
| Vector elements and bytes per frame | 1,048,576 / 4,194,304 bytes |
| Gallery frames per full or overlap collection | 250,000 |
| Gallery vector elements and bytes per full or overlap collection | 16,777,216 / 67,108,864 bytes |
| Query-vector elements and bytes across queries | 1,048,576 / 4,194,304 bytes |
| Scalar vector elements requested per full or overlap scoring phase | 33,554,432 |
| Positive intervals per query / across an evaluation | 4,096 / 32,768 |
| Metric cutoffs | 64 |
| Full/staged per-query and aggregate At-K records | 262,144 |

Matrix shape, element count, and byte count are checked before finite-value scanning or
copying, including for zero-stride views whose apparent shape is much larger than their
backing buffer. Candidate counts are checked per query and in aggregate before cadence
tuples or stream unions are materialized. Frame numbers remain bounded to the largest
exact binary64 integer, and exact rational rate components to 1,000,000,000.

## Metric semantics

`QueryAnnotations` requires an exact positive annotation `Fraction` and one or more
ordered, nonoverlapping inclusive positive-frame intervals before the query cutoff.
Annotation IDs must exactly equal the completed query ID set; missing, extra, or
duplicate IDs fail before evaluation.

For both full and staged rankings, the cadence-captured positives are candidates that
fall inside an explicit positive interval. Conditional metrics are defined only when
that set is nonempty:

- AP is mean precision at each captured positive's rank.
- MRR is the reciprocal rank of the first captured positive.
- Hit@K is one when a captured positive has rank at most K, otherwise zero.
- Recall@K is captured positives ranked at most K divided by the number of captured
  positive response frames.

Missed positive frames that were absent from the cadence are not added to AP or recall
denominators. A cadence capture miss yields null conditional AP, MRR, Hit@K, and Recall@K
as one absent `ConditionalRanking`; its end-to-end Hit@K values are zero. Conditional
macro means include only capture-hit queries. End-to-end hit means include every query,
and capture coverage is reported separately. Nearest-cadence distance is reported in
annotation frames and converted to seconds only with the annotation rate supplied for
that query.

Captured candidates and nearest interval distance are computed together by one
deterministic two-pointer sweep over sorted unique candidates and sorted nonoverlapping
intervals. For `C` candidates and `I` intervals, it performs at most `2*C + I`
candidate/interval comparisons and uses `O(C + I)` time rather than a Cartesian product.
Across an accepted evaluation this is bounded by the existing aggregate candidate and
interval caps. This complexity statement does not claim a measured runtime speedup.

These are narrowly defined frame-retrieval diagnostics. They are not official metrics
for any dataset, object localization or detection scores, learned stable object identity,
tracking, temporal history, or production quality. A region is retrieval evidence, not
a predicted object box. The helpers neither establish data access/licensing nor parse
an official annotation format.

## Verification

From `server/`, using the already locked Python 3.12 ML environment:

```sh
uv run --locked --project ml python scripts/verify_retrieval_eval.py
```

The deterministic gate runs Ruff check/format, strict mypy, and the inline synthetic
pytest suite under branch coverage. It creates a unique private temporary directory for
coverage data and JSON, rereads and runtime-validates exact source membership and every
required non-bool nonnegative counter, and cleans the directory on success or failure.
It requires nonempty 100% statement coverage independently for
`retrieval_eval_core.py` and `retrieval_eval_metrics.py`; covered counts cannot exceed
totals. Valid branch coverage is printed without a branch threshold. Pytest's
empty-discovery status and missing required files fail the gate. No model, dataset,
private input, raw result report, credential, or network access is required.

Evaluator dataclasses use redacted constant-shape object representations; default
`repr` does not recursively expose IDs, frames, vectors, boxes, scores, annotations, or
metric values. This reduces accidental diagnostics exposure but is not a logging policy
or a confidentiality boundary against process-level inspection.

Related checks, also from `server/`:

```sh
uv run --locked --project ml python -m memotrace_ml.verify
uv run --locked --project ml ruff check --config ml/pyproject.toml scripts/retrieval-smoke.py scripts/test_retrieval_smoke.py
uv run --locked --project ml ruff format --check --config ml/pyproject.toml scripts/retrieval-smoke.py scripts/test_retrieval_smoke.py
uv run --locked --project ml pytest -c ml/pyproject.toml scripts/test_retrieval_smoke.py
```

Keep downloaded media, annotations, model weights, and raw evaluation reports outside
Git. Any future external runner remains responsible for licensed access, immutable input
provenance, actual media/frame validation, environment identity, and independent review.
