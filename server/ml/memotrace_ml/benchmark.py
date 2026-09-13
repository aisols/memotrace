"""Explicit real-weight retrieval pilot. No model/data acquisition in this command."""

import argparse
import base64
import hashlib
import os
import platform
import resource
import statistics
import time
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from memotrace_ml.artifacts import read_bytes
from memotrace_ml.common import (
    JSON,
    external_root,
    file_digest,
    list_value,
    object_value,
    read_json,
    string_value,
    write_json,
)
from memotrace_ml.dataset import Item
from memotrace_ml.images import Mode, Policy
from memotrace_ml.model import SiglipEncoder, validate_runtime_bounds
from memotrace_ml.openimages import CLASS_PROFILE, verified_acquisition
from memotrace_ml.worker import Worker

QUERIES = {
    "/m/01bms0": {"en": "a photo of a screwdriver", "ru": "фотография отвёртки"},
    "/m/01lsmm": {"en": "a photo of scissors", "ru": "фотография ножниц"},
    "/m/03l9g": {"en": "a photo of a hammer", "ru": "фотография молотка"},
    "/m/04ctx": {"en": "a photo of a knife", "ru": "фотография ножа"},
    "/m/0k1tl": {"en": "a photo of a pen", "ru": "фотография ручки"},
    "/m/04dr76w": {"en": "a photo of a bottle", "ru": "фотография бутылки"},
    "/m/02jvh9": {"en": "a photo of a mug", "ru": "фотография кружки"},
    "/m/050k8": {
        "en": "a photo of a mobile phone",
        "ru": "фотография мобильного телефона",
    },
}
RRF_K = 60
REPORT_VERSION = "openimages-retrieval-pilot-v3"
type TimedRanking = tuple[list[tuple[str, float]], float, float]


def validate_query_profile(ground_truth: dict[str, JSON]) -> None:
    profile_mids = tuple(mid for _, mid in CLASS_PROFILE)
    if tuple(QUERIES) != profile_mids or set(QUERIES) != set(ground_truth):
        raise ValueError("benchmark query profile mismatch")


def reciprocal_rank_fusion(first: list[str], second: list[str]) -> list[tuple[str, float]]:
    """Fuse exactly two complete rankings with fixed RRF k=60."""
    if len(set(first)) != len(first) or len(set(second)) != len(second):
        raise ValueError("duplicate asset in fusion ranking")
    if set(first) != set(second):
        raise ValueError("fusion candidate sets differ")
    first_ranks = {identity: rank for rank, identity in enumerate(first, 1)}
    second_ranks = {identity: rank for rank, identity in enumerate(second, 1)}
    scores = [
        (identity, 1 / (RRF_K + first_ranks[identity]) + 1 / (RRF_K + second_ranks[identity]))
        for identity in first
    ]
    return sorted(scores, key=lambda pair: (-pair[1], pair[0]))


def language_query_description(mid: str, language: str, text: str) -> dict[str, JSON]:
    if language not in {"en", "ru"}:
        raise ValueError("invalid evaluation language")
    return {
        "kind": "text",
        "language": language,
        "text": text,
        "paired_query_id": mid + (":ru" if language == "en" else ":en"),
        "pair_role": (
            "manually_curated_english_evaluation_translation"
            if language == "en"
            else "manually_curated_russian_evaluation_query"
        ),
        "automatic_translation": False,
    }


def language_evaluation_metadata() -> dict[str, JSON]:
    return {
        "version": "curated-ru-en-rrf-v1",
        "query_groups": ["en", "ru", "fusion"],
        "english_provenance": "manually_curated_evaluation_translation",
        "automatic_translation": False,
        "fusion": {"method": "reciprocal_rank_fusion", "k": RRF_K},
    }


