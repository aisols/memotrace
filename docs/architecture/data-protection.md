# Data Protection and Processing Trust

Status: Proposed controls, recording the 2026-09-09 discussion. Trusted server
processing is the agreed direction; detailed mechanisms and operational gates
remain subject to review under [ADR 0005](../decisions/0005-server-foundation.md).
The [security policy](../../SECURITY.md) describes current repository status.
Server/contracts are scaffolds; this document asserts no deployed protection.

## Purpose and Trust Boundary

Protect a personal visual archive and its retrieval history while allowing useful
local OCR, embeddings, and search. Alpha targets the user's trusted home node.
A future common/shared server must preserve owner boundaries rather than inherit
an unscoped single-user shortcut. Home LAN location is not authentication.

In the agreed model, the processing service can obtain plaintext originals,
decoded images, OCR, and vectors. The trusted computing base includes the relevant
OS, database, application and inference processes, model/runtime dependencies,
key custody, and the people or systems able to replace those components.
Disk encryption, access control, and audited administration reduce exposure; they
do not make this service end-to-end encrypted against its own processing operator.

The goal is strong practical defense, including no routine staff/admin browsing
of archives. Exceptional operational access must be limited and accountable.
This is an operational restriction, not a cryptographic guarantee that a fully
privileged host administrator can never read content. Compromise of the trusted
endpoint or its update chain remains a residual risk even with stronger modes.

## Assets, Adversaries, and Failure Cases

Sensitive data extends beyond JPEG files:

- Originals, EXIF, timestamps, device/session relationships, location clues, and
  camera settings can reveal habits and the people or documents in a scene.
- Crops, thumbnails, OCR, embeddings, episode membership, object observations,
  and indexes can disclose archive content; vectors are not anonymous by default.
- Questions, query photographs, speech/audio, transcripts, answers, conversation
  references, and result histories reveal what the user is investigating.
- Logs, telemetry, temporary files, decoder outputs, crash/core dumps, swap,
  database journals, snapshots, and backups can contain copies of all of these.
- Pairing credentials, archive keys, recovery material, signing/update authority,
  and model artifacts control access or the code that processes plaintext.

| Threat or failure | Proposed defense | Remaining boundary |
| --- | --- | --- |
| Passive or active LAN attacker; fake server | Encrypted authenticated transport and authenticated enrollment | A compromised paired endpoint can still expose data |
| Another owner or revoked device | Credential-derived scope on every operation and artifact; isolation tests | Authorization bugs and privileged bypass require defense in depth |
| Lost phone, stolen disk, copied backup | Device protection, revocation, disk/backup encryption, scoped keys | An unlocked endpoint or stolen usable keys defeat at-rest protection |
| Malicious input, decoder exploit, resource exhaustion | Validation, bounded decoding, least-privilege workers and quotas | Native code and model loaders remain attack surfaces |
| Curious staff or accidental support export | No routine content browser; scoped exceptional access and minimal logs | Fully privileged runtime/deployment access is still trusted |
| Host, administrator, or update-chain compromise | Reviewed changes, privilege separation, external audit trail | Ordinary processing cannot promise secrecy from this compromise |
| Crash, deletion race, ransomware, key loss | Durable receipts, reconciliation, backup/restore and key-recovery tests | Availability and recovery depend on actual surviving copies and keys |

## Owner and Device Isolation

Associate access with an owner/archive and a specific registered device. Resolve
owner scope from authenticated credentials and authorized membership, never a
caller-provided `user_id` treated as authority. A frame identifier or checksum
does not grant access. Check scope for uploads, receipts, original reads, jobs,
worker results, search, neighboring frames, and future deletion/export operations.

Carry the same scope into filesystem/object access, derived-artifact downloads,
queue dispatch, vector and full-text filtering, pagination, and cache keys.
Filtering only a final search response is insufficient if earlier stages leak
counts, identifiers, snippets, or another owner's cached result. Workers receive
only the authorized job input; validate source/result association at persistence.

Use a least-privilege database runtime role, distinct from migration/administrative
roles. Proposed PostgreSQL row-level security (RLS) is defense in depth, not a
replacement for application authorization. The runtime must not be a superuser,
have `BYPASSRLS`, or own protected tables. Review connection-pool scope reset and
fail-closed behavior when owner context is absent. RLS does not constrain root,
database superusers, or someone who can change policies/deployments; uniqueness
errors and other side channels also require review.

Do not perform cross-user content deduplication or expose a checksum-existence
oracle. Exact retry detection is owner-scoped. Start with two synthetic owners
even on the single-user alpha: denied upload attachment, receipt read, original
read, and eventually tenant-isolated search must be demonstrated. Per-user storage
quotas and fair processing queues are future shared-service requirements.

## Enrollment, Transport, and Revocation

