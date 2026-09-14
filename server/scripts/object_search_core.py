"""Bounded experimental object-search algorithms; no inference or persistence.

Runner API: build UnitVector/UnitMatrix from already normalized float32 arrays,
rank_semantic(query, semantic_frames), encode the exact top-K frame keys, then
rerank_shortlist(ranking, crops, top_k). validate_search_result recomputes both
spaces from retained evidence. Semantic and instance scores are never blended.

associate_tracklets operates on at most 64 supplied frames per stream. These are
short, conservative appearance/geometry associations, not calibrated thresholds,
physical identities, continuous presence, or verified locations. Empty observed
frames matter: runners must supply them and explicitly record coverage gaps.
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Never, cast

import numpy as np
from numpy.typing import NDArray

MAX_FRAMES = 10_000
MAX_OBSERVATIONS = 10_000
MAX_STREAMS = 1_024
MAX_FRAMES_PER_STREAM_WINDOW = 64
MAX_REGIONS_PER_FRAME = 64
MAX_QUERY_REGIONS = 32
MAX_VECTOR_DIMENSION = 8_192
MAX_VECTOR_ELEMENTS = 33_554_432
MAX_SCORING_VECTOR_ELEMENTS = 33_554_432
MAX_EXACT_INTEGER = (1 << 53) - 1
MAX_IDENTIFIER_LENGTH = 512
UNIT_NORM_TOLERANCE = 1e-5
MIN_ASSOCIATION_COSINE = 0.85
MIN_ASSOCIATION_IOU = 0.10
ASSOCIATION_AMBIGUITY_MARGIN = 0.05
MAX_ASSOCIATION_GAP_MS = 1_500

FloatArray = NDArray[np.float32]
DoubleArray = NDArray[np.float64]


def _reject(message: str) -> Never:
    raise ValueError(message)


def _integer(value: object, maximum: int = MAX_EXACT_INTEGER) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        _reject("expected a bounded exact nonnegative integer")
    return value


def _identifier(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_IDENTIFIER_LENGTH
        or any(unicodedata.category(c).startswith("C") for c in value)
    ):
        _reject("invalid exact identifier")
    return value


def _hash(value: object) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        _reject("content_sha256 must be canonical lowercase SHA-256 hex")


def _items[T](value: tuple[T, ...], kind: type[T], maximum: int) -> tuple[T, ...]:
    if type(value) is not tuple or len(value) > maximum or any(type(x) is not kind for x in value):
        _reject("invalid or oversized typed tuple")
    return value


def _float(value: object, low: float, high: float) -> float:
    if type(value) is not float or not math.isfinite(value) or not low <= value <= high:
        _reject("invalid finite float")
    return value


def _array(value: FloatArray, dimensions: int) -> FloatArray:
    if (
        type(value) is not np.ndarray
        or value.dtype != np.dtype(np.float32)
        or value.ndim != dimensions
        or not 1 <= value.shape[-1] <= MAX_VECTOR_DIMENSION
        or (dimensions == 2 and value.shape[0] > MAX_REGIONS_PER_FRAME)
    ):
        _reject("expected bounded float32 array")
    return value


def _unit_rows(array: FloatArray) -> None:
    # Shape and aggregate budgets are checked before calling this in public APIs.
    rows = array.astype(np.float64)
    norms = np.linalg.norm(rows, axis=-1)
    if not bool(np.isfinite(rows).all()) or not bool(
        (np.abs(norms - 1.0) <= UNIT_NORM_TOLERANCE).all()
    ):
        _reject("cosine inputs must be finite, nonzero, and unit normalized")


@dataclass(frozen=True, slots=True)
class UnitVector:
    """Immutable bytes, not merely a read-only view of a mutable array owner."""

    data: bytes
    dimension: int

    def __post_init__(self) -> None:
        _vector_shape(self)
        _unit_rows(self.array())

    @classmethod
    def from_array(cls, array: FloatArray) -> UnitVector:
        source = _array(array, 1)
        return cls(source.tobytes(order="C"), int(source.shape[0]))

    def array(self) -> FloatArray:
        # Return a fresh view so callers cannot mutate retained shape metadata.
        return np.frombuffer(self.data, dtype=np.float32)


@dataclass(frozen=True, slots=True)
class UnitMatrix:
    """Row-normalized crop descriptors; zero rows explicitly means no proposals."""

    data: bytes
    rows: int
    dimension: int

    def __post_init__(self) -> None:
        _matrix_shape(self)
        _unit_rows(self.array())

    @classmethod
    def from_array(cls, array: FloatArray) -> UnitMatrix:
        source = _array(array, 2)
        return cls(source.tobytes(order="C"), int(source.shape[0]), int(source.shape[1]))

    def array(self) -> FloatArray:
        return np.frombuffer(self.data, dtype=np.float32).reshape(self.rows, self.dimension)


def _vector_shape(vector: UnitVector) -> int:
    if type(vector) is not UnitVector:
        _reject("expected UnitVector")
    dimension = _integer(vector.dimension, MAX_VECTOR_DIMENSION)
    if not dimension or type(vector.data) is not bytes or len(vector.data) != dimension * 4:
        _reject("invalid vector byte storage")
    return dimension


def _matrix_shape(matrix: UnitMatrix) -> int:
    if type(matrix) is not UnitMatrix:
        _reject("expected UnitMatrix")
    dimension = _integer(matrix.dimension, MAX_VECTOR_DIMENSION)
    rows = _integer(matrix.rows, MAX_REGIONS_PER_FRAME)
    if not dimension or type(matrix.data) is not bytes or len(matrix.data) != rows * dimension * 4:
        _reject("invalid matrix byte storage")
    return rows * dimension


@dataclass(frozen=True, slots=True, order=True)
class FrameKey:
    stream_id: str
    frame_id: str

    def __post_init__(self) -> None:
        _identifier(self.stream_id)
        _identifier(self.frame_id)


@dataclass(frozen=True, slots=True, order=True)
class ObservationKey:
    stream_id: str
    frame_id: str
    region_ordinal: int

    def __post_init__(self) -> None:
        FrameKey(self.stream_id, self.frame_id)
        _integer(self.region_ordinal, MAX_REGIONS_PER_FRAME - 1)


@dataclass(frozen=True, slots=True)
class NormalizedBox:
    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        for coordinate in (self.x0, self.y0, self.x1, self.y1):
            _float(coordinate, 0.0, 1.0)
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            _reject("normalized box must have positive area")


@dataclass(frozen=True, slots=True)
class FrameRecord:
    stream_id: str
    frame_id: str
    timestamp_ms: int
    content_sha256: str
    sequence_id: str

    def __post_init__(self) -> None:
        FrameKey(self.stream_id, self.frame_id)
        _integer(self.timestamp_ms)
        _hash(self.content_sha256)
        _identifier(self.sequence_id)

    @property
    def key(self) -> FrameKey:
        return FrameKey(self.stream_id, self.frame_id)


@dataclass(frozen=True, slots=True)
class Observation:
    """One proposal, not an assertion that the depicted physical object is known."""

    stream_id: str
    frame_id: str
    timestamp_ms: int
    region_ordinal: int
    class_id: int
    box: NormalizedBox

    def __post_init__(self) -> None:
        ObservationKey(self.stream_id, self.frame_id, self.region_ordinal)
        _integer(self.timestamp_ms)
        _integer(self.class_id)
        if type(self.box) is not NormalizedBox:
            _reject("expected typed normalized box")
        self.box.__post_init__()

    @property
    def key(self) -> ObservationKey:
        return ObservationKey(self.stream_id, self.frame_id, self.region_ordinal)


@dataclass(frozen=True, slots=True)
class StreamCutoff:
    """Exclusive timestamp cutoff in this stream's own clock."""

    stream_id: str
    timestamp_ms: int

    def __post_init__(self) -> None:
        _identifier(self.stream_id)
        _integer(self.timestamp_ms)


