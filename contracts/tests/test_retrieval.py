"""Retrieval-family wire, raw JSON, HTTP and semantic-boundary regressions.

SPDX-License-Identifier: AGPL-3.0-only
"""

from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
import socket
import unittest
from unittest.mock import patch

from jsonschema.exceptions import ValidationError

from tools.contract import BUNDLE_VERSION, Contract, FAMILIES, ROOT, parse_json, read_json, walk
from tools.retrieval import validate
from tools.snapshot import manifest

CONTRACT = Contract(family="retrieval")
INGESTION = Contract()
VALID = read_json(ROOT / "examples/retrieval-valid.json")
INVALID = read_json(ROOT / "examples/retrieval-invalid.json")
RAW = read_json(ROOT / "examples/raw-json.json")
SEARCH = "/v1/archives/{archive_id}/search"
HISTORY = "/v1/archives/{archive_id}/history"
ORIGINAL = SEARCH + "/assets/{asset_id}/original"
FROZEN = {
    "schemas/ingestion.schema.json": "9dcc7ab98a2d77357c3a00e966590e282525962fa33c2aeb58c1b12ccdecb783",
    "openapi/ingestion.json": "eafc37a24fddd70c6afd6c6ed1290f60ad62c691f650ba8af365cfbd9156b37b",
}
REQUIRED = {
    "TextQuery": "text", "ImageQuery": "asset_id", "WallTimeline": "kind",
    "SequenceTimeline": "kind sequence_id", "SearchRequest": "generation_id query",
    "HistoryRequest": "generation_id query min_score", "Dataset": "name version item_id",
    "Region": "kind box",
    "Hit": "asset_id source_kind frame_id dataset sha256 score region observed_at_ms sequence_id sequence_position_ms original_path",
    "Coverage": "assets_total assets_indexed pending failed regions_indexed",
    "SearchResponse": "contract_version archive_id generation_id coverage hits truncated",
    "Observation": "start_ms end_ms max_score evidence",
    "HistoryResponse": "contract_version archive_id generation_id coverage timeline history_available observations unsequenced_hits first_observed_ms last_observed_ms truncated interpretation",
}
OPTIONAL = {
    "ImageQuery": "box", "SearchRequest": "limit min_score timeline before_ms",
    "HistoryRequest": "limit timeline before_ms gap_ms",
}
TEXT_FIELDS = [
    ("TextQuery", ("text",), 2048), ("Query", ("text",), 2048),
    ("SearchRequest", ("query", "text"), 2048),
    *[("Dataset", (key,), 512) for key in ("name", "version", "item_id")],
    *[("Hit", ("dataset", key), 512) for key in ("name", "version", "item_id")],
    ("SequenceID", (), 256), ("SequenceTimeline", ("sequence_id",), 256),
    ("HistoryRequest", ("timeline", "sequence_id"), 256),
]


def mutated(definition, path, value):
    if not path:
        return value
    instance = deepcopy(VALID[definition])
    node = instance
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return instance


def descend(errors):
    for error in errors:
        yield error
        yield from descend(error.context)


