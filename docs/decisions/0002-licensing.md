# ADR 0002: AGPL-3.0-only

Status: Accepted

## Context

MemoTrace is intended to be open source while discouraging appropriation into
closed distributed or network-served derivatives. The author also considered
restricting unpaid commercial use.

Open-source licensing permits commercial use. AGPL cannot guarantee payment or
prevent a business from using the software while meeting the license conditions.
That limitation was explained and AGPL-3.0-only was selected explicitly.

## Decision

License original project material under the unmodified GNU Affero General Public
License, version 3 only (`AGPL-3.0-only`). Keep the full official text at the
repository root and make the version-only grant explicit in project notices.
Do not append noncommercial restrictions or a mandatory royalty requirement.

Third-party material retains its own terms. Contributions do not transfer
copyright or automatically grant rights for a proprietary licensing program.
No alternative commercial license is currently offered.

## Consequences

- The project remains open source and permits compliant commercial use.
- Applicable distribution and remote-network source obligations protect users'
  access to corresponding source, not an automatic payment to the author.
- Copyleft does not guarantee upstream patches or prevent independent competition.
- Alternative licensing would require rights clearance for affected contributions
  and dependencies before such an arrangement is offered.
- Every extracted component or distribution must carry the applicable full
  license and notices; a repository split does not change license obligations.

See the [licensing policy](../licensing.md) and [full license](../../LICENSE).