@dataclass(frozen=True, slots=True)
class SearchQuery:
    query_id: str
    source: FrameKey
    source_content_sha256: str
    cutoffs: tuple[StreamCutoff, ...]
    semantic_space: str
    semantic_vector: UnitVector
    instance_space: str
    instance_vectors: UnitMatrix

    def __post_init__(self) -> None:
        _query_shape(self)
        _unit_rows(self.semantic_vector.array())
        _unit_rows(self.instance_vectors.array())


def _query_shape(query: SearchQuery) -> int:
    if type(query) is not SearchQuery:
        _reject("expected SearchQuery")
    _identifier(query.query_id)
    if type(query.source) is not FrameKey:
        _reject("expected query source FrameKey")
    query.source.__post_init__()
    _hash(query.source_content_sha256)
    cutoffs = _items(query.cutoffs, StreamCutoff, MAX_STREAMS)
    for cutoff in cutoffs:
        cutoff.__post_init__()
    if not cutoffs or len({c.stream_id for c in cutoffs}) != len(cutoffs):
        _reject("cutoffs require unique stream IDs")
    _identifier(query.semantic_space)
    _identifier(query.instance_space)
    elements = _vector_shape(query.semantic_vector) + _matrix_shape(query.instance_vectors)
    if not 1 <= query.instance_vectors.rows <= MAX_QUERY_REGIONS:
        _reject("query requires a bounded nonempty instance crop matrix")
    return elements


