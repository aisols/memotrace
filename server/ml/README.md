# CPU object-retrieval worker

Server-owned offline inference supports exactly three approved genuine SigLIP2
checkpoints. Code is **AGPL-3.0-only** under the complete autonomous
[`LICENSE`](LICENSE); the
separately acquired Google models are **Apache-2.0**. These are benchmark candidates,
not an assertion that any checkpoint has the best quality.

| Checkpoint | Pinned revision | Input / patch | Dimension | Parameters |
| --- | --- | --- | --- | --- |
| `google/siglip2-base-patch16-224` | `75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2` | 224 / 16 | 768 | 375,187,970 |
| `google/siglip2-base-patch16-384` | `f775b65a79762255128c981547af89addcfe0f88` | 384 / 16 | 768 | 375,479,810 |
| `google/siglip2-so400m-patch16-384` | `dd658faac399427308559e2c3ac1e99cbe43845d` | 384 / 16 | 1,152 | 1,136,039,602 |

## Install and ordinary verification

Run these commands **from the `server/` directory** with Linux x86-64, Python 3.12
and **uv 0.11.3**:

```bash
uv sync --locked --project ml
uv run --locked --project ml python -m memotrace_ml.verify
```

The verifier runs Ruff lint, Ruff format checking, **strict mypy over all source
and tests**, and pytest under pinned **coverage.py 7.10.6**. Synthetic tests
exercise spatial coverage, exact decimal boxes, EXIF, padding, bounds, JSONL recovery,
download redirects/deadlines, artifact confinement/provenance, content aliases and
judged metrics. They also build the actual wheel and sdist with locked Hatchling,
inspect their exact package resources and unmodified license, and install/import the
wheel without dependencies or network access. They forbid network connections and require no weights,
dataset, Go service, database, sibling component, or credentials. The fake encoder
exists only in tests and measures no retrieval quality. Two local mypy annotations
identify untyped third-party Transformers entry points; first-party checking is strict.

Independent ML review requested the component-local **≥95% statement coverage gate
for `memotrace_ml.images` only**. This cohesive deterministic spatial/decoder boundary
is where lost edges, invalid boxes and orientation mistakes can corrupt retrieval
geometry. `verify` enforces covered statements / total statements using coverage.py's
JSON report; it does not substitute the combined line/branch percentage. Branch
coverage is measured and reported without a separate branch threshold pending review.
The latest run covered **114/114 statements and 36/36 branches (100%)**. There is no
arbitrary package-wide coverage percentage. `.coverage-images.json` is generated,
ignored evidence; synthetic tests include exact 64/65-region boundaries and decimal
rasterization boundaries.

`uv.lock` contains actual resolved versions and distribution hashes, including
Hatchling 1.27.0 and its build dependencies. Torch uses the
explicit CPU index `https://download.pytorch.org/whl/cpu`, pinned to `2.8.0+cpu`;
the Linux x86-64 lock has no CUDA/NVIDIA/Triton dependencies. A dependency install
is separate from offline inference. Do not add model/data acquisition to ordinary CI.

## Explicit model acquisition and live smoke

```bash
uv run --locked --project ml python -m memotrace_ml.acquire \
  --model-dir /tmp/opencode/memotrace-search-models/siglip2-base-patch16-224

uv run --locked --project ml python -m memotrace_ml.acquire \
  --model-id google/siglip2-base-patch16-384 \
  --model-dir /tmp/opencode/memotrace-search-models/siglip2-base-patch16-384

uv run --locked --project ml python -m memotrace_ml.acquire \
  --model-id google/siglip2-so400m-patch16-384 \
  --model-dir /tmp/opencode/memotrace-search-models/siglip2-so400m-patch16-384

uv run --locked --project ml python -m memotrace_ml.smoke \
  --model-dir /tmp/opencode/memotrace-search-models/siglip2-base-patch16-224
```