def raw_document(value):
    """Fixture serialization preserving exact decimals before literal insertion."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(key) + ":" + raw_document(child) for key, child in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(raw_document(child) for child in value) + "]"
    return json.dumps(value, allow_nan=False)


def assert_case(definition, instance, keyword=None, path=()):
    errors = list(CONTRACT.validator(definition).iter_errors(instance))
    if keyword is None:
        if errors:
            raise AssertionError(f"Unexpected {definition} schema error: {errors[0].validator}")
    elif not any(e.validator == keyword and tuple(e.absolute_path) == path for e in descend(errors)):
        raise AssertionError(f"Expected {definition} {keyword} at {path}")


def matrix_cases():
    for definition, instance in VALID.items():
        yield f"fixture_valid_{definition}", definition, instance, None, ()
    for case in INVALID:
        yield f'fixture_invalid_{case["name"]}', case["definition"], case["instance"], case["keyword"], tuple(case["path"])
    nullable = {
        ("Hit", key) for key in ("frame_id", "observed_at_ms", "sequence_id", "sequence_position_ms")
    } | {("HistoryResponse", key) for key in ("timeline", "first_observed_ms", "last_observed_ms")}
    for definition, names in REQUIRED.items():
        for name in names.split():
            instance = deepcopy(VALID[definition])
            del instance[name]
            yield f"required_{definition}_{name}", definition, instance, "required", ()
            keyword = None if (definition, name) in nullable else "type"
            if name in {"contract_version", "interpretation"} or name == "kind" and "Timeline" in definition:
                keyword = "const"
            if name == "source_kind" or (definition, name) == ("Region", "kind"):
                keyword = "enum"
            if name == "query":
                keyword = "oneOf"
            yield f"null_{definition}_{name}", definition, mutated(definition, (name,), None), keyword, (name,)
        yield f"closed_{definition}", definition, {**VALID[definition], "future_field": 1}, "additionalProperties", ()
        for index, value in enumerate((None, [], 1, True, "object")):
            yield f"object_type_{definition}_{index}", definition, value, "type", ()
    for definition, fields in OPTIONAL.items():
        for field in fields.split():
            instance = deepcopy(VALID[definition])
            instance.pop(field, None)
            if field == "timeline":
                instance.pop("before_ms", None)
            yield f"optional_missing_{definition}_{field}", definition, instance, None, ()
            null_instance = mutated(definition, (field,), None)
            if field == "timeline":
                null_instance.pop("before_ms", None)
            yield (f"optional_null_{definition}_{field}", definition,
                   null_instance, None if field in {"timeline", "before_ms"} else "type", (field,))
            yield (f"optional_type_{definition}_{field}", definition,
                   mutated(definition, (field,), True), "oneOf" if field == "timeline" else "type", (field,))

    numeric = [
        ("Count", (), 0, 9007199254740991), ("Milliseconds", (), 0, 9007199254740991),
        *[(d, ("limit",), 1, 100) for d in ("SearchRequest", "HistoryRequest")],
        ("HistoryRequest", ("gap_ms",), 0, 3600000),
        ("HistoryRequest", ("before_ms",), 0, 9007199254740991),
        *[("Hit", (key,), 0, 9007199254740991) for key in ("observed_at_ms",)],
        *[("Observation", (key,), 0, 9007199254740991) for key in ("start_ms", "end_ms")],
        *[("Coverage", (key,), 0, 9007199254740991) for key in REQUIRED["Coverage"].split()],
    ]
    for definition, path, low, high in numeric:
        values = [(low, None), (high, None), (float(low), None), (low - 1, "minimum"), (high + 1, "maximum")]
        values += [(value, "type") for value in (1.5, True, False, "1", [], {})]
        for index, (value, keyword) in enumerate(values):
            yield f"integer_{definition}_{path}_{index}", definition, mutated(definition, path, value), keyword, path
    scores = [("Score", ()), ("SearchRequest", ("min_score",)), ("HistoryRequest", ("min_score",)), ("Hit", ("score",)), ("Observation", ("max_score",))]
    coordinates = [("Coordinate", ()), *[("Box", (i,)) for i in range(4)], *[("ImageQuery", ("box", i)) for i in range(4)], *[("Hit", ("region", "box", i)) for i in range(4)]]
    for definition, path in scores + coordinates:
        low = -1 if (definition, path) in scores else 0
        below = Decimal("-1.00000000000000001") if low == -1 else Decimal("-1e-400")
        values = [(low, None), (1, None), (Decimal("0.125"), None), (below, "minimum"), (Decimal("1.00000000000000001"), "maximum")]
        values += [(value, "type") for value in (True, False, None, "0.5", [], {})]
        for index, (value, keyword) in enumerate(values):
            yield f"float_{definition}_{path}_{index}", definition, mutated(definition, path, value), keyword, path
    for definition, path, high in TEXT_FIELDS:
        for size, keyword in ((0, "minLength"), (1, None), (high, None), (high + 1, "maxLength")):
            yield f"text_length_{definition}_{path}_{size}", definition, mutated(definition, path, "📷" * size), keyword, path
        for index, value in enumerate(("\0", "a\0b", "\ud800", "\udfff", "a\ud800\nb")):
            yield f"text_domain_{definition}_{path}_{index}", definition, mutated(definition, path, value), "pattern", path
    for definition, path, low in (("Box", (), 4), ("SearchResponse", ("hits",), 0), ("Observation", ("evidence",), 1), ("HistoryResponse", ("unsequenced_hits",), 0)):
        high = 4 if definition == "Box" else 100
        item = 0 if definition == "Box" else VALID["Hit"]
        for size in {0, 1, low, high, high + 1}:
            keyword = "minItems" if size < low else "maxItems" if size > high else None
            yield f"array_{definition}_{size}", definition, mutated(definition, path, [item] * size), keyword, path
    for definition in ("SearchRequest", "HistoryRequest"):
        for query in ({}, {"text": "x", "box": [0, 0, 1, 1]}, {"text": None}, {"asset_id": None}, {"asset_id": VALID["UUID"], "box": None}, {"asset_id": VALID["UUID"], "text": "x"}, {"text": "x", "source_uri": "private"}):
            yield f"union_{definition}_{query!r}", definition, mutated(definition, ("query",), query), "oneOf", ("query",)
        for before in (0, 9007199254740991):
            for timeline in (None, "missing"):
                instance = deepcopy(VALID[definition])
                instance["before_ms"] = before
                if timeline is None:
                    instance["timeline"] = None
                else:
                    instance.pop("timeline", None)
                yield f"cutoff_{definition}_{before}_{timeline}", definition, instance, "not" if timeline is None else "required", ("timeline",) if timeline is None else ()


class RetrievalTests(unittest.TestCase):
    def test_bundle_keeps_exact_ingestion_bytes_and_977_test_corpus(self):
        for path, expected in FROZEN.items():
            self.assertEqual(sha256((ROOT / path).read_bytes()).hexdigest(), expected)
        loader = unittest.TestLoader()
        count = sum(loader.discover(str(ROOT / "tests"), pattern=name).countTestCases() for name in ("test_contract.py", "test_json_interoperability.py"))
        self.assertEqual(count, 977)

    def test_versions_are_family_specific_and_all_refs_are_offline(self):
        self.assertEqual(BUNDLE_VERSION, "0.2.0")
        self.assertEqual({name: f["version"] for name, f in FAMILIES.items()}, {"ingestion": "0.1.0", "retrieval": "0.2.0"})
        self.assertEqual(len(CONTRACT.documents), 6)  # Four files, two unique schema IDs.
        self.assertEqual(set(VALID), set(CONTRACT.schema["$defs"]))
        self.assertEqual(len(INVALID), len({case["name"] for case in INVALID}))
        self.assertEqual(CONTRACT.openapi["info"]["version"], "0.2.0")
        self.assertEqual(CONTRACT.schema["$defs"]["ContractVersion"]["const"], "0.2.0")
        self.assertEqual(CONTRACT.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(CONTRACT.openapi["jsonSchemaDialect"], CONTRACT.schema["$schema"])
        self.assertEqual(CONTRACT.openapi["openapi"], "3.1.0")
        with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")):
            CONTRACT.validate_documents()
            for definition, value in VALID.items():
                validate(definition, value, CONTRACT)
        for uri in ("https://unregistered.example/schema", "file:///etc/passwd", "../../server/private.json"):
            with self.subTest(uri=uri), self.assertRaises(Exception):
                CONTRACT.resolve(uri)
        for definition in ("SearchResponse", "HistoryResponse"):
            assert_case(definition, {**VALID[definition], "contract_version": "0.1.0"}, "const", ("contract_version",))

    def test_mixed_or_duplicate_family_versions_fail(self):
        for family in FAMILIES:
            for artifact in ("schema", "openapi"):
                contract = Contract()
                schema, openapi = contract.families[family]
                with self.subTest(family=family, artifact=artifact):
                    if artifact == "schema":
                        schema["$defs"]["ContractVersion"]["const"] = "9.9.9"
                    else:
                        openapi["info"]["version"] = "9.9.9"
                    with self.assertRaisesRegex(ValueError, "wire-family"):
                        contract.validate_documents()
        def duplicate_id(path):
            value = read_json(path)
            if str(path).endswith("retrieval.schema.json"):
                value["$id"] = INGESTION.schema["$id"]
            return value
        with patch("tools.contract.read_json", side_effect=duplicate_id), self.assertRaisesRegex(ValueError, "Duplicate"):
            Contract()
        with patch("pathlib.Path.read_text", return_value="0.1.0"), self.assertRaisesRegex(ValueError, "bundle"):
            CONTRACT.validate_documents()
        with self.assertRaises(KeyError):
            Contract(family="private-ipc")

    def test_provenance_hashes_both_pairs_without_relabeling_ingestion(self):
        result = manifest("synthetic:memotrace", "0ebc2a87752e533f1fa50fd138b15b68546b4fcc", "unreleased-working-tree")
        self.assertEqual(result["bundle_version"], "0.2.0")
        self.assertEqual(result["wire_versions"], {"ingestion": "0.1.0", "retrieval": "0.2.0"})
        self.assertEqual(result["source_status"], "unreleased-working-tree")
        self.assertNotIn("contract_version", result)
        self.assertEqual(set(result["files"]), {"VERSION", "schemas/ingestion.schema.json", "openapi/ingestion.json", "schemas/retrieval.schema.json", "openapi/retrieval.json"})
        for path, digest in result["files"].items():
            self.assertEqual(digest, sha256((ROOT / path).read_bytes()).hexdigest())
        for revision, status in (("0ebc2a8", "unreleased-working-tree"), ("g" * 40, "committed"), ("0" * 40, "unknown")):
            with self.subTest(revision=revision, status=status), self.assertRaises(ValueError):
                manifest("synthetic:memotrace", revision, status)

    def test_field_policy_and_defaults(self):
        for definition, names in REQUIRED.items():
            schema = CONTRACT.schema["$defs"][definition]
            self.assertEqual(set(schema["required"]), set(names.split()))
            self.assertEqual(set(schema["properties"]), set(names.split()) | set(OPTIONAL.get(definition, "").split()))
        for path, node in walk(CONTRACT.schema):
            if isinstance(node, dict) and node.get("type") == "object":
                self.assertIs(node.get("additionalProperties"), False, path)
                self.assertIn(path[1], REQUIRED)
        for definition in ("SearchRequest", "HistoryRequest"):
            fields = CONTRACT.schema["$defs"][definition]["properties"]
            self.assertEqual(fields["limit"]["default"], 20)
            self.assertIsNone(fields["timeline"]["default"])
            self.assertEqual(fields.get("gap_ms", {}).get("default"), 30000 if definition == "HistoryRequest" else None)
            self.assertEqual(fields["min_score"].get("default"), -1 if definition == "SearchRequest" else None)

    def test_http_full_matrix_canonical_refs_media_headers_statuses(self):
        expected = {
            (SEARCH, "post"): ("SearchRequest", "SearchResponse", "200 400 401 404 405 413 415 503"),
            (HISTORY, "post"): ("HistoryRequest", "HistoryResponse", "200 400 401 404 405 413 415 503"),
            (ORIGINAL, "get"): (None, "binary", "200 400 401 404 405 409 503"),
        }
        error_codes = {"400": ["invalid_request"], "401": ["unauthorized"], "404": ["not_found", "invalid_request"], "405": ["invalid_request"], "409": ["integrity_error"], "413": ["payload_too_large"], "415": ["unsupported_media_type"], "503": ["unavailable"]}
        paths = CONTRACT.openapi["paths"]
        actual = {(path, method) for path, item in paths.items() for method in item if method != "parameters"}
        self.assertEqual(actual, set(expected))
        self.assertEqual(CONTRACT.openapi["security"], [{"deviceToken": []}])
        scheme_ref = CONTRACT.openapi["components"]["securitySchemes"]["deviceToken"]
        self.assertEqual(scheme_ref, {"$ref": "ingestion.json#/components/securitySchemes/deviceToken"})
        scheme = CONTRACT.dereference(scheme_ref)
        self.assertEqual(scheme, INGESTION.openapi["components"]["securitySchemes"]["deviceToken"])
        self.assertIn("case-insensitive", scheme["description"])
        self.assertIn("case-sensitive", scheme["description"])
        for (path, method), (request, response, statuses) in expected.items():
            operation = paths[path][method]
            self.assertEqual(operation.get("security", CONTRACT.openapi["security"]), [{"deviceToken": []}])
            params = [CONTRACT.dereference(p) for p in paths[path]["parameters"]]
            self.assertEqual({p["name"] for p in params}, {"archive_id", "asset_id"} if path == ORIGINAL else {"archive_id"})
            for param in params:
                self.assertEqual(param["in"], "path")
                self.assertIs(param["required"], True)
                self.assertEqual(param["schema"], {"$ref": "../schemas/ingestion.schema.json#/$defs/UUID"})
            if request:
                body = operation["requestBody"]
                self.assertIs(body["required"], True)
                self.assertEqual(body["x-max-bytes"], 1048576)
                self.check_content(body["content"], request)
            else:
                self.assertNotIn("requestBody", operation)
            self.assertEqual(set(operation["responses"]), set(statuses.split()))
            for status, ref in operation["responses"].items():
                result = CONTRACT.dereference(ref)
                self.check_content(result["content"], response if status == "200" else "Error")
                headers = result["headers"]
                required_headers = {"Cache-Control", "X-Content-Type-Options"}
                if status == "401":
                    required_headers.add("WWW-Authenticate")
                    self.assertEqual(headers["WWW-Authenticate"], {"$ref": "ingestion.json#/components/headers/BearerChallenge"})
                if status == "200" and path == ORIGINAL:
                    required_headers.add("Content-Length")
                    self.assertEqual(headers["Content-Length"]["schema"], {"$ref": "../schemas/ingestion.schema.json#/$defs/ByteLength"})
                    self.assertIs(headers["Content-Length"]["required"], True)
                self.assertEqual(set(headers), required_headers)
                for name, value in (("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"), ("WWW-Authenticate", 'Bearer realm="memotrace"')):
                    if name not in headers:
                        continue
                    header = CONTRACT.dereference(headers[name])
                    self.assertIs(header["required"], True)
                    self.assertEqual(header["schema"], {"type": "string", "const": value})
                    validator = CONTRACT.schema_validator(header["schema"])
                    validator.validate(value)
                    for wrong in (None, "", 'Basic realm="memotrace"', 'MemoTraceInvitation realm="memotrace-pairing"'):
                        with self.assertRaises(ValidationError):
                            validator.validate(wrong)
                if status != "200":
                    self.assertEqual(result["x-error-codes"], error_codes[status])
                    for code in result["x-error-codes"]:
                        self.assertIn(int(status), CONTRACT.openapi["x-error-statuses"][code])
                        error = {"error": {"code": code, "message": "Synthetic generic error.", "retryable": code == "unavailable"}}
                        INGESTION.validator("Error").validate(error)
                        error["error"]["retryable"] = not error["error"]["retryable"]
                        with self.assertRaises(ValidationError):
                            INGESTION.validator("Error").validate(error)
        codes = {code for values in error_codes.values() for code in values}
        self.assertEqual(CONTRACT.openapi["x-error-statuses"], {code: INGESTION.openapi["x-error-statuses"][code] for code in codes})

    def check_content(self, content, definition):
        self.assertEqual(set(content), {"image/jpeg" if definition == "binary" else "application/json"})
        schema = next(iter(content.values()))["schema"]
        if definition == "binary":
            self.assertEqual(schema, {"type": "string", "format": "binary"})
        else:
            family = "ingestion" if definition == "Error" else "retrieval"
            self.assertEqual(schema, {"$ref": f"../schemas/{family}.schema.json#/$defs/{definition}"})
            value = read_json(ROOT / "examples/valid.json")[definition] if definition == "Error" else VALID[definition]
            CONTRACT.schema_validator(schema, CONTRACT.openapi_uri).validate(value)

    def test_real_openapi_rejects_broken_document_and_discovers_every_schema(self):
        broken = deepcopy(CONTRACT.openapi)
        del broken["info"]["title"]
        with self.assertRaises(ValidationError):
            CONTRACT.validate_openapi(broken)
        old_valid = read_json(ROOT / "examples/valid.json")
        for _, node in walk(CONTRACT.openapi):
            if not isinstance(node, dict):
                continue
            if "$ref" in node and "/$defs/" in node["$ref"]:
                definition = node["$ref"].split("/$defs/")[1]
                value = old_valid[definition] if "ingestion.schema.json" in node["$ref"] else VALID[definition]
                CONTRACT.schema_validator(node, CONTRACT.openapi_uri).validate(value)
            if "schema" in node:
                validator = CONTRACT.schema_validator(node["schema"], CONTRACT.openapi_uri)
                if "example" in node:
                    validator.validate(node["example"])
                for example in node.get("examples", {}).values():
                    example = CONTRACT.dereference(example)
                    self.assertNotIn("externalValue", example)
                    validator.validate(example["value"])
        ids = [node["operationId"] for doc in (CONTRACT.openapi, INGESTION.openapi) for _, node in walk(doc) if isinstance(node, dict) and "operationId" in node]
        self.assertEqual(len(ids), len(set(ids)))

    def test_original_path_has_only_canonical_api_shape(self):
        good = VALID["OriginalPath"]
        for value in ("https://memotrace.example" + good, "/" + good, good + "/", good + "?x=1", good + "#x", good + "\n", good.replace("search/assets", "../assets"), good.replace("44444444", "AAAAAAAA"), good.replace("/search/", "/%73earch/"), good.replace("/original", "/original.jpg")):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                CONTRACT.validator("OriginalPath").validate(value)

    def test_shared_identifiers_remain_linked_at_each_public_field(self):
        fields = {
            "UUID": [("ImageQuery", ("asset_id",)), ("Hit", ("asset_id",)),
                     *[(d, ("archive_id",)) for d in ("SearchResponse", "HistoryResponse")]],
            "SHA256": [("Hit", ("sha256",)), *[(d, ("generation_id",)) for d in ("SearchRequest", "HistoryRequest", "SearchResponse", "HistoryResponse")]],
        }
        for primitive, places in fields.items():
            invalid = ("FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF", "0" * 32, "not-a-uuid", 1) if primitive == "UUID" else ("F" * 64, "g" * 64, "0" * 63, "0" * 65, 1)
            for definition, path in places:
                for wrong in invalid:
                    with self.subTest(definition=definition, path=path, wrong=wrong), self.assertRaises(ValidationError):
                        CONTRACT.validator(definition).validate(mutated(definition, path, wrong))
        frame = VALID["Observation"]["evidence"][0]
        for wrong in (None, "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF", "0" * 32, 1):
            with self.subTest(frame_id=wrong), self.assertRaises(ValidationError):
                CONTRACT.validator("Hit").validate({**frame, "frame_id": wrong})

    def test_timestamp_boolean_enum_and_nested_response_boundaries(self):
        timed_hit = VALID["Observation"]["evidence"][0]
        for field in ("observed_at_ms", "sequence_position_ms"):
            for value in (0, 9007199254740991, 1.0):
                CONTRACT.validator("Hit").validate({**timed_hit, field: value})
            for value in (-1, 9007199254740992, 0.5, True, "1", [], {}):
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    CONTRACT.validator("Hit").validate({**timed_hit, field: value})
        history = {**VALID["HistoryResponse"], "timeline": VALID["SequenceTimeline"], "history_available": True, "observations": [VALID["Observation"]], "first_observed_ms": 0, "last_observed_ms": 9007199254740991, "unsequenced_hits": []}
        CONTRACT.validator("HistoryResponse").validate(history)
        for field in ("first_observed_ms", "last_observed_ms"):
            for wrong in (-1, 9007199254740992, 0.5, True, "1", None):
                with self.subTest(field=field, value=wrong), self.assertRaises(ValidationError):
                    CONTRACT.validator("HistoryResponse").validate({**history, field: wrong})
        for definition, field in (("SearchResponse", "truncated"), ("HistoryResponse", "truncated"), ("HistoryResponse", "history_available")):
            for wrong in (0, 1, "false", [], {}):
                assert_case(definition, mutated(definition, (field,), wrong), "type", (field,))
        for definition, field in (("Region", "kind"), ("Hit", "source_kind")):
            for wrong in ("", "detected", 1, None):
                assert_case(definition, mutated(definition, (field,), wrong), "enum", (field,))
        for count in (0, 1, 100, 101):
            candidate = {**history, "observations": [VALID["Observation"]] * count}
            assert_case("HistoryResponse", candidate, "minItems" if count == 0 else "maxItems" if count > 100 else None, ("observations",))
        for bad_timeline in ({}, {"kind": "sequence"}, {"kind": "sequence", "sequence_id": None}, {"kind": "wall", "sequence_id": None}, {"kind": "WALL"}, []):
            assert_case("Timeline", bad_timeline, "oneOf")

    def test_semantic_comparisons_reject_schema_valid_counterexamples(self):
        cases = [("Box", [0.75, 0, 0.5, 1]), ("Box", [0, 0.5, 1, 0.5]),
                 ("ImageQuery", {"asset_id": VALID["UUID"], "box": [0, 0, 0, 1]}),
                 ("Hit", mutated("Hit", ("region", "box"), [1, 0, 0, 1])),
                 ("Coverage", {**VALID["Coverage"], "assets_total": 999}),
                 ("Coverage", {"assets_total": 1, "assets_indexed": 1, "pending": 0, "failed": 0, "regions_indexed": 0}),
                 ("Observation", {**VALID["Observation"], "end_ms": 0}),
                 ("Observation", {**VALID["Observation"], "max_score": -1}),
                 ("Hit", {**VALID["Hit"], "asset_id": "ffffffff-ffff-ffff-ffff-ffffffffffff"}),
                 ("HistoryResponse", {**VALID["HistoryResponse"], "archive_id": "ffffffff-ffff-ffff-ffff-ffffffffffff"}),
                 ("SearchResponse", {**VALID["SearchResponse"], "hits": [VALID["Hit"], VALID["Hit"]]})]
        for definition, value in cases:
            with self.subTest(definition=definition):
                CONTRACT.validator(definition).validate(value)
                with self.assertRaises(ValueError):
                    validate(definition, value, CONTRACT)
        for box in ([0, 0, 1, 1], [0.1, 0.2, 0.9, 0.8], [0, 0, Decimal("1e-400"), 1]):
            validate("Box", box, CONTRACT)

    def test_nonfinite_numbers_fail_even_in_memory_and_at_nested_fields(self):
        for value in (float("nan"), float("inf"), float("-inf"), Decimal("NaN"), Decimal("Infinity")):
            for definition, path in (("Score", ()), ("Box", (2,)), ("Hit", ("score",)), ("ImageQuery", ("box", 0))):
                with self.subTest(definition=definition, path=path), self.assertRaisesRegex(ValueError, "Non-finite"):
                    validate(definition, mutated(definition, path, value), CONTRACT)
        for raw in ('{"text":"x","text":"y"}', '{"text":"x","\\u0074ext":"y"}', '{"text":"\\ud800"}', '{"\\udfff":1}', '{"min_score":NaN}', '{}{}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_json(raw)
        for raw in (b'"\xff"', b'"\xed\xa0\x80"'):
            with self.assertRaises(UnicodeDecodeError):
                parse_json(raw)

    def test_history_unknown_time_and_source_coupling(self):
        for timeline in (None, VALID["WallTimeline"], VALID["SequenceTimeline"]):
            value = {**VALID["HistoryResponse"], "timeline": timeline}
            validate("HistoryResponse", value, CONTRACT)
            for key, wrong in (("history_available", True), ("first_observed_ms", 0), ("last_observed_ms", 0), ("observations", [VALID["Observation"]]), ("interpretation", "physical_identity")):
                with self.subTest(timeline=timeline, key=key), self.assertRaises(ValidationError):
                    CONTRACT.validator("HistoryResponse").validate({**value, key: wrong})
        for key, value in (("dataset", None), ("frame_id", VALID["UUID"]), ("sequence_position_ms", 0), ("sequence_id", "synthetic")):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                CONTRACT.validator("Hit").validate({**VALID["Hit"], key: value})
        frame = VALID["Observation"]["evidence"][0]
        validate("Hit", frame, CONTRACT)
        history = {**VALID["HistoryResponse"], "timeline": VALID["SequenceTimeline"], "history_available": True, "observations": [VALID["Observation"]], "unsequenced_hits": [], "first_observed_ms": 1000, "last_observed_ms": 1000}
        validate("HistoryResponse", history, CONTRACT)
        # Complete indexed bounds can lie outside selected evidence after Top-K.
        limited = {**history, "first_observed_ms": 0, "last_observed_ms": 9007199254740991, "truncated": True}
        validate("HistoryResponse", limited, CONTRACT)
        validate("HistoryResponse", {**limited, "observations": [], "unsequenced_hits": [VALID["Hit"]]}, CONTRACT)
        # The instance cannot establish whether these complete bounds, the cutoff,
        # max cosine, source exclusion, or indexed coverage are actually truthful.


def load_tests(loader, tests, pattern):
    names = set()
    for name, definition, instance, keyword, path in matrix_cases():
        if name in names:
            raise AssertionError(f"Duplicate retrieval matrix case: {name}")
        names.add(name)
        def check(definition=definition, instance=instance, keyword=keyword, path=path):
            assert_case(definition, instance, keyword, path)
        tests.addTest(unittest.FunctionTestCase(check, description="retrieval_" + name))
    for definition, path, _ in TEXT_FIELDS:
        for case in RAW["text"]:
            def check_text(definition=definition, path=path, case=case):
                raw = raw_document(mutated(definition, path, "RAW_PLACEHOLDER")).replace('"RAW_PLACEHOLDER"', case["json"])
                if case["outcome"] == "parse_error":
                    try:
                        parse_json(raw)
                    except ValueError as error:
                        str(error).encode("utf-8", errors="strict")
                        return
                    raise AssertionError("Invalid scalar JSON accepted")
                instance = parse_json(raw)
                assert_case(definition, instance, case.get("keyword"), path)
                if case["outcome"] == "valid":
                    actual = instance
                    for key in path:
                        actual = actual[key]
                    if actual != case["value"]:
                        raise AssertionError("Valid scalar text changed")
            tests.addTest(unittest.FunctionTestCase(check_text, description=f"retrieval_raw_text_{definition}_{path}_{case['name']}"))
    for definition, path in (("Milliseconds", ()), ("HistoryRequest", ("before_ms",)), ("Hit", ("observed_at_ms",)), ("Coverage", ("assets_total",)), ("Observation", ("start_ms",))):
        for case in RAW["numbers"]:
            def check_integer(definition=definition, path=path, case=case):
                raw = raw_document(mutated(definition, path, "RAW_PLACEHOLDER")).replace('"RAW_PLACEHOLDER"', case["json"])
                assert_case(definition, parse_json(raw), case.get("keyword"), path)
            tests.addTest(unittest.FunctionTestCase(check_integer, description=f"retrieval_raw_integer_{definition}_{path}_{case['name']}"))
    for definition, path in (("Score", ()), ("SearchRequest", ("min_score",)), ("HistoryRequest", ("min_score",)), ("Hit", ("score",))):
        for literal, keyword in (("-1.00000000000000001", "minimum"), ("1.00000000000000001", "maximum"), ("1e-400", None), ("-1e-400", None), ("0.125", None), ("1e400", "maximum")):
            def check_score(definition=definition, path=path, literal=literal, keyword=keyword):
                raw = raw_document(mutated(definition, path, "RAW_PLACEHOLDER")).replace('"RAW_PLACEHOLDER"', literal)
                assert_case(definition, parse_json(raw), keyword, path)
            tests.addTest(unittest.FunctionTestCase(check_score, description=f"retrieval_raw_score_{definition}_{path}_{literal}"))
    return tests
