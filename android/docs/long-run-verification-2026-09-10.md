# Long-Run Verification, 2026-09-10

MAIN-observed evidence supplied for this documentation-only record, not device
verification by the documentation builder or implementation owner. It covers the
current uncommitted long-run revision identified by the artifact hashes below. It
does not replace the historical
[2026-09-09 profile evidence](profiles-verification-2026-09-09.md).
Device: Samsung SM-A336B, Android 16/API 36, build `BP2A.250605.031.A3`.

## Artifacts And Host Gates

- Application: versionCode `3`, versionName `0.3.0`.
- Debug APK SHA-256: `77a86f881b7eb4f7806a62b05a619dc21f78fa28c10e507ce9324b7b91260706`.
- Instrumentation APK SHA-256: `ca4170bbb290f27691f1d87836579a9c696509ff109b12a8c3c7b4f4bdfc50fb`.

The separate implementation-owner [local quality record](quality.md) reports the
exact clean gate passed
with 101 tasks: 24 core plus 115 app tests, 139 total, with no failures, errors, or
skips. Core coverage was 132/132 lines and 151/152 branches. Lint, Spotless, and both
APK assemblies passed. The isolated quality positive plus six expected negatives
and connected-safety debug/release positives plus seven expected negatives also
passed. These are host results, not MAIN device execution. Hosted CI has not run for
this revision.

## Connected Run

The first current-revision connected attempt was environment-blocked: the screen
was off and keyguard was showing, and three UI/camera tests failed after seven other
tests completed. This is neither an application failure diagnosis nor a native pass.

After normal user unlock, MAIN reran the guarded `connectedDebugAndroidTest` command.
All 10 tests passed with zero failures, errors, or skips. JUnit suite time was
26.228 s; instrumentation reported `OK (10 tests)` in 24.403 s. The package was
retained. MAIN did not run `pm clear`, uninstall the package, or delete application data.

The native runner's final status reported nine unresolved cleanup items: eight
`STILL_LINKED` and one `UNKNOWN`. Additional per-test `Cleanup NOT proven`
diagnostics were present. Fixture provenance remains retained; this is not a
residue-free result and no cleanup is claimed. These are isolated instrumentation
namespaces, not authority to clean the ordinary archive.

All six camera-profile logs reported requested = negotiated = actual dimensions:

| Profile | JPEG bytes |
| --- | ---: |
| 4000x3000 Q95 | 2,816,563 |
| 4000x3000 Q80 | 1,091,112 |
| 1920x1080 Q90 | 290,795 |
| 1920x1080 Q80 | 208,320 |
| 1440x1080 Q90 | 240,344 |
| 1440x1080 Q80 | 173,256 |

These single outputs are not a controlled image-quality, compression, or battery
benchmark.

## Normal-App Smoke

MAIN installed the normal APK with `adb install -r`, preserving application data.
On launch it loaded 27 pre-existing indexed JPEGs, displayed the fixed
**1920 x 1080, Q90** label, enabled Start, disabled Pause, and exposed no profile
selector. The 27 cannot all be attributed to the previously documented 18 because
additional ordinary runs had occurred.

MAIN started recording through the real Start UI and paused through the normal
flow. The completed session reported:

| Fact | Observed value |
| --- | --- |
| Duration/status | 194,724 ms (3:14), `COMPLETE` / `USER_PAUSE` |
| Attempts/saves | 96 / 96 |
| Camera/storage/interrupted failures | 0 / 0 / 0 |
| JPEG bytes | 27,407,874 |
| Normal indexed count | 27 before, 123 after |
| Request gaps p50/p95/max | 2,034 / 2,056 / 2,074 ms |
| Due overruns | 95; maximum 74 ms |
| Pipeline p50/p95/max | 404 / 501 / 1,202 ms |
| Successful-save p50/p95/max | 87 / 121 / 818 ms |
| Capture dimensions/profile | requested = negotiated = actual 1920x1080 Q90 |

Six telemetry samples had session offsets `0`, `55`, `60044`, `120064`, `180049`,
and `194724` ms. Battery changed from 52% to 50%; temperature changed from 30.5 C
to 31.1 C; maximum thermal severity was 0. `dumpsys` reported the phone unplugged.
Reported free storage changed from 22,606 MiB to 22,581 MiB, also the observed minimum.
These short-run values are observations, not battery or thermal benchmarks.

The internal viewer decoded the final JPEG at 1920x1080 and 218,471 bytes, fit it
without cropping, and exposed only Close.

## ADB-Off Interval

Host ADB disconnect plus daemon stop lasted exactly 77 seconds, from
`2026-09-10T05:32:27Z` through `2026-09-10T05:33:44Z`. Exported capture offsets show
roughly 2.03-second uninterrupted cadence across that interval, including attempts
from approximately 51,292 through 126,569 ms. The foreground service was present
after reconnect and absent after Pause/drain.

This is ADB-off evidence, not sustained screen-off evidence. `dumpsys` showed a
power-button sleep followed by wake after about 4.6 seconds. After reconnect, direct
inspection found the screen unlocked with no keyguard.

## Export And Retention

SAF export to local Downloads completed only after the explicit stream-closed
success state. The ZIP was 3,700 bytes with SHA-256
`a7014c8b94cc945226bead63e15d668f0439877056dea07eb5b10432b67da125`.
It passed ZIP integrity and contained exactly `manifest.json`, `sessions.csv`,
`samples.csv`, and `captures.csv`; the manifest schema was
`memotrace-long-run-report-v3`.

Inspection found session-local ordinals and offsets and no UUID, content URI,
storage/Pictures path, image bytes, hash field, or absolute wall/boot capture
timestamp. Manufacturer/model/OS/build/app fields remain intentionally present.

This smoke created 96 normal public JPEGs and one Download report; they remain
intentionally. Four existing ordinary quarantine tombstones remain reported
separately and are not included in saved-image counts. No retained fixture, report,
JPEG, tombstone, or application data was deleted for this record.

## Limitations

- This was 3:14, not the required two-hour run, and was not body-worn.
- Sustained screen-off recording was not tested.
- Force-stop, reboot, power loss, restore, and restored-backup behavior were not tested.
- The profile outputs and short battery change are not controlled quality or battery benchmarks.
- Hosted CI has not run for this revision.
- Unresolved native cleanup has no physical-unlink or residue-free proof.