@dataclass(frozen=True, slots=True)
class SemanticFrame:
    frame: FrameRecord
    space_id: str
    vector: UnitVector

    def __post_init__(self) -> None:
        _semantic_shape(self)
        _unit_rows(self.vector.array())


def _record(record: FrameRecord) -> None:
    if type(record) is not FrameRecord:
        _reject("expected FrameRecord")
    record.__post_init__()


def _semantic_shape(frame: SemanticFrame) -> int:
    _record(frame.frame)
    _identifier(frame.space_id)
    return _vector_shape(frame.vector)


@dataclass(frozen=True, slots=True)
class FrameCrops:
    """Rows correspond to strictly increasing observation ordinals.

    A fallback is permitted only with zero proposals and is a full-frame
    descriptor, never an Observation. Space IDs should pin model/preprocessing.
    """

    frame: FrameRecord
    space_id: str
    vectors: UnitMatrix
    observations: tuple[Observation, ...]
    fallback: UnitVector | None = None

    def __post_init__(self) -> None:
        _crop_shape(self)
        _unit_rows(self.vectors.array())
        if self.fallback is not None:
            _unit_rows(self.fallback.array())


def _crop_shape(frame: FrameCrops) -> int:
    _record(frame.frame)
    _identifier(frame.space_id)
    elements = _matrix_shape(frame.vectors)
    observations = _items(frame.observations, Observation, MAX_REGIONS_PER_FRAME)
    if len(observations) != frame.vectors.rows:
        _reject("crop matrix rows differ from proposal count")
    ordinals: list[int] = []
    for observation in observations:
        observation.__post_init__()
        if (
            observation.stream_id != frame.frame.stream_id
            or observation.frame_id != frame.frame.frame_id
            or observation.timestamp_ms != frame.frame.timestamp_ms
        ):
            _reject("observation differs from its frame identity or timestamp")
        ordinals.append(observation.region_ordinal)
    if ordinals != sorted(set(ordinals)):
        _reject("proposal ordinals must be unique and increasing")
    if frame.fallback is not None:
        elements += _vector_shape(frame.fallback)
        if observations or frame.fallback.dimension != frame.vectors.dimension:
            _reject("full-frame fallback requires zero proposals and matching dimension")
    return elements


def _validate_records(query: SearchQuery, records: tuple[FrameRecord, ...]) -> None:
    cutoffs = {c.stream_id for c in query.cutoffs}
    keys: set[FrameKey] = set()
    times: set[tuple[str, int]] = set()
    for record in records:
        if record.stream_id not in cutoffs:
            _reject("missing explicit stream cutoff")
        if record.key in keys or (record.stream_id, record.timestamp_ms) in times:
            _reject("duplicate frame ID or inconsistent stream timestamp")
        if record.key == query.source and record.content_sha256 != query.source_content_sha256:
            _reject("query source content hash differs from gallery source")
        keys.add(record.key)
        times.add((record.stream_id, record.timestamp_ms))


def _validate_inputs(
    query: SearchQuery,
    semantic: tuple[SemanticFrame, ...],
    crops: tuple[FrameCrops, ...],
) -> None:
    # All shape/count/storage work is bounded before scanning values or scoring.
    elements = _query_shape(query)
    _items(semantic, SemanticFrame, MAX_FRAMES)
    _items(crops, FrameCrops, MAX_FRAMES)
    observation_count = 0
    for frame in semantic:
        elements += _semantic_shape(frame)
        if frame.space_id != query.semantic_space or frame.vector.dimension != (
            query.semantic_vector.dimension
        ):
            _reject("semantic scoring space or dimension mismatch")
    for crop in crops:
        elements += _crop_shape(crop)
        observation_count += len(crop.observations)
        if crop.space_id != query.instance_space or crop.vectors.dimension != (
            query.instance_vectors.dimension
        ):
            _reject("instance scoring space or dimension mismatch")
    if elements > MAX_VECTOR_ELEMENTS or observation_count > MAX_OBSERVATIONS:
        _reject("aggregate retained vector or observation bound exceeded")
    _validate_records(query, tuple(f.frame for f in semantic))
    _validate_records(query, tuple(f.frame for f in crops))
    _unit_rows(query.semantic_vector.array())
    _unit_rows(query.instance_vectors.array())
    for frame in semantic:
        _unit_rows(frame.vector.array())
    for crop in crops:
        _unit_rows(crop.vectors.array())
        if crop.fallback is not None:
            _unit_rows(crop.fallback.array())


