# ADR 0003: Adaptive JPEG Capture Prototype

Status: Accepted (prototype choice)

Date: 2026-09-09

## Context

The first recorder slice needs measurable capture quality, cadence, and resource
use before expanding device interactions. The user confirmed adaptive JPEG
capture as the prototype choice. After originally requesting occlusion-based
suppression, the user explicitly approved shadow-mode diagnostics until false
positives have been measured. These are accepted choices, not claims of
implemented or verified device support.

## Decision

- Capture JPEGs at a baseline interval of 2 seconds, temporarily approximately
  1 second during motion. Initial timing, motion thresholds, and return-to-baseline
  policy are configurable experiments to evaluate on the device.
- Bound in-flight capture and persistence work. Skip or coalesce busy ticks;
  never accumulate a backlog of overdue captures.
- Detect motion through low-resolution, nonblocking CameraX `ImageAnalysis`.
  Analysis images and transient motion outputs are not archived. Preserve the
  original captured JPEG bytes without re-encoding or diagnostic modification.
- Occlusion is **shadow-mode diagnostics only** in the first prototype. Record
  lightweight occlusion diagnostic metadata separately from transient analysis
  images and motion outputs. Occlusion must not suppress or delete captures or
  change capture policy. Any later suppression decision requires measured false
  positives and a separately reviewed decision.
- Compare HEVC later. No local VLM runs on the phone or server in this prototype.
- Hardware keys, kiosk/wake behavior, and synchronization are outside the first
  recorder slice, not cancelled product requirements. The
  [interaction requirements](../ux/README.md) still apply, including access to
  ordinary Android use rather than a locked-down kiosk.

## Consequences

Adaptive cadence may improve temporal sampling but does not fix motion blur:
exposure, focus, and lighting determine image sharpness. Faster capture can
increase storage, battery use, and heat; shadow mode deliberately retains
occluded captures while diagnostic accuracy is evaluated.

Keep scheduler, motion, and occlusion policy pure and testable independently of
camera, filesystem, and Android lifecycle side effects. Unit and regression
tests must cover cadence transitions, configurable thresholds, busy-tick
coalescing/skipping, bounded work, and the invariant that occlusion diagnostics
cannot alter capture or retention. Component integration tests should cover
capture/persistence failures and preservation of original JPEG bytes. Define
and review component-local coverage gates with the first implementation.

Device verification must measure image quality under motion and varied lighting,
actual baseline and motion cadence, backpressure under slow capture/storage,
storage growth and failures, lifecycle behavior (including screen-off operation
and pause/resume), battery consumption, and heat during sustained recording.
Evaluate occlusion diagnostics against known occluded and unobstructed scenes
and report false positives before considering suppression. Record device/OS,
configuration, revision, duration, results, failures, and unavailable checks;
the reference device and required behaviors are described in the interaction
requirements. No device capability or performance target is verified by this ADR.
