# Open Images pilot — review fixes / v2, 2026-09-09

> **HISTORICAL PRE-HARDENING PERFORMANCE EVIDENCE.** The later
> [final P2 verification](final-p2-verification-2026-09-09.md) recorded different
> historical implementation/model/generation identities. Neither record supplies a
> current live identity: current fingerprints and generations are unavailable pending
> fresh v3 acquisition and a live hardened-source model/data run. At the time, this
> report assigned a new full benchmark and Go end-to-end run to MAIN; it did not claim
> their completion. The report and timings below apply only to the preceding source
> revision.

**Executed Python/data evidence at this preceding revision:** all eight independent-
review findings were addressed, exact-decimal query boxes were coordinated with the
unchanged private JSON-number protocol, and the genuine CPU benchmark was rerun after
the implementation fingerprint changed. The original dataset/provenance and
historical [`report-bounded.json` evidence](openimages-pilot-2026-09-09.md) were preserved.

## Review resolutions

1. **Acquisition routing/deadlines:** exact HTTPS provider allowlist, manual redirects
   validated before the next DNS/connect, rejection of every non-public DNS answer,
   numeric-address pinning with TLS hostname/SNI verification retained. A parent
   process enforces the whole DNS/connect/TLS/headers/retry/body wall deadline with
   bounded terminate/kill cleanup. Offline tests reproduce forbidden redirects,
   private DNS, stalled phases and continuously trickled bytes. Public probes executed
   during this review succeeded for the pinned HF tokenizer.model, Google class
   metadata and a CVDF S3
   JPEG under `/tmp/opencode/memotrace-download-review-public-20260909`.
2. **Artifact confinement:** descriptor-relative `O_NOFOLLOW` walks, regular-file
   reads, exclusive unpredictable staging, fsync and atomic no-clobber publication.
   Outside-directory and fixed-partial symlink sentinels remain untouched in tests.
   Existing different JSON is rejected, not overwritten.
3. **Resume provenance:** a completed trusted acquisition receipt must validate
   manifest/ground-truth/selection hashes, pinned metadata, image identities and
   every JPEG's hash/length. Unreceipted JPEGs and changed valid JPEGs fail before
   metadata rewriting. The actual 48-image acquisition revalidated without changing
   its original receipt or files. Newly created receipts also pin attribution.
4. **Content identity:** verified SHA-256 aliases are deduplicated before indexing
   and scoring; the smallest ID represents a content group. All source-SHA aliases
   are excluded before image-query scoring. Known/unknown judgments can merge;
   contradictory positive/negative judgments for identical bytes reject evaluation.
   This corpus has **48 distinct hashes and zero aliases**; the earlier pilot was
   not biased by duplicate bytes. Each inference read also rechecks its item hash.
   The 48–100 acquisition bound applies to source items; a deduplicated corpus can
   contain fewer distinct images without falsely counting aliases as extra evidence.
5. **Primary metrics:** primary macro means require both positive and negative
   judged content candidates after source exclusion. Scissors is excluded with
   `no_negative`; Hammer with `no_positive`. The earlier positive-only policy remains
   an explicitly labeled secondary diagnostic, with per-query output and counts.
6. **Implementation identity:** the model fingerprint includes a digest and per-file
   hashes of all packaged first-party Python, including the new decimal/helper code.
   Tests show source/wheel-resource path independence and generation invalidation
   for changed/added code. The source distribution and wheel rebuilt successfully.
7. **Coverage:** coverage.py **7.10.6** is locked. Independent review's **≥95%
   statement gate on `memotrace_ml.images` only** is enforced by the component
   verifier. Branch coverage is reported separately without a branch gate.
   Exact 64/65-region, malformed-shape, padding and decimal boundary tests were added.
8. **Process claims:** documentation at this revision described the implemented
   credential-sanitized **same-UID process**. It did not claim an OS filesystem/network sandbox. Such
   isolation requires separately supplied deployment controls; the UID can still
   read other files allowed by the OS.

### Exact decimal integration