def _eligible(query: SearchQuery, frame: FrameRecord, cutoffs: dict[str, int]) -> bool:
    return (
        frame.timestamp_ms < cutoffs[frame.stream_id]
        and frame.key != query.source
        and frame.content_sha256 != query.source_content_sha256
    )


def _budget(elements: int) -> None:
    if elements > MAX_SCORING_VECTOR_ELEMENTS:
        _reject("scoring vector scalar element bound exceeded")


def _cosine(left: UnitVector, right: UnitVector) -> float:
    a, b = left.array().astype(np.float64), right.array().astype(np.float64)
    return float(np.clip(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)), -1.0, 1.0))


def _cosines(left: UnitMatrix, right: UnitMatrix) -> DoubleArray:
    a, b = left.array().astype(np.float64), right.array().astype(np.float64)
    denominator = np.linalg.norm(a, axis=1)[:, None] * np.linalg.norm(b, axis=1)[None, :]
    return cast(DoubleArray, np.clip((a @ b.T) / denominator, -1.0, 1.0))


@dataclass(frozen=True, slots=True)
class SemanticHit:
    frame: FrameRecord
    semantic_cosine: float

    def __post_init__(self) -> None:
        _record(self.frame)
        _float(self.semantic_cosine, -1.0, 1.0)


@dataclass(frozen=True, slots=True)
class SemanticRanking:
    query: SearchQuery
    frames: tuple[SemanticFrame, ...]
    full_ranking: tuple[SemanticHit, ...]


def _rank_semantic(
    query: SearchQuery, frames: tuple[SemanticFrame, ...]
) -> tuple[SemanticHit, ...]:
    cutoffs = {c.stream_id: c.timestamp_ms for c in query.cutoffs}
    selected = tuple(f for f in frames if _eligible(query, f.frame, cutoffs))
    _budget(sum(f.vector.dimension for f in selected))
    hits = tuple(SemanticHit(f.frame, _cosine(query.semantic_vector, f.vector)) for f in selected)
    return tuple(sorted(hits, key=lambda h: (-h.semantic_cosine, h.frame.key)))


def rank_semantic(query: SearchQuery, frames: tuple[SemanticFrame, ...]) -> SemanticRanking:
    """Full-vector cosine ranking; exact score ties use (stream_id, frame_id)."""
    _validate_inputs(query, frames, ())
    return SemanticRanking(query, frames, _rank_semantic(query, frames))


class EvidenceKind(Enum):
    PROPOSAL = "proposal"
    FULL_FRAME_FALLBACK = "full_frame_fallback"


@dataclass(frozen=True, slots=True)
class InstanceMatch:
    kind: EvidenceKind
    cosine: float
    query_region_ordinal: int
    observation: Observation | None

    def __post_init__(self) -> None:
        _float(self.cosine, -1.0, 1.0)
        _integer(self.query_region_ordinal, MAX_QUERY_REGIONS - 1)
        if type(self.kind) is not EvidenceKind:
            _reject("invalid instance evidence kind")
        if self.kind is EvidenceKind.PROPOSAL:
            if type(self.observation) is not Observation:
                _reject("proposal score requires observation evidence")
            self.observation.__post_init__()
        elif self.observation is not None:
            _reject("full-frame fallback is not an object detection")


@dataclass(frozen=True, slots=True)
class InstanceHit:
    semantic: SemanticHit
    best_match: InstanceMatch | None

    @property
    def frame(self) -> FrameRecord:
        return self.semantic.frame

    @property
    def instance_cosine(self) -> float | None:
        return self.best_match.cosine if self.best_match is not None else None


@dataclass(frozen=True, slots=True)
class SearchResult:
    semantic: SemanticRanking
    top_k: int
    crops: tuple[FrameCrops, ...]
    shortlist: tuple[FrameKey, ...]
    staged_ranking: tuple[InstanceHit | SemanticHit, ...]

    @property
    def proposals_only_ranking(self) -> tuple[InstanceHit, ...]:
        """Proposal-backed shortlist results only; fallback winners are omitted."""
        return tuple(
            hit
            for hit in self.staged_ranking[: len(self.shortlist)]
            if type(hit) is InstanceHit
            and hit.best_match is not None
            and hit.best_match.kind is EvidenceKind.PROPOSAL
        )


