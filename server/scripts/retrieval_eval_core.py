"""Pure, label-free planning and ranking for staged retrieval diagnostics."""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from fractions import Fraction
from typing import Never, cast

import numpy as np
from numpy.typing import NDArray

MAX_IDENTIFIER_LENGTH = 512
MAX_QUERY_COUNT = 4_096
MAX_STREAM_COUNT = 1_024
MAX_CANDIDATES_PER_QUERY = 100_000
MAX_TOTAL_CANDIDATES = 500_000
MAX_FRAME_NUMBER = (1 << 53) - 1
MAX_VECTOR_DIMENSION = 8_192
MAX_QUERY_VECTOR_BYTES = MAX_VECTOR_DIMENSION * np.dtype(np.float32).itemsize
MAX_REGIONS_PER_FRAME = 512
MAX_VECTOR_ELEMENTS_PER_FRAME = 1_048_576
MAX_VECTOR_BYTES_PER_FRAME = MAX_VECTOR_ELEMENTS_PER_FRAME * np.dtype(np.float32).itemsize
MAX_GALLERY_FRAMES = 250_000
MAX_TOTAL_GALLERY_VECTOR_ELEMENTS = 16_777_216
MAX_TOTAL_GALLERY_VECTOR_BYTES = MAX_TOTAL_GALLERY_VECTOR_ELEMENTS * np.dtype(np.float32).itemsize
MAX_TOTAL_QUERY_VECTOR_ELEMENTS = 1_048_576
MAX_TOTAL_QUERY_VECTOR_BYTES = MAX_TOTAL_QUERY_VECTOR_ELEMENTS * np.dtype(np.float32).itemsize
MAX_SCORING_VECTOR_ELEMENTS = 33_554_432
MAX_RATE_COMPONENT = 1_000_000_000
MAX_FLOAT32 = float(np.finfo(np.float32).max)

NormalizedBox = tuple[float, float, float, float]
FloatVector = NDArray[np.float32]
FloatMatrix = NDArray[np.float32]


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
        _reject("identifier is invalid")
    return value


