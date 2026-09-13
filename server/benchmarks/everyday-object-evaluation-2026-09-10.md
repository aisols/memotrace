# Everyday-object retrieval evaluation, 2026-09-10

**Historical pre-hardening consolidation of staged external experiments.** Every
digest, dataset/source measurement and model result in this record applies only to
the recorded 2026-09-10 source. None verifies the subsequently hardened ML source.
Current evaluation requires a freshly acquired, receipt-bound everyday-object v3
root; a live model/data rerun is pending. The recorded fingerprints and hashes remain
unchanged historical evidence and accompany the
[dated main verification](../docs/retrieval-main-verification-2026-09-10.md).

The experiments were staged on a dirty, uncommitted `feat/object-search-history`
working tree at HEAD/base `0ebc2a87752e533f1fa50fd138b15b68546b4fcc`;
`origin/main` was `407a5855fb9628dcc2d2f2ce88e90b2611d7d824`. No rebase,
commit or push occurred. Hosted CI, PR/merge and deployment remain pending.

The host was a Ryzen 9 5950X with 16 physical/32 logical CPUs and 62 GiB RAM.
Tooling was Go 1.26.4, Python 3.12.3, uv 0.11.3 and Docker 29.1.3. Models,
Open Images data and raw JSON reports remain under `/tmp/opencode/`, outside Git.

| Experiment stage | ML implementation SHA-256 | Identity status |
| --- | --- | --- |
| Runtime matrix | `876fa59c2a20c51dfbb2730d6c11b222b894ddbce7f0dbbeb34ecbe2ab3e802f` | prior-source, immutable |
| Checkpoint comparison | `4d3459af52a0734420ec48006b31298e3ad18509945be15f178a76ba63f595fa` | prior-source, immutable |
| Intermediate language report | `75d5f681c30a58b7d464462a410250b43727c80d4f4068480cc8c31bb9174ed3` | prior-source, immutable |
| Final everyday-object Base384 report | `4b5d69daa80fbc1be375bb8222618ed58a6f9953ea80ae11e513c87e296d291d` | historical pre-hardening implementation |

## Base224 thread and batch matrix

The tuning matrix used the historical narrow 48-image Open Images profile with
three primary classes, Base224 and fixed full-then-overlap execution. Each cell
had one run; the two finalists had three runs total.

| Threads x batch | Full seconds | Overlap seconds |
| --- | ---: | ---: |
| 4x2 | 8.3081 | 49.4503 |
| 4x4 | 8.3167 | 49.7321 |
| 4x8 | 10.6036 | 56.9355 |
| 8x2 | 5.1975 | 27.6982 |
| 8x4 | 5.8366 | 33.6322 |
| 8x8 | 5.0276 | 25.6003 |
| 16x2 | 5.1037 | 26.5599 |
| 16x4 | 5.3073 | 23.5408 |
| 16x8 | 5.3884 | 26.1292 |

| Finalist | Overlap repeats, seconds | Median |
| --- | --- | ---: |
| 8x8 | 25.6003, 25.2314, 24.8057 | 25.2314 |
| 16x4 | 23.5408, 22.7048, 23.3027 | 23.3027 |

The provisional external-run setting was **16 threads, batch size 4**, inferred from
this prior-source 48-image comparison. Its overlap median was about 7.6% faster than
8x8, with peak RSS about 1,399,108 KiB (1.334 GiB). The setting was used for the
historical final Base384 benchmark and Go smoke, but all thread alternatives were not
rerun on that 100-image profile; 16x4 is not a demonstrated 100-image
comparative optimum. Batch size has no material mechanism to improve single-region
full mode; the small differences there are run noise. This small, fixed-order,
single-host matrix did not isolate thermal state or filesystem/OS caches and is not
sustained-load evidence.

All matrix artifacts are in `/tmp/opencode/memotrace-openimages/`:

