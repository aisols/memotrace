# ADR 0005: Server Foundation and Trusted Processing

Status: Proposed (broader foundation; historical proposal retained)

Discussion recorded: 2026-09-09. Trusted server processing is the agreed security
direction from the discussion. At that point, the Go core with Python inference
was the preferred recommendation for review, not a finalized stack or implementation.
The user subsequently approved the first executable contract and minimal Go server;
[ADR 0006](0006-ingestion-v0-1.md) accepts that concrete local-first ingestion
direction. Go is adopted for that slice. Python inference and the broader stack
remain unimplemented proposals. This historical foundation is not blanket acceptance
of its remaining choices; an Accepted ADR would not establish verified behavior.

## Context

[SPEC.md](../../SPEC.md) is the original product baseline: a personal visual memory
for at least 1–2 years, durable originals, local retrieval, and optional cloud
reasoning over selected evidence. It prefers Python/FastAPI. That baseline remains
intact; this record explains the subsequent recommendation rather than silently
rewriting the earlier preference.

At baseline `992323f`, Android had an executable local recorder; the server and
contracts were scaffolds, without a released API, schema, protocol version, build
or tests. The current slice now has executable Go/PostgreSQL ingestion and contract
0.1.0 checks, still unreleased. The Linux Ryzen 9 5950X / 64 GB / no-GPU host is a
benchmark target, not proof that any model or overnight processing budget is feasible.

Long-term value comes from preserving evidence and finding it later, not from
running a VLM over every frame each day. Reliability, owner isolation, recoverable
encryption, and model reproducibility must be designed before the first ingest.

## Agreed Direction and Proposed Decisions

- **Agreed security direction:** ordinary processing on a trusted server, initially
  the user's own home node. Prevent routine staff/admin archive viewing and constrain
  exceptional access. Do not promise cryptographic secrecy from a fully compromised
  processing host, privileged administrator, or build/deployment chain.
- **Preferred stack proposal:** Go owns API, pairing/authentication, ingestion,
  archive persistence, migrations, durable job orchestration, search, and optional
  reasoning integration. Python is a narrow inference process or bounded worker
  pool, with strict static checking, runtime validation, and pinned dependencies.
  The accepted Go slice now covers enrollment, ingestion/persistence and initial
  pending-job insertion; search, queue consumers and Python inference remain future.
- **Storage proposal:** PostgreSQL plus pgvector for metadata, text/vector indexes,
  and an initial durable database queue; filesystem originals with explicit
  crash reconciliation. A durable archive receipt is independent of inference
  completion and backup completion.
- **Contract-first sequence:** settle trust, enrollment, and key-recovery choices,
  then define only the public pairing/upload/receipt/original-read thin slice.
  Test two synthetic owners from the first implementation, including denied reads.
- **Preserved ownership:** [ADR 0001](0001-component-boundaries.md) still applies.
  Public exchange definitions belong to `contracts/`; SQL, jobs, and typed private
  inference IPC belong to `server/`. API and workers share a server component and
  release, with no sibling build imports or speculative independent microservices.

## Rationale and Alternatives

Go's explicit types, errors, networking, and orchestration are attractive for a
maintainable core. Python retains model access and fast ML iteration; compiled
native kernels often dominate inference cost. Neither language proves security
or durability, and Python can be statically checked. Two runtimes and IPC add real
packaging, validation, lifecycle, and debugging costs.

Full Python/FastAPI remains the simpler iteration alternative. Go with ONNX via
C/community bindings requires export/preprocessing parity and native deployment;
Rust adds stronger safe memory/concurrency checks with implementation and ML FFI
costs. C#/.NET with the official ONNX Runtime API is compelling if production
Python is excluded. Compare these in the [server design](../../server/docs/design.md);
do not lower model quality merely to fit a language choice.

An opaque end-to-end encrypted relay/backup with user-owned compute, or an attested
confidential-computing design, changes the trust boundary. These remain alternatives
with distinct costs, not a switch on ordinary server inference. FHE/MPC is not a
practical alpha plan for the full pipeline. See the
[data-protection design](../architecture/data-protection.md) for guarantees and limits.

## Consequences and Review Gates

The first useful milestone is durable, authorized original retrieval after restart
and safe retry, independent of Android runtime, ML, or cloud availability. Visual
search follows, then OCR/episodes, lazy provenance, and optional VLM/voice integration.
Preserved originals permit better future models; they also create substantial
storage, deletion, backup, and recovery obligations.

ADR 0006 settles this slice's local enrollment, operator-owned encryption/recovery
responsibilities and full-file upload retry. Internal IPC, exact model/runtime
choices, deletion/retention and mobile metadata mapping remain open. Shared-service
operation needs further privileged-access and isolation gates.
The [server roadmap](../../server/docs/design.md#delivery-plan-and-gates) and
[ingestion semantics](../../contracts/docs/ingestion-design.md) identify the next
decisions and verification evidence. Executable targets now belong to the
[server](../../server/README.md) and [contracts](../../contracts/README.md), not this
historical proposal.
