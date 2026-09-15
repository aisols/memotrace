# Expanded frozen object-search evaluation, 2026-09-14

**Committed experimental source; expanded private evidence, not a product-quality
claim.** Thirty fixed queries from thirty new distinct parent videos were frozen
before inference. Actual model runs completed with completion seals for **25**;
**5 unsupported queries remain in the operational denominator**. The 1 Hz cadence
captured annotated response evidence for **22/25 supported queries (88%)**, or
**22/30 selected queries (73.33%)**. There were three capture misses.

Keep **SigLIP2 Base224 full indexing** as the default. DINO reranking at **K=50** is
the next challenger: conditional candidate-frame mAP rose from **0.273268** to
**0.346679**, but localized Hit@20 at IoU >=0.5 was only **6/22 captured queries**
or **6/30 operational queries**. Returned proposal coverage and wrong-region
winners need investigation before promotion. This cohort supports neither a
population estimate nor statistical significance or automatic default selection.

This record summarizes main-agent execution and supplied independent review.
The [first 2026-09-14 report](object-search-experiment-2026-09-14.md) remains
historical evidence, including its accurate **uncommitted-at-measurement** source
description, public smoke, v7 repeat and three-query tracklets. The
[operational guide](../docs/object-search-experiment.md) describes the committed
bounded runner; the expanded selector, runner and evaluator are ignored private
helpers, not a newly distributed dataset adapter. No paid services or new model
downloads were used in this expansion. No new tracklet performance was measured.

## Source, models and external receipts

