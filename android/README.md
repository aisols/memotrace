# MemoTrace Android

Autonomous component for the wearable recorder and user-facing client.

## Scope

- Camera capture and reliable local image/metadata storage.
- Durable synchronization state, retries, and archive acknowledgments.
- Accessible interaction, voice queries, and evidence viewing.
- Recorder/ordinary-phone mode transitions and physical button handling.
- On-device speech recognition, initially evaluating Vosk.

The reference device is a Samsung Galaxy A33 on Android 16 / One UI 8. Existing
applications must remain usable. Screen-off capture, wake behavior, and key
handling require explicit hardware verification.

## Layout and Build Status

`app/src/main/` reserves application sources, `app/src/test/` local tests, and
`app/src/androidTest/` device tests. These directories contain no implementation.
There is no Gradle project or build command yet.

When implementation starts, keep the Gradle Wrapper, settings, dependency
configuration, and build/test instructions inside this directory. The project
must build after this directory is extracted, without a parent Gradle project,
sibling source trees, or a live server for client generation.

Keep cohesive capture, local-state, synchronization, device-control, speech, and
UI packages before introducing multiple Gradle modules. Reuse tremor-tolerant
controls without breaking accessibility semantics.

## Boundaries

Consume the public API and versioned formats, not server database models. Pin any
contract snapshot/artifact and record its provenance; do not depend on a sibling
contracts directory at build time. Use mocks or safe fixtures for local tests.

Wireless ADB is for development only. Application synchronization uses its own
authenticated, encrypted protocol. Keep signing keys, recordings, downloaded
models, and local SDK paths out of Git. Runtime state belongs in Android-managed
application storage, not a source checkout.

## License

Original component material is licensed under `AGPL-3.0-only`. The full license
is in the enclosing repository's top-level `LICENSE`; include a complete copy
when extracting or distributing this component independently. Third-party
libraries and speech models retain their own terms.
