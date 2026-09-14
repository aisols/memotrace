# Everyday-object and private video diagnostics, 2026-09-13

**Current source-local external evidence.** These results apply to source commit
`3f99aa945f35cf0366985f3a4444157d27302404`. Its title is
`fix(server): distinguish Open Images derivative provenance`. The ML implementation
SHA-256 is
`980af7d9955f95dd0cbad7ee823d48c5e89cab1402d4cffebdb1ad699a493ef3`.
They identify that exact source and external artifacts, not `main`, a release, a
deployment, or production readiness.

This safe record contains only hashes and aggregate counts, timings, and metrics.
It contains no private IDs, titles, paths, images, annotations, media hashes,
model weights, or raw rankings. Downloaded public data, public attribution files,
model artifacts, raw public reports, private inputs, the private adapter, and raw
private reports remain outside Git.

## Open Images everyday-object v3

Fresh acquisition completed with **100/100 unique CVDF JPEGs**, **25,265,327
bytes**, zero download failures, and dataset version
`v5-everyday-object-pilot-v3-0712e3f8aafbaa83`. Acquisition took 133.2196
seconds. All 100 actual CVDF JPEG lengths differed from the official Flickr
`OriginalSize`; the CVDF derivatives and official original metadata therefore
retain separate provenance.

| External artifact | SHA-256 |
| --- | --- |
| Acquisition receipt | `74d6693e8f4f225144653112c988588115822d52645cfb383b11193005acf2fa` |
| Manifest | `f1a16f2afebba913765c5114e7d7f90459179b0f930c57be0183c6339c14bc62` |
| Ground truth | `dfd1761d217ca746876ea559365d9c301eb58b7b477c118ebf65532fa600e9e6` |
| Selection | `3023e81760fd56b2525200a61e055ce065a7f2d953668b2f4bc84d4cb1381e23` |
| Attribution | `4d68eb77fbb66051e717743f5b0f30d38ead6b1897dc9862537c520f70dfff32` |

Initial derivative acquisition is trust on first use through the allowlisted CVDF
HTTPS/WebPKI path. A completed resume verifies the receipt and every actual CVDF
SHA-256 and byte length, but this is not a signature or independent proof of
canonical media.

Six classes had both positive and negative judgments and entered the primary
macros. Scissors was excluded for no negative and Hammer for no positive; both
remain represented in source and exclusion evidence. Missing judgments remained
unknown rather than becoming negatives. The image-query corpus averaged about 84%
unknown judgments. Open Images measures sparse class-level retrieval, not instance
identity, tracking, or chronology, and supplies no observation times.

## Current checkpoint comparison

All three current-source reports used the same receipt-bound v3 acquisition.
Times are seconds and peak memory is Linux peak RSS. `Fusion AP` is the primary
condensed judged-corpus RRF result; `image AP` uses the documented image-query
proxy. Neither is an official Open Images or Ego4D metric.

| Checkpoint | Report SHA-256 | Model fingerprint | Peak KiB | Total s | Full / overlap index s | Full / overlap fusion AP | Full / overlap image AP |
| --- | --- | --- | ---: | ---: | --- | --- | --- |
| Base224 | `3fe28cd7727d96a96905c71cc3c022b7ee44263a45431a4a1b2d97eff343bb6d` | `c08a2b59d777738143744ee5d63cd9e3383c9047a93b8e162835611d5420e369` | 1,400,168 | 122.41 | 16.06 / 97.44 | .8558 / .8420 | .8256 / .8382 |
| Base384 | `849418b8a8b85810ee7af079fdef1823ab6a611be37af54331cf7e9d25185765` | `7e38e25328a25ee6c7745ea47a861ce0ed48992ce05bba36ae29b042dd904368` | 1,399,408 | 377.94 | 46.90 / 320.48 | .8903 / .8831 | .7740 / .8173 |
| SO400M384 | `0b1fcb1833455401c21d52486ea364bc4a37d7eb9b1da8accfa87674422d94d3` | `d9c96e195e54a2f1c5e73fd472094047c11706bd402ea947e3d01620b29939d2` | 3,942,576 | 1568.41 | 200.39 / 1341.24 | .9005 / .8834 | .7650 / .7616 |

For continued **visual-query** work, this comparison selects Base224 because its
image-query result and substantially lower CPU cost are the relevant tradeoff.
SO400M384's small full-mode text-fusion gain does not justify its visual-query
cost here. Full indexing remains the default; overlap and staged retrieval remain
experimental. This is a scoped working selection, not a final-best-model claim.

## Generic evaluator identity

The private video diagnostic used the tracked generic evaluator described in
[`../docs/retrieval-evaluation.md`](../docs/retrieval-evaluation.md):

| Tracked source | SHA-256 |
| --- | --- |
| Core | `fcc7f29b8930575ffad48f0f42695696b3e428a73e6d00795f409086512c05b4` |
| Metrics | `224e459200f701813e3a4c4c9ccbbf891088eb5a53cc3547166bcc408179236c` |

The ignored private v6 adapter runner had SHA-256
`2e375c3038144de1c40411c51db545e858e5c21155b2bf7ac9b3c5f25cd4b902`.
Its synthetic test had SHA-256
`e6bb20e2646fba3ce44904f05642ccbea172bc5360f7295e74608c9d13b8d296`,
and all 8 private adapter tests passed. The adapter calls the tracked generic core
and metrics; it is external diagnostic glue, not distributed product code. The
private annotation input identity was
`2460142091a222a398f46919d30639e5bea95effce4d2fec650046a10dc4d3c5`.
No annotation path or content is recorded here.

