"""Normative boundary matrices, independent of schema-derived limits.

SPDX-License-Identifier: AGPL-3.0-only
"""

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import itertools
import socket
import tomllib
import unittest
from unittest.mock import patch

from jsonschema.exceptions import ValidationError

from tools.contract import Contract, ROOT, read_json, walk

CONTRACT = Contract()
VALID = read_json(ROOT / "examples/valid.json")
INVALID = read_json(ROOT / "examples/invalid.json")
ARCHIVES = "/v1/archives/{archive_id}/frames"
ORIGINAL = ARCHIVES + "/{frame_id}/original"
RECEIPT = ARCHIVES + "/{frame_id}/receipt"
ERRORS = {
    "invalid_request": ([400, 404, 405], False),
    "unauthorized": ([401], False),
    "not_found": ([404], False),
    "conflict": ([409], False),
    "not_committed": ([409], True),
    "integrity_error": ([409], False),
    "checksum_mismatch": ([422], True),
    "invalid_image": ([422], False),
    "payload_too_large": ([413], False),
    "unsupported_media_type": ([415], False),
    "unavailable": ([503], True),
}
# Explicit protocol expectations, not derived from schema required/properties.
REQUIRED = {
    "Health": "status contract_version",
    "Invitation": "contract_version server_url tls_certificate_sha256 invitation_token expires_at archive_id",
    "PairRequest": "invitation_token device_name",
    "PairResponse": "contract_version owner_id archive_id device_id device_token",
    "Profile": "id requested_width requested_height jpeg_quality",
    "FrameMetadata": "frame_id request_wall_ms sha256 byte_length",
    "ManifestRequest": "frames",
    "ManifestFrame": "frame_id state receipt",
    "ManifestResponse": "contract_version frames",
    "Receipt": "contract_version archive_id frame_id sha256 byte_length committed_at integrity state",
    "ErrorDetail": "code message retryable",
    "Error": "error",
}
OPTIONAL = {
    "FrameMetadata": "session_id request_elapsed_ms saved_wall_ms capture_settings profile",
    "Profile": "negotiated_width negotiated_height",
}


def mutated(definition, path, value):
    instance = deepcopy(VALID[definition])
    if not path:
        return value
    node = instance
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return instance


def errors_with_context(errors):
    for error in errors:
        yield error
        yield from errors_with_context(error.context)


def assert_case(definition, instance, keyword=None, path=()):
    errors = list(CONTRACT.validator(definition).iter_errors(instance))
    if keyword is None:
        if errors:
            raise AssertionError(f"{definition} unexpectedly invalid: {errors[0]}")
        return
    matches = [
        error for error in errors_with_context(errors)
        if error.validator == keyword and list(error.absolute_path) == list(path)
    ]
    if not matches:
        actual = [(e.validator, list(e.absolute_path)) for e in errors_with_context(errors)]
        raise AssertionError(f"{definition}: expected {keyword} at {path}, got {actual}")


