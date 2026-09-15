# Ego4D text-search trial — 2026-09-14

**Actual offline text retrieval completed with three genuine SigLIP2 checkpoints.**
Base384 improved raw-title retrieval over Base224 on this small selected cohort;
it matched SO400M384's raw-title hit counts at substantially lower image-index cost.
This supports a broader text-specific check, not a final-best-model promotion.
Production remains Base224 full.

## Execution and frozen sample

The private harness called `SiglipEncoder` directly on existing PNGs in the existing
locked CPU environment: one separate process per checkpoint, four threads and batch
size two. This was per-clip offline retrieval, not a new Go/PostgreSQL video index,
HTTP search, or a whole-archive/cross-clip evaluation. There was no shared wall clock.

| Checkpoint | Pinned revision | Vector dimension | Fresh image vectors |
| --- | --- | ---: | ---: |
| `google/siglip2-base-patch16-224` (Base224) | `75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2` | 768 | 1,157 |
| `google/siglip2-base-patch16-384` (Base384) | `f775b65a79762255128c981547af89addcfe0f88` | 768 | 1,157 |
| `google/siglip2-so400m-patch16-384` (SO400M384) | `dd658faac399427308559e2c3ac1e99cbe43845d` | 1,152 | 1,157 |

- Freeze: the first ten verified completed slots from the
  [prior expanded evaluation](object-search-expanded-evaluation-2026-09-14.md), which
  completed 25 of 30 slots. These have distinct parent videos. Selection used the
  first verified completed slots, not retrieval quality, but is **completion-conditioned**.
- Candidates retain the same whole-prior **1 Hz within-clip** cadence and exclusive
  query cutoff, `range(0, query_frame, 5)`: 7–298 frames per query, 1,157 in total.
  Text queries have no image-source exclusion rule; one previously excluded source
  frame was restored and is nonpositive. The legacy Base224 cache of 1,156 vectors
  was not reused: every checkpoint freshly encoded all 1,157 images.
- Primary arm: the **exact original `object_title`** from metadata. Secondary arm:
  uniformly prepend `a photo of ` to that title. No translation or Russian arm.
  The ten titles are exact-distinct: seven one-word and three two-word titles.
  String uniqueness does not establish semantic specificity; no arbitrary ambiguity
  rating was assigned. Individual titles and private query/media details are omitted.
- Each checkpoint encoded ten queries in two arms: 20 text vectors, 60 overall,
  with zero text failures. There were **3,471 fresh image encodings** overall.
  Candidate response-episode ground truth was released only after all three model
  runs passed validation.

## Historical source and report identity

Source HEAD was `ab2fa799d225aa75452a9e799a5b6bb78d5a6067`. All 20 required source pins
(17 ML and three experiment files) were unchanged; the ML source digest was
`980af7d9955f95dd0cbad7ee823d48c5e89cab1402d4cffebdb1ad699a493ef3`.
Tracked production Python was unchanged; the new harness was private and ignored.

The actual freeze used an explicit **docs-only historical-reuse attestation** for
five pending documentation paths at the same HEAD. All other source-state fields
and pins were identical; original and current states were retained. The old strict
Git-state match was **false**: this was not a clean-tree claim or a pass of the old
strict source checker. Review and verification preceded this new documentation
change. These reports pin that historical state, not current reuse after docs edits.

Only aggregate source/harness and report-root SHA-256 identities are published here:

| Artifact | SHA-256 |
| --- | --- |
| Private harness | `2f70afcfa7da5d71063f919c2cb5a4fe9f2e72a283f0c1ccbc187e43e86bd6d8` |
| Private harness tests | `b30e2c48e82afbd64940e184eb60abbcb5a1c6f7fc3b65087454e7a3f9a24813` |
| Frozen report root | `6bce43d246fafa50c5db0e26f77365d29430136ed73eb8a2947439365f0c57ed` |
| Base224 report root | `55306b96412e48ce8ebcd24894612646f96e79b07ca60993fb1eb7fa82911973` |
| Base384 report root | `6843422e6c8db80cc17c38fb4cc62d92d257c18133d8b2549ff92d2f6b22e1cc` |
| SO400M384 report root | `424505a02400438098e7ac1c33641f51390dae7f603c53ae1d8096141542d8e7` |
| Evaluation report root | `db6753fe4841091fd707a0c6fa6e3056bb1443bed0a240c809d0b1ac38db7479` |
| Evaluation completion report | `ff7c2a0c17da296bf76ae0d92fd34338324974bd4c18e63ba3e8d323b2b58623` |

Immutable pending reports require both seals and a final decision; five bundles
were verified. This establishes local computation/integrity, not power-loss
durability of the final-decision link.

## Primary results: all ten queries

Capture was **8/10**; the two capture misses remain in the primary denominator with
zero retrieval metrics. There were zero text failures and zero invalid intervals.
Relevance is the **last annotated response episode**, not exhaustive semantic
relevance. AP averages precision at positive frames, MRR averages reciprocal first
positive position, and Hit@K counts queries with a positive in the first K results.
Metrics below are rounded to four decimals; hit counts are exact, each out of ten.

