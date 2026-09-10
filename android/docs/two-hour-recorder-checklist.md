# Unplugged Two-Hour Recorder Checklist

This is an operator procedure for the current Android long-run revision. It is not
evidence that the run has occurred. Use an approved nonprivate scene for setup and
follow the project's private evidence-handling rules for the real body-worn run.

## Before The Run

1. Install the reviewed versionCode 3 / versionName 0.3.0 APK using the main-agent
   procedure, then disconnect ADB and close Android Studio/log viewers. Do not clear
   app data or delete prior JPEGs.
2. Charge the phone, then unplug external power. Record the displayed wall time and
   battery percentage outside MemoTrace. Disable battery saver for the run if that
   is the agreed test condition; do not grant BATTERY_STATS, usage access, location,
   network, accessibility, kiosk, or other special access.
3. Confirm enough free storage for the expected images plus the recorder's 128 MiB
   reserve. Check Gallery/Photos/OneDrive backup behavior: public Pictures may be
   cloud-synced independently even though MemoTrace has no network permission.
4. Open MemoTrace normally. Wait for archive checking to finish. Confirm the fixed
   label says **1920 x 1080, Q90**, Start is enabled, Pause is disabled, and no
   profile selector is present.
5. Open **Test: diagnostics/report**. Record the previous latest-session state if
   relevant. Return to the main screen. Confirm notification permission or note the
   visible warning that recording remains discoverable in Android's active-app list.

## Start And Wear

1. Tap **Start** once. If this installation has not accepted public-Pictures consent,
   read and accept it, then grant camera permission. Do not grant unrelated access.
2. Wait for the status to say recording only after the saved counts advance. Confirm
   the ongoing notification and its session-scoped Pause action.
3. Optionally open the last JPEG once to confirm framing. The internal viewer must
   fit the image without cropping and offer only Close, with no edit/delete/share.
4. Mount the unplugged phone in the approved body-worn orientation without covering
   ventilation or the camera. Turn the screen off if that is the test condition.
   Do not reconnect a debugger, cable, or power during the two-hour interval.
5. Record externally any handling, thermal warning, Android permission/privacy event,
   camera contention, reboot, process death, accidental Pause, or clock change. Do
   not relabel an interrupted session as a clean two-hour run.

## Finish And Export

1. After at least two hours by the external clock, unlock normally and tap **Pause**
   once. The stopping state is not complete: wait until the UI explicitly reports
   Pause, Start becomes enabled, and Pause becomes disabled. At most one already
   requested frame may finish during drain.
2. Open diagnostics. Verify start/end/duration and terminal state, sample age/count,
   attempt and saved/failure counts, bytes, request gaps/overruns, pipeline/save
   latency, battery/temperature/thermal summaries, safe phone/app facts, storage
   start/end/minimum, and negotiated/actual dimensions. Pipeline latency is
   request-to-commit; successful-save latency is writer-drain-to-commit. Neither is
   shutter latency. Current, charge, energy and temperature
   are whole-device Android/OEM measurements, not MemoTrace-only consumption.
3. Export the versioned ZIP. Choose a destination knowingly: the system document
   provider may cloud-sync it. Wait for the explicit stream-closed success message;
   cancellation or an error is not a completed export.
4. Keep the ZIP and operator notes in the authorized private evidence location.
   The ZIP intentionally has no images, public filename/folder, URI/path, hashes, or
    unique/personal/media identifiers. Report-local ordinals replace private UUIDs;
    session-relative offsets replace absolute wall/boot timestamps; required
    manufacturer/model/OS/build/app facts remain. Do not delete JPEGs or private
    diagnostics to make a run appear clean.
5. If the app reports interruption or archive/storage failure, preserve the state,
   relaunch once if authorized, and inspect diagnostics. Startup retains and marks an
   open session interrupted; it never auto-restarts recording. Escalate the report
   and operator notes to the main agent rather than repeating silently.

No implementation/unit/build result substitutes for this physical endurance run,
screen-off behavior, OEM thermal behavior, power-loss durability, restored-backup
behavior, or independent review at the exact tested APK revision.