| Report basename | SHA-256 |
| --- | --- |
| `report-matrix-base224-t4-b2-2026-09-10.json` | `d4d518a70e3d250cdb0283d5aa8f7461ca9286bcbc479c8c4584b9ce1596237b` |
| `report-matrix-base224-t4-b4-2026-09-10.json` | `d23e98767063870f339c60d47c3db4d65caed19dc7e92ab934e9bc503c00e360` |
| `report-matrix-base224-t4-b8-2026-09-10.json` | `b79b1c7eb1f4ee525c818d038f5615655c7de035b7aaa326b184e1dfe902596d` |
| `report-matrix-base224-t8-b2-2026-09-10.json` | `1dbe104b4d4b2144d4923b67185574a8d77ec70761a9ed7d8c0953a0655af6ea` |
| `report-matrix-base224-t8-b4-2026-09-10.json` | `45c7da6831f82b2da1b87930dd744b04cb2662e3adb332e50773392cb9350943` |
| `report-matrix-base224-t8-b8-2026-09-10.json` | `e4357a0c28cb9d4a4d875575e257dd1a6bad38643c63b060174cbee9ed570239` |
| `report-matrix-base224-t8-b8-r2-2026-09-10.json` | `e9583e7158c937dcdd67bfb7660d3c7724d21b666ea578bee0da887ab1901000` |
| `report-matrix-base224-t8-b8-r3-2026-09-10.json` | `d298003bb4f34f123cbd830fdbb50e42d1d278279176a364a205d3dd006a6925` |
| `report-matrix-base224-t16-b2-2026-09-10.json` | `7156186ba779edca8c552848d9f9a9aea62003543d03e55fbc08bd0ecc0d2478` |
| `report-matrix-base224-t16-b4-2026-09-10.json` | `df9313448f628030726408f7e1da14c10693cf9353ef5fb9b73a026134323720` |
| `report-matrix-base224-t16-b4-r2-2026-09-10.json` | `bcae73201ee50d1d736794a78989cfd8bcf874c6b88d190b1b51c7f7fa0c6601` |
| `report-matrix-base224-t16-b4-r3-2026-09-10.json` | `53cb7ed32ba2825143057b93300dd1a7c0c3a0b3dcbb41ad44090254a5200b0d` |
| `report-matrix-base224-t16-b8-2026-09-10.json` | `3f26f85d28800909636989fd0e5812e2bbba8fe56741dd9260db7bb1c44f045c` |

## Checkpoint comparison

The model comparison used the same 48-image, three-primary-class profile and the
selected 16x4 runtime. Times are in-process model/image-pipeline seconds; AP is the
primary condensed judged-corpus mean for English, Russian and image proxy queries.

| Model | Load | Full | Overlap | Peak RSS KiB | Full AP EN/RU/image | Overlap AP EN/RU/image |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Base224 | 4.8644 | 5.4348 | 23.0707 | 1,398,304 | .88085 / .87666 / .80345 | .92303 / .87807 / .80903 |
| Base384 | 5.1051 | 13.5628 | 93.7894 | 1,398,224 | .95514 / .94794 / .71520 | .93716 / .92440 / .79964 |
| SO400M384 | 7.4872 | 48.9688 | 381.7126 | 3,996,604 | .94425 / .94310 / .71500 | .93915 / .94409 / .73043 |

Base384 was provisionally selected as the practical text-retrieval candidate from
this prior-source 48-image comparison. SO400M showed no consistent quality gain for
roughly four times Base384's overlap crop time, while Base224 remained best on
image-proxy AP in this tiny profile. Base384 was used in the historical final benchmark
and Go smoke, but all checkpoint alternatives were not rerun with that implementation
and 100-image profile. This is not a current-source comparative
optimum or evidence of a universally best model.

| Artifact | SHA-256 |
| --- | --- |
| `report-modelcompare-base224-t16-b4-2026-09-10.json` | `f51960d220d25276fd797031ca92c7285bd9183cdab7d25a4fe762412d452010` |
| `report-modelcompare-base384-t16-b4-2026-09-10.json` | `3b8789c36cf72f09b0a84f2778f277e95b17cebf7f08bf69e7784f82c0ebc119` |
| `report-modelcompare-so400m384-t16-b4-2026-09-10.json` | `6c04bbee4185bd008b44700a9324cc134a7cd1254d416d0d5a7c78729f95951f` |
| `report-language-base384-t16-b4-2026-09-10.json` | `b43454297144629fb44e420d4f0d7b044ca4b047852afb40f72849686de9f338` |

The listed intermediate language report is prior-source 48-image evidence with
implementation identity `75d5f681c30a58b7d464462a410250b43727c80d4f4068480cc8c31bb9174ed3`.
The final RRF metrics below come only from the then-current pre-hardening final report,
not from that intermediate artifact.

| Model manifest | SHA-256 |
| --- | --- |
| Base224 | `21ef879c78ad38bb13f9a71c2fa41a745e86d1d6e593425e570443b4c1a284dc` |
| Base384 | `5d06017c88408dcbb5982e7f757269396dba4ab25c702e213c36fe46da3c43b0` |
| SO400M384 | `4fe2b5252086169e3ac3213ac1e1ea6f7459b48ca15be2d3c72db92cab69cb5f` |

