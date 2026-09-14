# First usable offline object-search experiment, 2026-09-14

**Implemented, uncommitted, unreleased experimental tooling.** The first usable
offline pipeline now runs Base224 full-image semantic ranking, a fixed shortlist,
YOLOS-Tiny proposals, independent DINOv2-small descriptor reranking, and bounded
proposal tracklets. The production default remains **SigLIP2 Base224, full indexing**.
No new history endpoints, database object associations, or user-confirmation flow
are implemented. See the [operational guide](../docs/object-search-experiment.md)
for commands, input bounds, identities, ranking and temporal semantics.

This record summarizes the independently reviewed implementation/evidence supplied
by the main agent. Raw reports and private artifacts remain outside Git. Only safe
source/model/report hashes, public smoke query texts and aggregate results appear
here; no private IDs, object titles, media paths/hashes, annotation contents, raw
ranks or weights are included.
The [2026-09-13 report](everyday-object-evaluation-2026-09-13.md) retains its historical
source and limitations; the updates below do not rewrite that evidence.

## Source and artifact binding

Source baseline HEAD: `39b24e3367ccf1a045c1690a734facc7d8d5918d`.
The new experiment source is uncommitted; this HEAD is **not** an experiment
implementation commit. The following SHA-256 inventory identifies the actual
source bytes inspected for this record (paths relative to `server/`):

| Source | SHA-256 |
| --- | --- |
| `scripts/object_search_core.py` | `ca7cf74f4970d6cf641dd5cdd9550450a0dbdd42d701c6e7aa2107946a6f5364` |
| `scripts/object_search_vision.py` | `7dad35c654e9b0b6cdd49c2173dc8e49b589b83bd2e43c06129bc098a9b5891a` |
| `scripts/object_search_experiment.py` | `7c6d0c47e5cb27e80cd3d5e4b1346bafae92746ebb5d42a0bd47f4884ffcb1c5` |
| `scripts/test_object_search_core.py` | `bc0ba8c62fc51a4043cbbccb1a8c2ddc531271a8743d328451ef71a94afb87fc` |
| `scripts/test_object_search_vision.py` | `43b5ee9aa89d7810fc871acbf68027d124080881834dce31a452b5a116e062c0` |
| `scripts/test_object_search_experiment.py` | `d05019125efd1adaa0f2e97427cbf23ac283cb70330c78f00131ba7ff167a795` |
| `scripts/verify_object_search.py` | `c7e31d9c0d99fa0265f23606289049465465c055c441037dfd968755f96e6539` |

The existing **17-file packaged production ML implementation is unchanged**, digest
`980af7d9955f95dd0cbad7ee823d48c5e89cab1402d4cffebdb1ad699a493ef3`.
The experiment has its own semantic and descriptor identities binding source/model
bytes, numerical runtime content and effective computation settings. It does not
reuse the production identity merely because the semantic model is Base224.

| External evidence | SHA-256 |
| --- | --- |
| Genuine Go/PostgreSQL CLI/TLS smoke summary | `b1a87d6711cc67faa68321aa1706320df956e0ac78045ebef0951c28f14c8968` |
| Independent exact-smoke-query check | `7e33e97230cbf899625024856758344107174fdf7b506ca7e5c8340fe267b7a4` |
| Public object-search experiment report | `cf251483d2dc6cef72323c318eade383a31fac28faea2c20723a2d9c9632335e` |
| Private v7 cohort-bound report | `caccfe1cb0dadbe6a48a6ca681e3d5078c75e31a4240bcb444dcccf8e9b65ab0` |
| Private cohort receipt | `31c0d1ae2ec0d0da453693c4ea3877667a8f8711f3f7774d5b52ccb0b8487641` |
| Private three-query preparation report | `b72c02ca20bcfb16b7ec79ecf7fb70f7a7824374d2e19a49fc6bd3305465f92a` |
| Private three-query evaluation report | `31bab1e75f662c7108a533655d875bbe27affc0568d3637b5a8182d7a8f7772a` |

These identify actual external files, not Git artifacts or released binaries.
The private v7 report records its scoped dirty-worktree shape; it does not identify
a clean released artifact. Later source changes need fresh applicable verification.

## Genuine-model Go CLI/TLS smoke

The latest smoke imported **100 images**, indexed **100 full / 668 overlap vectors**,
and had **zero failures**. English/Russian CLI queries and HTTPS pairing, search,
history and original reads passed. Saved response schema validation passed **7/7**.
The production model fingerprint was
`c08a2b59d777738143744ee5d63cd9e3383c9047a93b8e162835611d5420e369`.

An independent check recomputed all **100 full-image embeddings**, then evaluated
the exact public smoke texts **`a screwdriver`** and **`отвёртка`**. It compared only
the **top-five IDs and scores**, which matched exactly: maximum absolute score
error **0**, absolute tolerance **1e-7**. This does not establish equality with
retained embeddings. Smoke texts differed from the old benchmark texts; this is
a direct matching check using the exact smoke inputs, not a same-query comparison
with that benchmark.