def matrix_cases():
    for definition, instance in VALID.items():
        yield f"fixture_valid_{definition}", definition, instance, None, ()
    for case in INVALID:
        yield (f'fixture_invalid_{case["name"]}', case["definition"], case["instance"],
               case["keyword"], case["path"])

    for definition, names in REQUIRED.items():
        for name in names.split():
            instance = deepcopy(VALID[definition])
            del instance[name]
            yield f"required_{definition}_{name}", definition, instance, "required", ()
            # pending receipt is intentionally nullable; every other required field is not.
            if (definition, name) != ("ManifestFrame", "receipt"):
                keyword = "type"
                if (definition, name) in {("Health", "status"), ("Receipt", "integrity"), ("Receipt", "state")}:
                    keyword = "const"
                if (definition, name) in {("ManifestFrame", "state"), ("ErrorDetail", "code")}:
                    keyword = "enum"
                yield (f"nonnull_{definition}_{name}", definition,
                       mutated(definition, (name,), None), keyword, (name,))
        yield (f"closed_{definition}", definition,
               {**VALID[definition], "future_field": True}, "additionalProperties", ())
        for wrong in (None, [], "object", 1, True):
            yield f"object_type_{definition}_{wrong!r}", definition, wrong, "type", ()

    for definition, names in OPTIONAL.items():
        for name in names.split():
            instance = deepcopy(VALID[definition])
            instance.pop(name, None)
            yield f"optional_missing_{definition}_{name}", definition, instance, None, ()
            yield (f"optional_null_{definition}_{name}", definition,
                   mutated(definition, (name,), None), None, ())
            yield (f"optional_type_{definition}_{name}", definition,
                   mutated(definition, (name,), True), "type", (name,))

    numeric = [
        ("Milliseconds", (), 0, 9007199254740991),
        ("ByteLength", (), 1, 16777216),
        ("Dimension", (), 1, 16384),
        ("FrameMetadata", ("request_wall_ms",), 0, 9007199254740991),
        ("FrameMetadata", ("request_elapsed_ms",), 0, 9007199254740991),
        ("FrameMetadata", ("saved_wall_ms",), 0, 9007199254740991),
        ("FrameMetadata", ("byte_length",), 1, 16777216),
        ("Receipt", ("byte_length",), 1, 16777216),
        *[("Profile", (field,), 1, 16384) for field in (
            "requested_width", "requested_height", "negotiated_width", "negotiated_height")],
        ("Profile", ("jpeg_quality",), 1, 100),
    ]
    for definition, path, low, high in numeric:
        boundaries = [(low, None), (high, None), (float(low), None),
                      (low - 1, "minimum"), (high + 1, "maximum")]
        boundaries += [(value, "type") for value in (1.5, True, False, "1", [], {})]
        for index, (value, keyword) in enumerate(boundaries):
            yield (f"number_{definition}_{path}_{index}", definition,
                   mutated(definition, path, value), keyword, path)

    for definition, field, low, high in (
        ("PairRequest", "device_name", 1, 80),
        ("Profile", "id", 1, 64),
        ("FrameMetadata", "capture_settings", 0, 2048),
    ):
        for count, keyword in [(low, None), (high, None), (high + 1, "maxLength")]:
            yield (f"unicode_{definition}_{field}_{count}", definition,
                   mutated(definition, (field,), "📷" * count), keyword, (field,))
        if low:
            yield (f"empty_{definition}_{field}", definition,
                   mutated(definition, (field,), ""), "minLength", (field,))
        yield (f"string_type_{definition}_{field}", definition,
               mutated(definition, (field,), 1), "type", (field,))
        for index, value in enumerate(("\u0000", "a\u0000b", "\ud800", "\udbff", "\udc00", "\udfff", "a\ud800\nb")):
            yield (f"text_domain_{definition}_{field}_{index}", definition,
                   mutated(definition, (field,), value), "pattern", (field,))
        for index, value in enumerate(("📷", "\U00010000", "\U0010ffff", "\ufffd", "e\u0301", "a\n\tb")):
            yield (f"scalar_text_{definition}_{field}_{index}", definition,
                   mutated(definition, (field,), value), None, (field,))

    patterns = {
        "UUID": [
            ("00000000-0000-0000-0000-000000000000", None),
            ("ffffffff-ffff-ffff-ffff-ffffffffffff", None),
            ("01234567-89ab-cdef-0123-456789abcdef", None),
            ("01234567-89AB-cdef-0123-456789abcdef", "pattern"),
            ("0123456789abcdef0123456789abcdef", "pattern"),
            ("{01234567-89ab-cdef-0123-456789abcdef}", "pattern"),
            ("01234567-89ab-cdef-0123-456789abcdeg", "pattern"),
            ("01234567-89ab-cdef-0123-456789abcdef\n", "maxLength"),
            (123, "type"),
        ],
        "SHA256": [
            ("0" * 64, None), ("f" * 64, None), ("F" * 64, "pattern"),
            ("g" * 64, "pattern"), ("0" * 63, "minLength"),
            ("0" * 65, "maxLength"), ("0" * 64 + "\n", "maxLength"), (123, "type"),
        ],
        "Token": [
            ("A" * 43, None), ("_" * 42 + "8", None), ("-" * 42 + "A", None),
            ("A" * 42, "minLength"), ("A" * 44, "maxLength"),
            ("A" * 43 + "=", "maxLength"), ("+" * 42 + "A", "pattern"),
            ("/" * 42 + "A", "pattern"), ("A" * 43 + "\n", "maxLength"), (123, "type"),
        ],
        "UTCDateTime": [
            ("2024-02-29T23:59:59Z", None), ("2026-09-09T00:00:00Z", None),
            ("2026-09-09T12:34:56.123456789Z", None),
            ("2026-02-29T12:00:00Z", "format"), ("2026-02-30T12:00:00Z", "format"),
            ("2026-13-01T12:00:00Z", "format"), ("2026-09-09T24:00:00Z", "format"),
            ("2026-09-09T12:60:00Z", "format"), ("2026-09-09T12:00:61Z", "format"),
            ("2016-12-31T23:59:60Z", "format"),
            ("2026-09-09T12:00:00+00:00", "pattern"),
            ("2026-09-09T12:00:00-03:00", "pattern"),
            ("2026-09-09t12:00:00z", "pattern"), ("2026-09-09 12:00:00Z", "pattern"),
            ("2026-09-09T12:00:00", "pattern"), ("2026-09-09", "pattern"),
            ("2026-09-09T12:00:00Z\n", "not"), (123, "type"),
        ],
        "ServerOrigin": [
            ("https://memotrace.example", None), ("https://localhost:8443", None),
            ("https://127.0.0.1:443", None), ("https://[::1]:8443", None),
            ("https://memotrace.example:1", None), ("https://memotrace.example:65535", None),
            ("https://memotrace.example:00001", None), ("https://memotrace.example:00443", None),
            ("https://memotrace.example:000001", "pattern"),
            ("https://memotrace.example:100000", "pattern"),
            ("https://memotrace.example:", "pattern"),
            ("https://memotrace.example:-1", "pattern"),
            ("https://memotrace.example:1.5", "pattern"),
            ("HTTPS://memotrace.example", "pattern"),
            ("Https://memotrace.example", "pattern"),
            ("http://memotrace.example", "pattern"),
            ("https://user:pass@memotrace.example", "pattern"),
            ("https://memotrace.example/", "pattern"),
            ("https://memotrace.example/path", "pattern"),
            ("https://memotrace.example?query=1", "pattern"),
            ("https://memotrace.example#fragment", "pattern"),
            ("https://", "pattern"), ("https://host name", "pattern"),
            ("https://memotrace.example\n", "not"), (123, "type"),
        ],
    }
    # Exercise reusable constraints at every public field, not just in isolation.
    fields = {
        "UUID": [("Invitation", "archive_id"), ("PairResponse", "owner_id"),
                 ("PairResponse", "archive_id"), ("PairResponse", "device_id"),
                 ("FrameMetadata", "frame_id"), ("FrameMetadata", "session_id"),
                 ("ManifestFrame", "frame_id"), ("Receipt", "archive_id"), ("Receipt", "frame_id")],
        "SHA256": [("Invitation", "tls_certificate_sha256"), ("FrameMetadata", "sha256"), ("Receipt", "sha256")],
        "Token": [("Invitation", "invitation_token"), ("PairRequest", "invitation_token"), ("PairResponse", "device_token")],
        "UTCDateTime": [("Invitation", "expires_at"), ("Receipt", "committed_at")],
        "ServerOrigin": [("Invitation", "server_url")],
    }
    for primitive, values in patterns.items():
        for definition, path in [(primitive, ()), *[(d, (f,)) for d, f in fields[primitive]]]:
            for index, (value, keyword) in enumerate(values):
                yield (f"pattern_{definition}_{path}_{index}", definition,
                       mutated(definition, path, value), keyword, path)

    # Exhaust all 64 possible final alphabet characters: exactly 16 have zero pad bits.
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    for index, char in enumerate(alphabet):
        keyword = None if index % 4 == 0 else "pattern"
        yield f"token_final_{index}", "Token", "A" * 42 + char, keyword, ()

    for definition in ("ManifestRequest", "ManifestResponse"):
        for count, keyword in [(0, "minItems"), (1, None), (100, None), (101, "maxItems")]:
            frames = []
            template = VALID["FrameMetadata" if definition == "ManifestRequest" else "ManifestFrame"]
            for index in range(count):
                frames.append({**template, "frame_id": f"00000000-0000-0000-0000-{index:012x}"})
            yield (f"batch_{definition}_{count}", definition,
                   mutated(definition, ("frames",), frames), keyword, ("frames",))
        for value in (None, {}, "frames", 1):
            yield (f"batch_type_{definition}_{value!r}", definition,
                   mutated(definition, ("frames",), value), "type", ("frames",))

    for state, receipt in itertools.product(("pending", "committed"), (None, VALID["Receipt"])):
        valid = (state == "pending") == (receipt is None)
        instance = {"frame_id": VALID["Receipt"]["frame_id"], "state": state, "receipt": receipt}
        yield (f"state_receipt_{state}_{receipt is None}", "ManifestFrame", instance,
               None if valid else "type", ("receipt",))

    for code, (_, retryable) in ERRORS.items():
        for value in (retryable, not retryable, "true", 1, None):
            keyword = None if value is retryable else "const"
            yield (f"error_retryable_{code}_{value!r}", "Error",
                   {"error": {"code": code, "message": "Synthetic generic error.", "retryable": value}},
                   keyword, ("error", "retryable"))
    for field in ("message", "code", "retryable"):
        yield (f"error_field_type_{field}", "Error",
               mutated("Error", ("error", field), []),
               "enum" if field == "code" else "type", ("error", field))
    yield "empty_error_message", "Error", mutated("Error", ("error", "message"), ""), None, ()

    constants = [("ContractVersion", (), "0.2.0"), ("Health", ("status",), "ready"),
                 ("Receipt", ("integrity",), "fully-decoded"),
                 ("Receipt", ("state",), "indexed")]
    constants += [(d, ("contract_version",), "0.2.0") for d in (
        "Health", "Invitation", "PairResponse", "ManifestResponse", "Receipt")]
    for definition, path, value in constants:
        yield (f"constant_{definition}_{path}", definition,
               mutated(definition, path, value), "const", path)
    for state in ("archive_committed", "indexed", "", None, 1):
        yield (f"manifest_state_{state!r}", "ManifestFrame",
               mutated("ManifestFrame", ("state",), state), "enum", ("state",))

    # Nested constraints must remain connected through manifest and profile refs.
    yield ("nested_manifest_metadata", "ManifestRequest",
           mutated("ManifestRequest", ("frames", 0, "byte_length"), 0),
           "minimum", ("frames", 0, "byte_length"))
    yield ("nested_manifest_receipt", "ManifestResponse",
           mutated("ManifestResponse", ("frames", 0, "receipt", "sha256"), "g" * 64),
           "pattern", ("frames", 0, "receipt", "sha256"))
    yield ("nested_metadata_profile", "FrameMetadata",
           mutated("FrameMetadata", ("profile", "jpeg_quality"), 101),
           "maximum", ("profile", "jpeg_quality"))