Omitting `--model-id` remains the Base224 command and selects only its pinned revision.
[`model-manifest.json`](model-manifest.json),
[`model-manifest-siglip2-base-patch16-384.json`](model-manifest-siglip2-base-patch16-384.json)
and
[`model-manifest-siglip2-so400m-patch16-384.json`](model-manifest-siglip2-so400m-patch16-384.json)
pin SHA-256 and byte length of the model card/license declaration, configuration,
preprocessing configuration, tokenizer files and **safetensors** weights. Their weight
files are respectively **1,500,800,904**, **1,501,968,264**, and **4,544,267,488
bytes**. These sizes are intentional. SO400M needs substantially more RAM than its
4.54 GB float32 weight file alone, and 384-pixel crop batches also cost more memory
and CPU; provision and monitor it separately rather than assuming Base224 capacity.
Acquisition applies a fail-closed **4,544,267,488-byte per-artifact ceiling**, streams
HTTPS downloads with two attempts, verifies hashes and atomically publishes each
completed artifact. Initial URLs and every redirect are checked **before DNS or
connection** against exact public Hugging Face/CDN, Google Storage and CVDF S3
provider hosts in `public_download.py`. All DNS answers must be public; connections
use the validated numeric address, retaining TLS hostname verification/SNI. No
automatic redirect following, proxy, cookie or authorization forwarding is used.
A parent-owned subprocess wall deadline includes DNS, connect/TLS, headers, retries
and trickled bodies; expiration triggers terminate/kill with bounded cleanup.

Acquisition rejects roots inside Git and walks directory components with `O_NOFOLLOW`.
The effective user must own each model/data root, nested retained directory and
retained file; none may be group/other writable. Writable ancestry is also rejected,
except for a root/effective-user-owned sticky directory such as `/tmp`, where sticky
rename protection makes a private child safe. Thus examples below `/tmp/opencode`
require that intermediate directory to be `go-w`, and each artifact root should be
mode `0700` before use.
Writes use exclusive unpredictable same-directory stages, file/directory fsync, and
atomic no-clobber publication. Existing different bytes and symlinks fail closed;
identical explicitly verified artifacts are retained. Fixed `.partial` paths are
never followed. Unpinned pre-existing JPEGs are not accepted as downloaded data.
Open Images JPEG decoding and EXIF eligibility are validated in the downloader-owned
stage **before publication**. The pinned official image metadata supplies
`OriginalSize`, base64 `OriginalMD5`, and `Title`. The size and MD5 identify the original
Flickr content, not the resized CVDF JPEG. The actual CVDF artifact is bounded and
decoded before publication; its source, SHA-256 and byte length are retained separately
in the manifest, selection identity and attribution download record. Changed CVDF bytes
therefore cannot reuse a dataset version. The current v3 profile requires a receipt-bound
`attribution.json` with exactly one structurally validated license/author/title/URL entry
per selected image. Missing or drifted attribution and all older roots fail closed.
Rejected bodies leave no image-directory artifact; only the exclusive stage is removed.
A failed candidate followed by 48 valid images therefore produces a subset that
immediately passes provenance verification/resume.

Inference accepts a local manifest only when it exactly equals one of the three
packaged manifests, then verifies the exact inventory and every file. Unknown IDs,
manifest drift, extra files and symlink artifacts are rejected. It uses `SiglipModel` with
`trust_remote_code=False`, `use_safetensors=True`, `local_files_only=True`,
CPU float32, eager attention and deterministic algorithms. HF offline/telemetry
settings are set before importing Transformers. Keep the verified directory read-only
during inference. Verification uses open descriptors and is repeated after the
path-based framework load, closing persistent replacement between verification and
use. This does not defeat a malicious same-UID process that changes and restores bytes
during the load: the effective UID is the explicit trust boundary because this worker
is not an OS sandbox. There is no fallback encoder or runtime model download.