def _integer(value: object, minimum: int, maximum: int, message: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _reject(message)
    return value


def _tuple(value: object, maximum: int, message: str) -> tuple[object, ...]:
    if type(value) is not tuple or len(cast(tuple[object, ...], value)) > maximum:
        _reject(message)
    return cast(tuple[object, ...], value)


def _frame_tuple(
    value: object,
    *,
    maximum: int,
    allow_empty: bool,
    increasing: bool = True,
) -> tuple[int, ...]:
    items = _tuple(value, maximum, "frame collection is invalid")
    if (not allow_empty and not items) or any(
        type(item) is not int or not 0 <= item <= MAX_FRAME_NUMBER for item in items
    ):
        _reject("frame collection is invalid")
    frames = cast(tuple[int, ...], items)
    if len(frames) != len(set(frames)) or (increasing and frames != tuple(sorted(frames))):
        _reject("frames must be unique and correctly ordered")
    return frames


def _normalized_box(value: object) -> NormalizedBox:
    items = _tuple(value, 4, "normalized box is invalid")
    if len(items) != 4 or any(type(item) is not float for item in items):
        _reject("normalized box is invalid")
    box = cast(NormalizedBox, items)
    x0, y0, x1, y1 = box
    if not all(math.isfinite(coordinate) for coordinate in box) or not (
        0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0
    ):
        _reject("normalized box is invalid")
    return box


def _float_vector(value: object) -> FloatVector:
    if type(value) is not np.ndarray:
        _reject("query vector is invalid")
    vector = cast(FloatVector, value)
    if (
        vector.dtype != np.dtype(np.float32)
        or vector.ndim != 1
        or not 1 <= vector.shape[0] <= MAX_VECTOR_DIMENSION
        or vector.size > MAX_VECTOR_DIMENSION
        or vector.nbytes > MAX_QUERY_VECTOR_BYTES
        or not bool(np.isfinite(vector).all())
    ):
        _reject("query vector is invalid")
    return vector


def _float_matrix(value: object) -> FloatMatrix:
    if type(value) is not np.ndarray:
        _reject("gallery vectors are invalid")
    matrix = cast(FloatMatrix, value)
    if (
        matrix.dtype != np.dtype(np.float32)
        or matrix.ndim != 2
        or not 1 <= matrix.shape[0] <= MAX_REGIONS_PER_FRAME
        or not 1 <= matrix.shape[1] <= MAX_VECTOR_DIMENSION
        or matrix.size > MAX_VECTOR_ELEMENTS_PER_FRAME
        or matrix.nbytes > MAX_VECTOR_BYTES_PER_FRAME
        or not bool(np.isfinite(matrix).all())
    ):
        _reject("gallery vectors are invalid")
    return matrix


def _immutable_vector(value: object) -> FloatVector:
    source = _float_vector(value)
    storage = source.tobytes(order="C")
    return cast(FloatVector, np.frombuffer(storage, dtype=np.float32).reshape(source.shape))


def _immutable_matrix(value: object) -> FloatMatrix:
    source = _float_matrix(value)
    storage = source.tobytes(order="C")
    return cast(FloatMatrix, np.frombuffer(storage, dtype=np.float32).reshape(source.shape))


def _has_immutable_bytes_storage(value: FloatVector | FloatMatrix) -> bool:
    current: object = value
    while type(current) is np.ndarray:
        base = cast(np.ndarray[tuple[int, ...], np.dtype[np.float32]], current).base
        if base is None:
            return False
        current = base
    return type(current) is bytes and not value.flags.writeable and value.flags.c_contiguous


def _frame_rate(value: object) -> Fraction:
    if type(value) is not Fraction:
        _reject("frame rate is invalid")
    rate = value
    if rate <= 0 or rate.numerator > MAX_RATE_COMPONENT or rate.denominator > MAX_RATE_COMPONENT:
        _reject("frame rate is invalid")
    return rate


@dataclass(frozen=True, repr=False)
class BlindQuery:
    """A stable query identity, stream, and exclusive evaluation-frame cutoff."""

    query_id: str
    stream_id: str
    cutoff_frame: int

    def __post_init__(self) -> None:
        _identifier(self.query_id)
        _identifier(self.stream_id)
        _integer(self.cutoff_frame, 1, MAX_FRAME_NUMBER, "query cutoff is invalid")


@dataclass(frozen=True, repr=False)
class Region:
    """One generic image region in display-normalized coordinates."""

    box: NormalizedBox

    def __post_init__(self) -> None:
        _normalized_box(self.box)


@dataclass(frozen=True, eq=False, repr=False)
class IndexedFrame:
    """Float32 region vectors and corresponding regions for one frame."""

    frame_number: int
    vectors: FloatMatrix
    regions: tuple[Region, ...]

    def __post_init__(self) -> None:
        _integer(self.frame_number, 0, MAX_FRAME_NUMBER, "gallery frame is invalid")
        regions = _tuple(self.regions, MAX_REGIONS_PER_FRAME, "gallery regions are invalid")
        if not regions or any(type(region) is not Region for region in regions):
            _reject("gallery regions are invalid")
        vectors = _immutable_matrix(self.vectors)
        if vectors.shape[0] != len(regions):
            _reject("gallery region and vector counts differ")
        object.__setattr__(self, "vectors", vectors)

    def __eq__(self, other: object) -> bool:
        if type(other) is not IndexedFrame:
            return NotImplemented
        return (
            self.frame_number == other.frame_number
            and self.regions == other.regions
            and bool(np.array_equal(self.vectors, other.vectors))
        )


@dataclass(frozen=True, repr=False)
class StreamGallery:
    """A sorted, duplicate-free set of indexed frames for one stream."""

    stream_id: str
    frames: tuple[IndexedFrame, ...]

    def __post_init__(self) -> None:
        _identifier(self.stream_id)
        frames = _tuple(self.frames, MAX_GALLERY_FRAMES, "stream gallery is invalid")
        if not frames or any(type(frame) is not IndexedFrame for frame in frames):
            _reject("stream gallery is invalid")
        numbers = tuple(cast(IndexedFrame, frame).frame_number for frame in frames)
        if numbers != tuple(sorted(numbers)) or len(numbers) != len(set(numbers)):
            _reject("stream gallery frames must be unique and increasing")
        dimensions = {cast(IndexedFrame, frame).vectors.shape[1] for frame in frames}
        if len(dimensions) != 1:
            _reject("stream gallery vector dimensions differ")
        if (
            sum(cast(IndexedFrame, frame).vectors.size for frame in frames)
            > MAX_TOTAL_GALLERY_VECTOR_ELEMENTS
            or sum(cast(IndexedFrame, frame).vectors.nbytes for frame in frames)
            > MAX_TOTAL_GALLERY_VECTOR_BYTES
        ):
            _reject("stream gallery vectors exceed the aggregate bound")


@dataclass(frozen=True, eq=False, repr=False)
class QueryEmbedding:
    """One immutable float32 query vector associated with a blind query ID."""

    query_id: str
    vector: FloatVector

    def __post_init__(self) -> None:
        _identifier(self.query_id)
        object.__setattr__(self, "vector", _immutable_vector(self.vector))

    def __eq__(self, other: object) -> bool:
        if type(other) is not QueryEmbedding:
            return NotImplemented
        return self.query_id == other.query_id and bool(np.array_equal(self.vector, other.vector))


@dataclass(frozen=True, repr=False)
class ScoredFrame:
    """A frame score and the first region attaining that score."""

    frame_number: int
    score: float
    region_index: int
    region: Region


@dataclass(frozen=True, repr=False)
class StreamFrames:
    """Required frame work for one stream."""

    stream_id: str
    frames: tuple[int, ...]


@dataclass(frozen=True, repr=False)
class QueryPlan:
    """The exclusive cutoff and private candidate cadence for one query."""

    query_id: str
    stream_id: str
    cutoff_frame: int
    candidates: tuple[int, ...]


@dataclass(frozen=True, repr=False)
class BlindPlan:
    """Per-query cadences plus their shared per-stream gallery unions."""

    stride: int
    queries: tuple[QueryPlan, ...]
    gallery_work: tuple[StreamFrames, ...]


@dataclass(frozen=True, repr=False)
class QueryRanking:
    """A complete ranking associated with one query and stream."""

    query_id: str
    stream_id: str
    entries: tuple[ScoredFrame, ...]


@dataclass(frozen=True, repr=False)
class QueryShortlist:
    """The exact full-ranking prefix selected for overlap rescoring."""

    query_id: str
    stream_id: str
    frames: tuple[int, ...]


@dataclass(frozen=True, repr=False)
class ShortlistPlan:
    """Per-query shortlists plus their shared per-stream overlap unions."""

    top_k: int
    queries: tuple[QueryShortlist, ...]
    overlap_work: tuple[StreamFrames, ...]


@dataclass(frozen=True, repr=False)
class CompletedQuery:
    """Immutable blind outputs for one query, before annotation data is joined."""

    query_id: str
    stream_id: str
    cutoff_frame: int
    candidates: tuple[int, ...]
    full_ranking: tuple[ScoredFrame, ...]
    shortlist: tuple[int, ...]
    staged_ranking: tuple[ScoredFrame, ...]


@dataclass(frozen=True, repr=False)
class CompletedBlindRun:
    """Immutable source evidence and completed work without relevance annotations."""

    plan: BlindPlan
    embeddings: tuple[QueryEmbedding, ...]
    full_galleries: tuple[StreamGallery, ...]
    shortlists: ShortlistPlan
    overlap_galleries: tuple[StreamGallery, ...]
    queries: tuple[CompletedQuery, ...]

    @property
    def stride(self) -> int:
        return self.plan.stride

    @property
    def top_k(self) -> int:
        return self.shortlists.top_k

    @property
    def full_gallery_work(self) -> tuple[StreamFrames, ...]:
        return self.plan.gallery_work

    @property
    def overlap_gallery_work(self) -> tuple[StreamFrames, ...]:
        return self.shortlists.overlap_work


def map_evaluation_frame(
    evaluation_frame: int, source_fps: Fraction, annotation_fps: Fraction
) -> int:
    """Map by an exact positive integral FPS ratio, not by PTS or VFR evidence."""

    frame = _integer(evaluation_frame, 0, MAX_FRAME_NUMBER, "evaluation frame is invalid")
    ratio = _frame_rate(source_fps) / _frame_rate(annotation_fps)
    if ratio.denominator != 1 or not 1 <= ratio.numerator <= MAX_RATE_COMPONENT:
        _reject("source and annotation rates lack a bounded integral ratio")
    multiplier = ratio.numerator
    if frame > MAX_FRAME_NUMBER // multiplier:
        _reject("mapped source frame exceeds the supported bound")
    return frame * multiplier


def candidate_frames(cutoff_frame: int, stride: int) -> tuple[int, ...]:
    """Return ``tuple(range(0, cutoff_frame, stride))`` with cutoff excluded."""

    cutoff, step, count = _candidate_count(cutoff_frame, stride)
    if count > MAX_CANDIDATES_PER_QUERY:
        _reject("candidate cadence exceeds the per-query bound")
    return tuple(range(0, cutoff, step))


def _candidate_count(cutoff_frame: int, stride: int) -> tuple[int, int, int]:
    cutoff = _integer(cutoff_frame, 1, MAX_FRAME_NUMBER, "candidate cutoff is invalid")
    step = _integer(stride, 1, MAX_FRAME_NUMBER, "candidate stride is invalid")
    count = ((cutoff - 1) // step) + 1
    return cutoff, step, count


def plan_blind_gallery(queries: tuple[BlindQuery, ...], stride: int) -> BlindPlan:
    """Plan private query cadences and sorted shared stream unions without annotations."""

    selected = _tuple(queries, MAX_QUERY_COUNT, "blind query collection is invalid")
    if not selected or any(type(query) is not BlindQuery for query in selected):
        _reject("blind query collection is invalid")
    step = _integer(stride, 1, MAX_FRAME_NUMBER, "candidate stride is invalid")
    typed = cast(tuple[BlindQuery, ...], selected)
    query_ids = tuple(query.query_id for query in typed)
    if len(query_ids) != len(set(query_ids)):
        _reject("blind query IDs must be unique")
    if len({query.stream_id for query in typed}) > MAX_STREAM_COUNT:
        _reject("planned streams exceed the aggregate bound")
    candidate_total = 0
    for query in typed:
        _, _, count = _candidate_count(query.cutoff_frame, step)
        if count > MAX_CANDIDATES_PER_QUERY:
            _reject("candidate cadence exceeds the per-query bound")
        candidate_total += count
        if candidate_total > MAX_TOTAL_CANDIDATES:
            _reject("planned candidates exceed the aggregate bound")
    planned = tuple(
        QueryPlan(
            query_id=query.query_id,
            stream_id=query.stream_id,
            cutoff_frame=query.cutoff_frame,
            candidates=candidate_frames(query.cutoff_frame, step),
        )
        for query in typed
    )
    unions: dict[str, set[int]] = {}
    for planned_query in planned:
        unions.setdefault(planned_query.stream_id, set()).update(planned_query.candidates)
    work = tuple(
        StreamFrames(stream_id=stream_id, frames=tuple(sorted(frames)))
        for stream_id, frames in sorted(unions.items())
    )
    result = BlindPlan(stride=step, queries=planned, gallery_work=work)
    _validate_plan(result)
    return result


def _validate_stream_work(work: object) -> tuple[StreamFrames, ...]:
    items = _tuple(work, MAX_STREAM_COUNT, "stream work collection is invalid")
    if not items or any(type(item) is not StreamFrames for item in items):
        _reject("stream work collection is invalid")
    typed = cast(tuple[StreamFrames, ...], items)
    stream_ids = tuple(_identifier(item.stream_id) for item in typed)
    if stream_ids != tuple(sorted(stream_ids)) or len(stream_ids) != len(set(stream_ids)):
        _reject("stream work IDs must be unique and increasing")
    for item in typed:
        _frame_tuple(item.frames, maximum=MAX_TOTAL_CANDIDATES, allow_empty=False)
    return typed


def _validate_plan(plan: object) -> BlindPlan:
    if type(plan) is not BlindPlan:
        _reject("blind plan is invalid")
    typed = plan
    step = _integer(typed.stride, 1, MAX_FRAME_NUMBER, "candidate stride is invalid")
    queries = _tuple(typed.queries, MAX_QUERY_COUNT, "query plan collection is invalid")
    if not queries or any(type(query) is not QueryPlan for query in queries):
        _reject("query plan collection is invalid")
    planned = cast(tuple[QueryPlan, ...], queries)
    query_ids = tuple(_identifier(query.query_id) for query in planned)
    if len(query_ids) != len(set(query_ids)):
        _reject("query plan IDs must be unique")
    if len({query.stream_id for query in planned}) > MAX_STREAM_COUNT:
        _reject("planned streams exceed the aggregate bound")
    candidate_total = 0
    for query in planned:
        _, _, count = _candidate_count(query.cutoff_frame, step)
        if count > MAX_CANDIDATES_PER_QUERY:
            _reject("candidate cadence exceeds the per-query bound")
        candidate_total += count
        if candidate_total > MAX_TOTAL_CANDIDATES:
            _reject("planned candidates exceed the aggregate bound")
    expected_unions: dict[str, set[int]] = {}
    for query in planned:
        _identifier(query.stream_id)
        _integer(query.cutoff_frame, 1, MAX_FRAME_NUMBER, "query cutoff is invalid")
        expected = candidate_frames(query.cutoff_frame, step)
        if query.candidates != expected:
            _reject("query candidates differ from the blind cadence")
        expected_unions.setdefault(query.stream_id, set()).update(expected)
    work = _validate_stream_work(typed.gallery_work)
    expected_work = tuple(
        StreamFrames(stream_id=stream_id, frames=tuple(sorted(frames)))
        for stream_id, frames in sorted(expected_unions.items())
    )
    if work != expected_work:
        _reject("full gallery work differs from the query unions")
    return typed


def _validate_scored_frame(item: ScoredFrame) -> ScoredFrame:
    _integer(item.frame_number, 0, MAX_FRAME_NUMBER, "scored frame is invalid")
    if type(item.score) is not float or not math.isfinite(item.score):
        _reject("frame score is invalid")
    if abs(item.score) > MAX_FLOAT32:
        _reject("frame score is outside finite float32 range")
    if float(np.float32(item.score)) != item.score:
        _reject("frame score is not an exact float32 value")
    _integer(item.region_index, 0, MAX_REGIONS_PER_FRAME - 1, "region index is invalid")
    if type(item.region) is not Region:
        _reject("scored region is invalid")
    _normalized_box(item.region.box)
    return item


def validate_full_ranking(ranking: tuple[ScoredFrame, ...], candidates: tuple[int, ...]) -> None:
    """Require one deterministically ordered score for every candidate, exactly once."""

    expected = _frame_tuple(
        candidates,
        maximum=MAX_CANDIDATES_PER_QUERY,
        allow_empty=False,
        increasing=False,
    )
    values = _tuple(ranking, MAX_CANDIDATES_PER_QUERY, "ranking is invalid")
    if any(type(value) is not ScoredFrame for value in values):
        _reject("ranking is invalid")
    typed = cast(tuple[ScoredFrame, ...], values)
    for value in typed:
        _validate_scored_frame(value)
    frames = tuple(value.frame_number for value in typed)
    if len(frames) != len(set(frames)) or set(frames) != set(expected):
        _reject("ranking does not contain every candidate exactly once")
    ordered = tuple(sorted(typed, key=lambda value: (-value.score, value.frame_number)))
    if typed != ordered:
        _reject("full ranking order is invalid")


def _validate_gallery(gallery: object) -> StreamGallery:
    if type(gallery) is not StreamGallery:
        _reject("stream gallery is invalid")
    _identifier(gallery.stream_id)
    frames = _tuple(gallery.frames, MAX_GALLERY_FRAMES, "stream gallery is invalid")
    if not frames or any(type(frame) is not IndexedFrame for frame in frames):
        _reject("stream gallery is invalid")
    typed_frames = cast(tuple[IndexedFrame, ...], frames)
    numbers: list[int] = []
    dimensions: set[int] = set()
    vector_elements = 0
    vector_bytes = 0
    for frame in typed_frames:
        _integer(frame.frame_number, 0, MAX_FRAME_NUMBER, "gallery frame is invalid")
        regions = _tuple(frame.regions, MAX_REGIONS_PER_FRAME, "gallery regions are invalid")
        if not regions or any(type(region) is not Region for region in regions):
            _reject("gallery regions are invalid")
        for region in cast(tuple[Region, ...], regions):
            _normalized_box(region.box)
        vectors = _float_matrix(frame.vectors)
        if not _has_immutable_bytes_storage(vectors):
            _reject("gallery vectors lack immutable byte storage")
        if vectors.shape[0] != len(regions):
            _reject("gallery region and vector counts differ")
        numbers.append(frame.frame_number)
        dimensions.add(vectors.shape[1])
        vector_elements += vectors.size
        vector_bytes += vectors.nbytes
    if numbers != sorted(numbers) or len(numbers) != len(set(numbers)):
        _reject("stream gallery frames must be unique and increasing")
    if len(dimensions) != 1:
        _reject("stream gallery vector dimensions differ")
    if (
        vector_elements > MAX_TOTAL_GALLERY_VECTOR_ELEMENTS
        or vector_bytes > MAX_TOTAL_GALLERY_VECTOR_BYTES
    ):
        _reject("stream gallery vectors exceed the aggregate bound")
    return gallery


def _validate_embedding(value: QueryEmbedding) -> QueryEmbedding:
    _identifier(value.query_id)
    vector = _float_vector(value.vector)
    if not _has_immutable_bytes_storage(vector):
        _reject("query vector lacks immutable byte storage")
    return value


def rank_candidates(
    query_vector: FloatVector,
    gallery: StreamGallery,
    candidates: tuple[int, ...],
) -> tuple[ScoredFrame, ...]:
    """Rank explicit candidates by max region dot product with deterministic ties."""

    vector = _float_vector(query_vector)
    indexed = _validate_gallery(gallery)
    expected = _frame_tuple(
        candidates,
        maximum=MAX_CANDIDATES_PER_QUERY,
        allow_empty=False,
        increasing=False,
    )
    by_frame = {frame.frame_number: frame for frame in indexed.frames}
    _validate_scoring_work(((vector, indexed.stream_id, expected),), {indexed.stream_id: by_frame})
    return _rank_candidates_validated(vector, by_frame, expected)


def _validate_scoring_work(
    requests: tuple[tuple[FloatVector, str, tuple[int, ...]], ...],
    indexes: dict[str, dict[int, IndexedFrame]],
) -> None:
    """Bound exact scalar vector elements before any requested dot product."""

    total = 0
    for vector, stream_id, frames in requests:
        by_frame = indexes[stream_id]
        for frame_number in frames:
            frame = by_frame.get(frame_number)
            if frame is None:
                _reject("gallery is missing a requested candidate")
            if frame.vectors.shape[1] != vector.shape[0]:
                _reject("query and gallery vector dimensions differ")
            total += int(frame.vectors.shape[0]) * int(frame.vectors.shape[1])
            if total > MAX_SCORING_VECTOR_ELEMENTS:
                _reject("requested scoring work exceeds the aggregate bound")


def _rank_candidates_validated(
    vector: FloatVector,
    by_frame: dict[int, IndexedFrame],
    candidates: tuple[int, ...],
) -> tuple[ScoredFrame, ...]:
    """Score inputs already validated and work-bounded by the enclosing phase."""

    scored: list[ScoredFrame] = []
    for frame_number in candidates:
        frame = by_frame[frame_number]
        scores = frame.vectors @ vector
        if (
            scores.dtype != np.dtype(np.float32)
            or scores.ndim != 1
            or not bool(np.isfinite(scores).all())
        ):
            _reject("similarity scores are invalid")
        region_index = int(np.argmax(scores))
        score = float(scores[region_index])
        scored.append(
            ScoredFrame(
                frame_number=frame_number,
                score=score,
                region_index=region_index,
                region=frame.regions[region_index],
            )
        )
    ranking = tuple(sorted(scored, key=lambda value: (-value.score, value.frame_number)))
    validate_full_ranking(ranking, candidates)
    return ranking


def _gallery_indexes(
    galleries: dict[str, StreamGallery],
) -> dict[str, dict[int, IndexedFrame]]:
    return {
        stream_id: {frame.frame_number: frame for frame in gallery.frames}
        for stream_id, gallery in galleries.items()
    }


def _embeddings_by_id(
    embeddings: object, expected_ids: tuple[str, ...]
) -> dict[str, QueryEmbedding]:
    items = _tuple(embeddings, MAX_QUERY_COUNT, "query embedding collection is invalid")
    if any(type(item) is not QueryEmbedding for item in items):
        _reject("query embedding collection is invalid")
    typed = cast(tuple[QueryEmbedding, ...], items)
    for item in typed:
        _validate_embedding(item)
    if (
        sum(item.vector.size for item in typed) > MAX_TOTAL_QUERY_VECTOR_ELEMENTS
        or sum(item.vector.nbytes for item in typed) > MAX_TOTAL_QUERY_VECTOR_BYTES
    ):
        _reject("query vectors exceed the aggregate bound")
    identifiers = tuple(item.query_id for item in typed)
    if len(identifiers) != len(set(identifiers)) or set(identifiers) != set(expected_ids):
        _reject("query embedding IDs do not match planned queries")
    return {item.query_id: item for item in typed}


def _galleries_by_stream(
    galleries: object, expected_work: tuple[StreamFrames, ...]
) -> dict[str, StreamGallery]:
    items = _tuple(galleries, MAX_STREAM_COUNT, "gallery collection is invalid")
    if any(type(item) is not StreamGallery for item in items):
        _reject("gallery collection is invalid")
    typed = cast(tuple[StreamGallery, ...], items)
    for item in typed:
        _validate_gallery(item)
    if (
        sum(len(item.frames) for item in typed) > MAX_GALLERY_FRAMES
        or sum(frame.vectors.size for item in typed for frame in item.frames)
        > MAX_TOTAL_GALLERY_VECTOR_ELEMENTS
        or sum(frame.vectors.nbytes for item in typed for frame in item.frames)
        > MAX_TOTAL_GALLERY_VECTOR_BYTES
    ):
        _reject("galleries exceed aggregate frame or vector bounds")
    identifiers = tuple(item.stream_id for item in typed)
    expected_ids = tuple(item.stream_id for item in expected_work)
    if len(identifiers) != len(set(identifiers)) or set(identifiers) != set(expected_ids):
        _reject("gallery stream IDs do not match planned work")
    result = {item.stream_id: item for item in typed}
    for work in expected_work:
        observed = tuple(frame.frame_number for frame in result[work.stream_id].frames)
        if observed != work.frames:
            _reject("gallery frames do not match planned work")
    return result


def rank_full_plan(
    plan: BlindPlan,
    embeddings: tuple[QueryEmbedding, ...],
    galleries: tuple[StreamGallery, ...],
) -> tuple[QueryRanking, ...]:
    """Rank every query's own cadence against a validated shared full gallery."""

    planned = _validate_plan(plan)
    query_ids = tuple(query.query_id for query in planned.queries)
    vectors = _embeddings_by_id(embeddings, query_ids)
    galleries_by_stream = _galleries_by_stream(galleries, planned.gallery_work)
    indexes = _gallery_indexes(galleries_by_stream)
    _validate_scoring_work(
        tuple(
            (vectors[query.query_id].vector, query.stream_id, query.candidates)
            for query in planned.queries
        ),
        indexes,
    )
    rankings = tuple(
        QueryRanking(
            query_id=query.query_id,
            stream_id=query.stream_id,
            entries=_rank_candidates_validated(
                vectors[query.query_id].vector,
                indexes[query.stream_id],
                query.candidates,
            ),
        )
        for query in planned.queries
    )
    _validate_full_rankings(planned, rankings)
    return rankings


def _validate_full_rankings(plan: BlindPlan, rankings: object) -> tuple[QueryRanking, ...]:
    items = _tuple(rankings, MAX_QUERY_COUNT, "full ranking collection is invalid")
    if any(type(item) is not QueryRanking for item in items):
        _reject("full ranking collection is invalid")
    typed = cast(tuple[QueryRanking, ...], items)
    if tuple(item.query_id for item in typed) != tuple(query.query_id for query in plan.queries):
        _reject("full ranking IDs or order do not match the plan")
    for query, ranking in zip(plan.queries, typed, strict=True):
        if ranking.stream_id != query.stream_id:
            _reject("full ranking stream does not match the plan")
        validate_full_ranking(ranking.entries, query.candidates)
    return typed


def plan_shortlists(
    plan: BlindPlan,
    full_rankings: tuple[QueryRanking, ...],
    top_k: int,
) -> ShortlistPlan:
    """Select exact full-ranking prefixes and sorted shared overlap work unions."""

    planned = _validate_plan(plan)
    rankings = _validate_full_rankings(planned, full_rankings)
    limit = _integer(top_k, 1, MAX_CANDIDATES_PER_QUERY, "shortlist top-K is invalid")
    selected = tuple(
        QueryShortlist(
            query_id=query.query_id,
            stream_id=query.stream_id,
            frames=tuple(
                item.frame_number for item in ranking.entries[: min(limit, len(ranking.entries))]
            ),
        )
        for query, ranking in zip(planned.queries, rankings, strict=True)
    )
    unions: dict[str, set[int]] = {}
    for query in selected:
        unions.setdefault(query.stream_id, set()).update(query.frames)
    work = tuple(
        StreamFrames(stream_id=stream_id, frames=tuple(sorted(frames)))
        for stream_id, frames in sorted(unions.items())
    )
    result = ShortlistPlan(top_k=limit, queries=selected, overlap_work=work)
    _validate_shortlists(planned, rankings, result)
    return result


def _validate_shortlists(
    plan: BlindPlan, full_rankings: tuple[QueryRanking, ...], shortlists: object
) -> ShortlistPlan:
    if type(shortlists) is not ShortlistPlan:
        _reject("shortlist plan is invalid")
    typed = shortlists
    limit = _integer(typed.top_k, 1, MAX_CANDIDATES_PER_QUERY, "shortlist top-K is invalid")
    items = _tuple(typed.queries, MAX_QUERY_COUNT, "shortlist collection is invalid")
    if any(type(item) is not QueryShortlist for item in items):
        _reject("shortlist collection is invalid")
    selected = cast(tuple[QueryShortlist, ...], items)
    if tuple(item.query_id for item in selected) != tuple(query.query_id for query in plan.queries):
        _reject("shortlist IDs or order do not match the plan")
    expected_unions: dict[str, set[int]] = {}
    for query, ranking, shortlist in zip(plan.queries, full_rankings, selected, strict=True):
        expected = tuple(
            item.frame_number for item in ranking.entries[: min(limit, len(ranking.entries))]
        )
        if shortlist.stream_id != query.stream_id or shortlist.frames != expected:
            _reject("shortlist is not the exact full-ranking prefix")
        expected_unions.setdefault(query.stream_id, set()).update(expected)
    work = _validate_stream_work(typed.overlap_work)
    expected_work = tuple(
        StreamFrames(stream_id=stream_id, frames=tuple(sorted(frames)))
        for stream_id, frames in sorted(expected_unions.items())
    )
    if work != expected_work:
        _reject("overlap work differs from the shortlist unions")
    return typed


def complete_staged_run(
    plan: BlindPlan,
    embeddings: tuple[QueryEmbedding, ...],
    full_galleries: tuple[StreamGallery, ...],
    full_rankings: tuple[QueryRanking, ...],
    shortlists: ShortlistPlan,
    overlap_galleries: tuple[StreamGallery, ...],
) -> CompletedBlindRun:
    """Rescore only each shortlist and retain every original full-tail object."""

    planned = _validate_plan(plan)
    query_ids = tuple(query.query_id for query in planned.queries)
    vectors = _embeddings_by_id(embeddings, query_ids)
    full_indexes = _gallery_indexes(_galleries_by_stream(full_galleries, planned.gallery_work))
    _validate_scoring_work(
        tuple(
            (vectors[query.query_id].vector, query.stream_id, query.candidates)
            for query in planned.queries
        ),
        full_indexes,
    )
    rankings = _validate_full_rankings(planned, full_rankings)
    selected = _validate_shortlists(planned, rankings, shortlists)
    overlap_indexes = _gallery_indexes(
        _galleries_by_stream(overlap_galleries, selected.overlap_work)
    )
    _validate_scoring_work(
        tuple(
            (vectors[query.query_id].vector, shortlist.stream_id, shortlist.frames)
            for query, shortlist in zip(planned.queries, selected.queries, strict=True)
        ),
        overlap_indexes,
    )
    completed = _build_completed_queries(planned, rankings, selected, vectors, overlap_indexes)
    result = CompletedBlindRun(
        plan=planned,
        embeddings=embeddings,
        full_galleries=full_galleries,
        shortlists=selected,
        overlap_galleries=overlap_galleries,
        queries=completed,
    )
    validate_completed_blind_run(result)
    return result


def _build_completed_queries(
    plan: BlindPlan,
    rankings: tuple[QueryRanking, ...],
    shortlists: ShortlistPlan,
    vectors: dict[str, QueryEmbedding],
    indexes: dict[str, dict[int, IndexedFrame]],
) -> tuple[CompletedQuery, ...]:
    completed: list[CompletedQuery] = []
    for query, full, shortlist in zip(plan.queries, rankings, shortlists.queries, strict=True):
        prefix = _rank_candidates_validated(
            vectors[query.query_id].vector,
            indexes[query.stream_id],
            shortlist.frames,
        )
        tail = full.entries[len(shortlist.frames) :]
        staged = (*prefix, *tail)
        completed.append(
            CompletedQuery(
                query_id=query.query_id,
                stream_id=query.stream_id,
                cutoff_frame=query.cutoff_frame,
                candidates=query.candidates,
                full_ranking=full.entries,
                shortlist=shortlist.frames,
                staged_ranking=staged,
            )
        )
    return tuple(completed)


def _validate_complete_membership(
    ranking: object, candidates: tuple[int, ...]
) -> tuple[ScoredFrame, ...]:
    values = _tuple(ranking, MAX_CANDIDATES_PER_QUERY, "completed ranking is invalid")
    if any(type(value) is not ScoredFrame for value in values):
        _reject("completed ranking is invalid")
    typed = cast(tuple[ScoredFrame, ...], values)
    for value in typed:
        _validate_scored_frame(value)
    frames = tuple(value.frame_number for value in typed)
    if len(frames) != len(set(frames)) or set(frames) != set(candidates):
        _reject("completed ranking does not contain every candidate exactly once")
    return typed


def validate_completed_blind_run(run: object) -> CompletedBlindRun:
    """Recompute all rankings from retained generic source evidence."""

    if type(run) is not CompletedBlindRun:
        _reject("completed blind run is invalid")
    typed = run
    plan = _validate_plan(typed.plan)
    query_ids = tuple(query.query_id for query in plan.queries)
    vectors = _embeddings_by_id(typed.embeddings, query_ids)
    full_indexes = _gallery_indexes(_galleries_by_stream(typed.full_galleries, plan.gallery_work))
    _validate_scoring_work(
        tuple(
            (vectors[query.query_id].vector, query.stream_id, query.candidates)
            for query in plan.queries
        ),
        full_indexes,
    )
    recomputed_full = tuple(
        QueryRanking(
            query_id=query.query_id,
            stream_id=query.stream_id,
            entries=_rank_candidates_validated(
                vectors[query.query_id].vector,
                full_indexes[query.stream_id],
                query.candidates,
            ),
        )
        for query in plan.queries
    )
    shortlists = _validate_shortlists(plan, recomputed_full, typed.shortlists)
    overlap_indexes = _gallery_indexes(
        _galleries_by_stream(typed.overlap_galleries, shortlists.overlap_work)
    )
    _validate_scoring_work(
        tuple(
            (vectors[query.query_id].vector, shortlist.stream_id, shortlist.frames)
            for query, shortlist in zip(plan.queries, shortlists.queries, strict=True)
        ),
        overlap_indexes,
    )
    expected = _build_completed_queries(plan, recomputed_full, shortlists, vectors, overlap_indexes)
    items = _tuple(typed.queries, MAX_QUERY_COUNT, "completed query collection is invalid")
    if not items or any(type(item) is not CompletedQuery for item in items):
        _reject("completed query collection is invalid")
    completed = cast(tuple[CompletedQuery, ...], items)
    if tuple(item.query_id for item in completed) != query_ids:
        _reject("completed query IDs or order do not match retained source evidence")
    for item, recomputed in zip(completed, expected, strict=True):
        _identifier(item.query_id)
        _identifier(item.stream_id)
        if (
            item.stream_id != recomputed.stream_id
            or item.cutoff_frame != recomputed.cutoff_frame
            or item.candidates != recomputed.candidates
            or item.shortlist != recomputed.shortlist
        ):
            _reject("completed query planning differs from retained source evidence")
        validate_full_ranking(item.full_ranking, recomputed.candidates)
        staged = _validate_complete_membership(item.staged_ranking, recomputed.candidates)
        if not _ranking_matches_source(item.full_ranking, recomputed.full_ranking):
            _reject("full ranking differs from retained source evidence")
        if not _ranking_matches_source(staged, recomputed.staged_ranking):
            _reject("staged ranking differs from retained source evidence")
        prefix_count = len(recomputed.shortlist)
        full_tail = item.full_ranking[prefix_count:]
        staged_tail = staged[prefix_count:]
        if staged_tail != full_tail or any(
            staged_item is not full_item
            for staged_item, full_item in zip(staged_tail, full_tail, strict=True)
        ):
            _reject("completed staged tail differs from the original full tail")
    return typed


def _ranking_matches_source(
    observed: tuple[ScoredFrame, ...], expected: tuple[ScoredFrame, ...]
) -> bool:
    return len(observed) == len(expected) and all(
        actual.frame_number == source.frame_number
        and np.float32(actual.score).tobytes() == np.float32(source.score).tobytes()
        and actual.region_index == source.region_index
        and actual.region is source.region
        for actual, source in zip(observed, expected, strict=True)
    )
