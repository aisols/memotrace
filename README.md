# MemoTrace

Your private visual memory.

MemoTrace is a local-first visual archive for finding everyday objects and
recovering the context of past events. An Android phone records images; a home
server stores the originals, builds search indexes, and retrieves supporting
episodes. Cloud vision-language analysis is optional, not a prerequisite for
basic search.

## Status

The first [Android recorder prototype](android/README.md) is buildable: adaptive
JPEG capture, durable local storage, Russian controls, local tests, coverage gates
and executable CI orchestration. Independent review, hosted CI and reference-device
verification remain separate gates; implementation is not hardware evidence.
There is no server implementation or published API yet. Synchronization, speech
and advanced device interactions remain future work, without placeholder controls.

The JPEG comparison prototype offers six profiles and public Gallery/My Files
originals after explicit first-Start consent. MemoTrace itself stays offline, but
Gallery/Photos/OneDrive may independently back up these images. See
[profiles and storage](android/README.md#compare-profiles) and [security](SECURITY.md).

The initial reference device is a dedicated Samsung Galaxy A33 running Android
16 / One UI 8, with continued access to its existing applications. The reference
server is Linux with a Ryzen 9 5950X, 64 GB RAM, and no GPU.

## Repository

| Directory | Responsibility |
| --- | --- |
| [android/](android/README.md) | Recorder, local queue, synchronization, voice, and accessible user interface |
| [server/](server/README.md) | Ingestion, archive, processing, search, and optional VLM integration |
| [contracts/](contracts/README.md) | Public API and versioned exchange formats |
| [deploy/](deploy/README.md) | Development assembly and deployment of the whole system |
| [integration/](integration/README.md) | Cross-component tests and safe fixtures |
| [docs/](docs/README.md) | Product, architecture, decisions, and interaction requirements |
| [tools/](tools/README.md) | Repository-wide coordination tools |

The three component roots are intended to remain independently buildable and
extractable into separate repositories. They are ordinary directories today;
there are no submodules yet. The outer repository owns system assembly and
cross-component verification, not component implementation details.

## Start Here

- [Product specification](SPEC.md)
- [Architecture and extraction rules](docs/architecture/README.md)
- [Accepted repository-boundary decision](docs/decisions/0001-component-boundaries.md)
- [Recorder interaction requirements](docs/ux/README.md)
- [Contribution guidelines](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Licensing policy](docs/licensing.md)

The specification remains the original product baseline. Later accepted
decisions and interaction clarifications are recorded separately; unresolved
device behavior is not presented as an implemented or verified feature.

## Privacy

Do not commit personal recordings, document images, database dumps, credentials,
signing keys, or downloaded model weights. Use synthetic or explicitly approved
public fixtures. Runtime archives and backups belong outside the source tree.

## License

Unless explicitly stated otherwise, original project material in this
repository is licensed under the GNU Affero General Public License, version 3
only (`AGPL-3.0-only`). See [LICENSE](LICENSE).

Commercial use is permitted under the license. AGPL is a copyleft license, not a
noncommercial license or a requirement to pay the authors. Third-party software,
models, and datasets retain their own licenses; see the [licensing policy](docs/licensing.md).
