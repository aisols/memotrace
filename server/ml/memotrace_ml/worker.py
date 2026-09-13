"""Bounded private JSONL inference. Stdout is exclusively protocol responses."""

import argparse
import base64
import binascii
import math
import sys
from pathlib import Path
from typing import BinaryIO

from memotrace_ml.common import JSON, canonical, object_value, parse_json, string_value
from memotrace_ml.images import (
    MAX_IMAGE_BYTES,
    Mode,
    Policy,
    decode_jpeg,
    query_crop,
    validate_box,
)
from memotrace_ml.model import Encoder, SiglipEncoder, UnsupportedText

MAX_LINE = 24 * 1024 * 1024
MAX_OUTPUT = 2 * 1024 * 1024


class InvalidRequest(ValueError):
    pass


class InputFailed(RuntimeError):
    pass


def validate_text(text: str) -> str:
    if not 1 <= len(text) <= 2048 or any(
        ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F or 0xD800 <= ord(char) <= 0xDFFF
        for char in text
    ):
        raise ValueError("invalid text")
    return text


def validated_vector(vector: list[float], dimension: int) -> list[JSON]:
    if len(vector) != dimension or not all(math.isfinite(x) for x in vector):
        raise ValueError("invalid embedding")
    if abs(math.sqrt(sum(x * x for x in vector)) - 1) > 1e-4:
        raise ValueError("invalid embedding norm")
    return [*vector]


class Worker:
    def __init__(self, encoder: Encoder, policy: Policy) -> None:
        self.encoder = encoder
        self.policy = policy

    def describe(self) -> dict[str, JSON]:
        return {
            "model_fingerprint": self.encoder.model_fingerprint,
            "dimension": self.encoder.dimension,
            "model_id": self.encoder.model_id,
            "model_revision": self.encoder.model_revision,
            "input_resolution": self.encoder.input_resolution,
            "preprocessing_version": self.encoder.preprocessing_version,
            "policies": {
                "full": self.policy.fingerprint("full"),
                "overlap": self.policy.fingerprint("overlap"),
            },
        }

    def handle(self, request: dict[str, JSON]) -> dict[str, JSON]:
        try:
            op = string_value(request.get("op"))
        except ValueError as error:
            raise InvalidRequest("invalid operation") from error
        fields = {
            "describe": {"id", "op"},
            "text": {"id", "op", "text"},
            "image": {"id", "op", "image_base64", "mode"},
            "query_image": {"id", "op", "image_base64", "box"},
        }
        if op not in fields or request.keys() - fields[op]:
            raise InvalidRequest("invalid operation")
        if op == "describe":
            return self.describe()
        result: dict[str, JSON] = {"model_fingerprint": self.encoder.model_fingerprint}
        if op == "text":
            try:
                text = validate_text(string_value(request.get("text")))
            except ValueError as error:
                raise InvalidRequest("invalid text") from error
            try:
                vector = self.encoder.text(text)
            except UnsupportedText as error:
                raise InvalidRequest("invalid text") from error
            result["embedding"] = validated_vector(vector, self.encoder.dimension)
            return result
        try:
            encoded = string_value(request.get("image_base64"))
        except ValueError as error:
            raise InvalidRequest("invalid image") from error
        if len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
            raise InvalidRequest("image too large")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise InvalidRequest("invalid image") from error
        try:
            image = decode_jpeg(data)
        except (OSError, ValueError) as error:
            # The synchronized worker remains healthy; the specific input did not decode.
            raise InputFailed("original image decode failed") from error
        if op == "query_image":
            if "box" in request:
                try:
                    image = query_crop(image, validate_box(request["box"]))
                except ValueError as error:
                    raise InvalidRequest("invalid box") from error
            result["embedding"] = validated_vector(
                self.encoder.images([image])[0], self.encoder.dimension
            )
            return result
        mode: Mode
        if request.get("mode") == "full":
            mode = "full"
        elif request.get("mode") == "overlap":
            mode = "overlap"
        else:
            raise InvalidRequest("invalid mode")
        try:
            regions = self.policy.regions(*image.size, mode)
        except ValueError as error:
            raise InvalidRequest("invalid image geometry") from error
        # Retain only model-sized letterboxes for all crops, not 64 large JPEGs.
        # The encoder letterboxes again, and the already-square resize is an identity.
        from memotrace_ml.images import letterbox

        embeddings = self.encoder.images(
            [letterbox(image.crop(r.pixels), self.encoder.input_resolution) for r in regions]
        )
        if len(embeddings) != len(regions):
            raise ValueError("invalid region output")
        vectors: list[JSON] = [
            {
                "kind": region.kind,
                "box": region.box(*image.size),
                "embedding": validated_vector(embedding, self.encoder.dimension),
            }
            for region, embedding in zip(regions, embeddings, strict=True)
        ]
        result.update(
            policy_fingerprint=self.policy.fingerprint(mode),
            width=image.width,
            height=image.height,
            vectors=vectors,
        )
        return result

    def response(self, raw: bytes) -> bytes:
        request_id = ""
        try:
            request = object_value(parse_json(raw, exact_numbers=True))
            request_id = string_value(request.get("id"))
            if not 1 <= len(request_id) <= 128 or any(ord(c) < 32 for c in request_id):
                request_id = ""
                raise InvalidRequest("invalid id")
        except (ValueError, TypeError, RecursionError):
            return canonical({"id": request_id, "ok": False, "error": "invalid_request"}) + b"\n"
        try:
            result = {"id": request_id, "ok": True, **self.handle(request)}
            encoded = canonical(result)
            if len(encoded) + 1 > MAX_OUTPUT:
                raise RuntimeError("output limit")
            return encoded + b"\n"
        except InputFailed:
            return canonical({"id": request_id, "ok": False, "error": "input_failed"}) + b"\n"
        except InvalidRequest:
            return canonical({"id": request_id, "ok": False, "error": "invalid_request"}) + b"\n"
        except Exception:
            # No query, decoded image metadata, filesystem path, or traceback leaks.
            return canonical({"id": request_id, "ok": False, "error": "inference_failed"}) + b"\n"


def serve(worker: Worker, source: BinaryIO, destination: BinaryIO) -> None:
    while raw := source.readline(MAX_LINE + 1):
        if len(raw) > MAX_LINE or not raw.endswith(b"\n"):
            destination.write(
                canonical({"id": "", "ok": False, "error": "invalid_request"}) + b"\n"
            )
            destination.flush()
            return  # Do not consume an unbounded remainder or desynchronize requests.
        destination.write(worker.response(raw))
        destination.flush()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--model-dir", required=True, type=Path)
    result.add_argument("--threads", type=int, default=4)
    result.add_argument("--batch-size", type=int, default=2)
    result.add_argument("--min-side-fraction", type=float, default=0.75)
    result.add_argument("--overlap", type=float, default=0.25)
    return result


def main() -> None:
    args = parser().parse_args()
    try:
        policy = Policy(args.min_side_fraction, args.overlap)
        encoder = SiglipEncoder(args.model_dir, args.threads, args.batch_size)
    except Exception:
        print("model initialization failed; verify local artifacts and runtime", file=sys.stderr)
        raise SystemExit(1) from None
    serve(Worker(encoder, policy), sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    main()