| Single-sample timing | Seconds |
| --- | ---: |
| Full / overlap indexing | 24.036 / 106.701 |
| English / Russian CLI query | 7.125 / 7.321 |
| First HTTPS search / subsequent history | 6.982 / 0.192 |

Cold-start/model-load effects differ between calls. These samples establish neither
warm p95 latency nor sustained throughput. Retained raw-transport/binary provenance
is limited; the smoke is scoped local integration evidence, not deployment evidence.
Open Images times remain unknown, so successful history means the unknown-time
response semantics, not verified temporal tracking.

## Additional model pins and runtime

| Model | Pinned revision | Safetensors bytes | Weight SHA-256 |
| --- | --- | ---: | --- |
| `hustvl/yolos-tiny` | `95a90f3c189fbfca3bcfc6d7315b9e84d95dc2de` | 25,978,888 | `5a6a017a20cb522dd347271fa5bd670467e456176aaccd940090e50985ac6e74` |
| `facebook/dinov2-small` | `ed25f3a31f01632728cabb09d1542f84ab7b0056` | 88,249,960 | `ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1` |

The pinned [YOLOS model card](https://huggingface.co/hustvl/yolos-tiny/blob/95a90f3c189fbfca3bcfc6d7315b9e84d95dc2de/README.md)
and [DINOv2 model card](https://huggingface.co/facebook/dinov2-small/blob/ed25f3a31f01632728cabb09d1542f84ab7b0056/README.md)
declare **Apache-2.0**. The original [YOLOS source license](https://github.com/hustvl/YOLOS/blob/5717fc29d727dab84ad585c56457b4de1225eddc/LICENSE)
is **MIT**, a distinct source-code license. These are scoped artifact/license
observations, not distribution approvals; model, upstream source and dataset terms
remain separate under the [licensing policy](../../docs/licensing.md).

No new pip dependencies were added. Acquisition is explicit and separate from
inference. Verified local-only safetensors loading uses CPU float32/eager/eval;
there is no runtime download or remote model code. Semantic and DINO descriptor
scores remain separate spaces: only the fixed semantic prefix is reranked. The
production package identity and Go-only container boundary remain unchanged.

## Public class-proxy experiment

The run used the **same 100 unique-image corpus and six exact image-query
signatures** as the historical benchmark. Baseline and reranked values below were
computed afresh. Signature equality does not assert bitwise score equality with
the historical benchmark's different cosine implementation.

| Metric | Full baseline | Proposal/descriptor reranked |
| --- | ---: | ---: |
| Primary condensed judged-corpus mAP | 0.8255880740712612 | 0.8371804683025443 |
| Condensed Hit@1 | 6/6 | 5/6 |
| Actual-corpus known-positive Hit@1 | 5/6 | 5/6 |

Historical dense-overlap mAP was **0.8382305910949056**, not a fresh dense-overlap
run in this experiment. Per-class AP improved for **two**, regressed for **three**,
and tied for **one**. About **84%** of judgments are unknown; unknowns are not
negatives. Condensed Recall@20 is trivially 1 because each query has at most 20
judged candidates. It does not demonstrate complete real-result recall.

Shared work comprised **66 detector frames**, **120 shortlist visits / 54 cache
hits**, **449 proposals**, **3 zero-proposal full-image fallbacks**, and **6 query
descriptors**: **458 descriptor rows**. Of **6,600 detector slots**, **6,006** were
low-score and **145** truncated, leaving **449** returned proposals.

| Stage | Seconds |
| --- | ---: |
| Semantic computation | 15.582 |
| Detector | 26.704 |
| Descriptor | 26.811 |
| Ranking | 0.207 |
| Model loads | 7.306 |
| Total | 80.022 |

The earlier roughly 122-second benchmark included a different mixed workload;
this is **not a controlled speedup comparison**. YOLOS's direct COCO vocabulary
does not include screwdriver or pen, and query-winning proposals sometimes cover
another object or background. This sparse class proxy establishes neither
same-instance retrieval nor localization performance.

## Private v7 cohort-bound repeat

The ignored private runner now accepts the existing **cohort-v1** input, revalidates
its schema, hash, policy and counts before running and before publication, and
embeds the receipt in a no-clobber **v7 report**. The v7 designation is the report
version, not the cohort input version. This closes the earlier detached-receipt
binding gap for this repeat; it does not retroactively prove the historical policy's
precommitment. The private adapter and inputs remain outside distributed code.

A real **30-clip / 132-query** rerun reproduced the v6 numerical results exactly:
capture **127/132**, conditional full mAP **0.25329409312552287**, staged mAP
**0.2808210266064571**. Among the **127 capture-hit queries**, AP improved for
**39**, worsened for **38**, and tied for **50**; the other **5** queries were
capture misses. Full processing took **1104.83 s**, incremental staged work
**1374.24 s**, and combined staged processing **2479.06 s**. This remains a selected,
unweighted cohort, not a population estimate. Its generic staged-crop experiment
is distinct from the proposal/descriptor experiment below.

## Private fixed three-query proposal/tracklet experiment

The three prior queries were fixed **before scoring**. A source-clip PTS scan checked
**8,999 frames / all 8,998 steps**, exactly **30 FPS**; the source/VQ frame-rate ratio
was **6**, with exact selected milliseconds. Canonical content and frame-zero
alignment still remain assumptions, and there is no wall clock. This narrow scan
does not establish timing provenance for the whole 30-clip cohort or independently
reproducible licensed acquisition. Authorized/licensed private inputs were used;
official VQ2D evaluation was not run.

Each query used its last **at most 64 cadence observations before the query**:
candidate counts **64 / 13 / 64**, or **141 gallery inputs plus 3 query PNGs**.
These are bounded windows, not entire-archive search. All **3/3** queries captured
response evidence: **11 of 51 annotated response-frame observations** were on
cadence; the other **40** were off cadence. In this sample no prior positive on the
1 Hz cadence was omitted by the window.

| Metric | Full baseline | Reranked |
| --- | ---: | ---: |
| mAP | 0.2951720732970733 | 0.4647435897435897 |
| MRR | 0.23974358974358975 | 0.5064102564102564 |
| Hit@1 | 0/3 | 1/3 |
| Hit@5 / Hit@10 / Hit@20 | 2/3 each | 2/3 each |

One query's AP improved, one regressed and one tied. One query had no true positive
in the semantic top 20, which fixed-shortlist reranking cannot repair. Proposal
IoU >=0.5 occurred on **9/11 positive frames**, with unequal per-query coverage in
a tiny sample; this is not whole-task detector accuracy.

Returned history contained **51 tracklets / 52 observations / one link**:
**50 singletons and one pair**. Geometry was independently checked. Descriptors
were not serialized, so mutual-best appearance matching cannot be independently
rechecked from the retained report; the in-process core was validated. Of **52
query-winning proposals**, **35** lacked an adjacent class/IoU-compatible neighbor:
**27** had no compatible class and **8** no compatible IoU. High overlap is not
established as the main fragmentation cause. Normal inter-cadence unknown visibility
and explicitly recorded missing coverage are separate; even a link establishes no
continuous presence or persistent object identity.

## Verification and next work

Main-agent evidence reports the following local checks and independent review of
all implementation and evidence. These are not fresh executions by this docs slice.

| Gate | Supplied result |
| --- | --- |
| New object-search verifier | PASS, 226 tests; Ruff lint/format and strict mypy PASS |
| Independently approved pure-core statement gate, >=95% | PASS, 612/636 = 96.23%; branches 186/210 reported separately, no branch threshold |
| Contracts (unchanged baseline) / packaged ML / generic evaluator | PASS, 2,090 / 231 / 60 tests |
| Full Go verifier | PASS, required PostgreSQL/race/fault and genuine Pillow-decoder checks |
| Standalone Go-only Docker build | PASS |
| Smoke helper / canonical snapshot parity | PASS, 23 tests / read-only parity |

### Completed server-source extraction

Main-agent server-source extraction verification is **complete**. The isolated
snapshot under an external root contains only server files selected from Git's
cached/tracked file inventory plus intended untracked server files. All imported
`memotrace_ml` modules and the three `object_search_core`, `object_search_vision`
and `object_search_experiment` modules resolve inside that snapshot.

Execution used the **existing provisioned locked-dependency interpreter**, with
`PYTHONPATH` set to the isolated snapshot's ML and server roots. This verifies
source isolation with provisioned dependencies, not a fresh virtual environment
or offline dependency bootstrap.

| Isolated server-source gate | Supplied result |
| --- | --- |
| Object-search verifier | PASS, 226 tests; Ruff lint/format, strict mypy and pure-core 96.23% statement gate |
| Packaged ML verifier | PASS, 231 tests |
| Full Go verifier | PASS, PostgreSQL/race/fault and genuine Pillow-decoder checks; protocol 94.4%, retrieval 95.2% statement coverage |

Hosted CI, PR/merge, release, deployment, encrypted private operation,
restored-backup/physical power-loss, Android sync/device and production evidence
remain separate pending gates. The local smoke above resolves the previous
current-source genuine-model CLI/TLS evidence gap only within its stated scope.

Next priorities are a frozen, broader same-instance/hard-negative benchmark and
holdout (a hard-negative recorder corpus is not yet established), then proposal
coverage and semantic-shortlist recall **before threshold tuning**. Retain diagnostic
descriptor/rejection evidence for independently reproducible association analysis.
Only then evaluate calibrated tracklets and persistent storage/API feedback;
production object associations and user confirmation remain future work.