The explicit live smoke launches the actual JSONL child in its own process group with
an explicit offline allowlist, private temporary `HOME`, and a generated synthetic
JPEG. It sends SIGTERM on timeout, waits boundedly, and treats descendant leakage or
forced SIGKILL as failure. It checks both languages, both index
modes, EXIF coordinates, exact tiny/close/huge-exponent query boxes, original-image
fault mapping, a million-zero significand below the public 1 MiB request bound,
overlong-token rejection and recovery. This checks real inference/IPC
compatibility, not retrieval accuracy.

## Benchmark language evaluation

The Open Images benchmark emits three text-evaluation groups for every class and
each spatial index mode (`full` and `overlap`):

- `ru` embeds the manually curated Russian evaluation query and ranks by maximum
  per-asset cosine similarity.
- `en` embeds its manually curated equivalent English evaluation translation and
  independently ranks the same candidates by maximum cosine similarity. It is not
  output from an automatic translation model.
- `fusion` applies deterministic two-ranking Reciprocal Rank Fusion to the complete
  `en` and `ru` candidate rankings, with fixed `k=60` and identity tie-breaking.
  Its reported values are RRF scores, not cosine similarities.

The report retains both component results and records component query IDs, embedding
durations, ranking durations, and the additional fusion duration. Candidate-set drift
or duplicate IDs fails closed. This is an offline benchmark-only evaluation; it adds
no translation dependency and changes no worker or production search API behavior.
Curated translations test bilingual retrieval potential, but do not measure any
automatic translator's latency, translation quality, privacy, or operational risk.

Current runs use the ordered Open Images everyday-object v3 profile: Screwdriver,
Scissors, Hammer, Knife, Pen, Bottle, Mug and Mobile phone. Acquisition records that
exact name/MID profile and the benchmark fails closed unless its eight EN/RU query
pairs exactly match the verified ground truth. Candidate traversal order is
reproducible, but the first successful downloaded subset can differ after transient
provider/network failures; the recorded failure list and selected content determine
the resulting dataset version. Use a fresh external data root with `--count 100`;
earlier profiles are deliberately not reusable. Reports must
retain all eight classes in expected/actual evidence, including classes excluded from
primary macro averages for lacking a judged positive or negative.

## Private JSONL integration

The simplest worker command, with `server/` as the working directory:

```bash
uv run --locked --project ml python -m memotrace_ml.worker \
  --model-dir /tmp/opencode/memotrace-search-models/siglip2-base-patch16-224
```

Equivalent trusted Go argv configuration:

```json
["uv","run","--locked","--project","ml","python","-m","memotrace_ml.worker","--model-dir","/tmp/opencode/memotrace-search-models/siglip2-base-patch16-224"]
```

Install dependencies before starting the service; an operator can additionally set
`UV_OFFLINE=1` to make uv refuse dependency network access. Go owns child lifecycle,
serialized requests, timeouts, restart and an explicit environment allowlist without
DB/admin/AWS/device secrets, PGPASSWORD/PGPASSFILE, cloud/GitHub/HF credentials,
proxies, PYTHONPATH or loader injection. `HOME` is a fresh private directory and uv/HF
offline flags are mandatory. The implemented launcher is a **credential-sanitized,
same-UID process, not an OS sandbox**. HF offline flags constrain library behavior;
they do not enforce network isolation. Filesystem/egress restrictions require
deployment-provided OS controls and are not established by this launcher. The worker
interface/code implements no SQL, job leases/retries, archive deletion or ground-truth
lookup, but the OS can still permit access to other files readable by that UID.

Each request is one UTF-8 JSON object followed by a newline. Each response is one
JSON object with the same `id`, `ok:true` and the fields below, or
`{"id":"...","ok":false,"error":"invalid_request"}` / `"input_failed"` /
`"inference_failed"`.
Malformed IDs use `id:""`. IDs are strings of 1–128 characters. Duplicate keys,
unknown fields, nonfinite JSON, unsupported operations and malformed inputs fail.
Stdout contains only JSONL; initialization errors use a generic bounded stderr
message and exit nonzero. Request exceptions do not leak text, paths or tracebacks.
Corrupt/invalid stored JPEG decoding before encoder invocation returns `input_failed`;
Go retains the synchronized worker and maps the image-operation fault to the existing
public service-side behavior (`503 unavailable`). Unsupported/overlong text returns
`invalid_request` and also retains the worker. Generic encoder, runtime, malformed
output, and other inference failures return `inference_failed` and force worker
termination/restart. Go accepts retained-worker errors only as exact correlated
three-field frames; malformed, extra-field, or wrong-ID frames fail closed.

