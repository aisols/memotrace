# Recorder Interaction Requirements

These clarify the original specification using the product discussion. They are
requirements and design proposals, not claims about implemented Android support.

## Confirmed Requirements

- The reference phone is a Samsung Galaxy A33 with Android 16 and One UI 8.
- It is a dedicated recorder, but existing applications must remain accessible.
- Recording should continue with the screen off after a user starts it.
- Waking the phone should present MemoTrace first, with a route to ordinary
  Android unlocking and use of other applications. This is not a locked-down kiosk.
- One volume button should control recording/pause; the other should take a
  photograph of an object for a contextual query. Exact button assignment is open.
- Automatic archive synchronization is triggered by connection to power and
  availability of the home server on the allowed local network.
- A manual synchronization action must also work without external power.
- Merely joining home Wi-Fi without power must not trigger archive upload.
- Vosk is the proposed on-device offline speech recognizer; recognition quality
  still needs evaluation on the intended user's speech.
- Minimize decisions, taps, and navigation for an older person unfamiliar with
  current mobile interfaces. Do not require long-press or double-tap gestures.
- JPEG comparison uses six readable profiles via large accessible buttons.
  Pause/drain before changing; each Start creates a profile-bearing album.
  Distinguish requested size, CameraX stream size and actual JPEG size.
- First Start explains public Pictures and independent cloud backup by
  Gallery/Photos/OneDrive, with an accessible cancel route. Conversation consent
  is not consent for another installation. Show the session folder and read-only
  last-image viewer, with honest unavailable status.

## Tremor-Tolerant Touches

Remember the button selected by the initial contact, but do not execute its action
on pointer-down. Provide immediate visual feedback instead. Small movement or
slippage beyond its visible boundary must not automatically discard the tap or
retarget a neighboring button.

Execute the initial action once on release if the gesture remains a tap. In a
scrollable region, movement beyond the configured threshold along the scrolling
axis cancels the button action and starts scrolling. Once scrolling wins, the
gesture cannot turn back into a tap before release. Respect system cancellation.

Measure displacement relative to the starting position, not accumulated travel
from tremor. Determine tolerances with real interaction tests. Prevent accidental
repeat actions and hardware key-repeat toggles without requiring careful timing.

Prefer a stable main screen without scrolling, while remaining usable with large
system text. Use large labeled controls, generous spacing, distinguishable state
feedback, and accessible semantics. Confirm successful recording or saving only
after it actually succeeds. A short tap to start a spoken question is preferable
to requiring the user to hold a button throughout speech.

## Decisions and Device Tests Still Needed

- Verify sustained camera operation, battery use, heat, and capture quality.
- Verify waking into MemoTrace after other applications were used.
- Verify volume-key delivery with the screen fully off; AccessibilityService
  alone is not proof that this works on the reference device.
- Choose a permission and foreground-service lifecycle that Android 16 permits,
  including pause/resume and recovery after reboot.
- Define the extent of archive and query access without the device PIN.
- Define when volume buttons return to ordinary volume control.
- Decide whether unplugging pauses an automatic transfer already in progress.
- Define whether taking a query photo immediately submits a query, and how a
  foreground query-photo transfer differs from bulk archive synchronization.
- Evaluate speech pauses and errors; Vosk produces text, not search reasoning.

Do not equate showing an Activity above the keyguard with unlocking the device,
or assume that this guarantees foreground placement on every wake. Do not make
ADB, root access, factory reset, or removal of existing applications a prerequisite
without an explicit product decision.