| Model | Text arm | mAP | MRR | Hit@1 | Hit@5 | Hit@10 | Hit@20 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Base224 | Exact title (primary) | 0.1611 | 0.1607 | 1/10 | 2/10 | 2/10 | 5/10 |
| Base224 | Template (secondary) | 0.1993 | 0.2305 | 2/10 | 2/10 | 3/10 | 5/10 |
| Base384 | Exact title (primary) | 0.2393 | 0.3413 | 3/10 | 4/10 | 4/10 | 5/10 |
| Base384 | Template (secondary) | 0.1687 | 0.1963 | 1/10 | 2/10 | 4/10 | 5/10 |
| SO400M384 | Exact title (primary) | 0.2872 | 0.3396 | 3/10 | 4/10 | 4/10 | 5/10 |
| SO400M384 | Template (secondary) | 0.2669 | 0.3255 | 3/10 | 3/10 | 3/10 | 6/10 |

The captured-only diagnostic uses the **same eight-query intersection** for all
models and both arms; there is no per-query best-of selection.

| Model | Captured-only exact-title mAP | Captured-only template mAP |
| --- | ---: | ---: |
| Base224 | 0.2013 | 0.2491 |
| Base384 | 0.2992 | 0.2108 |
| SO400M384 | 0.3589 | 0.3336 |

### Sensitivity and paired changes

One degenerate query has all seven candidate frames positive: AP, reciprocal rank
and every Hit@K equal one regardless of ordering. It remains in the primary result.
**Post-hoc sensitivity only:** removing just that query leaves nine, including both
capture misses; raw-title mAP becomes 0.0679 / 0.1548 / 0.2079 and Hit@1 becomes
0/9 / 2/9 / 2/9 for Base224 / Base384 / SO400M384. This does not redefine the primary.

Paired raw-title AP changes, across all ten queries:

| Comparison | Gains | Losses | Ties |
| --- | ---: | ---: | ---: |
| Base224 → Base384 | 6 | 1 | 3 |
| Base224 → SO400M384 | 5 | 2 | 3 |
| Base384 → SO400M384 | 4 | 3 | 3 |

| Template effect versus exact title | AP gains / losses / ties | Change in macro AP |
| --- | --- | ---: |
| Base224 | 5 / 2 / 3 | +0.0382 |
| Base384 | 4 / 3 / 3 | −0.0707 |
| SO400M384 | 3 / 3 / 4 | −0.0203 |

The template does not automatically improve retrieval; paired wins can coexist
with lower macro AP. This small selected cohort supports no statistical-significance
claim and no final-best-model choice.

## Measured CPU stage costs

| Model | Model load (s) | Image-index stage, 1,157 images (s) | Text stage, 20 queries (s) | Mean text stage/query (ms) | Ranking stage, 20 queries (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Base224 | 7.537 | 242.539 | 1.387 | 69.34 | 0.393 |
| Base384 | 7.639 | 668.983 | 1.492 | 74.61 | 0.389 |
| SO400M384 | 12.141 | 2,568.751 | 5.430 | 271.50 | 0.528 |

Image-index time includes PNG loading, pixel verification, encoding and persistence.
Model loading, preflight and final-scope verification are separate stages. Text means
are stage-total arithmetic using unrounded timings, not API p95 measurements.
These measurements establish no Go, IPC or network latency and no warmed-service
throughput.

## Completed verification

Before this docs change, the main agent completed all three actual-model runs and
the final `verify_evaluation`. The main agent passed 95 synthetic harness tests;
the builder passed 413 existing helper regressions, and the independent reviewer
passed the 95 harness tests on the code before this documentation change.

The independent read-only reviewer:

- Rehashed **4,213 files / 14,571,450,437 bytes** and verified all five bundles.
- Confirmed all **1,157 PNG/RGB matches** and vector-array norm deviation at most
  **3.33 × 10⁻⁸**.
- Replayed all **60 rankings / 6,942 scores**, with maximum score difference **zero**.
- Matched all **60 metric records and aggregates exactly**.

That review replayed persisted vectors; it did not regenerate fresh embeddings.
These are historical run/review results, not tests newly executed by this docs-only
edit. No fresh Go or Android verification is claimed.

## Interpretation and next text-specific check

Earlier views of the **same physical object**, or of the same category, can be
protocol-nonrelevant because labels cover only the last annotated response episode.
Such results are not necessarily semantic mistakes. This is neither exhaustive
semantic precision nor a manual physical-hard-negative evaluation, an official
VQ2D text task, localization, or tracklet-quality evidence. Low lighting was not
separately stratified; per-clip results do not estimate archive-wide performance.

**Base384 is a practical text-search candidate for broader evaluation:** stronger
than Base224 here, with the same raw-title hit counts as SO400M384 and cheaper image
indexing. SO400M384 has higher raw-title mAP here; neither result changes the default.
Next, expand titles/queries and obtain human semantic judgments of Top-K results to
separate wrong-object retrieval from wrong-latest-episode retrieval. Predeclare a
Russian arm separately, then measure a warmed persisted service/index afterward.
