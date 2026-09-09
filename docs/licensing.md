# Licensing Policy

## Project License

Unless explicitly stated otherwise, original MemoTrace material in this
repository, including code, documentation, and contracts, is licensed under the
GNU Affero General Public License, version 3 only. The SPDX identifier is
`AGPL-3.0-only`, not `AGPL-3.0-or-later`.

The complete, unmodified license is in [LICENSE](../LICENSE). Its source is the
[official GNU text](https://www.gnu.org/licenses/agpl-3.0.txt). The example notice
in the license's application appendix does not change this project's explicit
version-3-only grant.

This document explains project policy; it does not add restrictions or replace
the license. Review the actual license and obtain appropriate legal advice for
specific distribution, integration, or commercial arrangements.

## Commercial Use and Copyleft

Commercial use, selling copies, and paid support are allowed under AGPL. There is
no mandatory payment, revenue share, or general prohibition on business use.
Restricting commercial use would conflict with the
[Open Source Definition](https://opensource.org/osd).

When covered software is conveyed, applicable source-distribution, notice, and
copyleft requirements must be met. Under section 13, a modified version that
supports remote network interaction must prominently offer its Corresponding
Source to users interacting with it remotely. This is not limited to paid SaaS
or the public Internet. It is not a blanket requirement to publish every private
change or to disclose unrelated programs, recordings, credentials, or user data.

AGPL does not automatically require sending patches upstream. Recipients and
remote users obtain the applicable source rights; the project may benefit from
their exercise of those rights, but payment or upstream contribution is not
guaranteed. Whether an integration forms a covered combined work depends on its
actual design and applicable law, not simply its repository layout.

## Alternative Licensing and Contributions

No alternative commercial license is granted or offered by this repository.
Relevant copyright holders may negotiate a separate license in the future, but
only for material they have the authority to license on those terms.

Contributors retain ownership and contribute under `AGPL-3.0-only`. There is no
blanket copyright assignment or contributor agreement granting proprietary
relicensing rights. Before offering an alternative license, secure the necessary
rights to included contributions and dependencies. Accepting a pull request does
not itself secure those rights. See [CONTRIBUTING.md](../CONTRIBUTING.md).

## Third-Party Material

Third-party code, libraries, generated templates, fonts, models, and datasets
retain their own licenses. The repository-wide grant cannot override them.

Before adding or distributing external material, record:

- Its upstream source and exact version, revision, or artifact identity.
- Its license identifier/text and required copyright or attribution notices.
- A checksum for downloaded model or dataset artifacts.
- Relevant commercial-use, modification, and redistribution conditions.
- Compatibility with the planned use, combination, and distribution of MemoTrace.

Do not assume a model uses the license of its inference engine. Do not commit
weights or private evaluation data. No dependency or model has been approved
merely because it is mentioned as a candidate in the specification.

## Release and Extraction Checklist

- Include the complete license and required notices with distributions.
- Make the appropriate Corresponding Source available for the exact release,
  including needed build/install scripts and interface definitions.
- Preserve source-access and legal-notice facilities where the license requires
  them; plan for accessible UI without hiding these facilities.
- Check dependency, model, fixture, and generated-artifact licensing separately.
- When extracting a component, place a full copy of the root `LICENSE` and its
  relevant notices in the new repository root and preserve the version-only grant.
- Do not publish archive data, tokens, or signing secrets as supposed source code.

The Free Software Foundation copyright notice in `LICENSE` identifies the author
of the license document, not the copyright owner of MemoTrace contributions.
