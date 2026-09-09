# Profile Verification, 2026-09-09

MAIN-observed evidence supplied for this docs-only record, not verification by
the documentation editor. Code HEAD `6445bad` is feature `ceef24e` plus a UI-only
action reorder; versionCode `2`, versionName `0.2.0`. Device: Samsung A33
(SM-A336B), Android 16/API 36. These dated results do not cover future commits;
[PR #3](https://github.com/aisols/memotrace/pull/3) is authoritative for final status.

## Artifacts And Gates

Final debug APK SHA-256, verified built and installed:

`ad443385bcb1586d727faf36e0b56dc01bec98d21eac80f794f9ec085ec5b4c1`

Instrumentation APK SHA-256:

`23bb3896da7c4bc63cae6bd677a351eb8599706f9dafc6cea303fc80a0afbd22`

| MAIN check | Result |
| --- | --- |
| README command with `clean` | Passed, 101 tasks |
| Unit tests | 23 core + 82 app = 105; zero failures/skips |
| Core coverage | 123/123 lines (100%); 151/152 branches (99.34%) |
| Core thresholds | Unchanged: >=90% lines, >=80% branches |
| Isolated quality verifier | Positive + six expected negatives passed |
| Connected-safety verifier | Debug/release positives + seven expected negatives passed; no device action |
| Independent storage/lifecycle/UX/retention reviews | All known findings closed |
| CI at `6445bad` | [Passed, run 34378499995](https://github.com/aisols/memotrace/actions/runs/34378499995) |

Earlier 81-app-test results in `quality.md` are historical, not this final count.

## Failure And Retention Timeline

The [initial failure report](a33-gallery-failure-2026-09-09.md) remains unchanged:
2 passed, 8 failed, zero skipped, then cleanup crashed; FUSE `fstat` ENOENT and unsafe AGP/UTP
default teardown were identified. At the user's request, the old 660 private
JPEGs (1,862,158,115 JPEG bytes) and v1 index had been explicitly deleted **before
new testing**. The unsafe old host attempt subsequently uninstalled the target,
losing private fixture ledgers; runner-stage retention did not survive that host.

Corrective [retention flags and guards](connected-test-safety.md) were verified.
APK retention was enabled and incompatible-APK uninstall disabled.
Native `ceef24e` passed 10/10; a private control file was verified unchanged after
host completion, then only that probe was removed. Latest UI revision `6445bad`
again passed 10/10, none skipped, with the same retention configuration and the
package still installed.

## Native Profile Samples

One frame per profile in the latest native run; requested, negotiated and actual
dimensions all matched:

| Requested dimensions | Configured Q | JPEG bytes |
| --- | --- | --- |
| 4000x3000 | 95 | 2,169,417 |
| 4000x3000 | 80 | 893,153 |
| 1920x1080 | 90 | 260,086 |
| 1920x1080 | 80 | 187,864 |
| 1440x1080 | 90 | 205,760 |
| 1440x1080 | 80 | 159,587 |

Single-frame/scene observations are not a controlled quality benchmark. No
battery, thermal, OCR-recall, durability or endurance claim follows. Q is a
configured parameter, not proof of firmware quantization; 16:9 and 4:3 have
different fields of view. CameraX temporary scratch remains possible; there is
no application re-encode or permanent duplicate.

## Manual UI And New Photos

Start/Pause/Profile/View Last were visible above diagnostics on the A33. MAIN
opened the last JPEG using the button; Android's resolver appeared and MAIN
selected Gallery **Only now**, without changing a global default. Samsung
`com.sec.android.mimage.photoretouching/.SPEActivity` loaded an editor, not a
verified pure gallery viewer. No Save was pressed; MAIN returned to MemoTrace.

All 18 ordinary new JPEGs were subsequently hash/byte-verified unchanged. SQLite
integrity was OK: 18 committed, 3 QUARANTINED, no pending; service absent, paused.
The three uncleared quarantine records are cancel metadata, not saved images,
and do not block a new session.

| New ordinary profile set | Files | JPEG bytes |
| --- | --- | --- |
| Compact 1440x1080 Q90 | 3 | 697,874 |
| Full 4000x3000 Q80 | 5 | 4,310,471 |
| FHD 1920x1080 Q90 | 4 | 906,569 |
| Reference 4000x3000 Q95 | 6 | 12,774,689 |
| Total | 18 | 18,689,603 |

These are **new normal folders, not the old 660-image archive**. New photos were
left untouched and the user's Reference Q95 selection preserved. The code default
is Compact Q90 only when no selection is set.

## Diagnostic Residue

Latest native output contained 22 cleanup-uncertainty **log lines, not 22 files**.
Ledgers were retained, but that does not prove complete cleanup. After that run,
a scoped, read-only physical-tree inspection of `Pictures/MemoTrace-instrumentation`
observed eight JPEG names and `du` 386 KiB including directories. Some older
failed-run ledgers were lost through host uninstall; respect unknown provenance.
This is a separate diagnostic namespace, not the normal comparison folders.
No unsafe broad cleanup or ordinary-file deletion was performed; no residue-free
claim is made.

## Try A Comparison

1. Pause and wait for writer drain/archive checking to finish.
2. Select a profile, Start, and record the same fixed test scene.
3. Pause and wait for drain, then use View Last or Gallery/My Files at
   `Pictures/MemoTrace/<profile>/<profile>_<UTC-time>_<session-UUID>/`.
4. Repeat with another profile under matched conditions; do not save viewer edits.

A controlled [same-scene comparison](device-verification.md#same-scene-benchmark)
remains user work. No actual capture timestamps, UUID folders, private images,
device endpoint or serial are included here.
