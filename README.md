# MemoTrace

Your private visual memory.

MemoTrace is a local-first visual archive for finding everyday objects and
recovering the context of past events. The product goal is for an Android phone
to record images and a home server to store originals, build search indexes, and
retrieve supporting episodes. Optional cloud vision-language analysis is part of
the future design; search and analysis are not implemented yet.

## Status

The first [Android recorder prototype](android/README.md) is buildable: adaptive
JPEG capture, durable local storage, Russian controls, local tests, coverage gates
and executable CI orchestration. Independent review, hosted CI and reference-device
verification remain separate gates; implementation is not hardware evidence.

The first [Go ingestion server](server/README.md) and
[contract 0.1.0](contracts/README.md) are executable, **unreleased** development
components. The server provides TLS-only local-CLI enrollment, archive-scoped
device credentials, immutable metadata registration, exact JPEG upload/read and
stable historical receipts using PostgreSQL 15 and a private Linux data root.
Contract validation and server verification commands are wired in
[ingestion CI](.github/README.md#ingestion-contracts-and-server); independent review,
main-agent verification and hosted results remain separate gates.

Each committed original creates one **pending** processing job; no ML consumer,
Python inference, search or cloud integration exists. Android synchronization,
speech and advanced device interactions remain future work. Pairing currently
uses a manually transported CLI payload, with no QR UI or Android enrollment flow.
There is no published API release or supported client/server combination yet.

The JPEG comparison prototype offers six profiles and public Gallery/My Files
originals after explicit first-Start consent. The Android app has no network
permission or synchronization, but Gallery/Photos/OneDrive may independently back
up these images. See
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
- [Accepted ingestion implementation direction](docs/decisions/0006-ingestion-v0-1.md)
- [Server setup and verification](server/README.md) and [contract checks](contracts/README.md#quality-command)
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

The ingestion slice trusts the local operator. Encrypted disks, coherent encrypted
backups and protected recovery keys are operator-provisioned, not supplied or
attested by the application. Historical receipts do not prove current original
availability, ML completion, backup or permission to evict phone data; `/healthz`
reports process liveness. See [security boundaries](SECURITY.md) and
[server storage/recovery limits](server/docs/storage.md).

## License

Unless explicitly stated otherwise, original project material in this
repository is licensed under the GNU Affero General Public License, version 3
only (`AGPL-3.0-only`). See [LICENSE](LICENSE).

Commercial use is permitted under the license. AGPL is a copyleft license, not a
noncommercial license or a requirement to pay the authors. Third-party software,
models, and datasets retain their own licenses; see the [licensing policy](docs/licensing.md).
