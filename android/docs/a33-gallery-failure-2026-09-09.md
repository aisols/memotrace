# A33 Gallery Test Failure, 2026-09-09

MAIN-owned device run, not implementation-owner device access. This records a
failed run before the FUSE unlink adaptation, not a pass for the adaptation.

Source read before any clean build: `app/build/outputs/androidTest-results/connected/debug/TEST-SM-A336B - 16-_app-.xml`.
XML timestamp `2026-09-09T14:27:06`, SM-A336B / Android 16, 10 tests,
2 passed, 8 failures, 0 skipped, 103.777 seconds. The run subsequently reported
`Instrumentation run failed due to Process crashed` during runner cleanup.
Report contents preserved outside build cleanup at
`/tmp/opencode/memotrace-a33-gallery-failure-20260909.xml` (local transient evidence).

| Test | Recorded result |
| --- | --- |
| realTrashRestoreKeepsHistoryButDisablesViewingWhileTrashed | fstat ENOENT in TestMediaNamespace.cleanup |
| batchRequiresStillPendingIdentityAndNeverDeletesPublishedOrMovedOriginal | fstat ENOENT in TestMediaNamespace.cleanup |
| concurrentPublishAndPendingCleanupCannotBothSucceed | fstat ENOENT in witness check |
| insertedProviderRowBeforeFirstOpenRecoversReadyWithoutCreatingAFile | Passed |
| missingRowWithoutWitnessRetainsLedgerRatherThanClaimingPhysicalCleanup | UnlinkUnprovenException from deletePending |
| privateLedgerRecoversLostUriButDoesNotDeleteUnregisteredSameOwnerUuidSentinel | linked/unverifiable fixture; ledger retained; exception escaped |
| accessibleControlsAndPauseWithoutCameraConsent | Passed |
| storageRoundTripRecoveryAndShadowRetention | fstat ENOENT in TestMediaNamespace.cleanup |
| sixRealCameraProfilesRecordRequestedNegotiatedAndActualSizes | 45-second awaitState timeout at RecorderDeviceTest.kt:208; 49.517 seconds total |
| foregroundCaptureSurvivesActivityStopAndPauses | 45-second awaitState timeout at RecorderDeviceTest.kt:159; 45.058 seconds total |

MAIN's scoped `MemoTraceTest` log reported one actual saved camera frame:
`v1-4000x3000-q95`, requested 4000x3000, Q95, negotiated 4000x3000,
actual 4000x3000, 1,975,719 bytes. This is one profile observation, not verification
of all profiles, endurance, battery consumption or image quality.

At that revision, line 208 waits for `app.canStart` at the beginning of each
profile iteration. The first-frame log occurs after Pause's `!sessionOpen` check,
so the later timeout is not evidence that that Pause never drained. Line 159
waits for `ready && !sessionOpen` before the FGS test starts. The code turns any
abandon/cleanup exception into a storage failure, latching readiness false. That
explains this sequence and is reproduced locally; the XML itself does not contain
a direct service-state snapshot or the specific service-abandon errno.

The final crash is explicit: `IsolatedTestRunner.finish` called
`IsolatedRecorderApplication.cleanup`, whose Future.get threw ExecutionException
wrapping UnlinkUnprovenException. Expected cleanup uncertainty masked normal
instrumentation completion. One retained runner ledger in the crash was
`media-fixtures-46be7016-c79e-47cb-96d4-bd49371e54c6`.
"Retained" here describes the runner stage, not survival after host teardown.

MAIN force-stopped the app after this failed run for quiescence. The implementation
owner did not access the phone or remove device fixtures. Any surviving fixture
artifacts must not be swept/deleted as a reset shortcut; the host finding below
means private ledger survival must not be assumed.

## Subsequent Host Finding

MAIN later confirmed that `adb pm path` returned no target package. Independent
AGP 8.13.2/UTP 31.13.2 investigation identified default post-test uninstall without
keeping data, for both target and test APKs and regardless of test success.
The private cache/index/preferences/fixture ledgers may therefore have been removed
by the host after the runner's diagnostics. Do not claim those ledgers remain on
the phone. The original 660 JPEGs/v1 index had already been explicitly deleted
before this test run; this finding does not authorize any further cleanup.
See [host safety and the new pre-install gate](connected-test-safety.md).

## Adaptation Under Test

ENOENT from a retained FUSE descriptor means UNKNOWN, not proven unlink. Preserve
that distinction from STILL_LINKED and PROVEN_UNLINKED; EBADF/EIO and unrelated
provider/DB failures remain real errors. After acknowledged camera failure/abort
and writer drain, only typed cleanup uncertainty may be durably quarantined without
disabling the next Start. ERROR_FILE_IO is still fatal and an aborted frame is not
a successful save. Native tests and runner cleanup must report retained ledgers
without treating expected uncertainty as a process crash or successful cleanup.
No watchdog increase, plain-delete fallback, broad scan, or dependency upgrade.

The revised tests are not device evidence until MAIN reruns them after review.
