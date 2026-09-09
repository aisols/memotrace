# Connected-Test Host Safety

## Incident And Boundary

MAIN confirmed that `org.memotrace.recorder` was absent (`adb pm path`) after the
failed A33 connected run. The 660 original JPEGs/v1 index had already been deleted
with explicit user authorization before those tests. This finding is about host
teardown, not authority to delete anything else. The implementation owner did not
access the phone.

An isolated Application protects test code from using ordinary archive paths; it
cannot protect the target package from AGP/UTP on the host. Uninstall without
`-k` removes private data, including caches, preferences, indexes and fixture
ledgers. Earlier "ledger retained" diagnostics describe the runner stage only;
they do not establish that those ledgers survived host teardown. Do not claim old
ledgers still exist on the phone. Public media may remain, but reinstall does not
reconstruct the private index or prove restored ownership.

## Pinned Source Audit

Inspected the following pinned compiled artifacts with `javap -p -c`, corroborating
MAIN's independent AGP/UTP investigation. No AGP internals are imported by the gate.

- [AGP 8.13.2 artifact](https://dl.google.com/dl/android/maven2/com/android/tools/build/gradle/8.13.2/gradle-8.13.2.jar),
  local cache `com.android.tools.build/gradle/8.13.2/5975ee61ee7e3f9413fbe10270f230cfb6d227fc/gradle-8.13.2.jar`.
- `com.android.build.gradle.options.BooleanOption`: the property
  `android.injected.androidTest.leaveApksInstalledAfterRun` defaults to false.
- `DeviceProviderInstrumentTestTask$TestRunnerFactory.createTestRunner`, bytecode
  offsets 194-217, negates `getKeepInstalledApks` for the UTP uninstall flag.
  `UtpConfigFactory.createApkInstallerPlugin` uses that flag for both target and
  test APK installables' `uninstallAfterTest` setting.
- `DeviceProviderInstrumentTestTask.doTaskAction` calls the provider/run machinery;
  its static `run` invokes `DeviceProviderFactory.getDeviceProvider` at offset 32.
  Device discovery/installation is inside the task action, not our first guard.
- [UTP APK installer 31.13.2 artifact](https://dl.google.com/dl/android/maven2/com/android/tools/utp/android-test-plugin-host-apk-installer/31.13.2/android-test-plugin-host-apk-installer-31.13.2.jar),
  local cache `com.android.tools.utp/android-test-plugin-host-apk-installer/31.13.2/f8d64c6cc2a6d03dbfefd40fd4e47ab3a84e4e08/android-test-plugin-host-apk-installer-31.13.2.jar`.
- `AndroidTestApkInstallerPlugin.afterAll`, offsets 86-91 checks
  `getUninstallAfterTest`; offsets 198-206 calls uninstall with default keep-data
  false. It does not condition this cleanup on test success. A failed test/run
  therefore does not protect the package or its private data.

These are version-specific implementation facts. A toolchain change requires a
new audit of task naming/action order and both retention options before device use.

## Enforced Configuration

Component `gradle.properties` explicitly sets:

```properties
android.injected.androidTest.leaveApksInstalledAfterRun=true
android.experimental.testOptions.uninstallIncompatibleApks=false
```

`app/build.gradle.kts` requires those exact effective values, including `-P`
overrides; missing or unsafe values fail closed. Disabling incompatible-APK
uninstall means an incompatible install must fail, not erase data and retry.

- `:app:verifyConnectedTestSafety` checks configuration without a device.
- Every `connected*AndroidTest` task depends on that gate and has the same check
  as its named first action. This covers debug, release when configured, flavors
  following the pinned naming pattern, and the aggregate. `connectedCheck` reaches
  the guarded variant through its normal dependencies. The action guard remains
  even if someone excludes the prerequisite task.
- `:app:verifyConnectedTestSafetyWiring` verifies the prerequisite and first-action
  identity on actual registered tasks, then executes ONLY that guard. It never
  executes AGP's following actions, DeviceProvider or installer. It fails if no
  expected debug/release variant exists. Default configuration registers
  `connectedDebugAndroidTest` and `connectedAndroidTest`; release is not fabricated.
  Read-only reflection on the pinned variant's TestRunnerFactory bean also checks
  the actual keep-installed/uninstall-incompatible values AGP will consume. It
  never calls createTestRunner/getDeviceProvider and requires no internal imports.
- `lintDebug` depends on this no-device wiring regression, so the unchanged
  README/CI quality command includes it. Existing unit tests, nonempty/zero-skip,
  lint/style and 90% line/80% branch coverage gates remain intact.

The wiring inspection is explicitly not configuration-cache compatible; this
does not skip its execution. The configuration guard uses Gradle property Providers.
This protects the pinned connected-test path, not arbitrary modified build/init
scripts, custom/managed device tasks, orchestrator data-clearing options or manual
ADB commands or OS cache eviction. Such paths need separate review; never add a data-clear fallback.

## No-Device Verification

From `android/`, with the documented JDK/SDK environment:

```bash
./gradlew --no-daemon :app:verifyConnectedTestSafety :app:verifyConnectedTestSafetyWiring
./gradlew --no-daemon :app:verifyConnectedTestSafety -Pandroid.injected.androidTest.leaveApksInstalledAfterRun=false
./gradlew --no-daemon :app:verifyConnectedTestSafety -Pandroid.experimental.testOptions.uninstallIncompatibleApks=true
python3 tools/verify-connected-test-safety.py --temp-parent /tmp/opencode
```

The first command must pass. The next two must fail with `Connected test safety
gate` before any DeviceProvider invocation. The script uses a component-only
temporary copy: default/debug wiring and a release-test-build-type fixture, unsafe values, missing component values,
empty retention (rejected earlier by AGP's boolean parser), and both unsafe
overrides against the real first-action guards. Only verifier tasks execute; no
device test task, installation, uninstall or data clear is run. CI also runs this
script. A dry-run/skipped verifier is not a successful safety check.

## Main-Owned Device Commands

The normal README command remains `./gradlew :app:connectedDebugAndroidTest`.
For clarity the safe values can also be repeated explicitly:

```bash
./gradlew :app:connectedDebugAndroidTest \
  -Pandroid.injected.androidTest.leaveApksInstalledAfterRun=true \
  -Pandroid.experimental.testOptions.uninstallIncompatibleApks=false
```

After review, scene/backup approval, normal unlock and paused/drained recording,
MAIN may instead avoid UTP host teardown with direct installation/instrumentation:

```bash
adb -s "$ANDROID_SERIAL" install -r app/build/outputs/apk/debug/app-debug.apk
adb -s "$ANDROID_SERIAL" install -r -t app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb -s "$ANDROID_SERIAL" shell am instrument -w -r org.memotrace.recorder.test/org.memotrace.recorder.IsolatedTestRunner
```

Require successful installation output and status; on signature/version/install
incompatibility stop and resolve the cause. Never uninstall, run `pm clear`, or
delete archives as a fallback. Both APKs intentionally remain installed.

ADB exit 0 alone is NOT test success. Preserve the complete instrumentation output
outside Git. Require normal final `INSTRUMENTATION_CODE: -1`, `OK (10 tests)`, all
ten named test cases completing successfully, no skipped/assumption cases, no
FAILURES/INSTRUMENTATION_FAILED/process crash/shortMsg/cleanup.error, and no missing
completion. Test status code 0 differs from final instrumentation code -1; standalone
cleanup `stream` status events are not extra successful test cases. Record every
`Cleanup NOT proven` / `memotrace.cleanup.unresolved` separately: test success is
not proof of complete fixture cleanup or post-host data retention. Check package
presence/retained evidence after host completion, not merely inside the runner.