## Private Ego4D diagnostic

Authorized/licensed Ego4D access was available and used, and downloaded private
media and annotations were used for this external selected-cohort frame-retrieval
diagnostic.
Those inputs remain outside Git. Their canonical-media, PTS and frame-zero provenance
and independently reproducible licensed acquisition provenance were not established.
Official VQ2D evaluation was not run, and no private data, dataset adapter, or official
task implementation was added to the repository.

### Cadence choice

The paired 10-clip comparison evaluated 39 valid queries:

| Cadence | Report SHA-256 | Queries with captured response frames | Staged end-to-end Hit@10 |
| --- | --- | ---: | ---: |
| Stride 5 | `83001d4cc5760a65a406ce33a76c7af08aaceb187ca4dfcb130c5058f5b648f2` | 36/39 | .4103 |
| Stride 11 | `6065da0c261a9dc7b5890cf9a45cc48b2c1035e7a72bc9325471a7dddd7e52d8` | 31/39 | .3333 |

Stride 5 was retained for the larger diagnostic. The paired cohort was a
lexicographic prefix and therefore biased; its selection policy was external to
the reports. This comparison is a cadence decision for the diagnostic, not a
population estimate.

### Score-blind 30-clip cohort

The mode-0600 cohort receipt had SHA-256
`31c0d1ae2ec0d0da453693c4ea3877667a8f8711f3f7774d5b52ccb0b8487641`.
Selection was score-blind systematic UUID quantiles within valid-query-count
strata: 20 of 818 eligible clips from the 1-3-query stratum, 8 of 334 from the
4-6-query stratum, and 2 of 5 from the 7+-query stratum. The deliberate
overrepresentation of exploratory higher-query strata makes this a selected,
unweighted cohort, not a population estimate.

The 30 clips supplied **132 valid and evaluated queries**. The mode-0600 report
had SHA-256
`b0cdeaad932895052a405a523e1f2c3e45e54d37a62e32fb99c7f15cb2f3641a`.

Base224, stride 5, and shortlist K=20 produced capture coverage
**127/132 (.9621)**:

| Metric | Full | Staged |
| --- | ---: | ---: |
| Conditional mAP | .2533 | .2808 |
| Conditional MRR | .3031 | .3287 |
| Conditional Hit@1 | .1890 | .2205 |
| Conditional Hit@5 | .4094 | .4252 |
| Conditional Hit@10 | .5512 | .5512 |
| End-to-end Hit@1 | .1818 | .2121 |
| End-to-end Hit@5 | .3939 | .4091 |
| End-to-end Hit@10 | .5303 | .5303 |

Per-query AP improved for 39 queries, worsened for 38, and was unchanged for 50
among capture-hit queries. Full indexing produced 6,623 vectors in 1110.25 seconds.
The overlap shortlist covered 1,393 frames and produced 9,751 vectors in 1400.41
seconds. It avoided 78.97% of hypothetical all-overlap work, but staged processing
still took 2510.66 seconds, **2.261x** the full-only time. Extraction took 246.84
seconds and total prepublication work took 2792.52 seconds. These measurements keep
full as the default and staged retrieval experimental.

## Limits and pending evidence

- The private diagnostic is not official VQ2D. It has no detector, response peak,
  tracker, object localization metric, or official task score.
- Fixed-cadence extraction can miss a response. Conditional metrics exclude capture
  misses; end-to-end Hit@K includes every query and assigns misses zero.
- Initial private-media handling was TOFU and assumed canonical media, constant
  frame rate, and frame-zero alignment. No independent canonical-media, PTS, decode-
  order, time-base, or variable-frame-rate proof is claimed.
- No statistical significance was calculated. The private cohort is selected,
  stratified, unweighted, and disproportionately exploratory.
- The external cohort receipt is detached. Independent retrospective comparison
  matched receipt/report IDs, counts, query total, and annotation hash, but the
  report does not bind the receipt hash or policy and cannot prove policy
  precommitment.
- Provenance-matched core validation checked full-tail preservation in process, but
  the retained report evidence is truncated at K=20 and does not independently
  expose the complete tail.
- Neither corpus establishes learned stable instance identity, tracking, production
  chronology, first/last physical sightings, sustained-load behavior, or production
  quality.
- Current genuine-model Go/PostgreSQL CLI/TLS and authenticated HTTPS evidence is
  still pending. The current genuine-model evidence here is Python model/data
  evaluation only.
- Authorized/licensed access and use of downloaded private inputs are established
  above; independently reproducible licensed acquisition provenance and official
  VQ2D evaluation are not. Hosted CI, PR/merge, release, deployment, encrypted
  private operation, Android sync, and device evidence remain pending. No
  production-readiness claim is made.

## Source verification and review

At source commit `3f99aa945f35cf0366985f3a4444157d27302404`:

| Gate | Result |
| --- | --- |
| Contracts | PASS, 2,090 tests |
| ML | PASS, 231 tests; `memotrace_ml.images` 114/114 statements and 36/36 branches |
| Generic evaluator | PASS, 60 tests; core 578/578 statements and 210/210 branches; metrics 186/186 statements and 52/52 branches |
| Full server verifier | PASS, including PostgreSQL-15, race, fault, and decoder checks; protocol 94.4% (238/252), retrieval 95.2% (277/291) |
| Standalone Go-only Docker build | PASS |

Independent code review reported no remaining findings. Evidence reviews reported
only the low-severity limitations documented above. These local results do not
substitute for current genuine-model Go CLI/TLS execution, hosted CI, delivery,
deployment, Android/device, official VQ2D, or production evidence.