def fusion_query_result(
    mid: str,
    mode: str,
    judgments: dict[str, JSON],
    english: TimedRanking,
    russian: TimedRanking,
) -> dict[str, JSON]:
    english_ranking, english_embedding_seconds, english_ranking_seconds = english
    russian_ranking, russian_embedding_seconds, russian_ranking_seconds = russian
    component_query_ids: list[JSON] = [mid + ":en", mid + ":ru"]
    started = time.monotonic()
    fused = reciprocal_rank_fusion(
        [identity for identity, _ in english_ranking],
        [identity for identity, _ in russian_ranking],
    )
    fusion_seconds = time.monotonic() - started
    component_seconds = (
        english_embedding_seconds
        + russian_embedding_seconds
        + english_ranking_seconds
        + russian_ranking_seconds
    )
    return {
        "query_id": mid + ":fusion",
        "class": mid,
        "mode": mode,
        "source_id_excluded": None,
        "source_sha256_excluded": None,
        "source_aliases_excluded": 0,
        "query": {
            "kind": "ranking_fusion",
            "method": "reciprocal_rank_fusion",
            "k": RRF_K,
            "component_query_ids": component_query_ids,
            "automatic_translation": False,
        },
        "ranking_score_kind": "rrf",
        "timing": {
            "components_reused": True,
            "component_embedding_seconds": {
                "en": english_embedding_seconds,
                "ru": russian_embedding_seconds,
            },
            "component_ranking_seconds": {
                "en": english_ranking_seconds,
                "ru": russian_ranking_seconds,
            },
            "component_total_seconds": component_seconds,
            "additional_fusion_seconds": fusion_seconds,
            "accounted_total_seconds": component_seconds + fusion_seconds,
        },
        "metrics": metrics([identity for identity, _ in fused], judgments),
        "ranking": [
            {"id": identity, "rrf_score": score, "relevance": judgments.get(identity)}
            for identity, score in fused
        ],
    }


def metrics(ranking: list[str], judgments: dict[str, JSON]) -> dict[str, JSON]:
    """Condensed judged-corpus metrics; unknowns are removed, never made negative."""
    if len(set(ranking)) != len(ranking):
        raise ValueError("duplicate asset in ranking")
    judged = [identity for identity in ranking if judgments.get(identity) is not None]
    positives = sum(judgments.get(identity) is True for identity in judged)
    result: dict[str, JSON] = {
        "corpus_candidates": len(ranking),
        "judged_candidates": len(judged),
        "unknown_candidates": len(ranking) - len(judged),
        "positives": positives,
        "negatives": len(judged) - positives,
    }
    found = 0
    precision_sum = 0.0
    for rank, identity in enumerate(judged, 1):
        if judgments.get(identity) is True:
            found += 1
            precision_sum += found / rank
    result["AP"] = precision_sum / positives if positives else None
    for k in (1, 5, 10, 20):
        hits = sum(judgments.get(identity) is True for identity in judged[:k])
        result[f"Hit@{k}"] = int(hits > 0) if positives else None
        result[f"Recall@{k}"] = hits / positives if positives else None
        result[f"unknown_in_corpus_top{k}"] = sum(
            judgments.get(identity) is None for identity in ranking[:k]
        )
    return result


def rank_assets(
    vectors: dict[str, NDArray[np.float32]],
    query: NDArray[np.float32],
    content_hashes: dict[str, str],
    exclude_sha256: str | None,
) -> list[tuple[str, float]]:
    # Select one stable ID per byte identity BEFORE any score/rank computation.
    representatives: dict[str, str] = {}
    for identity in sorted(vectors):
        digest = content_hashes[identity]
        if digest != exclude_sha256:
            representatives.setdefault(digest, identity)
    scores = [
        (identity, float(np.max(vectors[identity] @ query)))
        for identity in representatives.values()
    ]
    return sorted(scores, key=lambda pair: (-pair[1], pair[0]))


