# MemoTrace Server

Autonomous component for the durable archive, processing, and retrieval system.

## Scope

- Idempotent ingestion, integrity checking, and durable archive acknowledgments.
- Original-image storage, metadata, and database migrations.
- Durable processing jobs, OCR, embeddings, and model-result versioning.
- Visual/text/temporal retrieval and evidence-backed query results.
- Optional external VLM analysis of selected evidence.

The reference host is Linux with a Ryzen 9 5950X, 64 GB RAM, and no GPU. Daily
throughput and model quality targets require benchmarks, not hardware assumptions.

## Layout and Build Status

- `src/memotrace/`: future Python package.
- `migrations/`: server-owned database migrations.
- `tests/`: component tests, including tests with its own database.
- `benchmarks/`: capture/retrieval/processing evaluation definitions and runners.

These are reserved directories, not an implemented package. There is no Python
build manifest, dependency lockfile, Docker image, or executable test suite yet.
Introduce `pyproject.toml`, a component-local lockfile, and reproducible commands
with the first working implementation. Docker builds must use this directory as
their context, not the enclosing repository.

## Internal Boundaries

Keep API, ingestion, archive, jobs, processing, search, reasoning, and storage as
cohesive internal modules. API and workers initially share one server release;
separate processes do not imply separate source repositories.

Processing functions accept images and explicit model settings and return data.
They must not own SQL transactions, job retries, or archive deletion. Persist
results and orchestrate work in the server layer. This keeps later extraction of
a processing library possible without requiring an early ML microservice.

The server owns migrations and internal job formats. Public API/exchange formats
are owned by the contracts component and consumed as pinned artifacts or
controlled snapshots, never implicit sibling imports. Test implementation
conformance as well as end-to-end behavior.

## Data and Verification

Keep actual archives, database state, caches, models, and backups outside the
source tree. Component tests must not depend on a private archive, a real phone,
or live cloud credentials. Treat OCR text and logs as sensitive.

Record model identities, preprocessing, precision, checksums, and licenses in
reproducible evaluation configuration when models are selected. Model weights
are external artifacts, not repository content.

## License

Original component material is licensed under `AGPL-3.0-only`. The full license
is in the enclosing repository's top-level `LICENSE`; include a complete copy
when extracting or distributing this component independently. Dependencies and
model weights retain their own terms.
