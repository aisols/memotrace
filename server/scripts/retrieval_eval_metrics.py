"""Post-ranking metrics for completed blind retrieval runs."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from fractions import Fraction
from statistics import fmean
from typing import Never, cast

from scripts.retrieval_eval_core import (
    MAX_CANDIDATES_PER_QUERY,
    MAX_FRAME_NUMBER,
    MAX_IDENTIFIER_LENGTH,
    MAX_QUERY_COUNT,
    MAX_RATE_COMPONENT,
    CompletedBlindRun,
    ScoredFrame,
    validate_completed_blind_run,
)

MAX_INTERVALS_PER_QUERY = 4_096
MAX_TOTAL_INTERVALS = 32_768
MAX_METRIC_CUTOFF_COUNT = 64
MAX_METRIC_AT_K_RECORDS = 262_144


def _reject(message: str) -> Never:
    raise ValueError(message)


def _identifier(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_IDENTIFIER_LENGTH
        or any(
            ord(character) < 0x20
            or 0x7F <= ord(character) <= 0x9F
            or 0xD800 <= ord(character) <= 0xDFFF
            or unicodedata.category(character) == "Cf"
            for character in value
        )
    ):
        _reject("annotation query identifier is invalid")
    return value


def _integer(value: object, minimum: int, maximum: int, message: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _reject(message)
    return value


def _tuple(value: object, maximum: int, message: str) -> tuple[object, ...]:
    if type(value) is not tuple or len(cast(tuple[object, ...], value)) > maximum:
        _reject(message)
    return cast(tuple[object, ...], value)


def _rate(value: object) -> Fraction:
    if type(value) is not Fraction:
        _reject("annotation frame rate is invalid")
    rate = value
    if rate <= 0 or rate.numerator > MAX_RATE_COMPONENT or rate.denominator > MAX_RATE_COMPONENT:
        _reject("annotation frame rate is invalid")
    return rate


@dataclass(frozen=True, repr=False)
class FrameInterval:
    """An inclusive positive-response interval in annotation-frame coordinates."""

    start: int
    end: int

    def __post_init__(self) -> None:
        start = _integer(self.start, 0, MAX_FRAME_NUMBER, "response interval is invalid")
        end = _integer(self.end, 0, MAX_FRAME_NUMBER, "response interval is invalid")
        if end < start:
            _reject("response interval is invalid")


def _intervals(value: object) -> tuple[FrameInterval, ...]:
    values = _tuple(
        value,
        MAX_INTERVALS_PER_QUERY,
        "positive interval collection is invalid",
    )
    if not values or any(type(item) is not FrameInterval for item in values):
        _reject("positive interval collection is invalid")
    intervals = cast(tuple[FrameInterval, ...], values)
    for interval in intervals:
        interval.__post_init__()
    if intervals != tuple(sorted(intervals, key=lambda item: (item.start, item.end))):
        _reject("positive intervals must be ordered")
    if any(left.end >= right.start for left, right in zip(intervals, intervals[1:], strict=False)):
        _reject("positive intervals must not overlap")
    return intervals


@dataclass(frozen=True, repr=False)
class QueryAnnotations:
    """Explicit annotation rate and positive intervals for one completed query."""

    query_id: str
    annotation_fps: Fraction
    positive_intervals: tuple[FrameInterval, ...]

    def __post_init__(self) -> None:
        _identifier(self.query_id)
        _rate(self.annotation_fps)
        _intervals(self.positive_intervals)


@dataclass(frozen=True, repr=False)
class ConditionalAtK:
    """Hit and captured-positive recall at one cutoff."""

    k: int
    hit: int
    recall: float


@dataclass(frozen=True, repr=False)
class EndToEndAtK:
    """A capture-aware hit at one cutoff; a capture miss is zero."""

    k: int
    hit: int


@dataclass(frozen=True, repr=False)
class ConditionalRanking:
    """Ranking metrics defined only when cadence captured a positive frame."""

    average_precision: float
    reciprocal_rank: float
    at_k: tuple[ConditionalAtK, ...]


@dataclass(frozen=True, repr=False)
class RankingOutcome:
    """Conditional metrics and all-query end-to-end hits for one ranking."""

    conditional: ConditionalRanking | None
    end_to_end_at_k: tuple[EndToEndAtK, ...]


@dataclass(frozen=True, repr=False)
class QueryEvaluation:
    """Capture and ranking diagnostics for one query."""

    query_id: str
    captured_positive_frames: tuple[int, ...]
    nearest_cadence_distance_frames: int
    nearest_cadence_distance_seconds: float
    full: RankingOutcome
    staged: RankingOutcome


@dataclass(frozen=True, repr=False)
class AggregateAtK:
    """Conditional means and an all-query end-to-end hit mean at one cutoff."""

    k: int
    conditional_mean_hit: float | None
    conditional_mean_recall: float | None
    end_to_end_mean_hit: float


@dataclass(frozen=True, repr=False)
class RankingAggregate:
    """Macro ranking diagnostics with explicit conditional denominators."""

    conditional_query_count: int
    conditional_mean_average_precision: float | None
    conditional_mean_reciprocal_rank: float | None
    at_k: tuple[AggregateAtK, ...]


@dataclass(frozen=True, repr=False)
class EvaluationSummary:
    """Capture coverage and separate full/staged aggregate ranking diagnostics."""

    query_count: int
    captured_query_count: int
    capture_coverage: float
    full: RankingAggregate
    staged: RankingAggregate


@dataclass(frozen=True, repr=False)
class BlindEvaluation:
    """Annotations joined after ranking, represented only as metric values."""

    queries: tuple[QueryEvaluation, ...]
    summary: EvaluationSummary


def _sweep_candidates_and_intervals(
    candidates: tuple[int, ...], intervals: tuple[FrameInterval, ...]
) -> tuple[tuple[int, ...], int, int]:
    """Return captures, nearest distance, and at most ``2*C + I`` comparisons."""

    captured: list[int] = []
    nearest = MAX_FRAME_NUMBER
    interval_offset = 0
    comparisons = 0
    for frame in candidates:
        while interval_offset < len(intervals):
            comparisons += 1
            interval = intervals[interval_offset]
            if interval.end >= frame:
                break
            nearest = min(nearest, frame - interval.end)
            interval_offset += 1
        if interval_offset == len(intervals):
            continue
        interval = intervals[interval_offset]
        comparisons += 1
        if frame < interval.start:
            nearest = min(nearest, interval.start - frame)
        else:
            captured.append(frame)
            nearest = 0
    return tuple(captured), nearest, comparisons


def _ranking_outcome(
    ranking: tuple[ScoredFrame, ...],
    captured: tuple[int, ...],
    cutoffs: tuple[int, ...],
) -> RankingOutcome:
    captured_set = set(captured)
    positive_ranks = tuple(
        rank for rank, item in enumerate(ranking, start=1) if item.frame_number in captured_set
    )
    if not captured:
        return RankingOutcome(
            conditional=None,
            end_to_end_at_k=tuple(EndToEndAtK(k=cutoff, hit=0) for cutoff in cutoffs),
        )
    average_precision = fmean(found / rank for found, rank in enumerate(positive_ranks, start=1))
    conditional_at_k = tuple(
        ConditionalAtK(
            k=cutoff,
            hit=int(any(rank <= cutoff for rank in positive_ranks)),
            recall=sum(rank <= cutoff for rank in positive_ranks) / len(captured),
        )
        for cutoff in cutoffs
    )
    return RankingOutcome(
        conditional=ConditionalRanking(
            average_precision=float(average_precision),
            reciprocal_rank=float(1.0 / positive_ranks[0]),
            at_k=conditional_at_k,
        ),
        end_to_end_at_k=tuple(EndToEndAtK(k=value.k, hit=value.hit) for value in conditional_at_k),
    )


def _aggregate(
    evaluations: tuple[QueryEvaluation, ...],
    attribute: str,
    cutoffs: tuple[int, ...],
) -> RankingAggregate:
    outcomes = tuple(cast(RankingOutcome, getattr(item, attribute)) for item in evaluations)
    conditional = tuple(
        outcome.conditional for outcome in outcomes if outcome.conditional is not None
    )
    at_k: list[AggregateAtK] = []
    for offset, cutoff in enumerate(cutoffs):
        at_k.append(
            AggregateAtK(
                k=cutoff,
                conditional_mean_hit=(
                    float(fmean(item.at_k[offset].hit for item in conditional))
                    if conditional
                    else None
                ),
                conditional_mean_recall=(
                    float(fmean(item.at_k[offset].recall for item in conditional))
                    if conditional
                    else None
                ),
                end_to_end_mean_hit=float(
                    fmean(outcome.end_to_end_at_k[offset].hit for outcome in outcomes)
                ),
            )
        )
    return RankingAggregate(
        conditional_query_count=len(conditional),
        conditional_mean_average_precision=(
            float(fmean(item.average_precision for item in conditional)) if conditional else None
        ),
        conditional_mean_reciprocal_rank=(
            float(fmean(item.reciprocal_rank for item in conditional)) if conditional else None
        ),
        at_k=tuple(at_k),
    )


def evaluate_blind_run(
    run: CompletedBlindRun,
    annotations: tuple[QueryAnnotations, ...],
    cutoffs: tuple[int, ...],
) -> BlindEvaluation:
    """Join explicit annotations to an already completed blind run and compute metrics."""

    completed = validate_completed_blind_run(run)
    values = _tuple(annotations, MAX_QUERY_COUNT, "annotation collection is invalid")
    if any(type(value) is not QueryAnnotations for value in values):
        _reject("annotation collection is invalid")
    typed_annotations = cast(tuple[QueryAnnotations, ...], values)
    for item in typed_annotations:
        _identifier(item.query_id)
        _rate(item.annotation_fps)
        _intervals(item.positive_intervals)
    if sum(len(item.positive_intervals) for item in typed_annotations) > MAX_TOTAL_INTERVALS:
        _reject("positive intervals exceed the aggregate bound")
    annotation_ids = tuple(item.query_id for item in typed_annotations)
    run_ids = tuple(item.query_id for item in completed.queries)
    if len(annotation_ids) != len(set(annotation_ids)) or set(annotation_ids) != set(run_ids):
        _reject("annotation query IDs do not exactly match completed query IDs")
    requested = _tuple(cutoffs, MAX_METRIC_CUTOFF_COUNT, "metric cutoff collection is invalid")
    if not requested or any(
        type(value) is not int or not 1 <= value <= MAX_CANDIDATES_PER_QUERY for value in requested
    ):
        _reject("metric cutoff collection is invalid")
    typed_cutoffs = cast(tuple[int, ...], requested)
    if typed_cutoffs != tuple(sorted(set(typed_cutoffs))):
        _reject("metric cutoffs must be unique and increasing")
    at_k_records = (len(completed.queries) * len(typed_cutoffs) * 4) + (len(typed_cutoffs) * 2)
    if at_k_records > MAX_METRIC_AT_K_RECORDS:
        _reject("metric outputs exceed the aggregate bound")
    by_id = {item.query_id: item for item in typed_annotations}
    evaluations: list[QueryEvaluation] = []
    for query in completed.queries:
        annotation = by_id[query.query_id]
        if any(interval.end >= query.cutoff_frame for interval in annotation.positive_intervals):
            _reject("positive intervals must precede the query cutoff")
        captured, nearest, _ = _sweep_candidates_and_intervals(
            query.candidates, annotation.positive_intervals
        )
        seconds = float(Fraction(nearest, 1) / annotation.annotation_fps)
        evaluations.append(
            QueryEvaluation(
                query_id=query.query_id,
                captured_positive_frames=captured,
                nearest_cadence_distance_frames=nearest,
                nearest_cadence_distance_seconds=seconds,
                full=_ranking_outcome(query.full_ranking, captured, typed_cutoffs),
                staged=_ranking_outcome(query.staged_ranking, captured, typed_cutoffs),
            )
        )
    results = tuple(evaluations)
    captured_count = sum(bool(item.captured_positive_frames) for item in results)
    summary = EvaluationSummary(
        query_count=len(results),
        captured_query_count=captured_count,
        capture_coverage=captured_count / len(results),
        full=_aggregate(results, "full", typed_cutoffs),
        staged=_aggregate(results, "staged", typed_cutoffs),
    )
    return BlindEvaluation(queries=results, summary=summary)