def content_corpus(items: list[Item]) -> tuple[list[Item], dict[str, list[Item]]]:
    groups: dict[str, list[Item]] = {}
    for item in items:
        groups.setdefault(item.sha256, []).append(item)
    for values in groups.values():
        values.sort(key=lambda item: item.id)
    return [values[0] for values in groups.values()], groups


def content_judgments(groups: dict[str, list[Item]], raw: dict[str, JSON]) -> dict[str, JSON]:
    result: dict[str, JSON] = {}
    for aliases in groups.values():
        values = [raw.get(item.id) for item in aliases]
        if any(value is not None and not isinstance(value, bool) for value in values):
            raise ValueError("invalid human judgment")
        if True in values and False in values:
            raise ValueError("conflicting judgments for identical image bytes")
        result[aliases[0].id] = True if True in values else False if False in values else None
    return result


def aggregate_queries(queries: list[JSON], *, both_polarities: bool) -> dict[str, JSON]:
    aggregate: dict[str, JSON] = {}
    for mode in ("full", "overlap"):
        for group in ("en", "ru", "fusion", "image"):
            candidates = [
                object_value(value)
                for value in queries
                if object_value(value).get("mode") == mode
                and string_value(object_value(value)["query_id"]).endswith(":" + group)
            ]
            selected: list[dict[str, JSON]] = []
            excluded: list[JSON] = []
            for value in candidates:
                scores = object_value(value["metrics"])
                reason = (
                    "no_positive"
                    if scores["positives"] == 0
                    else ("no_negative" if both_polarities and scores["negatives"] == 0 else None)
                )
                if reason is not None:
                    excluded.append({"query_id": value["query_id"], "reason": reason})
                else:
                    selected.append(value)
            means: dict[str, JSON] = {
                "query_count": len(candidates),
                "eligible_queries": len(selected),
                "excluded_queries": excluded,
                "eligibility": "both_polarities" if both_polarities else "positive_only_diagnostic",
            }
            for metric in ("AP", "Hit@1", "Hit@5", "Recall@5", "Recall@10", "Recall@20"):
                values = [object_value(value["metrics"])[metric] for value in selected]
                numbers = [float(value) for value in values if isinstance(value, int | float)]
                means[metric] = statistics.mean(numbers) if numbers else None
                means[metric + "_evaluable_queries"] = len(numbers)
            aggregate[mode + ":" + group] = means
    return aggregate


def image_request(item: Item, root: Path, op: str, mode: Mode = "full") -> dict[str, JSON]:
    raw = read_bytes(root / item.path, item.byte_length)
    if len(raw) != item.byte_length or hashlib.sha256(raw).hexdigest() != item.sha256:
        raise ValueError("image changed after manifest verification")
    request: dict[str, JSON] = {
        "id": item.id,
        "op": op,
        "image_base64": base64.b64encode(raw).decode("ascii"),
    }
    if op == "image":
        request["mode"] = mode
    return request