Go must retain `json.Number` lexemes into the existing JSONL `box` number array.
Python uses exact decimal parsing, validation and floor/ceil rasterization; enormous
exponents are represented symbolically rather than expanded into huge integers.
The valid boxes `[0,0,1e-400,1]` and `[0.5,0,0.50000000000000001,1]` select touched
pixels instead of becoming zero-width floats. Equal/reversed endpoints still fail.
The preprocessing version at this revision was
`exif-rgb-letterbox-bilinear-224-pad127-exact-box-v2`.
JPEG decoding faults return `inference_failed`; unsupported text returns
`invalid_request`. Go owns public error mapping. Display-oriented EXIF coordinates,
full/overlap response fields and dimension 768 remain the documented protocol.

## Verification and measured command

From `server/`, Python **3.12.3**, uv **0.11.3**:

```bash
uv run --locked --project ml python -m memotrace_ml.verify
uv run --locked --project ml python -m memotrace_ml.openimages \
  --data-dir /tmp/opencode/memotrace-openimages --count 48
uv run --locked --project ml python -m memotrace_ml.smoke \
  --model-dir /tmp/opencode/memotrace-search-models/siglip2-base-patch16-224
uv run --locked --project ml python -m memotrace_ml.benchmark \
  --model-dir /tmp/opencode/memotrace-search-models/siglip2-base-patch16-224 \
  --data-dir /tmp/opencode/memotrace-openimages \
  --output /tmp/opencode/memotrace-openimages/report-review-v2-final.json \
  --threads 4 --batch-size 2 --image-queries --gt-query-crop
uv run --locked --project ml python -m memotrace_ml.summary \
  --report /tmp/opencode/memotrace-openimages/report-review-v2-final.json
```

For an independent repeat, change the output to a fresh filename, for example
`report-review-v2-independent.json`; different existing reports cannot be clobbered.

- **113 tests passed** with network forbidden in ordinary tests.
- Ruff lint/format and **strict mypy across all 22 source/test files passed**.
- `images`: **103/103 statements, 34/34 branches = 100%**. Statement gate passed.
- Live smoke: **12 genuine-model JSONL requests passed**, including tiny/close/huge
  decimal boxes and image-error mapping; **0 stderr bytes**.
- `uv build --project ml`: source distribution and wheel built successfully.
- The recorded acquisition passed its then-new provenance/resume validation.

## Dataset identity and judgments

Dataset `openimages-tools-validation`, version **`v5-pilot1-3e085ee7ebc52701`**.
The recorded manifest was Go's input:
`/tmp/opencode/memotrace-openimages/manifest.json`.
There were **48 assets, 48 unique content hashes, zero aliases**. All three time
fields were null; there was no Open Images chronology or fabricated capture time.

| Class | Positive / negative / unknown images | Primary text eligibility |
| --- | ---: | --- |
| Screwdriver | 3 / 1 / 44 | included; very small judged corpus |
| Scissors | 1 / 0 / 47 | excluded: no negative |
| Hammer | 0 / 1 / 47 | excluded: no positive |
| Knife | 11 / 11 / 26 | included |
| Pen | 11 / 10 / 27 | included |

The selection, public metadata sources/licenses and annotation availability were
unchanged from the historical report. Hammer's sole source positive had unknown
rotation. Knife/Pen supplemented the sparse requested tools; no class was silently
reselected during these fixes. Ground-truth boxes are used only for optional query
crops, never candidate indexing.

## Fingerprints and artifact hashes of this historical run

Genuine checkpoint: `google/siglip2-base-patch16-224`, revision
`75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2`, Apache-2.0,
**375,187,970 float32 parameters**, **768-dimensional L2 features**.

```text
implementation_sha256:
ab03ee839e98d5f968dbd82478c066b0622188a78f492b446730f8d909dfe713
model_fingerprint:
8134f6458613cfad0432636a1699f0bfbe660392f891caa0700c43f012b5b117

full policy:
c2dac9ddd5d959fe0440dee20555a746cef450f433b39658e16dbaac43bb42fb
overlap policy:
826ed3eb8fa14278e762479e8e259256adf1c1a2116cdd7b9270ac568022c3eb

full generation:
4ee4719ab89d6b4d5658ff6d2d00bbcf6f2b541ea2d432ffea0774d6f8d88bb7
overlap generation:
a3051e9f07719009a40a9ce09cb15771ef3fe9d0dac59a6b52d54315bf99cdc7
```

Generation remains SHA-256 of UTF-8 `model_fingerprint + ':' + policy_fingerprint`.
Use dynamic `describe` values for the actual installed runtime. Further packaged
Python code changes invalidate these fingerprints and require new evidence.