Always combine transport encryption and identity checks. A device token alone
does not protect plaintext traffic; an encrypted connection to an unauthenticated
server does not establish that it is the user's node. Network discovery supplies
a candidate address, not trust. Do not use ADB, public debugging ports, or insecure
TLS-verification bypasses as application transport/bootstrap.

Enrollment should authenticate the server using a trusted QR bootstrap, pinned
fingerprint, or a private-CA path. Choose certificate lifecycle, mTLS versus token
authentication, and recovery UX before the public pairing contract. No option is
selected here. Pairing authorizations need bounded lifetime, single-use/replay
resistance, and explicit binding of the new device to the intended owner/archive.

Issue unique revocable credentials per device, with a lost-phone revocation and
replacement path. Specify revocation enforcement for active sessions, queued work,
receipt recovery, and downloads; possession of an old receipt must not bypass it.
Authentication reset and encryption-key recovery are separate operations.
Lock-screen archive access still needs the product policy required by SECURITY.md.

## Encryption and Key Lifecycle

Propose TLS in transit and encryption of server disks and backups. Consider
per-archive envelope encryption when its isolation/recovery benefits justify the
cost: data keys protect content, a separately controlled wrapping key protects
those keys. Use authenticated encryption (AEAD) through established libraries,
cryptographic randomness, correct nonce handling, and authenticated context binding.
Algorithms, formats, storage mechanisms, and KMS/HSM providers are not selected.

Ordinary OCR and vector indexes must be readable to the trusted processing and
database processes. Storage encryption underneath PostgreSQL is not encrypted
pgvector approximate-nearest-neighbor computation. Protect index files, journals,
replicas, caches, and backups as sensitive derived data too.

Same-host key files or environment secrets are not root-proof. A KMS/HSM may stop
raw key export, but a compromised authorized application can still request decrypt
operations or read returned plaintext in memory. Key-policy administrators may
be able to change permissions/grants. Separation of data, storage, and key roles
limits some compromises; it does not automatically exclude every administrator.

Before relying on encryption, define and exercise:

1. Key generation, provisioning, custody, least-privilege use, and inventory of
   every recoverable copy, including offline recovery material.
2. Key versions and rotation, including whether old content is re-encrypted or
   old data keys are rewrapped, and how older backups remain readable.
3. Recovery on a clean node after disk/host loss, with backup and keys restored
   together under the intended identity/authorization policy.
4. Device loss and credential revocation without accidental destruction of the
   owner's only archive-decryption path.
5. Key retirement/deletion, backup expiry, and response to suspected compromise.

If all usable decryption keys are lost, a password reset cannot recreate them.
Another trusted device or a separately protected recovery key may be a recovery
path only if designed beforehand. No secure-erase or cryptographic-erasure claim
is justified without accounting for key copies, plaintext copies, and backups.

## Local Operation and Future Shared Administration

For alpha, the user knowingly trusts their own home processing host. Protect local
secrets and permissions; keep archive/database/model/backup data outside the source
tree. A second owner in tests is a correctness gate, not a claim that a production
shared service is ready.

Before shared operation, establish separate runtime, database administration,
storage, and key-management roles; scoped just-in-time privileged access; MFA;
approval and justification; short expiry; and audit of exceptional access.
Routine support should work from sanitized operational information. Do not create
a permanent universal admin content-browsing facility.

Audit deployments, policy/key changes, privilege activation, and sensitive access
without copying archive content into the audit record. Limit identity/path detail
and retention. Send appropriate audit events to a separately controlled sink so
the processing host is not the only record keeper. Same-host logs are not
tamper-proof against root; an external sink still does not prove every access
was logged or prevent plaintext exposure during a compromise.

Review release/build inputs, model provenance, update authorization, and rollback
procedures. A malicious server update can exfiltrate trusted-process plaintext;
a malicious client update can capture keys or plaintext even in an E2EE design.
Language choice alone does not remove these supply-chain or authorization risks.

## Minimization, Processing, and Outbound Copies

Preserve originals for their evidentiary purpose, while minimizing incidental
metadata, support telemetry, and retention of questions/audio/conversations.
Define access and retention for each derived class. Avoid private logs, developer
archive copies, real-user fixtures, request-body traces, and content-bearing dumps.
Bound temporary-file lifetime and permissions and review swap/core-dump behavior.

Constrain input bytes, dimensions, decode memory, execution time, output size, and
worker concurrency. Isolate model loaders/decoders and inference with per-job input
access and limited process/network privileges. No inference database credentials,
transaction authority, retry policy, or archive-delete capability. Authenticate
artifact provenance and pin model/runtime dependencies before deployment; no
weights, credentials, or private data belong in Git.

