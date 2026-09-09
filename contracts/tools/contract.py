"""Real validators and a closed, component-local reference registry.

SPDX-License-Identifier: AGPL-3.0-only
"""

import json
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema_path import SchemaPath
from openapi_spec_validator import OpenAPIV31SpecValidator
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = "schemas/ingestion.schema.json"
OPENAPI_PATH = "openapi/ingestion.json"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON property")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"Non-JSON numeric constant: {value}")


def _exact_decimal(value):
    number = Decimal(value)
    # Decimal construction and this equality do not round through binary float
    # or the decimal context's precision. jsonschema recognizes nonintegral
    # Decimals as numbers, while genuinely integral values use its native ints.
    return int(number) if number == number.to_integral_value() else number


def _check_scalar_strings(value):
    if isinstance(value, str):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            # Never include rejected text in a diagnostic: it may not encode as UTF-8.
            raise ValueError("JSON strings must contain Unicode scalar values")
    elif isinstance(value, dict):
        for key, child in value.items():
            _check_scalar_strings(key)
            _check_scalar_strings(child)
    elif isinstance(value, list):
        for child in value:
            _check_scalar_strings(child)


def parse_json(text):
    """Lossless JSON parsing; schema validation separately enforces field rules.

    Python's decoder combines valid escaped surrogate pairs and preserves lone
    surrogates, which we reject before any UTF-8 encoding or lossy conversion.
    NUL is syntactically JSON: the user-text schema patterns reject it.
    """
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="strict")
    value = json.loads(
        text,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
        parse_float=_exact_decimal,
    )
    _check_scalar_strings(value)
    return value


def read_json(path):
    return parse_json(Path(path).read_text(encoding="utf-8", errors="strict"))


def walk(value, path=()):
    """Discover nodes, including refs/examples in newly added definitions."""
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, (*path, index))


class Contract:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.schema_uri = (self.root / SCHEMA_PATH).as_uri()
        self.openapi_uri = (self.root / OPENAPI_PATH).as_uri()
        self.schema = read_json(self.root / SCHEMA_PATH)
        self.openapi = read_json(self.root / OPENAPI_PATH)
        self.documents = {
            self.schema_uri: self.schema,
            self.schema["$id"]: self.schema,
            self.openapi_uri: self.openapi,
        }
        self.registry = Registry(retrieve=self._deny_retrieval).with_resources(
            (uri, Resource.from_contents(doc, default_specification=DRAFT202012))
            for uri, doc in self.documents.items()
        )
        self.formats = FormatChecker()

    @staticmethod
    def _deny_retrieval(uri):
        raise NoSuchResource(ref=uri)

    def _document(self, uri):
        # Never fall back to file/HTTP loading, including in OpenAPI's resolver.
        if uri not in self.documents:
            raise NoSuchResource(ref=uri)
        return self.documents[uri]

    def validator(self, definition):
        if definition not in self.schema["$defs"]:
            raise KeyError(definition)
        return self.schema_validator(
            {"$ref": f'{self.schema["$id"]}#/$defs/{definition}'}
        )

    def schema_validator(self, schema, base_uri=None):
        return Draft202012Validator(
            {"$id": base_uri or self.schema_uri, **schema},
            registry=self.registry,
            format_checker=self.formats,
        )

    def resolve(self, ref, base_uri=None):
        return self.registry.resolver(base_uri or self.openapi_uri).lookup(ref).contents

    def dereference(self, value):
        while isinstance(value, dict) and "$ref" in value:
            value = self.resolve(value["$ref"])
        return value

    def validate_openapi(self, document=None):
        path = SchemaPath.from_dict(
            self.openapi if document is None else document,
            base_uri=self.openapi_uri,
            handlers={scheme: self._document for scheme in ("file", "https", "http")},
        )
        OpenAPIV31SpecValidator(path).validate()

    def validate_documents(self):
        Draft202012Validator.check_schema(self.schema)
        for definition in self.schema["$defs"].values():
            Draft202012Validator.check_schema(definition)
        for uri, document in (
            (self.schema_uri, self.schema),
            (self.openapi_uri, self.openapi),
        ):
            for _, node in walk(document):
                if isinstance(node, dict) and "$ref" in node:
                    self.resolve(node["$ref"], uri)
        self.validate_openapi()