The newly acquired Base384 and SO400M384 checkpoints each passed the 13-request
genuine-model smoke with zero stderr before later benchmark-only implementation
changes. Their old smoke fingerprints are therefore not current identities. Final
Base384 loading at the recorded pre-hardening implementation was established by the
final benchmark below and the
[dated Go smoke](../docs/retrieval-main-verification-2026-09-10.md#historical-real-gopostgresqlclitls-evidence).

## Historical everyday-object v2 data

This v2 root cannot satisfy the current v3 acquisition and attribution requirements
and must not be reused for a current-source rerun.

The final external root was
`/tmp/opencode/memotrace-openimages-everyday-v2-100-2026-09-10`. It contains 100
unique assets, zero content aliases, zero acquisition failures and eight ordered
classes. Dataset version:
`v5-everyday-object-pilot-v2-87a0b260b15ba59b`.

| Dataset artifact | SHA-256 |
| --- | --- |
| `manifest.json` | `b706449faf18b760e2e6ef77e612d8ed2e3f68d504ac79e6da06ba81a58b82b9` |
| `ground-truth.json` | `dfd1761d217ca746876ea559365d9c301eb58b7b477c118ebf65532fa600e9e6` |
| `selection.json` | `ce92a04d8af73bf8b3b94f1c03fe79c759e70a462a864e1b754053de3e342476` |
| `acquisition.json` | `92113574f52245b1439a9a66c135550aa4468200e0242c887105bfa2b64cdfae` |

| Class | Selected positive | Selected negative | Primary status |
| --- | ---: | ---: | --- |
| Screwdriver | 3 | 1 | eligible |
| Scissors | 1 | 0 | excluded: `no_negative` |
| Hammer | 0 | 1 | excluded: `no_positive` |
| Knife | 10 | 10 | eligible |
| Pen | 10 | 10 | eligible |
| Bottle | 10 | 11 | eligible |
| Mug | 9 | 9 | eligible |
| Mobile phone | 9 | 9 | eligible |

Six classes enter primary macros. Scissors and Hammer remain explicit in source,
per-query and exclusion evidence; they are not silently dropped or counted as zero.
Unknown judgments remain unknown rather than becoming negatives.

## Historical final Base384 evaluation

Final report:
`/tmp/opencode/memotrace-openimages-everyday-v2-100-2026-09-10/report-final-base384-t16-b4-2026-09-10.json`

| Identity | Value |
| --- | --- |
| Report SHA-256 | `cfe6fc3ca729f6f6731a67ec5d8d23eece142abaf976fe3176873f91ee6a7703` |
| Implementation SHA-256 | `4b5d69daa80fbc1be375bb8222618ed58a6f9953ea80ae11e513c87e296d291d` |
| Model fingerprint | `cbb0df37c19f6c6ac51e7a94190c35ceb1dc7b7292722f725fbf33d351c9bb12` |
| Full generation | `8c10b343531e7b8098c8cb1fbbfe82cd063791e986724b75c5ef1d2a2574d8a0` |
| Overlap generation | `7f086abb3ce740c068daec0561f9ac9b06895407c6645dfbdd58bf5176ceccbe` |

Model load was 4.7857 seconds. Full indexing produced 100 vectors in 24.9571
seconds; overlap produced 668 vectors in 180.5659 seconds. Peak RSS was 1,399,060
KiB. The six-primary-class macro results were:

| Mode | Query | AP | Hit@1 | Recall@10 |
| --- | --- | ---: | ---: | ---: |
| Full | English | .87124 | .8333 | .84444 |
| Full | Russian | .87619 | 1 | .79074 |
| Full | Fusion | .89027 | 1 | .82778 |
| Full | Image proxy | .77395 | .8333 | .84722 |
| Overlap | English | .87359 | 1 | .80556 |
| Overlap | Russian | .84847 | 1 | .80741 |
| Overlap | Fusion | .88311 | 1 | .82407 |
| Overlap | Image proxy | .81731 | 1 | .82870 |

Deterministic EN/RU Reciprocal Rank Fusion had the best AP in both modes. The
English phrases are manually curated evaluation pairs, not automatic translator
outputs. Translator quality, latency, privacy and operational behavior remain
untested.

At the recorded pre-hardening source, independent review reproduced all 60 final
query-mode records, exact RRF scores/timings/macros/exclusions, all 100 selected IDs and class
counts, candidate universes, 100/668 vectors, attribution receipts, model fingerprint,
both generations and that implementation digest. Those results do not close current
source verification; fresh v3 acquisition and a live model/data rerun remain pending.

## Limits

Open Images evaluates class-level retrieval, not the same physical instance, tracking
or history. It provides no timestamps. Only six classes enter primary aggregates;
judgments are sparse and unknowns can occupy corpus ranks. These are single-host,
small-corpus runs without sustained load or automatic translation. Ego4D temporal
evaluation remains pending, and no official Ego4D metric is claimed. Private encrypted
deployment, Android synchronization,
device behavior, physical power-loss and restored-backup evidence are separate gates.