def run(
    model_dir: Path,
    data_dir: Path,
    output: Path,
    threads: int,
    batch_size: int,
    image_queries: bool,
    gt_query_crop: bool,
) -> dict[str, JSON]:
    validate_runtime_bounds(threads, batch_size)
    overall_started = time.monotonic()
    external_root(output.parent)
    _, dataset, source_items = verified_acquisition(data_dir)
    items, content_groups = content_corpus(source_items)
    content_hashes = {item.id: item.sha256 for item in source_items}
    if not 48 <= len(source_items) <= 100:
        raise ValueError("benchmark requires 48..100 verified images")
    if any(i.observed_at_ms is not None or i.sequence_id is not None for i in items):
        raise ValueError("Open Images pilot requires null clocks")
    ground_truth = object_value(read_json(data_dir / "ground-truth.json")["classes"])
    validate_query_profile(ground_truth)
    selection = read_json(data_dir / "selection.json")
    judged_by_class = {
        mid: content_judgments(content_groups, object_value(object_value(value)["judgments"]))
        for mid, value in ground_truth.items()
    }
    encoder = SiglipEncoder(model_dir, threads, batch_size)
    worker = Worker(encoder, Policy())
    modes: dict[str, JSON] = {}
    index: dict[str, dict[str, NDArray[np.float32]]] = {}
    for mode in ("full", "overlap"):
        typed_mode: Mode = "full" if mode == "full" else "overlap"
        indexed: dict[str, NDArray[np.float32]] = {}
        latencies: list[float] = []
        for item in items:
            started = time.monotonic()
            response = worker.handle(image_request(item, data_dir, "image", typed_mode))
            vectors = [
                object_value(value)["embedding"] for value in list_value(response["vectors"])
            ]
            indexed[item.id] = np.asarray(vectors, dtype=np.float32)
            latencies.append(time.monotonic() - started)
        index[mode] = indexed
        modes[mode] = {
            "index_seconds": sum(latencies),
            "asset_count": len(items),
            "vector_count": sum(len(matrix) for matrix in indexed.values()),
            "asset_latency_median_seconds": statistics.median(latencies),
            "asset_latency_max_seconds": max(latencies),
            "first_asset_seconds": latencies[0],
            "policy": worker.policy.specification(typed_mode),
            "policy_fingerprint": worker.policy.fingerprint(typed_mode),
            "generation": hashlib.sha256(
                (encoder.model_fingerprint + ":" + worker.policy.fingerprint(typed_mode)).encode()
            ).hexdigest(),
        }
        print(f"{mode}: {len(items)} images, {sum(latencies):.3f}s", flush=True)
    queries: list[JSON] = []

    def evaluate(
        query_id: str,
        mid: str,
        request: dict[str, JSON],
        source_id: str | None,
        query_description: dict[str, JSON],
    ) -> dict[str, TimedRanking]:
        started = time.monotonic()
        embedding = worker.handle(request)["embedding"]
        query_seconds = time.monotonic() - started
        vector = np.asarray(embedding, dtype=np.float32)
        judgments = judged_by_class[mid]
        source_digest = content_hashes[source_id] if source_id is not None else None
        results: dict[str, TimedRanking] = {}
        for mode in ("full", "overlap"):
            started = time.monotonic()
            ranked = rank_assets(index[mode], vector, content_hashes, source_digest)
            rank_seconds = time.monotonic() - started
            queries.append(
                {
                    "query_id": query_id,
                    "class": mid,
                    "mode": mode,
                    "source_id_excluded": source_id,
                    "source_sha256_excluded": source_digest,
                    "source_aliases_excluded": (
                        len(content_groups[source_digest]) if source_digest is not None else 0
                    ),
                    "query": query_description,
                    "ranking_score_kind": "max_cosine",
                    "query_embedding_seconds": query_seconds,
                    "ranking_seconds": rank_seconds,
                    "metrics": metrics([identity for identity, _ in ranked], judgments),
                    "ranking": [
                        {"id": identity, "score": score, "relevance": judgments.get(identity)}
                        for identity, score in ranked
                    ],
                }
            )
            results[mode] = (ranked, query_seconds, rank_seconds)
        return results

    for mid, translations in QUERIES.items():
        language_results: dict[str, dict[str, TimedRanking]] = {}
        for language, text in translations.items():
            language_results[language] = evaluate(
                mid + ":" + language,
                mid,
                {"id": "query", "op": "text", "text": text},
                None,
                language_query_description(mid, language, text),
            )
        for mode in ("full", "overlap"):
            queries.append(
                fusion_query_result(
                    mid,
                    mode,
                    judged_by_class[mid],
                    language_results["en"][mode],
                    language_results["ru"][mode],
                )
            )
        if image_queries:
            gt = object_value(ground_truth[mid])
            judgments = object_value(gt["judgments"])
            boxes = object_value(gt["boxes"])
            query_candidates = sorted(
                (
                    item
                    for item in source_items
                    if judgments.get(item.id) is True and boxes.get(item.id)
                ),
                key=lambda item: item.id,
            )
            if (
                not query_candidates
                or sum(value is True for value in judged_by_class[mid].values()) < 2
            ):
                queries.append(
                    {
                        "query_id": mid + ":image",
                        "unavailable": "need boxed query and at least one other positive",
                    }
                )
                continue
            source = query_candidates[0]
            request = image_request(source, data_dir, "query_image")
            if gt_query_crop:
                # Largest box, stable annotation-order tie. Ground truth never enters indexing.
                annotated = [object_value(value) for value in list_value(boxes[source.id])]

                def area(value: dict[str, JSON]) -> float:
                    array = np.asarray(value["box"], dtype=np.float64)
                    return float((array[2] - array[0]) * (array[3] - array[1]))

                request["box"] = max(annotated, key=area)["box"]
            evaluate(
                mid + ":image",
                mid,
                request,
                source.id,
                {
                    "kind": "class-level-image-proxy",
                    "gt_query_crop": gt_query_crop,
                    "box": request.get("box"),
                },
            )
    aggregate = aggregate_queries(queries, both_polarities=True)
    report: dict[str, JSON] = {
        "version": REPORT_VERSION,
        "dataset": dataset,
        "manifest_sha256": file_digest(data_dir / "manifest.json"),
        "ground_truth_sha256": file_digest(data_dir / "ground-truth.json"),
        "selection_sha256": file_digest(data_dir / "selection.json"),
        "acquisition_sha256": file_digest(data_dir / "acquisition.json"),
        "source_asset_count": len(source_items),
        "unique_content_count": len(items),
        "content_alias_count": len(source_items) - len(items),
        "source_counts": selection["classes"],
        "model": worker.describe(),
        "model_identity": encoder.identity,
        "parameter_count": encoder.parameter_count,
        "model_load_seconds": encoder.load_seconds,
        "model_load_cache_state": "uncontrolled OS cache; digest verification reads weights first",
        "runtime": {
            "platform": platform.platform(),
            "cpu": platform.processor(),
            "logical_cpus": os.cpu_count(),
            "threads": threads,
            "batch_size": batch_size,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
        "modes": modes,
        "queries": queries,
        "language_evaluation": language_evaluation_metadata(),
        "macro_averages": aggregate,
        "secondary_positive_only_macro_averages": aggregate_queries(queries, both_polarities=False),
        "content_policy": "SHA256 dedup;smallest-ID representative;conflicting labels fail",
        "metric_policy": (
            "class-condensed judged candidates;unknown removed;component max cosine per asset;"
            "language fusion reciprocal rank fusion k=60"
        ),
        "limitations": [
            "48-100 image class-balanced selected pilot;not full-dataset generalization",
            "image query excludes every source-SHA alias;class proxy not physical instance/history",
            "no temporal ground truth;not Ego4D VQ official metrics",
            "fixed full-then-overlap order;one run;no isolated thermal/cache control",
            "in-process worker pipeline includes JPEG/base64 but excludes JSONL IPC, Go and SQL",
            "imperfect annotations;unknowns not negatives;judged metrics optimistic for deployment",
            "curated English translations;no automatic translator latency,quality,"
            "privacy evaluated",
        ],
        "duration_seconds": time.monotonic() - overall_started,
    }
    write_json(output, report)
    print(f"report: {output}")
    print(aggregate)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--image-queries", action="store_true")
    parser.add_argument("--gt-query-crop", action="store_true")
    args = parser.parse_args()
    if args.gt_query_crop and not args.image_queries:
        parser.error("--gt-query-crop requires --image-queries")
    run(
        args.model_dir,
        args.data_dir,
        args.output,
        args.threads,
        args.batch_size,
        args.image_queries,
        args.gt_query_crop,
    )


if __name__ == "__main__":
    main()
