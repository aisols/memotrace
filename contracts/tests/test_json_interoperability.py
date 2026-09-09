"""Raw JSON regressions: preserve information before genuine schema validation.

SPDX-License-Identifier: AGPL-3.0-only
"""

from copy import deepcopy
from decimal import Decimal, localcontext
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

from tools.contract import Contract, ROOT, parse_json, read_json

CONTRACT = Contract()
VALID = read_json(ROOT / "examples/valid.json")
RAW = read_json(ROOT / "examples/raw-json.json")
TEXT_FIELDS = (
    ("PairRequest", ("device_name",)),
    ("Profile", ("id",)),
    ("FrameMetadata", ("capture_settings",)),
    ("FrameMetadata", ("profile", "id")),
    ("ManifestRequest", ("frames", 0, "capture_settings")),
)


def raw_field_document(definition, path, literal):
    document = deepcopy(VALID[definition])
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = "RAW_JSON_TEST_PLACEHOLDER"
    # Escape Python strings first. Only the raw fixture literal is inserted;
    # malformed surrogate escapes never pass through a UTF-8 encoder as text.
    return json.dumps(document).replace('"RAW_JSON_TEST_PLACEHOLDER"', literal)


def field_value(document, path):
    for key in path:
        document = document[key]
    return document


def keyword_error(definition, instance, keyword, path):
    def descend(errors):
        for error in errors:
            yield error
            yield from descend(error.context)

    errors = descend(CONTRACT.validator(definition).iter_errors(instance))
    if not any(e.validator == keyword and tuple(e.absolute_path) == path for e in errors):
        raise AssertionError(f"Expected {keyword} at {definition}.{path!r}")


class JSONInteroperabilityTests(unittest.TestCase):
    def test_read_json_uses_exact_parser_under_low_decimal_precision(self):
        # Exercise the public file reader, not just an alternate test decoder.
        with localcontext() as context:
            context.prec = 2
            for case in RAW["numbers"]:
                with self.subTest(name=case["name"]):
                    with patch.object(Path, "read_text", return_value=case["json"]):
                        value = read_json(ROOT / "synthetic-raw-input.json")
                    self.assertEqual(value, parse_json(case["json"]))
                    self.assertEqual(Decimal(value), Decimal(case["json"]))

    def test_read_json_rejects_unpaired_surrogates_and_duplicates(self):
        for case in RAW["invalid_documents"]:
            with self.subTest(name=case["name"]):
                with patch.object(Path, "read_text", return_value=case["json"]):
                    with self.assertRaises(ValueError) as error:
                        read_json(ROOT / "synthetic-raw-input.json")
                str(error.exception).encode("utf-8", errors="strict")

    def test_utf8_decoding_is_strict(self):
        for raw in (b'"\xff"', b'"\xed\xa0\x80"', b'"\xc0\x80"', b'"\xf0\x9f"'):
            with self.subTest(raw=raw), self.assertRaises(UnicodeDecodeError):
                parse_json(raw)

    def test_property_names_preserve_valid_scalars_before_closed_schema_rejects(self):
        for literal, expected in ((r'"\ud83d\udcf7"', "📷"), (r'"\ufffd"', "�")):
            instance = parse_json("{" + literal + ":1}")
            self.assertEqual(list(instance), [expected])
            keyword_error("PairRequest", instance, "additionalProperties", ())

    def test_genuine_replacement_and_escaped_pair_are_lossless(self):
        literal = parse_json('"📷�"'.encode("utf-8"))
        escaped = parse_json(r'"\ud83d\udcf7\ufffd"')
        self.assertEqual(literal, escaped)
        self.assertEqual(literal.encode("utf-8"), bytes.fromhex("f09f93b7efbfbd"))

    def test_raw_fixture_names_are_unique(self):
        for cases in RAW.values():
            self.assertEqual(len(cases), len({case["name"] for case in cases}))


def load_tests(loader, tests, pattern):
    for case in RAW["numbers"]:
        def number_check(case=case):
            value = parse_json(case["json"])
            Draft202012Validator({"type": "number"}).validate(value)
            if case.get("keyword") == "type":
                if not isinstance(value, Decimal) or value != Decimal(case["json"]):
                    raise AssertionError("Nonintegral decimal lost its exact numeric value")
            elif type(value) is not int:
                raise AssertionError("Genuinely integral decimal must normalize to int")
            if "keyword" in case:
                keyword_error("Milliseconds", value, case["keyword"], ())
            else:
                CONTRACT.validator("Milliseconds").validate(value)
                if value != case["value"]:
                    raise AssertionError("Integral value changed")
            # The same raw lexeme must keep its meaning when nested in a request.
            document = parse_json(raw_field_document("FrameMetadata", ("request_wall_ms",), case["json"]))
            if "keyword" in case:
                keyword_error("FrameMetadata", document, case["keyword"], ("request_wall_ms",))
            else:
                CONTRACT.validator("FrameMetadata").validate(document)

        tests.addTest(unittest.FunctionTestCase(number_check, description=f'raw_number_{case["name"]}'))

    for definition, path in TEXT_FIELDS:
        for case in RAW["text"]:
            def text_check(definition=definition, path=path, case=case):
                raw = raw_field_document(definition, path, case["json"])
                if case["outcome"] == "parse_error":
                    try:
                        parse_json(raw)
                    except ValueError as error:
                        str(error).encode("utf-8", errors="strict")
                        return
                    raise AssertionError("Invalid scalar text was silently accepted")
                instance = parse_json(raw)
                if case["outcome"] == "schema_error":
                    keyword_error(definition, instance, case["keyword"], path)
                else:
                    CONTRACT.validator(definition).validate(instance)
                    actual = field_value(instance, path)
                    if actual != case["value"] or actual.encode("utf-8") != case["value"].encode("utf-8"):
                        raise AssertionError("Scalar text changed")

            tests.addTest(unittest.FunctionTestCase(text_check, description=f'raw_text_{definition}_{path}_{case["name"]}'))

    for case in RAW["invalid_documents"]:
        def document_check(case=case):
            try:
                parse_json(case["json"])
            except ValueError as error:
                str(error).encode("utf-8", errors="strict")
                return
            raise AssertionError("Malformed raw JSON was silently accepted")

        tests.addTest(unittest.FunctionTestCase(document_check, description=f'raw_document_{case["name"]}'))
    return tests