def _instance_hit(semantic: SemanticHit, crop: FrameCrops, query: SearchQuery) -> InstanceHit:
    matrix = crop.vectors
    kind = EvidenceKind.PROPOSAL
    if not matrix.rows:
        if crop.fallback is None:
            return InstanceHit(semantic, None)
        matrix = UnitMatrix(crop.fallback.data, 1, crop.fallback.dimension)
        kind = EvidenceKind.FULL_FRAME_FALLBACK
    scores = _cosines(query.instance_vectors, matrix)
    # Crop ordinal first, then query ordinal: deterministic exact max ties.
    flat = int(np.argmax(scores.T))
    crop_index, query_index = divmod(flat, query.instance_vectors.rows)
    observation = crop.observations[crop_index] if kind is EvidenceKind.PROPOSAL else None
    match = InstanceMatch(kind, float(scores[query_index, crop_index]), query_index, observation)
    return InstanceHit(semantic, match)


def _rerank(ranking: SemanticRanking, crops: tuple[FrameCrops, ...], top_k: int) -> SearchResult:
    if type(ranking) is not SemanticRanking:
        _reject("expected SemanticRanking")
    _integer(top_k, MAX_FRAMES)
    _validate_inputs(ranking.query, ranking.frames, crops)
    # Bound combined recomputation before the first semantic or instance dot.
    cutoffs = {c.stream_id: c.timestamp_ms for c in ranking.query.cutoffs}
    cost = sum(
        f.vector.dimension for f in ranking.frames if _eligible(ranking.query, f.frame, cutoffs)
    )
    cost += sum(
        (f.vectors.rows + int(f.fallback is not None))
        * f.vectors.dimension
        * ranking.query.instance_vectors.rows
        for f in crops
    )
    _budget(cost)
    _items(ranking.full_ranking, SemanticHit, MAX_FRAMES)
    for hit in ranking.full_ranking:
        hit.__post_init__()
    if ranking.full_ranking != _rank_semantic(ranking.query, ranking.frames):
        _reject("semantic ranking differs from retained vector evidence")
    selected = ranking.full_ranking[:top_k]
    shortlist = tuple(hit.frame.key for hit in selected)
    index = {crop.frame.key: crop for crop in crops}
    if set(index) != set(shortlist):
        _reject("crop frame IDs must match exact semantic top-K membership")
    for hit in selected:
        if index[hit.frame.key].frame != hit.frame:
            _reject("crop metadata differs from retained semantic frame")
    prefix = tuple(_instance_hit(hit, index[hit.frame.key], ranking.query) for hit in selected)
    # Stable sorting retains semantic order for missing evidence and instance ties.
    ordered = tuple(
        sorted(
            prefix,
            key=lambda hit: (
                hit.instance_cosine is None,
                -hit.instance_cosine if hit.instance_cosine is not None else 0.0,
            ),
        )
    )
    return SearchResult(ranking, top_k, crops, shortlist, (*ordered, *ranking.full_ranking[top_k:]))


def rerank_shortlist(
    ranking: SemanticRanking, crops: tuple[FrameCrops, ...], top_k: int
) -> SearchResult:
    """Max query/crop instance cosine for exact top-K; retain semantic tail objects.

    K=0 is supported. K larger than the gallery selects the entire ranking.
    No evidence is represented by None, never a fabricated zero cosine.
    """
    return _rerank(ranking, crops, top_k)


def validate_search_result(result: SearchResult) -> SearchResult:
    """Recompute both spaces and require the original semantic full-tail objects."""
    if type(result) is not SearchResult:
        _reject("expected SearchResult")
    _items(result.shortlist, FrameKey, MAX_FRAMES)
    for key in result.shortlist:
        key.__post_init__()
    if type(result.staged_ranking) is not tuple or len(result.staged_ranking) > MAX_FRAMES:
        _reject("invalid staged ranking")
    for hit in result.staged_ranking:
        if type(hit) is SemanticHit:
            hit.__post_init__()
        elif type(hit) is InstanceHit and type(hit.semantic) is SemanticHit:
            hit.semantic.__post_init__()
            if hit.best_match is not None:
                if type(hit.best_match) is not InstanceMatch:
                    _reject("invalid instance match")
                hit.best_match.__post_init__()
        else:
            _reject("invalid staged hit type")
    expected = _rerank(result.semantic, result.crops, result.top_k)
    if result.shortlist != expected.shortlist or result.staged_ranking != expected.staged_ranking:
        _reject("staged result differs from recomputed vector evidence")
    count = len(expected.shortlist)
    if any(
        actual is not original
        for actual, original in zip(
            result.staged_ranking[count:], result.semantic.full_ranking[count:], strict=True
        )
    ):
        _reject("semantic tail objects must be retained unchanged")
    return result