class ContractTests(unittest.TestCase):
    def test_real_validators_and_offline_references(self):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")):
            CONTRACT.validate_documents()

    def test_openapi_validator_rejects_broken_document(self):
        broken = deepcopy(CONTRACT.openapi)
        del broken["info"]["title"]
        with self.assertRaises(ValidationError):
            CONTRACT.validate_openapi(broken)

    def test_unregistered_reference_fails_closed(self):
        for uri in ("https://unregistered.example/schema.json", "file:///etc/passwd"):
            with self.subTest(uri=uri), self.assertRaises(Exception):
                CONTRACT.resolve(uri)

    def test_versions_dialects_and_fixture_definition_coverage(self):
        version = (ROOT / "VERSION").read_text().strip()
        self.assertEqual(version, "0.1.0")
        self.assertEqual(CONTRACT.openapi["info"]["version"], version)
        self.assertEqual(CONTRACT.schema["$defs"]["ContractVersion"]["const"], version)
        self.assertIn(f"/{version}/", CONTRACT.schema["$id"])
        self.assertEqual(CONTRACT.openapi["openapi"], "3.1.0")
        self.assertEqual(CONTRACT.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(CONTRACT.openapi["jsonSchemaDialect"], CONTRACT.schema["$schema"])
        self.assertEqual(set(VALID), set(CONTRACT.schema["$defs"]))
        self.assertEqual(len({c["name"] for c in INVALID}), len(INVALID))
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertEqual(project["project"]["version"], version)

    def test_all_objects_have_explicit_field_policy(self):
        for definition, required in REQUIRED.items():
            schema = CONTRACT.schema["$defs"][definition]
            self.assertEqual(set(schema["required"]), set(required.split()), definition)
            fields = set(required.split()) | set(OPTIONAL.get(definition, "").split())
            self.assertEqual(set(schema["properties"]), fields, definition)
        for path, node in walk(CONTRACT.schema):
            if isinstance(node, dict) and node.get("type") == "object":
                self.assertIs(node.get("additionalProperties"), False, path)
                if len(path) == 2 and path[0] == "$defs":
                    self.assertIn(path[1], REQUIRED, "Add explicit policy/boundary tests for new objects")

    def test_paths_security_and_canonical_payload_refs(self):
        expected = {
            ("/healthz", "get"): (None, "200", "Health"),
            ("/v1/pairing/redeem", "post"): ("PairRequest", "201", "PairResponse"),
            (ARCHIVES, "post"): ("ManifestRequest", "200", "ManifestResponse"),
            (ORIGINAL, "put"): ("binary", "200", "Receipt"),
            (ORIGINAL, "get"): (None, "200", "binary"),
            (RECEIPT, "get"): (None, "200", "Receipt"),
        }
        actual = {
            (path, method) for path, item in CONTRACT.openapi["paths"].items()
            for method in item if method in {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
        }
        self.assertEqual(actual, set(expected))
        self.assertEqual(CONTRACT.openapi["security"], [{"deviceToken": []}])
        scheme = CONTRACT.openapi["components"]["securitySchemes"]["deviceToken"]
        self.assertEqual((scheme["type"], scheme["scheme"]), ("http", "bearer"))
        for (path, method), (request, status, response) in expected.items():
            operation = CONTRACT.openapi["paths"][path][method]
            self.assertEqual(operation.get("security", CONTRACT.openapi["security"]),
                             [] if path in ("/healthz", "/v1/pairing/redeem") else [{"deviceToken": []}])
            if request:
                body = operation["requestBody"]
                self.assertIs(body["required"], True)
                self.check_content(body["content"], request)
            else:
                self.assertNotIn("requestBody", operation)
            self.check_content(CONTRACT.dereference(operation["responses"][status])["content"], response)
            for error_status, ref in operation["responses"].items():
                result = CONTRACT.dereference(ref)
                for name, value in (("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff")):
                    header = CONTRACT.dereference(result["headers"][name])
                    self.assertEqual(header["schema"]["const"], value)
                    self.assertIs(header["required"], True)
                if int(error_status) >= 400:
                    self.check_content(result["content"], "Error")
                    for code in result["x-error-codes"]:
                        self.assertIn(int(error_status), ERRORS[code][0])
                if error_status != "401":
                    self.assertNotIn("WWW-Authenticate", result["headers"])

    def test_authentication_challenges_by_operation(self):
        for path, method in (("/v1/pairing/redeem", "post"), (ARCHIVES, "post"),
                             (ORIGINAL, "put"), (ORIGINAL, "get"), (RECEIPT, "get")):
            with self.subTest(path=path, method=method):
                expected = ('MemoTraceInvitation realm="memotrace-pairing"'
                            if path == "/v1/pairing/redeem" else 'Bearer realm="memotrace"')
                response = CONTRACT.dereference(CONTRACT.openapi["paths"][path][method]["responses"]["401"])
                header = CONTRACT.dereference(response["headers"]["WWW-Authenticate"])
                self.assertIs(header["required"], True)
                self.assertEqual(header["schema"], {"type": "string", "const": expected})
                validator = CONTRACT.schema_validator(header["schema"], CONTRACT.openapi_uri)
                validator.validate(expected)
                for wrong in ("", "Bearer", 'Basic realm="memotrace"',
                              'MemoTraceInvitation realm="memotrace-pairing"'
                              if path != "/v1/pairing/redeem" else 'Bearer realm="memotrace"'):
                    with self.assertRaises(ValidationError):
                        validator.validate(wrong)

    def test_endpoint_status_inventory(self):
        expected = {
            ("/healthz", "get"): "200 405 503",
            ("/v1/pairing/redeem", "post"): "201 400 401 405 413 415 503",
            (ARCHIVES, "post"): "200 400 401 404 405 409 413 415 503",
            (ORIGINAL, "put"): "200 400 401 404 405 409 413 415 422 503",
            (ORIGINAL, "get"): "200 400 401 404 405 409 503",
            (RECEIPT, "get"): "200 400 401 404 405 409 503",
        }
        for (path, method), statuses in expected.items():
            self.assertEqual(set(CONTRACT.openapi["paths"][path][method]["responses"]), set(statuses.split()))

    def check_content(self, content, definition):
        self.assertEqual(set(content), {"image/jpeg" if definition == "binary" else "application/json"})
        schema = next(iter(content.values()))["schema"]
        if definition == "binary":
            self.assertEqual(schema, {"type": "string", "format": "binary"})
        else:
            self.assertEqual(schema, {"$ref": f"../schemas/ingestion.schema.json#/$defs/{definition}"})
            CONTRACT.schema_validator(schema, CONTRACT.openapi_uri).validate(VALID[definition])

    def test_discover_every_openapi_schema_ref_and_example(self):
        for path, node in walk(CONTRACT.openapi):
            if not isinstance(node, dict):
                continue
            if "$ref" in node and not node["$ref"].startswith("#/"):
                self.assertTrue(node["$ref"].startswith("../schemas/ingestion.schema.json#/$defs/"), path)
                definition = node["$ref"].split("/$defs/")[1]
                CONTRACT.schema_validator(node, CONTRACT.openapi_uri).validate(VALID[definition])
            if "schema" in node:
                validator = CONTRACT.schema_validator(node["schema"], CONTRACT.openapi_uri)
                if "example" in node:
                    validator.validate(node["example"])
                for example in node.get("examples", {}).values():
                    example = CONTRACT.dereference(example)
                    self.assertNotIn("externalValue", example, "Fixtures must stay offline")
                    validator.validate(example["value"])

    def test_http_limits_error_codes_and_identifiers(self):
        paths = CONTRACT.openapi["paths"]
        self.assertEqual(paths[ARCHIVES]["post"]["requestBody"]["x-max-bytes"], 1048576)
        self.assertEqual(paths[ORIGINAL]["put"]["requestBody"]["x-max-bytes"], 16777216)
        header = paths[ORIGINAL]["get"]["responses"]["200"]["headers"]["Content-Length"]
        self.assertIs(header["required"], True)
        self.assertEqual(header["schema"]["$ref"], "../schemas/ingestion.schema.json#/$defs/ByteLength")
        self.assertEqual(CONTRACT.openapi["x-error-statuses"], {c: v[0] for c, v in ERRORS.items()})
        self.assertEqual(set(CONTRACT.schema["$defs"]["ErrorDetail"]["properties"]["code"]["enum"]), set(ERRORS))
        for path in (ARCHIVES, ORIGINAL, RECEIPT):
            params = [CONTRACT.dereference(p) for p in paths[path]["parameters"]]
            self.assertEqual({p["name"] for p in params}, {"archive_id"} if path == ARCHIVES else {"archive_id", "frame_id"})
            for param in params:
                self.assertEqual(param["schema"]["$ref"], "../schemas/ingestion.schema.json#/$defs/UUID")
                self.assertEqual(param["in"], "path")
                self.assertIs(param["required"], True)

    def test_token_encoding_roundtrip(self):
        for raw in (bytes(32), bytes([255]) * 32, bytes(range(32))):
            token = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
            CONTRACT.validator("Token").validate(token)
            self.assertEqual(len(token), 43)
            self.assertEqual(base64.urlsafe_b64decode(token + "="), raw)

    def test_schema_boundary_does_not_claim_semantic_checks(self):
        # Distinct-property uniqueness, cross-object equality, TTL and JPEG bytes
        # require a runtime. These schema-valid counterexamples record that limit.
        frame = VALID["FrameMetadata"]
        CONTRACT.validator("ManifestRequest").validate({"frames": [frame, frame]})
        mismatched = deepcopy(VALID["ManifestResponse"])
        mismatched["frames"][0]["receipt"]["frame_id"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        CONTRACT.validator("ManifestResponse").validate(mismatched)
        old = {**VALID["Invitation"], "expires_at": "2000-01-01T00:00:00Z"}
        CONTRACT.validator("Invitation").validate(old)
        for port in ("0", "00000", "65536", "99999"):
            # Port digit count is a schema rule; numeric port bounds are runtime.
            CONTRACT.validator("ServerOrigin").validate(f"https://memotrace.example:{port}")

    def test_invitation_expiry_preserves_microseconds_at_ttl_boundaries(self):
        issued = datetime(2026, 9, 9, 12, 34, 56, 123456, tzinfo=timezone.utc)
        for seconds in (1, 600):
            with self.subTest(seconds=seconds):
                expiry = issued + timedelta(seconds=seconds)
                text = expiry.isoformat(timespec="microseconds").replace("+00:00", "Z")
                invitation = {**VALID["Invitation"], "expires_at": text}
                CONTRACT.validator("Invitation").validate(invitation)
                parsed = datetime.fromisoformat(invitation["expires_at"])
                self.assertEqual(parsed, expiry)
                self.assertEqual(parsed.microsecond, issued.microsecond)
        # Invitation has no issued_at/TTL field: schema validation alone cannot
        # enforce CLI duration bounds or that output is generated before expiry.
        too_late = {**VALID["Invitation"], "expires_at": (issued + timedelta(seconds=601)).isoformat().replace("+00:00", "Z")}
        CONTRACT.validator("Invitation").validate(too_late)


def load_tests(loader, tests, pattern):
    names = set()
    for name, definition, instance, keyword, path in matrix_cases():
        if name in names:
            raise AssertionError(f"Duplicate matrix test: {name}")
        names.add(name)

        def check(definition=definition, instance=instance, keyword=keyword, path=path):
            assert_case(definition, instance, keyword, path)

        tests.addTest(unittest.FunctionTestCase(check, description=name))
    return tests
