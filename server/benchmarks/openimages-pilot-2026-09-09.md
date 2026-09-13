# Open Images / CPU SigLIP2 pilot — 2026-09-09

**Historical v1 evidence.** Its then-current implementation fingerprints and primary
aggregate policy were superseded by the next recorded historical
[review-fix v2 run](openimages-pilot-review-v2-2026-09-09.md). The original external
report and numbers below are preserved. Its text means include the positive-only
scissors class; they are secondary diagnostics under the revised both-polarities
primary policy, not primary scores for later revisions.

**Measured:** 48 public validation JPEGs; genuine pinned SigLIP2; full-frame versus
overlap; English/Russian text and three same-image-excluded class-level image
queries. This is a small selected pilot, not an instance/history benchmark.

## Historical command context and artifacts

Exact historical v1 reproduction tooling is not recorded here. The measured run used
`--threads 4 --batch-size 2 --image-queries --gt-query-crop`; those flags are retained
only as historical command context. The current
[benchmark guide](README.md#repeat-the-public-data-experiment) runs the successor v3
profile and intentionally rejects v1 roots, so it does not reproduce this 48-image
run. All artifacts below are external to Git:

```text
model directory: /tmp/opencode/memotrace-search-models/siglip2-base-patch16-224
data directory:  /tmp/opencode/memotrace-openimages
Go input:        /tmp/opencode/memotrace-openimages/manifest.json
ground truth:    /tmp/opencode/memotrace-openimages/ground-truth.json
selection:       /tmp/opencode/memotrace-openimages/selection.json
attribution:     /tmp/opencode/memotrace-openimages/attribution.json
measured report: /tmp/opencode/memotrace-openimages/report-bounded.json
```

Dataset: `openimages-tools-validation`, version `v5-pilot1-3e085ee7ebc52701`.
All 48 requested JPEGs were acquired; final selection had **0 missing downloads**.
Final assembly took **44.156 s**, reusing four metadata CSVs and six JPEGs acquired
during the initial sparse-tools inspection. This is not a cold network timing.
No image bytes, author identities, ground-truth contents or model weights are in Git.

| Artifact | SHA-256 |
| --- | --- |
| Dataset manifest | `5e80b91e992dbded88c2970c4b78f1c6bdfd488601bded9650cb5b389f10badd` |
| Ground truth | `b16db8ae213e41ff83b93013f07e89f96adceae37e40f96deac6d4b40f6eb511` |
| Selection | `51e032c4a275d13ab5f7d57570ed9e539b0d22ca9240011fa85a0c40cd98ce51` |
| Measured report | `13d6e5c3b5986f3371bb0dad700baebb1191f879b85ab1fd60b44b694bca81d0` |
| Model safetensors | `612923381c76ec5a9bed335d1c48827e3f2e506ac31b044b63b2031fadee6a0b` |
| Source model manifest | `28f63df6adf09940ef9bd9bcb56e555a69d7c3ffe85c2fd862c956724bbb66f1` |
| Python uv lock | `2e0ed3efc6cfee3b3549502abb545e5e3bf4bbe6ea6e670427dfef8819954991` |

The report hash includes measured timings and changes on a repeat run. Model files
and all four metadata sources are separately pinned in the implementation.

## Actual annotation availability

These counts are **images**, not boxes. `P/N/U` means human-positive,
human-negative, unknown for that class. Counts overlap between classes.

| Class | Validation source P / N | Eligible P / N | Selected P / N / U |
| --- | ---: | ---: | ---: |
| Screwdriver | 3 / 1 | 3 / 1 | 3 / 1 / 44 |
| Scissors | 1 / 0 | 1 / 0 | 1 / 0 / 47 |
| Hammer | 1 / 2 | 0 / 1 | 0 / 1 / 47 |
| Knife | 59 / 19 | 51 / 18 | 11 / 11 / 26 |
| Pen | 44 / 42 | 39 / 37 | 11 / 10 / 27 |

Eligibility requires declared CC BY 2.0, known zero dataset rotation and identity
JPEG EXIF. The hammer positive has unknown rotation and was not included. Knife
and Pen supplement the requested tools because only six eligible images were
available among Screwdriver/Scissors/Hammer. Every selected positive has a box.

The judged scissors score is **trivial**: one positive and no negatives. Screwdriver
has only four judged images. Hammer has no positive metric. The more informative
class-level comparisons here are Knife and Pen; broad claims from macro scores
would be unjustified. Unknowns are never inferred absent.

## Model identity and interoperable generation IDs

Model `google/siglip2-base-patch16-224`, revision
`75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2`, Apache-2.0; **375,187,970 parameters**,
**768 dimensions**. Pillow preprocessing version
`exif-rgb-letterbox-bilinear-224-pad127-v1`; genuine CPU float32 L2-normalized vectors.

```text
model fingerprint:
090d6cb453e3bcfb7380a8a50fedeb2882bf675d92beb0d31636745020334e72

full policy:
c2dac9ddd5d959fe0440dee20555a746cef450f433b39658e16dbaac43bb42fb
overlap policy:
826ed3eb8fa14278e762479e8e259256adf1c1a2116cdd7b9270ac568022c3eb

full generation:
7078cd96b4046a1969d1799e685246c0eb1fdc553d4d272848fdaa0dbe836c4a
overlap generation:
6e3e1c569a6c1e5463e1be1ed63e6d1487561fd1a6927a6f3ec8dceed0df386a
```

These model/generation hashes apply to the locked Python 3.12.3 environment and
4-thread/2-image-batch settings. Use `describe` for the actual deployment rather
than assuming another runtime yields these hashes.

## Measured resource use

Host: AMD Ryzen 9 5950X, 16 cores / 32 logical CPUs, approximately 64 GB RAM,
Linux 6.8.0-137-generic x86-64, glibc 2.39. Torch 2.8.0+cpu, Transformers 4.56.2,
NumPy 2.2.6, Pillow 11.3.0; exact transitive packages in `ml/uv.lock`.
PyTorch and NumPy BLAS bounded to **4 threads**, interop **1**, image batch **2**.

| Measurement | Full | Full + overlap |
| --- | ---: | ---: |
| Indexed images | 48 | 48 |
| Indexed vectors | 48 | 322 |
| Image-pipeline duration | 7.917 s | 48.930 s |
| Median per-image duration | 0.164 s | 1.052 s |
| Maximum per-image duration | 0.189 s | 1.359 s |

Model verification/loading: **4.750 s**. Entire benchmark: **62.769 s**.
Linux process peak resident set: **1,398,832 KiB** (approximately 1.33 GiB).
Safetensors uses mapped storage: RSS is not the model's total artifact size or a
bound on deployment RAM. Weight verification reads all files first; page-cache
state was uncontrolled, and this was not a cold-cache experiment. Full mode ran
first, overlap second. Timings include JPEG reads/base64/decode/preprocessing and
inference through the in-process worker; JSONL transport, Go/SQL and server queue
time are excluded. No throughput/capacity claim for a full day or year follows.

## Retrieval results

Metrics follow the [condensed judged-corpus definitions](README.md#ranking-and-metric-definitions).
Asset scoring is **max cosine over regions**, with stable ID ties and one rank per
asset. Both modes keep the full vector. Exact fixed EN/RU queries are recorded in
the runner/report; no tuning against results occurred. Image queries use the
largest ground-truth box only on the source query; candidate crops never use it.

| Query group | Mode | Evaluable queries | Mean AP | Mean Recall@5 | Mean Recall@10 | Mean Recall@20 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| English text | Full | 4 of 5 | 0.9106 | 0.7273 | 0.8864 | 0.9773 |
| English text | Overlap | 4 of 5 | 0.9423 | 0.7273 | 0.9091 | 1.0000 |
| Russian text | Full | 4 of 5 | 0.9075 | 0.7273 | 0.8864 | 0.9773 |
| Russian text | Overlap | 4 of 5 | 0.9086 | 0.7273 | 0.8864 | 1.0000 |
| GT-crop image proxy | Full | 3 | 0.8034 | 0.5333 | 0.7667 | 1.0000 |
| GT-crop image proxy | Overlap | 3 | 0.8090 | 0.5333 | 0.8000 | 1.0000 |

Mean **Hit@1 and Hit@5 were 1.0** for every evaluable group, in the condensed judged
lists. This must not be represented as a 100% unfiltered-corpus success rate:
unknown images occupy real ranks and are counted separately in the machine report.
The text averages include the trivial scissors class. Hammer text metrics are
null; scissors/hammer image queries are unavailable because no other positive is
available after source exclusion. The three image queries are Screwdriver, Knife,
and Pen, with 2, 10, and 10 remaining known-positive images, respectively.

Overlap provided a modest AP/recall improvement here at about **6.2×** image-pipeline
time and **6.7×** vectors. This pilot does not demonstrate small-object detection,
robust Russian-language performance, same physical instance identity, calibrated
scores, chronological history, or any official Ego4D visual-query score. A larger,
better-judged corpus and separate video/device/server measurements remain necessary
for those conclusions.

## Historical verification evidence for this builder slice

The command forms below record checks executed for this builder slice; they are not
current reproduction instructions.

- `uv run --locked --project ml python -m memotrace_ml.verify`: Ruff lint/format,
  strict mypy over **16 source/test files**, **64 tests passed**; tests prohibit network.
- `uv run --locked --project ml python -m memotrace_ml.smoke --model-dir ...`:
  **8 actual-model JSONL requests passed**, including EXIF, both policy modes,
  English/Russian, overlong-token rejection and recovery; **0 stderr bytes**.
- All pinned public model files downloaded and verified. The bounded final
  benchmark completed with the real weights and 48 verified public JPEGs.
- `uv build --project ml`: source distribution and wheel built successfully,
  including the pinned model manifest; generated distributions are ignored by Git.
- Go integration, full server/contract gates, independent review and merge approval
  are owned by the main agent and the other builders. This document records only
  executed Python/data evidence.