@dataclass(frozen=True, slots=True)
class CoverageGap:
    """Unknown open interval (start_ms, end_ms); endpoints can be observed."""

    stream_id: str
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        _identifier(self.stream_id)
        _integer(self.start_ms)
        _integer(self.end_ms)
        if self.start_ms >= self.end_ms:
            _reject("coverage gap must have positive duration")


class GapReason(Enum):
    BETWEEN_OBSERVATIONS = "between_observations"
    RECORDED_GAP = "recorded_gap"
    SEQUENCE_BOUNDARY = "sequence_boundary"
    MAX_TIME_GAP = "max_time_gap"
    EXCLUDED_FRAME = "excluded_frame"
    NO_PROPOSALS = "no_proposals"


@dataclass(frozen=True, slots=True)
class UnknownGap:
    stream_id: str
    start_ms: int
    end_ms: int
    reason: GapReason

    def __post_init__(self) -> None:
        CoverageGap(self.stream_id, self.start_ms, self.end_ms)
        if type(self.reason) is not GapReason:
            _reject("invalid unknown-gap reason")


@dataclass(frozen=True, slots=True)
class AssociationLink:
    previous: ObservationKey
    current: ObservationKey
    cosine: float
    iou: float
    joint_score: float

    def __post_init__(self) -> None:
        for key in (self.previous, self.current):
            if type(key) is not ObservationKey:
                _reject("expected association observation key")
            key.__post_init__()
        if (
            self.previous.stream_id != self.current.stream_id
            or self.previous.frame_id == self.current.frame_id
        ):
            _reject("association must join different frames within one stream")
        _float(self.cosine, MIN_ASSOCIATION_COSINE, 1.0)
        _float(self.iou, MIN_ASSOCIATION_IOU, 1.0)
        _float(self.joint_score, 0.0, 1.0)
        if self.joint_score != (self.cosine + self.iou) / 2.0:
            _reject("association joint score differs from cosine and geometry")


@dataclass(frozen=True, slots=True)
class Tracklet:
    stream_id: str
    sequence_id: str
    observations: tuple[Observation, ...]
    links: tuple[AssociationLink, ...]

    def __post_init__(self) -> None:
        _identifier(self.stream_id)
        _identifier(self.sequence_id)
        _items(self.observations, Observation, MAX_FRAMES_PER_STREAM_WINDOW)
        _items(self.links, AssociationLink, MAX_FRAMES_PER_STREAM_WINDOW - 1)
        if not self.observations or len(self.links) != len(self.observations) - 1:
            _reject("tracklet requires nonempty support and one link per adjacent observation")
        for observation in self.observations:
            observation.__post_init__()
            if observation.stream_id != self.stream_id:
                _reject("tracklet observation crosses streams")
        for previous, current, link in zip(
            self.observations[:-1], self.observations[1:], self.links, strict=True
        ):
            link.__post_init__()
            if (
                not 0 < current.timestamp_ms - previous.timestamp_ms <= MAX_ASSOCIATION_GAP_MS
                or link.previous != previous.key
                or link.current != current.key
            ):
                _reject("tracklet links differ from ordered timestamp-bounded support")

    @property
    def first_observed_timestamp_ms(self) -> int:
        return self.observations[0].timestamp_ms

    @property
    def last_observed_timestamp_ms(self) -> int:
        return self.observations[-1].timestamp_ms

    @property
    def support_ids(self) -> tuple[ObservationKey, ...]:
        return tuple(observation.key for observation in self.observations)

    @property
    def unknown_gaps(self) -> tuple[UnknownGap, ...]:
        return tuple(
            UnknownGap(
                self.stream_id, a.timestamp_ms, b.timestamp_ms, GapReason.BETWEEN_OBSERVATIONS
            )
            for a, b in zip(self.observations, self.observations[1:], strict=False)
        )


@dataclass(frozen=True, slots=True)
class TrackletResult:
    query: SearchQuery
    frames: tuple[FrameCrops, ...]
    coverage_gaps: tuple[CoverageGap, ...]
    tracklets: tuple[Tracklet, ...]
    unknown_gaps: tuple[UnknownGap, ...]


