# Security Policy

## Current Status

MemoTrace has no released or supported software versions yet. The repository
contains an early local-only Android recorder and server/API scaffolds, not a
production-ready system. The recorder requests no network permission and disables
backup of private state; it does not yet synchronize its archive. After explicit
in-app consent, new originals are public MediaStore images in Pictures/MemoTrace.
Gallery, Google Photos, OneDrive or other permitted apps may upload/share them
independently. No-network permission is not a phone-only guarantee for public files.
Public images may survive uninstall/data clearing while the private index and legacy
private archive are lost; reinstall does not restore their index or ownership.
Do not assume that other
described security controls are implemented.

## Reporting

A dedicated private reporting channel has not been established yet. If the
hosting platform offers private vulnerability reporting for this repository,
use it. Otherwise, ask the maintainer for a private contact without posting
exploit details, credentials, recordings, or identifying information publicly.
Establish and publish a private contact before the first external software release.

## Sensitive Material

- Keep archives, metadata exports, database dumps, and backups outside Git.
- Do not commit pairing tokens, cloud API keys, signing keys, or real `.env` files.
- Treat OCR text, image crops, screenshots, audio, and logs as potentially private.
- Use synthetic examples for issues, tests, and demonstrations.
- Review diffs and staged files; ignore rules are not a secret scanner.

If a secret is exposed, revoke or rotate it. Removing it from the latest commit
does not remove it from existing clones or history. Coordinate any history
cleanup rather than rewriting shared history without agreement.

## Design Requirements

Recordings remain local by default. Cloud analysis must be explicit and
disableable. Authentication does not replace transport encryption: device/server
communication must protect both identity and data in transit.

The public-Pictures prototype is a distinct user-approved visibility choice, not
permission for MemoTrace cloud analysis. First-Start consent explains other apps'
independent backups. Viewing grants read access to one URI, not directory/write
access; legacy private files are not silently exposed. See ADR 0004.

ADB wireless debugging is a development facility, not the application transport.
Do not expose debugging or application ports to the public Internet by default.

Lock-screen access to archive results has a privacy consequence independent of
the Android device PIN. Resolve and document that policy before exposing private
history while the device is locked.
