# Contract quality and evidence

Run from the component root with Python 3.12+ and uv 0.11.3:

```sh
uv run --locked python -m tools.verify
```

`.python-version` chooses Python 3.12 as the baseline. `pyproject.toml` pins the
direct validators; `uv.lock` pins every resolved dependency and artifact hash.
The lock must match the project (`--locked`, not an unchecked frozen install).
An explicit tooling update changes both files and requires rerunning the suite.
Development uses Python's standard `unittest`; no server, DB, cloud, or Android
runtime is involved. A nonzero result, skipped check, or empty discovery fails
the command. For individual diagnostic test output:

```sh
uv run --locked python -m unittest discover -s tests -v
```

After dependency provisioning, the same full check supports offline installation
from cache and always-offline schema resolution:

```sh
uv run --locked --offline python -m tools.verify
```

## Executable gates

1. **Parse actual files** using a lossless JSON decoder that rejects duplicate
   properties, non-JSON constants, invalid UTF-8 and unpaired surrogates in values
   or property names. Parse decimals exactly; only genuinely integral decimals
   become integers. Regression literals cover float rounding, underflow, exponent
   integers, maximum-safe values, and low decimal-context precision. Check the canonical schema and every definition using
   `jsonschema.Draft202012Validator.check_schema`.
2. **Validate actual OpenAPI** with `OpenAPIV31SpecValidator`, including external
   canonical refs. A broken OpenAPI document is a validator rejection test.
3. **Closed offline reference resolution**: discover all `$ref` values; every
   one must resolve in the two preloaded documents. Canonical `$id` is an identity,
   not a fetch URL. Both validators receive explicit local registries/handlers;
   there is no network or arbitrary-file fallback. Unknown refs fail closed.
4. **Fixture expectations**: every named definition has an accepted fixture.
   Every invalid fixture must produce its expected validation keyword at its
   expected instance path (including errors nested inside `anyOf`). Merely failing
   for some other reason is insufficient.
5. **Field-boundary matrices**: each public integer limit and field linkage has
   inclusive endpoints, one-past limits, and fractional/bool/string/container
   failures. Strings use Unicode code points at min/max/one-past. Every required
   property is removed and null-tested; each optional is missing/null/type-tested.
   Objects reject unknown properties. Batch cardinality is 0/1/100/101.
   User-text patterns reject NUL and unpaired surrogates; raw-JSON cases distinguish
   parse rejection from schema rejection, preserve valid surrogate pairs/astral
   scalars and genuine U+FFFD, and keep invalid text out of UTF-8 diagnostics.
6. **Encoded values and relationships**: UUID lower hex without a version
   restriction; digest lower hex; token length/alphabet and all 64 possible final
   characters (16 valid zero-padding-bit values); runtime calendar/date validity
   with UTC Z syntax; HTTPS origins; both states crossed with null/non-null
   receipts; all error codes crossed with correct/incorrect retryability.
7. **HTTP and schema drift**: explicit paths/methods/status inventory,
   request/success/error references, header/media requirements, path-UUID schemas,
   body limits, bearer scope, operation-specific required 401 challenges, and
   version/dialect pins. Wrong/missing challenge declarations fail; non-401
   response header expectations remain unchanged. Discover every OpenAPI
   schema reference and check it with canonical fixture data. Any inline OpenAPI
   examples added later are discovered and validated too. New definitions need
   fixtures; new objects need an explicit field policy and boundary tests.
8. **Invitation boundaries**: schema checks cover lower-case HTTPS, port digit
   count/leading zeros, and fractional expiry at TTL 1/600 examples. Numeric port
   bounds, actual CLI TTL rejection, and unexpired output timing are explicit
   server-runtime obligations. Schema-valid out-of-range ports/late expiry are
   retained as counterexamples, not presented as successful runtime checks.

The gate is exhaustive **declared boundary/relationship coverage**, not an
arbitrary application line-coverage percentage. Schema keywords and public
invariants are the objects under test; a Python code coverage percentage would
not establish protocol coverage. Independent review must assess whether these
matrices and the runtime scenario obligations cover each new requirement.
CI should invoke this exact component command; orchestration lives outside this
component. This document does not claim CI wiring or independent review passed.

## Scope of the evidence

Schema validation cannot express uniqueness by `frame_id`, response/input order,
cross-object identity/hash equality, null normalization across retries, token
randomness, invitation TTL, authorization, JPEG validity, body byte counting,
atomicity, durability, receipt byte stability, current file availability, or
non-disclosing error text. The suite records schema-valid semantic counterexamples
to make this distinction executable. See the normative scenarios in
`protocol.md`; server and later cross-component tests own those real behaviors.

Runtime-format validation must remain enabled. The pinned RFC3339 checker rejects
impossible dates but does not implement leap-second notation. This limitation and
integer lexical interoperability are documented in the protocol rather than
hidden by a custom partial validator. Host/port parsing and TLS verification
likewise remain real consumer responsibilities beyond the origin schema pattern.

To verify extraction independence, copy only this component's source files into
an empty directory, retain its internal paths, then run the same command there.
The check resolves its root from `tools/contract.py` and never reads parent or
sibling sources/configuration. Include the complete AGPL license and applicable
notices before distributing an extracted component (see `releases.md`).
