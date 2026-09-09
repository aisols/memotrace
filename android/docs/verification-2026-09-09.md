# Main-Agent Verification: 2026-09-09

This note records observations owned and independently obtained by the coordinating
main agent, not new executions by the documentation author. Evidence applies to
production source commit `6d2c95f` on `feat/adaptive-jpeg-recorder`. Later CI/docs-only
corrections do not change the verified runtime; runtime sources and the device APK are
unchanged. Reference device: SM-A336B, Android 16/API 36.

## Local Gates And Review

The main agent independently ran the [documented Gradle command](quality.md#required-local-checks)
with `clean`: all 100 tasks executed; 58 local tests passed (21 capture-core,
37 app), zero skipped. Lint, Spotless/ktlint and both app/instrumentation APK
assemblies passed. Core coverage was 98/98 lines (100%) and 149/150 branches
(99.33%), above the component-local >=90% line / >=80% branch gates.

The independent `python3 tools/verify-quality-failures.py --temp-parent /tmp/opencode`
run passed its isolated positive case. All six negatives (absent, all ignored,
and one ignored test in each module) failed the intended test-results gate;
source files were unchanged.

Two independent review agents identified CameraX disk-drain race, scratch recovery,
typed FILE_IO handling, nonempty/zero-skip gates, accessibility and batched-touch
issues. Fixes were independently re-reviewed; all findings were closed.

## Instrumentation And Identity

The initial three-test device run passed storage but failed both UI/camera tests
with secure keyguard showing. A reviewed, test-only `keepScreenOn` fixture keeps
started Activity windows awake and clears the flag when the Activity is STOPPED;
it changes no global settings and does not bypass PIN/keyguard authentication.
After normal user unlock, the main-agent retry passed **3/3 tests, none skipped**,
including two additional real-camera frames after Activity stop. This fixture is
not production screen-off evidence; see the separate manual observation below.

| Artifact | SHA-256 |
| --- | --- |
| Built and installed ordinary debug APK | `5726c3ffda75e292c508e327d9ff2971de0f8bc5f2562674efcb01bc4bdb013b` |
| Instrumentation APK | `08e5be5e853999da01f9caa8480b9b5bb57aa5abb74b71ae8c44cf9eb08b9383` |
| Official Gradle wrapper JAR | `81a82aaea5abcc8ff68b3dfcb58b3c3c429378efd98e7433460610fecd7ae45f` |

The installed base APK hash was independently measured and matched the built APK;
the wrapper JAR matched the official checksum.

## Manual Screen-Off Observation

The main agent installed the ordinary debug APK and verified the real Start,
runtime-permission Allow and Pause controls. The first manual 310-second interval
produced 168 new JPEGs but ended awake: **not valid screen-off proof**.

After user agreement to no interaction, the repeat observed:

| Measurement | Result |
| --- | --- |
| UTC interval, 2026-09-09 | 08:26:28 to 08:31:38; 310.13 seconds |
| Power/keyguard polls | 32; all `INTERACTIVE_STATE_SLEEP` / `SCREEN_STATE_OFF` |
| JPEG count around interval boundaries | 275 to 431; 156 new JPEGs |
| Request timestamps strictly inside the monotonic window | 154 |
| Successive request gaps | min 2004, median 2011, p95 2017, max 2020 ms |

p95 uses the nearest-lower sorted request-gap element at zero-based index
`floor(0.95 * (n - 1))`, where n is the number of gaps.
These are **request timestamps, not shutter metadata**.
The boundary counts and strictly in-window requests measure different scopes.
Polls do not rule out brief wakes between checks; this is a bounded observation,
not continuous proof or an endurance result.

## Archive And Pause

After the final normal operator unlock and Pause, the main agent observed 660
committed entries, all state 1, no pending entries; SQLite `integrity_check` was
`ok`. Scoped service dumpsys returned nothing, and the count stayed at 660.

- Total stored JPEG bytes: 1,862,158,115; mean 2,821,452 bytes.
- Across the whole run: 36 frames recorded a 1000 ms interval and 624 a 2000 ms
  interval. This was not a controlled motion/quality benchmark.
- First/middle/last samples were 2,883,349 / 2,818,447 / 2,807,865 bytes. Each
  sample's hash and byte count matched the index; ffprobe identified MJPEG,
  4000x3000, and ffmpeg full decode passed. This validates three samples, not
  every image or OCR/sharpness quality.

Images were streamed only locally for validation. No images, private index rows,
device serials, endpoints or unlock codes are published here. All 660 originals
remain on the phone (about 1.86 GB decimal); no unsynchronized originals were
deleted. The app was left paused.

## Limits And Hosted CI

- No 16-hour/endurance run or real battery/thermal benchmark without ADB.
- No controlled OCR, sharpness or motion-capture recall benchmark; cover
  false-positive calibration and the manual cover gate remain untested.
- No real power-loss, reboot or low-disk-fill tests. Storage-fault evidence is
  limited to unit/instrumented fixtures, not physical fault survival.
- No HEVC, sync, cloud, speech, global hardware keys or kiosk functionality.

The JPEG quality-95 default produced 4000x3000 images averaging 2.82 MB in this
scene, exceeding the 300 KB baseline. Arithmetic projection of that mean for
28,800 photos / 16 hours at two-second cadence is **about 81.3 GB decimal**,
excluding bursts and backup. This is not a representative capacity benchmark;
resolution/quality benchmarking is needed before day-long use. This documentation
change does not alter quality defaults.

The initial hosted run failed in setup-java before Gradle because of a pin
mismatch; `bfae181` corrected it to exact `21.0.12+8.0.LTS`. Its hosted rerun
[34341346464](https://github.com/aisols/memotrace/actions/runs/34341346464) passed
tests, coverage and APK assembly but failed lint's `OldTargetApi` because the
shared host SDK includes API 37. Independent review confirmed that the pinned
lint uses the highest installed API with a built-in API-36 floor. The separately
reviewed, currently uncommitted workflow correction isolates the declared API-36
platform and Build-Tools 36.0.0 SDK under `runner.temp` and adds an SDK inventory;
it adds no suppressions, weakens no gates and does not remove the host SDK.
The final corrected hosted run awaits the main agent at report time, not a claimed
pass. [PR #2](https://github.com/aisols/memotrace/pull/2) is authoritative for hosted
status. Latest-revision CI and unresolved required checks remain merge gates.
These observations do not establish full MVP readiness.