| Operation | Request fields after `id,op` | Successful response fields after `id,ok` |
| --- | --- | --- |
| `describe` | none | `model_fingerprint`, `dimension`, `model_id`, `model_revision`, `input_resolution`, `preprocessing_version`, `policies:{full:HASH,overlap:HASH}` |
| `image` | `image_base64`, `mode:"full"\|"overlap"` | `model_fingerprint`, `policy_fingerprint`, `width`, `height`, `vectors:[{kind:"full"\|"crop",box:[x0,y0,x1,y1],embedding:[float,...]}]` |
| `text` | `text` | `model_fingerprint`, `embedding` |
| `query_image` | `image_base64`, optional `box` | `model_fingerprint`, `embedding` |

**Limits:** original JPEG ≤16 MiB; decoded pixels ≤40,000,000; each dimension
≤16,384; input line including newline ≤24 MiB; output including newline ≤2 MiB;
≤64 regions. An oversized or unterminated line returns one error and ends the
stream rather than draining unbounded bytes or guessing the next request boundary.
Text is 1–2,048 Unicode characters, with nonempty content, no control/surrogate or
literal special tokens, and at most **64 model tokens including EOS**. Tokenization
does not truncate: overlong or unknown-token queries explicitly fail. No query
translation or invisible prompt template is applied.

Default CPU settings are `--threads 4 --batch-size 2`; threads are limited to 1–16 and
batch size to 1–8.
PyTorch intra-op and NumPy BLAS pools are bounded by the thread setting; PyTorch
interop uses one thread. Runtime settings enter the model fingerprint, so changing
them requires a separate generation even if vector dimensions remain identical.

## Coordinates and preprocessing

1. Decode the bounded JPEG with Pillow; reject corrupt/truncated files. Apply all
   eight EXIF orientation cases, then convert to RGB. Ignore ICC profiles; no
   external color-management inference is implied. Original JPEG bytes are unchanged.
2. **`width`, `height` and every box refer to the display-oriented image**, after
   EXIF transpose, with top-left origin. Boxes are normalized half-open pixel
   extents. An original-JPEG getter must preserve the EXIF bytes, and its viewer
   must honor EXIF exactly once before drawing boxes. Go's raw JPEG header dimensions
   alone are not the returned display dimensions when EXIF swaps axes.
3. Preserve the whole selected region using the checkpoint's trusted 224×224 or
   384×384 letterbox: longest side 224 or 384, other side rounded half-up with
   minimum 1 pixel, **Pillow bilinear** resize,
   RGB `(127,127,127)` padding, center offsets rounded down (an odd extra pixel goes
   right/bottom). There is no center crop. Convert RGB to float32 CHW and normalize
   with `pixel/127.5 - 1`, matching the pinned mean/std of 0.5.
4. Query boxes retain **exact JSON decimals** through positive-area validation and
   floor-start/ceil-end pixel rasterization. Ordinary decimals use `Decimal`; written
   exponents beyond Decimal's representable exponent range retain a symbolic exact
   significand/order. Work and storage scale with the input text, never `10**exponent`.
   Pixel multiplication sets explicit Decimal exponent bounds as well as input-sized
   precision, so a valid million-digit significand does not hit the default `Emax`.
   Go must preserve original `json.Number` lexemes in the unchanged JSON-number IPC,
   not convert them to binary floats. Both `[0,0,1e-400,1]` and
   `[0.5,0,0.50000000000000001,1]` are valid positive-area boxes and select touched
   pixels. Actually equal endpoints fail. Encode selected pixels in the same space.