Implementation commit: **`ab2fa799d225aa75452a9e799a5b6bb78d5a6067`**
(`feat(server): add bounded object-search experiment`, 19 files). It commits the
previously prepared source; there are no subsequent tracked code changes in this
experiment. The source SHA-256 inventory in the
[first report](object-search-experiment-2026-09-14.md#source-and-artifact-binding)
still identifies those bytes. In particular, paths below are relative to `server/`:

| Source | SHA-256 |
| --- | --- |
| `scripts/object_search_core.py` | `ca7cf74f4970d6cf641dd5cdd9550450a0dbdd42d701c6e7aa2107946a6f5364` |
| `scripts/object_search_vision.py` | `7dad35c654e9b0b6cdd49c2173dc8e49b589b83bd2e43c06129bc098a9b5891a` |
| `scripts/object_search_experiment.py` | `7c6d0c47e5cb27e80cd3d5e4b1346bafae92746ebb5d42a0bd47f4884ffcb1c5` |

The 17-file packaged production ML implementation is unchanged, with inventory
digest `980af7d9955f95dd0cbad7ee823d48c5e89cab1402d4cffebdb1ad699a493ef3`.
The semantic and descriptor experiment identities remain separate from production
and from each other. Source, model and effective runtime/settings bindings remain
part of the retained evidence; equal model names do not make vector spaces equal.

| Model | Unchanged pinned revision |
| --- | --- |
| `google/siglip2-base-patch16-224` | `75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2` |
| `hustvl/yolos-tiny` | `95a90f3c189fbfca3bcfc6d7315b9e84d95dc2de` |
| `facebook/dinov2-small` | `ed25f3a31f01632728cabb09d1542f84ab7b0056` |

The [previous model artifact record](object-search-experiment-2026-09-14.md#additional-model-pins-and-runtime)
retains YOLOS/DINO weight hashes, sizes and license observations. This expansion
reused those verified local artifacts and the Base224 full-image baseline.

| Confirmed external-root receipt | SHA-256 |
| --- | --- |
| Frozen expanded cohort | `4d2a20a6a5e881e8a2bcca19d3055ce69347e530a2a5c0ec71fc38e54ec4753a` |
| Expanded evaluation | `63dbf79cca17b6e1cdcbe981c2417a44929e847b892fbc444dc9fb0a9229f98d` |
| Whole 4,099-file inventory | `5bc73a52c18903c0688c2021f49ecb9a9b95ab83d39e1d6614ef10c89ac799c0` |

These hashes bind external evidence, not files distributed in Git. Individual
media hashes, private IDs and paths, object titles, annotation texts, raw rankings,
matrices and licensed inputs remain external. Only aggregate results and safe
source/model/root-receipt identifiers are recorded here.

## Score-blind cohort and execution eligibility

Selection used the fixed hash seed **`memotrace-object-expanded-v1-20260914`**,
independent of retrieval scores. It excluded every previously used parent video:
**37 parents / 38 clips**, not just the previously selected queries. The eligible
pool contained **966 clips / 376 parents**. Hash ordering selected one official
`is_valid` query per clip; **4 duplicate-parent candidates were skipped**, leaving
**30 queries / 30 distinct new parents**. The cohort was frozen before inference,
with **no replacements** after selection, preflight or scoring.

| Frozen-cohort outcome | Queries | Interpretation |
| --- | ---: | --- |
| Ready after query-crop preflight | 27 | Includes the two later source-length failures |
| Unsupported query-crop bounds | 3 | Invalid x/right/bottom bounds; selected crops retained |
| Completed supported model runs | 25 | Completion seals present |
| Unsupported source-length bound | 2 | Declared source frame counts 28,798 and 28,800 exceed the 20,000-frame bound. |
| Total selected | 30 | 25 completed + 5 unsupported |

The two long-source failures are **bound failures, not timestamp corruption**.
Neither they nor the three crop failures were silently replaced or removed from
operational results. A pending report alone cannot establish completion: the
completion seal is published after directory sync and establishes computational
completion under the protocol. It does **not** prove physical power-loss durability.

### Cadence, source exclusions and timing scope

The candidate plan spans the whole prior **1 Hz within-clip** cadence,
`range(0, query_frame, 5)`, with a **1,024-frame bound**. It is not the earlier
last-64-observation window or a search across all videos. Source-ordinal and exact
source-content-hash exclusions, and the exclusive query cutoff, apply **before
inference**.

For the 25 completed queries, **3,323 cadence frames were planned**, of which
**3,321 were eligible** after **2 source-frame exclusions**. There were **0
additional positive alias exclusions**. The eligible cadence contained **69
positive response frames**. Twenty-two queries retained at least one such frame;
three supported queries had no captured response evidence.

PTS verification established exact **30 FPS CFR for the 25 supported queries**.
The **27 PTS attempts** in work accounting below do not establish support for the
two bound failures. Canonical content/frame-zero alignment remains an assumption;
this is neither official Ego4D VQ2D evaluation nor proof of physical object
identity, hard-negative classification or independently reproducible acquisition.
Candidate-frame relevance refers to the annotated latest response episode.
Frames outside it can contain the **same object earlier**, so a non-hit is not a
verified different physical instance.

## Evaluation-only visible response geometry

Protocol **`visible-clipped-response-IoU-v1`** computes the visible intersection of
each finite, exact-rational response box with the image rectangle for IoU
evaluation. Response-frame interval membership is independent of this geometry
operation. These response annotations are joined for evaluation only; they do not
change the selected query crop, candidate inference or frozen cohort.

| Geometry population | Response boxes | Clipped boxes | Queries with clipping |
| --- | ---: | ---: | ---: |
| 25 supported queries | 340 | 73 | 19 |
| All 27 query-crop-ready queries | 364 | 92 | 21 |

There were **0 GT-unavailable outcomes among the 25 supported queries**. Among the
**69 positive cadence frames**, **10** had clipped response boxes across **6 queries**.
The old **preflight v2** incorrectly over-rejected **21 queries**
because response boxes extended offscreen. It is retained as a diagnostic. Final
**v3** documents the corrected visible-clipping evaluation protocol; this is not
a silent replacement of queries or a change to selected crops or model inference.
Future query-geometry support changes require their own explicit version.

## Capture and candidate-frame retrieval

Capture is **22/25 = 88%** among supported queries and **22/30 = 73.33%** over the
entire operational cohort. All conditional retrieval metrics below use the same
**22 captured queries**; unsupported queries (5) and capture misses (3) remain
visible rather than disappearing into a headline score.

Base224 ranks all eligible full frames. Each DINO arm reranks only the fixed
semantic prefix of **K=10, 20 or 50**, preserving the semantic tail. Query and
proposal descriptors are compared in the DINO space; semantic and descriptor
scores are not blended. AP uses the complete candidate-frame ranking against the
annotated response episode; mAP and MRR are macro means over the captured queries.
Hit@n means at least one positive response frame in the first n results. It does
**not** require that the winning proposal cover the correct object region.

| Arm | Conditional mAP | Conditional MRR | Hit@1 | Hit@5 | Hit@10 | Hit@20 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Base224 full baseline | 0.273268 | 0.341332 | 6/22 | 9/22 | 11/22 | 15/22 |
| DINO K=10 | 0.295521 | 0.379896 | 7/22 | 8/22 | 11/22 | 15/22 |
| DINO K=20 | 0.293170 | 0.396380 | 7/22 | 9/22 | 11/22 | 15/22 |
| DINO K=50 | 0.346679 | 0.459917 | 8/22 | 12/22 | 12/22 | 15/22 |

For operational Hit@n, use the **same numerators divided by 30**, assigning no hit
to the five unsupported queries and three capture misses. For example, K=50
candidate-frame Hit@1 is **8/30** and Hit@20 is **15/30** operationally.

An optional **review-derived all-30 zero-extension AP** assigns zero to all eight
queries outside the captured set. It is a derived operational convention, not an
unqualified reported mAP: baseline **0.200397**, K=10 **0.216715**, K=20 **0.214992**,
K=50 **0.254231**. It does not make an unsupported query a completed model result.

| Paired AP change from baseline, 22 captured queries | Gains | Losses | Ties |
| --- | ---: | ---: | ---: |
| K=10 | 4 | 3 | 15 |
| K=20 | 6 | 6 | 10 |
| K=50 | 11 | 6 | 5 |

The larger prefix improves this cohort's mean with heterogeneous per-query changes.
No significance test, population inference or automatic product promotion follows.

## Shortlist access, proposal coverage and winning regions

### Access to annotated response frames

| Semantic shortlist | Queries with a positive frame | Positive frames in prefix |
| --- | ---: | ---: |
| K=10 | 11/22 | 25/69 |
| K=20 | 15/22 | 33/69 |
| K=50 | 19/22 | 46/69 |

### Global returned-proposal coverage

This checks **any returned proposal** on every eligible positive cadence frame,
independent of semantic shortlist membership or the DINO winner. Query coverage
means at least one positive frame has a proposal meeting the IoU threshold.

| IoU threshold | Queries covered | Positive frames covered |
| --- | ---: | ---: |
| >=0.3 | 11/22 | 24/69 |
| >=0.5 | 11/22 | 23/69 |
| >=0.7 | 7/22 | 18/69 |

Every positive frame has **some** returned proposal, often on the wrong object
region. At IoU >=0.5, the global query-miss count is **11**, constant across K.
Of the 23 covered positive frames, **12 lie outside Top-50**. Only **2 queries**
have a globally good proposal but none in Top-50. Increasing K alone therefore
does not address the main coverage problem. Without raw detector outputs, these
failures cannot be uniquely assigned to the detector versus confidence filtering,
minimum crop size or proposal truncation.

### Oracle availability versus actual max-DINO winner, IoU >=0.5

| Prefix | Positive frames with any good proposal | Queries with any good prefix proposal | Positive frames whose DINO winner is good | Queries with a good DINO-winning frame |
| --- | ---: | ---: | ---: | ---: |
| K=10 | 6 | 4 | 5 | 3 |
| K=20 | 6 | 4 | 5 | 3 |
| K=50 | 11 | 9 | 8 | 6 |

An oracle-covered frame can still select a wrong-region max-DINO winner. The
**three K=50 wrong-region winner losses** have score gaps **0.03322–0.10521**;
these are numerical selection differences, not rounding ties.

Localized Hit@n additionally requires that a retrieved positive frame's actual
winning region meet IoU >=0.5 under the visible-clipped response protocol:

| Arm | Localized Hit@1 | Localized Hit@5 | Localized Hit@10 | Localized Hit@20 |
| --- | ---: | ---: | ---: | ---: |
| DINO K=10 | 3/22 | 3/22 | 3/22 | 3/22 |
| DINO K=20 | 3/22 | 3/22 | 3/22 | 3/22 |
| DINO K=50 | 4/22 | 5/22 | 5/22 | 6/22 |

Operational localized hits use these numerators **over 30**, including all failures.
Candidate-frame hits in the earlier table are not correct-object-region hits.

## First-blocker taxonomy at n=20, IoU >=0.5

The following ordered taxonomy partitions **all 30 selected queries** once per
arm. A query is assigned to its first applicable blocker. It is an operational
accounting convention, not proof of one unique causal failure.

| First applicable outcome | K=10 | K=20 | K=50 |
| --- | ---: | ---: | ---: |
| Unsupported | 5 | 5 | 5 |
| Capture miss | 3 | 3 | 3 |
| Shortlist miss: no positive frame in prefix | 11 | 7 | 3 |
| Global proposal miss: no good proposal on any eligible positive frame | 6 | 9 | 10 |
| Prefix proposal miss: globally good proposal exists, none in prefix | 1 | 2 | 0 |
| DINO region miss: good prefix proposal exists, no good winning region | 1 | 1 | 3 |
| Ranking miss: good winning frame exists, none in first 20 | 0 | 0 | 0 |
| Localized hit in first 20 | 3 | 3 | 6 |
| **Total** | **30** | **30** | **30** |

There are **0 technical failures, source-exclusion-only failures or GT-unavailable
outcomes**. The two excluded source frames are still recorded in cadence accounting;
they do not create a query-level source-exclusion blocker.

The actual global proposal-query miss count is **11/22 at every K**, not 6/9/10.
The taxonomy's 6/9/10 reflects earlier shortlist precedence: **5/2/1 queries** fail
both shortlist access and global proposal coverage, so they are already counted
as shortlist misses. Likewise, the two globally covered queries lacking any good
Top-50 proposal are classified earlier as shortlist misses; zero K=50 prefix
proposal blockers does not mean every globally good region is accessible.

## Work accounting

These are recorded stage-wall sums for the completed work, including **27 PTS
attempts**. There were **three concurrent workers on a shared host**. Summed stage
time is not elapsed end-to-end wall time, per-query service latency, sustained
throughput or a controlled speedup measurement.

| Stage | Recorded work | Summed stage-wall seconds |
| --- | --- | ---: |
| PTS verification | 27 attempts | 1,004.13 |
| Frame extraction | 166 child processes; 3,373 PNGs | 7,892.46 |
| Base224 semantic computation | 3,346 images; 1,691 batches | 707.19 |
| YOLOS | 3,321 frames; 38,199 returned proposals | 2,060.59 |
| DINO | 13,806 rows; 7,128 batches | 1,027.96 |
| Arm ranking | 75 arms | 4.14 |
| Other | Remaining recorded work | 842.97 |
| **Total stage-wall sum** | | **13,539.44** |

The report's separate **`elapsed_sum` is 13,539.76 s**; it is also a sum, not
observed end-to-end wall time. Candidate DINO rows for K=10/20/50 are
**2,987 / 5,965 / 13,781**. The cached union was computed once, with query rows
included in the total 13,806; there are **not three independently timed arms**.
The shared timings cannot support per-K latency or speedup claims.

## Verification scope

The main agent ran the actual models for the **25 completed queries** and checked
their completion seals. Independent review verified **4,110 pins**, **100 arrays**,
**75 arms**, **1,101 winners** and **900 completed cells**. It replayed the
metadata and matrix hash checks and scoring/metrics from persisted vectors; the
external root remained unchanged. Maximum cosine replay error was **7.78e-16**;
maximum norm error was **2.17e-7**. This review was **not fresh model inference**.

| Private-helper test group | Supplied passing tests |
| --- | ---: |
| Cohort selection | 185 |
| Run/completion protocol | 100 |
| Evaluation | 128 |
| Bridge | 294 |
| **Total** | **707** |

These private-helper results were reviewed; the main-agent confirmation rerun
completed with **707 passed**: 128 evaluation, 100 run/completion, 185 cohort and
294 bridge tests. Helpers and their private evidence remain ignored. The
existing full Go, packaged ML and contract gates belong to the
[previous implementation-stage verification](object-search-experiment-2026-09-14.md#verification-and-next-work);
they were **not rerun for this private-only expansion**, and tracked Python source
is unchanged. This docs slice does not supply fresh build, CI or device evidence.

## Next experiment

1. Keep **Base224 full** as default and **K=50 as the next challenger**, subject to
   a new frozen comparison rather than automatic promotion from this cohort.
2. Prioritize raw-proposal, confidence-filter, crop-size and cap recall diagnostics,
   plus query-aware or class-agnostic region-candidate alternatives. Global returned
   proposal coverage misses 11/22 captured queries even before shortlist access.
3. Then improve access to good regions beyond the semantic prefix and investigate
   max-DINO wrong-region selection using retained descriptor evidence.
4. Version future query-geometry and longer-video support explicitly. Preserve this
   cohort, its unsupported outcomes and its completed inference; do not revise
   frozen evidence to make later support fixes appear to have succeeded here.
5. Collect annotated physical-instance hard negatives and recorder data before
   asserting same-instance quality, useful tracking or production readiness.
