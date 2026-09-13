"""A deliberately test-only fake encoder checks IPC, never model quality."""

import base64
import io
import math

import pytest
from PIL import Image

from memotrace_ml.common import JSON, canonical, list_value, object_value, parse_json
from memotrace_ml.images import Policy
from memotrace_ml.model import UnsupportedText
from memotrace_ml.worker import MAX_OUTPUT, Worker, serve


class TestOnlyEncoder:
    __test__ = False
    model_fingerprint = "a" * 64
    model_id = "test-only/synthetic"
    model_revision = "test-only"
    dimension = 3
    input_resolution = 224
    preprocessing_version = "test-letterbox-224"

    def images(self, images: list[Image.Image]) -> list[list[float]]:
        assert all(image.size == (224, 224) for image in images)
        return [[1.0, 0.0, 0.0] for _ in images]

    def text(self, text: str) -> list[float]:
        return [0.0, 1.0, 0.0]


def request_image() -> dict[str, JSON]:
    buffer = io.BytesIO()
    Image.new("RGB", (160, 90), "red").save(buffer, format="JPEG")
    return {
        "id": "synthetic",
        "op": "image",
        "mode": "overlap",
        "image_base64": base64.b64encode(buffer.getvalue()).decode(),
    }


def test_ipc_describe_image_and_unicode() -> None:
    worker = Worker(TestOnlyEncoder(), Policy())
    requests: list[JSON] = [
        {"id": "describe", "op": "describe"},
        request_image(),
        {"id": "ru", "op": "text", "text": "отвёртка"},
    ]
    out = io.BytesIO()
    serve(worker, io.BytesIO(b"\n".join(canonical(r) for r in requests) + b"\n"), out)
    described, image, text = [
        object_value(parse_json(line)) for line in out.getvalue().splitlines()
    ]
    assert described["id"] == "describe" and described["ok"] is True
    assert described["input_resolution"] == 224
    assert described["preprocessing_version"] == "test-letterbox-224"
    assert object_value(described["policies"])["overlap"] == image["policy_fingerprint"]
    assert image["width"] == 160 and image["height"] == 90
    assert isinstance(image["vectors"], list) and len(image["vectors"]) == 7
    assert text["embedding"] == [0.0, 1.0, 0.0]


@pytest.mark.parametrize(
    "raw",
    [
        b'{"id":"x","op":"describe","op":"text"}',
        b'{"id":"x","op":"describe","extra":1}',
        b'{"id":"x","op":"query_image","box":[0,0,NaN,1]}',
        b'{"id":"x","op":"image","image_base64":"%%%%","mode":"full"}',
        b'{"id":"x","op":"text","text":null}',
        b"[]",
        b"null",
        b"{",
        b'{"id":1,"op":"describe"}',
        b'{"id":"x","op":"sql"}',
    ],
)
def test_invalid_requests_recover_without_traceback(raw: bytes) -> None:
    worker = Worker(TestOnlyEncoder(), Policy())
    response = object_value(parse_json(worker.response(raw)))
    assert response["ok"] is False and response["error"] == "invalid_request"
    assert object_value(parse_json(worker.response(b'{"id":"next","op":"describe"}')))["ok"]


def test_text_limit_before_encoder() -> None:
    worker = Worker(TestOnlyEncoder(), Policy())
    response = worker.response(canonical({"id": "x", "op": "text", "text": "x" * 2049}))
    assert object_value(parse_json(response))["ok"] is False


def test_over_tokenized_text_is_invalid_and_worker_recovers() -> None:
    class TokenLimitedEncoder(TestOnlyEncoder):
        def text(self, text: str) -> list[float]:
            if len(text.split()) > 64:
                raise UnsupportedText("synthetic tokenizer limit")
            return super().text(text)

    worker = Worker(TokenLimitedEncoder(), Policy())
    rejected = object_value(
        parse_json(worker.response(canonical({"id": "long", "op": "text", "text": "x " * 65})))
    )
    recovered = object_value(parse_json(worker.response(b'{"id":"next","op":"describe"}')))
    assert rejected == {"id": "long", "ok": False, "error": "invalid_request"}
    assert recovered["id"] == "next" and recovered["ok"] is True


@pytest.mark.parametrize("control", ["\x00", "\x1f", "\x7f", "\x80", "\x9f", "\ud800"])
def test_all_unicode_controls_and_surrogates_fail_at_worker_boundary(control: str) -> None:
    calls: list[str] = []

    class TextProbeEncoder(TestOnlyEncoder):
        def text(self, text: str) -> list[float]:
            calls.append(text)
            return super().text(text)

    response = Worker(TextProbeEncoder(), Policy()).response(
        canonical({"id": "x", "op": "text", "text": "visible" + control})
    )
    assert object_value(parse_json(response))["error"] == "invalid_request"
    assert calls == []