def box_iou(left: NormalizedBox, right: NormalizedBox) -> float:
    """Intersection over union of two validated, positive-area normalized boxes."""
    if type(left) is not NormalizedBox or type(right) is not NormalizedBox:
        _reject("expected typed normalized boxes")
    left.__post_init__()
    right.__post_init__()
    width_left, height_left = left.x1 - left.x0, left.y1 - left.y0
    width_right, height_right = right.x1 - right.x0, right.y1 - right.y0
    # Scale each axis before multiplying: valid tiny boxes must not produce
    # zero-area underflow and division by zero. The common scale cancels in IoU.
    width_scale, height_scale = max(width_left, width_right), max(height_left, height_right)
    width_overlap = max(0.0, min(left.x1, right.x1) - max(left.x0, right.x0))
    height_overlap = max(0.0, min(left.y1, right.y1) - max(left.y0, right.y0))
    intersection = (width_overlap / width_scale) * (height_overlap / height_scale)
    area_left = (width_left / width_scale) * (height_left / height_scale)
    area_right = (width_right / width_scale) * (height_right / height_scale)
    return min(1.0, intersection / (area_left + area_right - intersection))


def _unique_best(scores: DoubleArray) -> list[int | None]:
    result: list[int | None] = []
    for row in scores:
        candidates = [int(i) for i in np.flatnonzero(np.isfinite(row))]
        candidates.sort(key=lambda i: (-float(row[i]), i))
        if not candidates or (
            len(candidates) > 1
            and float(row[candidates[0]] - row[candidates[1]]) < ASSOCIATION_AMBIGUITY_MARGIN
        ):
            result.append(None)
        else:
            result.append(candidates[0])
    return result


def _associate_pair(left: FrameCrops, right: FrameCrops) -> tuple[AssociationLink, ...]:
    cosine = _cosines(left.vectors, right.vectors)
    joint = np.full(cosine.shape, -np.inf, dtype=np.float64)
    overlaps = np.zeros(cosine.shape, dtype=np.float64)
    for i, a in enumerate(left.observations):
        for j, b in enumerate(right.observations):
            if a.class_id != b.class_id or float(cosine[i, j]) < MIN_ASSOCIATION_COSINE:
                continue
            overlap = box_iou(a.box, b.box)
            if overlap >= MIN_ASSOCIATION_IOU:
                overlaps[i, j] = overlap
                joint[i, j] = (float(cosine[i, j]) + overlap) / 2.0
    forward, backward = _unique_best(joint), _unique_best(joint.T)
    return tuple(
        AssociationLink(
            left.observations[i].key,
            right.observations[j].key,
            float(cosine[i, j]),
            float(overlaps[i, j]),
            float(joint[i, j]),
        )
        for i, j in enumerate(forward)
        if j is not None and backward[j] == i
    )


def _gap_reason(left: FrameCrops, right: FrameCrops, gaps: tuple[CoverageGap, ...]) -> GapReason:
    if left.frame.sequence_id != right.frame.sequence_id:
        return GapReason.SEQUENCE_BOUNDARY
    if any(
        g.start_ms < right.frame.timestamp_ms and g.end_ms > left.frame.timestamp_ms for g in gaps
    ):
        return GapReason.RECORDED_GAP
    if right.frame.timestamp_ms - left.frame.timestamp_ms > MAX_ASSOCIATION_GAP_MS:
        return GapReason.MAX_TIME_GAP
    if not left.observations or not right.observations:
        return GapReason.NO_PROPOSALS
    return GapReason.BETWEEN_OBSERVATIONS