| Artifact | SHA-256 |
| --- | --- |
| Final `report-review-v2-final.json` | `2d7b5aba40ff207d79c050e9eadead9377128424e30fa35b5f27c7e9cddf90a6` |
| Preserved `report-bounded.json` | `13d6e5c3b5986f3371bb0dad700baebb1191f879b85ab1fd60b44b694bca81d0` |
| Preserved `manifest.json` | `5e80b91e992dbded88c2970c4b78f1c6bdfd488601bded9650cb5b389f10badd` |
| Preserved `ground-truth.json` | `b16db8ae213e41ff83b93013f07e89f96adceae37e40f96deac6d4b40f6eb511` |
| Preserved `selection.json` | `51e032c4a275d13ab5f7d57570ed9e539b0d22ca9240011fa85a0c40cd98ce51` |
| Preserved `acquisition.json` | `18157215e743fc1a459e69ce08b5c27b6254d20987323d97a71dd2b666cdfba2` |
| Recorded `ml/uv.lock` | `9cebdec0a9e50246fbd466b1d0e8bc1d126eac0b1e1723f991d6aeeefa9707d6` |
| Source model manifest | `28f63df6adf09940ef9bd9bcb56e555a69d7c3ffe85c2fd862c956724bbb66f1` |

Report hashes include measured timings and therefore change on independent repeats.
All JPEGs, ground-truth contents, source attribution and model weights remain external.
An intermediate `report-review-v2.json` also remains external. The `-final` report
above is the run after the final source-count/deduplication-bound correction and is
the evidence matching the recorded implementation fingerprint.

## Measured results at this historical revision

Ryzen 9 5950X, Linux 6.8.0-137-generic x86-64, approximately 64 GB host RAM.
CPU-only Torch 2.8.0+cpu, four PyTorch/BLAS threads, one interop thread, batch two.

| Measurement | Full | Full plus overlap |
| --- | ---: | ---: |
| Distinct indexed images | 48 | 48 |
| Vectors | 48 | 322 |
| Image-pipeline duration | 7.828 s | 48.075 s |
| Median image latency | 0.161 s | 1.028 s |
| Maximum image latency | 0.182 s | 1.363 s |

Model verification/load **4.776 s**; total benchmark **61.862 s**.
Linux peak RSS **1,398,976 KiB**, approximately **1.33 GiB**. This is resident memory,
not total mapped weight storage or a production memory guarantee. OS page cache and
other host load were uncontrolled. Full ran before overlap; no cold-cache assertion.
Image timing includes verified reads/base64/decode/preprocessing/inference, excluding
JSONL IPC, Go, SQL and queues.

**Primary both-polarities, condensed-judged metrics:**

| Query group | Mode | Eligible queries | Mean AP | Recall@5 | Recall@10 | Recall@20 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| English | Full | 3 of 5 | 0.8808 | 0.6364 | 0.8485 | 0.9697 |
| English | Overlap | 3 of 5 | 0.9230 | 0.6364 | 0.8788 | 1.0000 |
| Russian | Full | 3 of 5 | 0.8767 | 0.6364 | 0.8485 | 0.9697 |
| Russian | Overlap | 3 of 5 | 0.8781 | 0.6364 | 0.8485 | 1.0000 |
| GT-crop image proxy | Full | 3 | 0.8034 | 0.5333 | 0.7667 | 1.0000 |
| GT-crop image proxy | Overlap | 3 | 0.8090 | 0.5333 | 0.8000 | 1.0000 |

Mean Hit@1 and Hit@5 are 1.0 in these **judged lists**, not an unfiltered-corpus
100% success claim. Unknowns are removed without being declared negative; their
positions/counts in actual corpus ranks remain in the report. The three primary
classes are Screwdriver/Knife/Pen, with only four judged screwdriver assets. Image
queries exclude the source content and retain 2/10/10 known-positive candidates.
Scissors/Hammer image queries remain unavailable. The secondary positive-only text
mean APs retain the old diagnostics (EN 0.9106/0.9423, RU 0.9075/0.9086), clearly
separate from primary scores.

Overlap costs approximately **6.1×** image-pipeline time and **6.7×** vectors here.
This small selected, incompletely judged class-level pilot does not establish
same-instance history, small-object detection, calibrated probabilities, sustained
capacity or official Ego4D VQ quality. Go integration, independent verification of
any later revision and the other component gates were outside this builder record.