def test_jpeg_decode_failure_is_input_failed_before_encoder_and_recovers() -> None:
    calls: list[tuple[int, int]] = []

    class ImageProbeEncoder(TestOnlyEncoder):
        def images(self, images: list[Image.Image]) -> list[list[float]]:
            calls.extend(image.size for image in images)
            return super().images(images)

    worker = Worker(ImageProbeEncoder(), Policy())
    rejected = object_value(
        parse_json(
            worker.response(
                canonical(
                    {
                        "id": "bad-jpeg",
                        "op": "query_image",
                        "image_base64": base64.b64encode(b"invalid JPEG").decode(),
                    }
                )
            )
        )
    )
    recovered = object_value(parse_json(worker.response(b'{"id":"next","op":"describe"}')))
    assert rejected == {"id": "bad-jpeg", "ok": False, "error": "input_failed"}
    assert calls == []
    assert recovered["id"] == "next" and recovered["ok"] is True


def test_oversized_line_closes_without_resynchronizing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("memotrace_ml.worker.MAX_LINE", 64)
    out = io.BytesIO()
    serve(Worker(TestOnlyEncoder(), Policy()), io.BytesIO(b"x" * 65 + b"\n{}\n"), out)
    assert len(out.getvalue().splitlines()) == 1
    assert object_value(parse_json(out.getvalue()))["ok"] is False


def test_partial_line_closes() -> None:
    out = io.BytesIO()
    serve(Worker(TestOnlyEncoder(), Policy()), io.BytesIO(b'{"id":"x","op":"describe"}'), out)
    assert object_value(parse_json(out.getvalue()))["ok"] is False


def test_nonfinite_encoder_rejected() -> None:
    class InvalidTestEncoder(TestOnlyEncoder):
        def text(self, text: str) -> list[float]:
            return [math.nan, 0.0, 0.0]

    response = Worker(InvalidTestEncoder(), Policy()).response(
        b'{"id":"x","op":"text","text":"hi"}'
    )
    assert object_value(parse_json(response))["error"] == "inference_failed"


def test_exceptions_do_not_leak_sensitive_messages() -> None:
    class FailingTestEncoder(TestOnlyEncoder):
        def text(self, text: str) -> list[float]:
            raise RuntimeError("sensitive query or filesystem path")

    raw = Worker(FailingTestEncoder(), Policy()).response(b'{"id":"x","op":"text","text":"hi"}')
    assert b"sensitive" not in raw
    assert object_value(parse_json(raw))["error"] == "inference_failed"


def test_near_request_limit_significand_reaches_encoder_with_exact_crop() -> None:
    sizes: list[tuple[int, int]] = []

    class CropProbeEncoder(TestOnlyEncoder):
        def images(self, images: list[Image.Image]) -> list[list[float]]:
            sizes.extend(image.size for image in images)
            return [[1.0, 0.0, 0.0] for _ in images]

    buffer = io.BytesIO()
    Image.new("RGB", (4, 3), "red").save(buffer, format="JPEG")
    encoded = base64.b64encode(buffer.getvalue()).decode()
    raw = (
        b'{"id":"long-significand","op":"query_image","image_base64":'
        + canonical(encoded)
        + b',"box":[0.5,0,0.5'
        + b"0" * 1_000_000
        + b"1,1]}"
    )
    assert len(raw) < 1024 * 1024
    response = object_value(parse_json(Worker(CropProbeEncoder(), Policy()).response(raw)))
    assert response["ok"] is True and sizes == [(1, 3)]


def test_worker_uses_encoder_resolution_and_preprocessing_version() -> None:
    sizes: list[tuple[int, int]] = []

    class ResolutionProbeEncoder(TestOnlyEncoder):
        input_resolution = 384
        preprocessing_version = "test-letterbox-384"

        def images(self, images: list[Image.Image]) -> list[list[float]]:
            sizes.extend(image.size for image in images)
            return [[1.0, 0.0, 0.0] for _ in images]

    worker = Worker(ResolutionProbeEncoder(), Policy())
    result = worker.handle(request_image())
    assert len(list_value(result["vectors"])) == 7
    assert sizes == [(384, 384)] * 7
    assert worker.describe()["input_resolution"] == 384
    assert worker.describe()["preprocessing_version"] == "test-letterbox-384"


def test_max_regions_so400m_response_fits_protocol_ceiling() -> None:
    class LargeEncoder(TestOnlyEncoder):
        dimension = 1152
        input_resolution = 384
        preprocessing_version = "test-letterbox-384"

        def images(self, images: list[Image.Image]) -> list[list[float]]:
            assert len(images) == 64
            component = 1 / math.sqrt(self.dimension)
            return [[component] * self.dimension for _ in images]

    buffer = io.BytesIO()
    Image.new("RGB", (63, 1), "red").save(buffer, format="JPEG")
    request: dict[str, JSON] = {
        "id": "so400m-ceiling",
        "op": "image",
        "mode": "overlap",
        "image_base64": base64.b64encode(buffer.getvalue()).decode(),
    }
    response = Worker(LargeEncoder(), Policy()).response(canonical(request))
    assert len(response) <= MAX_OUTPUT
    parsed = object_value(parse_json(response))
    assert parsed["ok"] is True
    assert isinstance(parsed["vectors"], list) and len(parsed["vectors"]) == 64