def associate_tracklets(
    query: SearchQuery,
    frames: tuple[FrameCrops, ...],
    coverage_gaps: tuple[CoverageGap, ...] = (),
) -> TrackletResult:
    """Causal, same-stream adjacent-frame association with mutual unique bests.

    Class IDs must be equal, cosine >= .85, IoU >= .10, time gap <= 1500ms.
    Joint score is (cosine + IoU)/2; both directions need a >= .05 margin over
    every other eligible candidate. Exact ties therefore abstain. No smoothing,
    reacquisition across missing observations, merges, or cross-day identity.
    Input order must increase in timestamp within each stream; streams may be
    interleaved. The 64-frame limit counts all supplied frames, before filtering.
    """
    _items(frames, FrameCrops, MAX_FRAMES)
    groups: dict[str, list[FrameCrops]] = {}
    for frame in frames:
        _record(frame.frame)
        group = groups.setdefault(frame.frame.stream_id, [])
        if group and frame.frame.timestamp_ms <= group[-1].frame.timestamp_ms:
            _reject("stream frames must be in strictly increasing timestamp order")
        group.append(frame)
        if len(group) > MAX_FRAMES_PER_STREAM_WINDOW:
            _reject("tracklet stream window exceeds 64 supplied frames")
    _validate_inputs(query, (), frames)
    _items(coverage_gaps, CoverageGap, MAX_FRAMES)
    cutoffs = {c.stream_id: c.timestamp_ms for c in query.cutoffs}
    gaps_by_stream: dict[str, list[CoverageGap]] = {}
    for gap in coverage_gaps:
        gap.__post_init__()
        if gap.stream_id not in cutoffs:
            _reject("coverage gap lacks stream cutoff")
        gaps_by_stream.setdefault(gap.stream_id, []).append(gap)
    visible_gaps: dict[str, tuple[CoverageGap, ...]] = {}
    for stream, gaps in gaps_by_stream.items():
        ordered = sorted(gaps, key=lambda g: (g.start_ms, g.end_ms))
        if any(a.end_ms > b.start_ms for a, b in zip(ordered, ordered[1:], strict=False)):
            _reject("duplicate or overlapping coverage gaps")
        for gap in ordered:
            if any(
                gap.start_ms < f.frame.timestamp_ms < gap.end_ms for f in groups.get(stream, [])
            ):
                _reject("observed frame lies inside recorded missing-coverage interval")
        visible_gaps[stream] = tuple(
            CoverageGap(stream, g.start_ms, min(g.end_ms, cutoffs[stream]))
            for g in ordered
            if g.start_ms < cutoffs[stream]
        )
    # Remove future frames before preparing edges, ambiguity checks, or matching.
    visible = {
        stream: tuple(f for f in group if f.frame.timestamp_ms < cutoffs[stream])
        for stream, group in groups.items()
    }
    pairs: list[tuple[FrameCrops, FrameCrops]] = []
    unknown = [
        UnknownGap(g.stream_id, g.start_ms, g.end_ms, GapReason.RECORDED_GAP)
        for gaps in visible_gaps.values()
        for g in gaps
    ]
    selected: list[FrameCrops] = []
    for stream, visible_group in sorted(visible.items()):
        selected.extend(f for f in visible_group if _eligible(query, f.frame, cutoffs))
        for left, right in zip(visible_group, visible_group[1:], strict=False):
            reason = _gap_reason(left, right, visible_gaps.get(stream, ()))
            if not _eligible(query, left.frame, cutoffs) or not _eligible(
                query, right.frame, cutoffs
            ):
                reason = GapReason.EXCLUDED_FRAME
            unknown.append(
                UnknownGap(stream, left.frame.timestamp_ms, right.frame.timestamp_ms, reason)
            )
            if reason is GapReason.BETWEEN_OBSERVATIONS:
                pairs.append((left, right))
    _budget(sum(a.vectors.rows * b.vectors.rows * a.vectors.dimension for a, b in pairs))
    links = tuple(link for a, b in pairs for link in _associate_pair(a, b))
    predecessors = {link.current: link for link in links}
    chains: list[list[Observation]] = []
    chain_links: list[list[AssociationLink]] = []
    chain_sequences: list[str] = []
    owners: dict[ObservationKey, int] = {}
    for frame in selected:
        for observation in frame.observations:
            link = predecessors.get(observation.key)
            if link is None:
                index = len(chains)
                chains.append([])
                chain_links.append([])
                chain_sequences.append(frame.frame.sequence_id)
            else:
                index = owners[link.previous]
                chain_links[index].append(link)
            chains[index].append(observation)
            owners[observation.key] = index
    tracklets = tuple(
        Tracklet(chain[0].stream_id, sequence, tuple(chain), tuple(evidence))
        for chain, sequence, evidence in zip(chains, chain_sequences, chain_links, strict=True)
    )
    unknown_ordered = tuple(
        sorted(set(unknown), key=lambda g: (g.stream_id, g.start_ms, g.end_ms, g.reason.value))
    )
    return TrackletResult(query, frames, coverage_gaps, tracklets, unknown_ordered)


def validate_tracklet_result(result: TrackletResult) -> TrackletResult:
    """Recompute causal associations and unknown gaps from retained crop evidence."""
    if type(result) is not TrackletResult:
        _reject("expected TrackletResult")
    _items(result.tracklets, Tracklet, MAX_OBSERVATIONS)
    _items(result.unknown_gaps, UnknownGap, MAX_FRAMES * 2)
    if sum(len(t.observations) for t in result.tracklets) > MAX_OBSERVATIONS:
        _reject("tracklet output observation bound exceeded")
    for tracklet in result.tracklets:
        tracklet.__post_init__()
    for gap in result.unknown_gaps:
        gap.__post_init__()
    expected = associate_tracklets(result.query, result.frames, result.coverage_gaps)
    if result.tracklets != expected.tracklets or result.unknown_gaps != expected.unknown_gaps:
        _reject("tracklet result differs from recomputed observation evidence")
    return result