Cloud AI is explicitly optional and proposed disabled by default. Local retrieval
must work with internet unavailable or `Cloud AI = OFF`; a cloud error cannot
turn a valid local search into failure. Send only approved selected evidence and
necessary query context, not the full archive. No implicit training use of archive
or query data is authorized. Document provider retention/training terms before
enabling a provider, rather than infer them from this local policy.

Gallery publication consent, MemoTrace cloud-analysis consent, and any future E2EE
backup consent are independent. Google Photos, OneDrive, or another application
may upload public Gallery files under its own settings; Gallery consent does not
prevent that. Pending Android public-storage/profile work is not the merged
baseline. Private versus public storage is an end-to-end product decision requiring
coordination, not something a server-side encryption setting can settle.

Local deletion cannot retract copies already transferred to another application,
recipient, or cloud provider. State that limit when designing consent and deletion.

## Retention, Deletion, and Backup

Keep archival retention distinct from compute selection. Blur, occlusion,
near-duplication, or a model finding a frame uninteresting must not automatically
delete the original. Explicit owner deletion needs a separate lifecycle covering
originals, derived indexes/artifacts, queued/in-flight work, caches, and backup
expiry. Prevent a late job result from recreating deleted data.

A stale mobile queue must not silently re-upload a deliberately deleted archive.
Agree tombstone scope, persistence, synchronization, and intentional re-import
semantics with contracts/Android before deletion ships. Backup restore must honor
deletions according to the documented policy instead of silently resurrecting them.
Retention intervals and the treatment of offline devices remain open.

A durable local-disk receipt is not a backup receipt. Choose when the phone may
evict a synchronized copy using both the receipt and an explicit retention policy;
the current recorder has neither sync nor synchronized-copy eviction. Test restoration
of originals, metadata, ownership, supported persisted formats, and keys. RAID
does not replace a separately recoverable backup.

## Alternative Trust Models

**A. Trusted ordinary processing — agreed direction.** The home node, or a future
explicitly trusted shared service, performs ordinary inference and search on
plaintext. Operational controls restrict people; compromised trusted processing
remains capable of disclosure. This is the practical alpha path.

**B. User-owned compute plus opaque E2EE relay/backup — future option.** Keep keys,
OCR, embeddings, and search on the trusted user's device/home node. A shared service
stores or relays ciphertext and cannot read content if endpoints and key custody
remain uncompromised. It can still observe metadata such as size/timing, withhold
or delete data, and disrupt availability. A ciphertext checksum is not proof of
plaintext JPEG validity. A full remote encrypted archive backup would be a new,
separately opted-in mode relative to SPEC's local-full-archive default, independent
of cloud VLM consent. Protocol, recovery, indexing placement, and migration need
design; E2EE is not a retrofit switch on shared plaintext inference.

**C. Attested confidential processing — research option.** Release keys only to an
approved measured build verified by attestation, with controlled I/O and no
privileged guest shell or arbitrary code-loading route. A VM-encryption switch
alone is insufficient. Trust moves toward hardware, firmware, attestation/key
release, approved software, and update policy; application bugs, side channels,
and availability still matter. There is no ready, verified 5950X configuration
here. Apple PCC and AMD SEV are architectural references, not MemoTrace evidence.

FHE or MPC may change what is possible in principle, but neither has a demonstrated
practical alpha implementation for this decode/OCR/embedding/search pipeline.
Future privacy modes are not ruled out; each needs an explicit threat model,
performance evaluation, compatibility plan, and accounting of existing plaintext
copies. Switching modes cannot retroactively hide previously disclosed content.

## Decision Gates and References

Before initial ingest, settle enrollment, owner binding, key custody/recovery, and
the exact durability promise with server/contracts/Android owners. Before shared
operation, independently test isolation and privileged-access processes. Before
deletion, cloud transfer, or a new privacy mode, review that lifecycle end to end.
The [server plan](../../server/docs/design.md#delivery-plan-and-gates) and
[contract note](../../contracts/docs/ingestion-design.md) carry implementation gates.

External rationale, accessed 2026-09-09; these are not implemented integrations,
compliance claims, or certifications:

- [OWASP cryptographic storage](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html): threat model, authenticated encryption, key lifecycle.
- [PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html): runtime-role limits and bypass/side-channel caveats.
- [AWS KMS default key policy](https://docs.aws.amazon.com/kms/latest/developerguide/key-policy-default.html): key administrators can change policies/grants.
- [Microsoft privileged identity management](https://learn.microsoft.com/en-us/entra/id-governance/privileged-identity-management/pim-configure): time-bound, approved, audited privilege.
- [Apple Private Cloud Compute](https://security.apple.com/blog/private-cloud-compute/): measured software, restricted runtime access, and transparency.
- [AMD SEV](https://www.amd.com/en/developer/sev.html): confidential-VM mechanisms and platform-specific requirements.
