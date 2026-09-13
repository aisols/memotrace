# Final P2 fixes — historical builder verification

> **HISTORICAL PRE-HARDENING BUILDER RECORD.** Checks, counts, fingerprints and
> generations below apply only to the recorded 2026-09-09 source. Current model
> fingerprints and generations are unavailable pending fresh v3 acquisition and a
> live model/data run on the hardened source.

The two final independent re-review findings were fixed within `server/ml/` and
`server/benchmarks/`. The builder ran the full ML verifier, existing acquisition
resume validation, a genuine-model smoke including the long significand, and the
source/wheel build. **No full Open Images benchmark was rerun at this revision.**
At the time, this note assigned the fresh-generation benchmark and Go end-to-end
evidence to MAIN; it does not claim those follow-up steps were completed.

## Resolutions and regressions

**A — rejected download publication:** the downloader now accepts a bounded body
validator that runs on its exclusive staging file before atomic publication.
Open Images uses it for JPEG decoding/limits and identity EXIF validation. The
validated download receipt supplies the item digest/length. Rejection removes only
the owned stage, never a published or unknown pre-existing artifact.

Two complete synthetic acquisition regressions exercise the real staging/deadline/
publication path with a fake network fetch: first an invalid HTTP body, or first a
valid but EXIF-rotated JPEG, followed by 48 valid JPEGs. Both leave exactly 48 eligible
files, record the rejected candidate, and immediately pass `verified_acquisition`
and resume. An added unknown sentinel still triggers rejection and remains untouched.

**B — long-significand overflow:** pixel multiplication now explicitly sets Decimal
`Emax=MAX_EMAX` and `Emin=MIN_EMIN`, retaining precision bounded by written input
digits. The raw positive box with endpoint `0.5` followed by 1,000,000 zeros and a
final `1` remains below the public 1 MiB request limit and rasterizes to the expected
**1×3 crop for a 4×3 image**. A pure spatial regression checks the actual selected
column; a worker regression proves this crop reaches the test encoder successfully.
The recorded live smoke also sent this box to the genuine model. Then-existing tiny/
huge-exponent and equal/reversed-endpoint tests continued to pass.

## Executed checks

From `server/`, with Python 3.12.3 and uv 0.11.3:

```bash
uv run --locked --project ml python -m memotrace_ml.verify
uv run --locked --project ml python -m memotrace_ml.openimages \
  --data-dir /tmp/opencode/memotrace-openimages --count 48
uv run --locked --project ml python -m memotrace_ml.smoke \
  --model-dir /tmp/opencode/memotrace-search-models/siglip2-base-patch16-224
uv build --project ml
```

- **117 tests passed**, with network forbidden in ordinary tests.
- Ruff lint/format and **strict mypy over all 22 source/test files passed**.
- `memotrace_ml.images`: **103/103 statements and 34/34 branches, 100%**;
  the independently approved ≥95% statement gate remains enforced.
- **13 genuine-model JSONL smoke requests passed**, including the million-zero
  significand; **0 stderr bytes**.
- Source distribution and wheel built successfully.
- Existing **48-image acquisition revalidated with unchanged provenance**.

## Recorded smoke identities

Model: `google/siglip2-base-patch16-224`, revision
`75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2`, **768 dimensions**, CPU float32,
four threads and batch two. The preprocessing label at that revision was
`exif-rgb-letterbox-bilinear-224-pad127-exact-box-v2`; the changed source bytes
invalidated prior generations for those bug fixes.

```text
implementation_sha256:
1637853b5d1ecd6c4b1eed4ddc96f21e9e288f586cc0976427634812ca55f997
model_fingerprint:
039ea1fc87576995648b814babe64be19b135d2a2428c98800fd92c9e099f9da

full policy:
c2dac9ddd5d959fe0440dee20555a746cef450f433b39658e16dbaac43bb42fb
overlap policy:
826ed3eb8fa14278e762479e8e259256adf1c1a2116cdd7b9270ac568022c3eb

full generation:
faec3cb05e434b29d5b13840820045b6152fed64bac2ac4b97970e3334775ba2
overlap generation:
1c9c314934ad7992530ed328850ff317598d05679a70fa4b1df34d6f6634e21b
```

Generation is SHA-256 of UTF-8 `model_fingerprint + ':' + policy_fingerprint`.
These hashes matched the source revision used by the successful genuine smoke.

The recorded dataset was `openimages-tools-validation`, version
`v5-pilot1-3e085ee7ebc52701`, under `/tmp/opencode/memotrace-openimages`:

| Preserved artifact | SHA-256 |
| --- | --- |
| `manifest.json` | `5e80b91e992dbded88c2970c4b78f1c6bdfd488601bded9650cb5b389f10badd` |
| `ground-truth.json` | `b16db8ae213e41ff83b93013f07e89f96adceae37e40f96deac6d4b40f6eb511` |
| `selection.json` | `51e032c4a275d13ab5f7d57570ed9e539b0d22ca9240011fa85a0c40cd98ce51` |

## Historical commands proposed for MAIN's follow-up

The worker argv and exact JSON-number box protocol were unchanged at this recorded
revision. The planned Go run needed to preserve `json.Number` lexemes and use dynamic
`describe` hashes rather than treating the recorded identities above as current.

```bash
uv run --locked --project ml python -m memotrace_ml.worker \
  --model-dir /tmp/opencode/memotrace-search-models/siglip2-base-patch16-224

uv run --locked --project ml python -m memotrace_ml.benchmark \
  --model-dir /tmp/opencode/memotrace-search-models/siglip2-base-patch16-224 \
  --data-dir /tmp/opencode/memotrace-openimages \
  --output /tmp/opencode/memotrace-openimages/report-final-p2-main.json \
  --threads 4 --batch-size 2 --image-queries --gt-query-crop
```

These commands were supplied for MAIN as a historical follow-up plan, not claimed as
executed here and not current rerun instructions. At the time, a fresh output filename
was required to preserve older evidence. The earlier v2 report is explicitly historical
and contains no timing or retrieval-quality evidence for this recorded revision.