5. L2-normalize the genuine model's 768-dimensional Base or 1,152-dimensional
   SO400M image/text features. These cosine similarities are not calibrated probabilities.

`full` emits one full-frame region. `overlap` emits it first, followed by square
tiles: `side=ceil(fraction*min(width,height))`,
`step=max(1,floor(side*(1-overlap)))`. Defaults are fraction 0.75 and overlap 0.25.
Start at zero on each axis; append the final edge-anchored position when needed;
enumerate y-major/x-minor and omit only identical windows. **Reject the entire
request if >64 regions would result**; never silently prune edge coverage. Tiny
images can have effective overlap different from 25% because pixel steps are
integer. A 1600×900 image yields six tiles plus the full frame. Area coverage is
not a guarantee that an object is recognized or wholly contained in a tile.
Returned crop boxes are coarse match regions, not predicted object detections.

`--min-side-fraction` and `--overlap` configure the policy. `describe.policies`
provides both fingerprints before any indexing. The model fingerprint covers
manifest content, weights/tokenizer, preprocessing version, query rounding,
precision/runtime versions, Python/architecture and bounded runtime settings.
Numerical runtime identity is limited to the selected model runtime distributions:
Torch, Transformers, Tokenizers, NumPy, Pillow, Safetensors and threadpoolctl. For
each selected distribution, it parses the bounded `RECORD`, then reads, hashes, and
verifies the actual bounded regular-file bytes for Python and native wheels. It fails
closed on missing files, symlinks, unhashed entries, or declared hash/size drift.
Only installer-generated `../bin` scripts are excluded:
the module worker does not execute them and their shebangs encode installation
paths. The resulting inventory uses deterministic relative names, never installation
paths or environment values, and bounded file counts and bytes cap startup I/O. The
identity also includes Python ABI/build, libc, Torch build flags, effective Torch CPU
capability, and the intersection of host CPU feature flags.
It also includes `implementation_sha256` and per-file hashes of **all packaged
first-party `.py` files**, including recursively added encoding helpers. Relative
resource names and actual bytes, not absolute paths, are hashed, so source-tree and
wheel resource locations agree. Tests prove changed/added code changes model and
generation identities. This deliberately conservative scope also invalidates a
generation when a packaged acquisition/benchmark helper changes; do not modify code
or model artifacts under an active worker. Source distributions and wheels retain
the implementation bytes used for hashing.
The 224 and 384 paths have distinct preprocessing versions. Every checkpoint also
has different manifest/architecture identity, so each produces a separate model
fingerprint and separate full/overlap generations. Never mix vectors or reuse a
generation across checkpoint selections, including between the two 384 models.
The policy fingerprint hashes canonical JSON describing the spatial policy.
Go should use the returned hashes, not independently serialize this specification.

```text
generation = SHA256(UTF8(model_fingerprint + ":" + policy_fingerprint))
```

Do not mix generations or reuse one when numerical runtime identity differs. This
enforces separation across detected Python/native-wheel/libc/Torch/CPU environments;
it is not a proof of bit-identical output on unmeasured microcode or kernel changes.
The [historical everyday-object evaluation](../benchmarks/everyday-object-evaluation-2026-09-10.md)
records pre-hardening 16x4 tuning, checkpoint comparison and a 100-image Base384 run.
The [dated main verification](../docs/retrieval-main-verification-2026-09-10.md)
records matching pre-hardening genuine Go/PostgreSQL/CLI/TLS execution and local
gates. Current live evidence requires fresh v3 acquisition and a model/data rerun.
The [final P2 verification note](../benchmarks/final-p2-verification-2026-09-09.md)
and [previous pilot](../benchmarks/openimages-pilot-review-v2-2026-09-09.md) are
historical evidence only for their recorded source revision and Base224 identities.
Identity-changing multi-checkpoint work makes those hashes non-current.
[Benchmark commands](../benchmarks/README.md) acquire and evaluate public data explicitly.
