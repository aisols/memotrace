"""Synthetic counterexamples and evidence-integrity checks, without model weights."""

from __future__ import annotations

import hashlib
import math
from dataclasses import FrozenInstanceError, replace
from typing import cast

import numpy as np
import pytest
from numpy.typing import NDArray

from scripts import object_search_core as core


def vector(*values: float) -> core.UnitVector:
    return core.UnitVector.from_array(np.asarray(values, dtype=np.float32))


def matrix(rows: tuple[tuple[float, ...], ...], dimension: int = 2) -> core.UnitMatrix:
    values = np.asarray(rows, dtype=np.float32) if rows else np.empty((0, dimension), np.float32)
    return core.UnitMatrix.from_array(values)


def digest(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


def record(
    name: str, timestamp: int, stream: str = "s", sequence: str = "sequence"
) -> core.FrameRecord:
    return core.FrameRecord(stream, name, timestamp, digest(f"{stream}/{name}"), sequence)


def query(cutoff: int = 10_000, streams: tuple[str, ...] = ("s",)) -> core.SearchQuery:
    return core.SearchQuery(
        "query",
        core.FrameKey("s", "source"),
        digest("s/source"),
        tuple(core.StreamCutoff(stream, cutoff) for stream in streams),
        "semantic-model/preprocess-v1",
        vector(1.0, 0.0),
        "dino-model/preprocess-v1",
        matrix(((1.0, 0.0),)),
    )


def box(x0: float = 0.0, x1: float = 0.5) -> core.NormalizedBox:
    return core.NormalizedBox(x0, 0.0, x1, 1.0)


def crops(
    frame: core.FrameRecord,
    rows: tuple[tuple[float, ...], ...] = ((1.0, 0.0),),
    boxes: tuple[core.NormalizedBox, ...] | None = None,
    classes: tuple[int, ...] | None = None,
    fallback: core.UnitVector | None = None,
) -> core.FrameCrops:
    observations = tuple(
        core.Observation(
            frame.stream_id,
            frame.frame_id,
            frame.timestamp_ms,
            i,
            classes[i] if classes is not None else 1,
            boxes[i] if boxes is not None else box(),
        )
        for i in range(len(rows))
    )
    return core.FrameCrops(frame, query().instance_space, matrix(rows), observations, fallback)


def semantic(frame: core.FrameRecord, cosine: float) -> core.SemanticFrame:
    return core.SemanticFrame(
        frame, query().semantic_space, vector(cosine, math.sqrt(1.0 - cosine**2))
    )


def run() -> core.SearchResult:
    frames = (record("a", 0), record("b", 500), record("c", 1_000))
    ranked = core.rank_semantic(
        query(), tuple(semantic(f, score) for f, score in zip(frames, (1.0, 0.8, 0.6), strict=True))
    )
    return core.rerank_shortlist(
        ranked,
        (crops(frames[0], ((0.0, 1.0),)), crops(frames[1], ((-1.0, 0.0),))),
        2,
    )


def support(result: core.TrackletResult) -> tuple[tuple[tuple[str, int], ...], ...]:
    return tuple(
        tuple((key.frame_id, key.region_ordinal) for key in track.support_ids)
        for track in result.tracklets
    )


def test_cross_space_prefix_is_not_globally_sorted_and_tail_is_identical() -> None:
    result = run()
    a, b, tail = result.staged_ranking
    assert type(a) is core.InstanceHit and type(b) is core.InstanceHit
    assert a.instance_cosine == 0.0
    assert b.instance_cosine == -1.0
    assert a.semantic.semantic_cosine == 1.0
    assert b.semantic.semantic_cosine == pytest.approx(0.8)
    assert type(tail) is core.SemanticHit and tail.semantic_cosine == pytest.approx(0.6)
    assert tail is result.semantic.full_ranking[2]
    assert core.validate_search_result(result) is result


def test_instance_reorders_only_exact_shortlist_by_max_query_crop_cosine() -> None:
    q = replace(query(), instance_vectors=matrix(((1.0, 0.0), (0.0, 1.0))))
    frames = (record("a", 0), record("b", 500), record("c", 1_000))
    ranked = core.rank_semantic(q, tuple(semantic(f, 1.0) for f in reversed(frames)))
    result = core.rerank_shortlist(
        ranked,
        (
            crops(frames[0], ((-1.0, 0.0),)),
            crops(frames[1], ((-1.0, 0.0), (0.0, 1.0))),
        ),
        2,
    )
    assert result.shortlist == (frames[0].key, frames[1].key)
    assert tuple(h.frame.frame_id for h in result.staged_ranking) == ("b", "a", "c")
    winner = result.staged_ranking[0]
    assert type(winner) is core.InstanceHit and winner.best_match is not None
    assert winner.best_match.query_region_ordinal == 1
    assert winner.best_match.observation is result.crops[1].observations[1]
    assert winner.semantic is ranked.full_ranking[1]
    core.validate_search_result(result)


def test_separate_model_spaces_can_have_different_dimensions() -> None:
    q = replace(query(), instance_vectors=matrix(((0.0, 0.0, 1.0),)))
    frame = record("a", 0)
    indexed = replace(crops(frame), vectors=matrix(((0.0, 0.0, 1.0),)))
    result = core.rerank_shortlist(core.rank_semantic(q, (semantic(frame, 0.8),)), (indexed,), 1)
    hit = result.staged_ranking[0]
    assert type(hit) is core.InstanceHit and hit.instance_cosine == 1.0
    core.validate_search_result(result)


def test_exact_ties_use_frame_key_then_semantic_order_and_crop_then_query_ordinal() -> None:
    q = replace(query(streams=("s", "t")), instance_vectors=matrix(((1.0, 0.0), (1.0, 0.0))))
    frames = (record("b", 0, "t"), record("b", 500), record("a", 0))
    ranked = core.rank_semantic(q, tuple(semantic(f, 1.0) for f in frames))
    assert tuple(hit.frame.key for hit in ranked.full_ranking) == tuple(
        sorted(f.key for f in frames)
    )
    result = core.rerank_shortlist(
        ranked, tuple(crops(f, ((1.0, 0.0), (1.0, 0.0))) for f in frames), 3
    )
    assert tuple(hit.frame.key for hit in result.staged_ranking) == result.shortlist
    for hit in result.staged_ranking:
        assert type(hit) is core.InstanceHit and hit.best_match is not None
        assert hit.best_match.query_region_ordinal == 0
        assert hit.best_match.observation is not None
        assert hit.best_match.observation.region_ordinal == 0


def test_exclusions_and_exclusive_per_stream_cutoffs_precede_scoring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    q = replace(
        query(streams=("s", "t")),
        cutoffs=(core.StreamCutoff("s", 1_000), core.StreamCutoff("t", 500)),
    )
    frames = (
        record("source", 0),
        replace(record("copy", 10, "t"), content_sha256=q.source_content_sha256),
        record("s-past", 999),
        record("s-cutoff", 1_000),
        record("t-past", 499, "t"),
        record("t-cutoff", 500, "t"),
    )
    indexed = tuple(semantic(f, 1.0) for f in frames)
    calls: list[core.UnitVector] = []
    original = core._cosine

    def score(left: core.UnitVector, right: core.UnitVector) -> float:
        calls.append(right)
        return original(left, right)

    monkeypatch.setattr(core, "_cosine", score)
    ranking = core.rank_semantic(q, indexed)
    assert len(calls) == 2
    assert tuple(h.frame.frame_id for h in ranking.full_ranking) == ("s-past", "t-past")


def test_empty_proposals_and_full_frame_fallback_have_distinct_evidence() -> None:
    frames = tuple(
        record(name, i * 100) for i, name in enumerate(("empty", "fallback", "proposal"))
    )
    ranked = core.rank_semantic(query(), tuple(semantic(f, 1.0) for f in frames))
    crop_frames = (
        crops(frames[0], ()),
        crops(frames[1], (), fallback=vector(1.0, 0.0)),
        crops(frames[2], ((0.8, 0.6),)),
    )
    result = core.rerank_shortlist(ranked, crop_frames, 3)
    assert tuple(h.frame.frame_id for h in result.staged_ranking) == (
        "fallback",
        "proposal",
        "empty",
    )
    winner = result.staged_ranking[0]
    empty = result.staged_ranking[-1]
    assert type(winner) is core.InstanceHit and winner.best_match is not None
    assert winner.best_match.kind is core.EvidenceKind.FULL_FRAME_FALLBACK
    assert winner.best_match.observation is None
    assert type(empty) is core.InstanceHit and empty.instance_cosine is None
    assert tuple(h.frame.frame_id for h in result.proposals_only_ranking) == ("proposal",)
    tracked = core.associate_tracklets(query(), crop_frames)
    assert support(tracked) == ((("proposal", 0),),)
    assert any(g.reason is core.GapReason.NO_PROPOSALS for g in tracked.unknown_gaps)
    core.validate_search_result(result)


def test_negative_proposal_score_still_precedes_missing_evidence() -> None:
    a, b = record("a", 0), record("b", 1)
    ranking = core.rank_semantic(query(), (semantic(a, 1.0), semantic(b, 0.8)))
    result = core.rerank_shortlist(ranking, (crops(a, ()), crops(b, ((-1.0, 0.0),))), 2)
    assert tuple(h.frame.frame_id for h in result.staged_ranking) == ("b", "a")


def test_zero_and_oversized_k_and_empty_gallery() -> None:
    ranking = run().semantic
    zero = core.rerank_shortlist(ranking, (), 0)
    assert zero.shortlist == ()
    assert all(a is b for a, b in zip(zero.staged_ranking, ranking.full_ranking, strict=True))
    all_frames = core.rerank_shortlist(ranking, tuple(crops(f.frame) for f in ranking.frames), 100)
    assert len(all_frames.shortlist) == 3
    empty = core.rerank_shortlist(core.rank_semantic(query(), ()), (), 2)
    assert empty.staged_ranking == ()
    assert core.associate_tracklets(query(), ()).tracklets == ()
    core.validate_search_result(zero)
    core.validate_search_result(all_frames)
    core.validate_search_result(empty)


@pytest.mark.parametrize("change", ("missing", "extra", "duplicate", "wrong-tail", "metadata"))
def test_crop_ids_must_be_exact_shortlist(change: str) -> None:
    result = run()
    selected = result.crops
    if change == "missing":
        selected = selected[:1]
    elif change == "extra":
        selected = (*selected, crops(result.semantic.frames[2].frame))
    elif change == "duplicate":
        selected = (selected[0], selected[0])
    elif change == "wrong-tail":
        selected = (selected[0], crops(result.semantic.frames[2].frame))
    else:
        selected = (selected[0], crops(replace(selected[1].frame, sequence_id="wrong")))
    with pytest.raises(ValueError):
        core.rerank_shortlist(result.semantic, selected, 2)


@pytest.mark.parametrize("change", ("score", "order", "kind", "query", "crop", "tail", "shortlist"))
def test_final_validation_recomputes_retained_evidence_and_rejects_tamper(change: str) -> None:
    result = run()
    first = result.staged_ranking[0]
    assert type(first) is core.InstanceHit and first.best_match is not None
    if change == "score":
        modified = replace(first, best_match=replace(first.best_match, cosine=0.5))
        result = replace(result, staged_ranking=(modified, *result.staged_ranking[1:]))
    elif change == "order":
        result = replace(result, staged_ranking=tuple(reversed(result.staged_ranking)))
    elif change == "kind":
        modified = replace(
            first,
            best_match=replace(
                first.best_match, kind=core.EvidenceKind.FULL_FRAME_FALLBACK, observation=None
            ),
        )
        result = replace(result, staged_ranking=(modified, *result.staged_ranking[1:]))
    elif change == "query":
        modified_query = replace(result.semantic.query, instance_vectors=matrix(((0.0, 1.0),)))
        result = replace(result, semantic=replace(result.semantic, query=modified_query))
    elif change == "crop":
        changed_crop = replace(result.crops[0], vectors=matrix(((1.0, 0.0),)))
        result = replace(result, crops=(changed_crop, *result.crops[1:]))
    elif change == "tail":
        tail = result.staged_ranking[-1]
        assert type(tail) is core.SemanticHit
        result = replace(result, staged_ranking=(*result.staged_ranking[:-1], replace(tail)))
    else:
        result = replace(result, shortlist=tuple(reversed(result.shortlist)))
    with pytest.raises(ValueError):
        core.validate_search_result(result)


def test_semantic_score_and_vector_tampering_cannot_define_the_shortlist() -> None:
    result = run()
    ranking = result.semantic
    changed_hit = replace(ranking.full_ranking[0], semantic_cosine=0.9)
    changed = replace(ranking, full_ranking=(changed_hit, *ranking.full_ranking[1:]))
    with pytest.raises(ValueError, match="retained vector"):
        core.rerank_shortlist(changed, result.crops, 2)
    changed_frame = replace(ranking.frames[0], vector=vector(-1.0, 0.0))
    with pytest.raises(ValueError, match="retained vector"):
        core.validate_search_result(
            replace(result, semantic=replace(ranking, frames=(changed_frame, *ranking.frames[1:])))
        )


def test_byte_backed_vectors_are_independent_even_if_source_or_view_metadata_changes() -> None:
    source = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    retained_matrix = core.UnitMatrix.from_array(source)
    retained_vector = core.UnitVector.from_array(source[0])
    source[:] = 0.0
    assert retained_matrix.array().tolist() == [[1.0, 0.0], [0.0, 1.0]]
    assert retained_vector.array().tolist() == [1.0, 0.0]
    view = retained_matrix.array()
    view.shape = (4,)
    assert retained_matrix.array().shape == (2, 2)
    for array in (retained_vector.array(), retained_matrix.array()):
        with pytest.raises(ValueError):
            array.flags.writeable = True
    with pytest.raises(FrozenInstanceError):
        retained_vector.dimension = 3  # type: ignore[misc]


@pytest.mark.parametrize(
    "values", ((0.0, 0.0), (2.0, 0.0), (1.001, 0.0), (float("nan"), 0.0), (float("inf"), 0.0))
)
def test_cosine_requires_finite_already_normalized_vectors(values: tuple[float, ...]) -> None:
    with pytest.raises(ValueError, match="unit normalized"):
        vector(*values)
    with pytest.raises(ValueError, match="unit normalized"):
        matrix((values,))


def test_near_unit_input_is_scored_as_cosine_not_unchecked_dot_product() -> None:
    q = replace(query(), semantic_vector=vector(1.000001, 0.0))
    frame = core.SemanticFrame(record("a", 0), q.semantic_space, vector(1.000001, 0.0))
    assert core.rank_semantic(q, (frame,)).full_ranking[0].semantic_cosine == 1.0


@pytest.mark.parametrize(
    "array",
    (
        np.asarray([1.0, 0.0], dtype=np.float64),
        np.asarray([], dtype=np.float32),
        np.asarray([[1.0, 0.0]], dtype=np.float32),
        np.zeros(core.MAX_VECTOR_DIMENSION + 1, dtype=np.float32),
    ),
)
def test_bad_vector_shape_dtype_and_dimension(array: NDArray[np.float32]) -> None:
    with pytest.raises(ValueError):
        core.UnitVector.from_array(array)


@pytest.mark.parametrize("value", (True, False, -1, 1.0, np.int64(1), core.MAX_EXACT_INTEGER + 1))
def test_exact_integer_fields_reject_coercion(value: object) -> None:
    number = cast(int, value)
    with pytest.raises(ValueError):
        replace(record("a", 0), timestamp_ms=number)
    with pytest.raises(ValueError):
        core.StreamCutoff("s", number)
    with pytest.raises(ValueError):
        replace(crops(record("a", 0)).observations[0], region_ordinal=number)
    with pytest.raises(ValueError):
        replace(crops(record("a", 0)).observations[0], class_id=number)
    with pytest.raises(ValueError):
        core.rerank_shortlist(run().semantic, (), number)


@pytest.mark.parametrize("identifier", ("", "\n", "a\u200bb", "x" * 513, True, 1))
def test_exact_identifier_validation(identifier: object) -> None:
    with pytest.raises(ValueError):
        core.FrameKey(cast(str, identifier), "a")


@pytest.mark.parametrize("hash_value", ("A" * 64, "a" * 63, "g" * 64, True))
def test_canonical_content_hashes(hash_value: object) -> None:
    with pytest.raises(ValueError):
        replace(record("a", 0), content_sha256=cast(str, hash_value))


def test_typed_boxes_and_observation_frame_consistency() -> None:
    observation = crops(record("a", 0)).observations[0]
    with pytest.raises(ValueError):
        replace(observation, box=cast(core.NormalizedBox, (0.0, 0.0, 0.5, 1.0)))
    for bad in (True, 0, float("nan"), -0.1, 1.1):
        with pytest.raises(ValueError):
            core.NormalizedBox(cast(float, bad), 0.0, 0.5, 1.0)
    with pytest.raises(ValueError):
        core.NormalizedBox(0.5, 0.0, 0.5, 1.0)
    original = crops(record("a", 0))
    for changed in (
        replace(observation, timestamp_ms=1),
        replace(observation, stream_id="t"),
        replace(observation, frame_id="b"),
    ):
        with pytest.raises(ValueError, match="identity or timestamp"):
            replace(original, observations=(changed,))
    with pytest.raises(ValueError, match="unique and increasing"):
        replace(original, vectors=matrix(((1.0, 0.0), (1.0, 0.0))), observations=(observation,) * 2)
    with pytest.raises(ValueError):
        replace(original, vectors=matrix(()))
    with pytest.raises(ValueError, match="zero proposals"):
        replace(original, fallback=vector(1.0, 0.0))


def test_duplicate_frames_timestamps_source_hash_and_cutoff_streams_rejected() -> None:
    frame = semantic(record("a", 0), 1.0)
    for frames in (
        (frame, frame),
        (frame, semantic(record("b", 0), 1.0)),
        (semantic(record("a", 0, "undeclared"), 1.0),),
        (semantic(replace(record("source", 0), content_sha256=digest("wrong")), 1.0),),
    ):
        with pytest.raises(ValueError):
            core.rank_semantic(query(), frames)
    with pytest.raises(ValueError):
        replace(query(), cutoffs=(core.StreamCutoff("s", 1), core.StreamCutoff("s", 2)))


def test_same_dimension_different_model_space_rejected_for_both_stages() -> None:
    result = run()
    with pytest.raises(ValueError, match="semantic scoring space"):
        core.rank_semantic(query(), (replace(result.semantic.frames[0], space_id="other"),))
    with pytest.raises(ValueError, match="instance scoring space"):
        core.rerank_shortlist(
            result.semantic, (replace(result.crops[0], space_id="other"), result.crops[1]), 2
        )


def test_operation_revalidates_forged_bytes_nonfinite_norm_and_exact_score_types() -> None:
    result = run()
    object.__setattr__(result.semantic.query.semantic_vector, "data", bytearray(8))
    with pytest.raises(ValueError, match="byte storage"):
        core.validate_search_result(result)
    for raw in (np.asarray([2.0, 0.0], np.float32), np.asarray([np.nan, 0.0], np.float32)):
        result = run()
        object.__setattr__(result.crops[0].vectors, "data", raw.tobytes())
        with pytest.raises(ValueError, match="unit normalized"):
            core.validate_search_result(result)
    result = run()
    object.__setattr__(result.semantic.full_ranking[0], "semantic_cosine", True)
    with pytest.raises(ValueError, match="finite float"):
        core.validate_search_result(result)


def test_two_distinct_appearances_cross_and_collide_without_merging() -> None:
    positions = (
        (box(0.0, 0.45), box(0.55, 1.0)),
        (box(0.2, 0.65), box(0.35, 0.8)),
        (box(0.3, 0.75), box(0.3, 0.75)),
        (box(0.5, 0.95), box(0.1, 0.55)),
    )
    frames = tuple(
        crops(record(f"f{i}", i * 500), ((1.0, 0.0), (0.0, 1.0)), positions[i]) for i in range(4)
    )
    result = core.associate_tracklets(query(), frames)
    assert support(result) == (
        (("f0", 0), ("f1", 0), ("f2", 0), ("f3", 0)),
        (("f0", 1), ("f1", 1), ("f2", 1), ("f3", 1)),
    )
    for tracklet in result.tracklets:
        assert tracklet.first_observed_timestamp_ms == 0
        assert tracklet.last_observed_timestamp_ms == 1_500
        assert len(tracklet.links) == 3
        assert len(tracklet.unknown_gaps) == 3
        assert all(g.reason is core.GapReason.BETWEEN_OBSERVATIONS for g in tracklet.unknown_gaps)
        assert all(link.cosine == 1.0 and link.iou >= 0.1 for link in tracklet.links)
    assert result.tracklets[0].observations[0] is frames[0].observations[0]


def test_identical_appearances_at_collision_abstain_in_both_directions() -> None:
    frames = tuple(
        crops(record(f"f{i}", i * 500), ((1.0, 0.0), (1.0, 0.0)), (box(), box())) for i in range(3)
    )
    result = core.associate_tracklets(query(), frames)
    assert len(result.tracklets) == 6
    assert all(len(track.observations) == 1 and not track.links for track in result.tracklets)
    assert result == core.associate_tracklets(query(), frames)


def test_geometry_can_disambiguate_identical_appearance_when_spatially_separated() -> None:
    frames = tuple(
        crops(
            record(f"f{i}", i * 500),
            ((1.0, 0.0), (1.0, 0.0)),
            (box(0.0, 0.4), box(0.6, 1.0)),
        )
        for i in range(2)
    )
    assert support(core.associate_tracklets(query(), frames)) == (
        (("f0", 0), ("f1", 0)),
        (("f0", 1), ("f1", 1)),
    )


@pytest.mark.parametrize("offset,linked", ((0.01, False), (0.1, True)))
def test_reverse_ambiguity_margin_prevents_many_to_one(offset: float, linked: bool) -> None:
    left = crops(record("a", 0), ((1.0, 0.0), (1.0, 0.0)), (box(), box(offset, 0.5 + offset)))
    right = crops(record("b", 500))
    result = core.associate_tracklets(query(), (left, right))
    assert sum(len(t.links) for t in result.tracklets) == int(linked)
    assert len(result.tracklets) == 3 - int(linked)
    if linked:
        assert support(result)[0] == (("a", 0), ("b", 0))


def test_forward_ambiguity_also_abstains_without_greedy_second_choices() -> None:
    left = crops(record("a", 0))
    right = crops(record("b", 500), ((1.0, 0.0), (1.0, 0.0)))
    assert len(core.associate_tracklets(query(), (left, right)).tracklets) == 3


@pytest.mark.parametrize(
    ("cosine", "right_box", "class_id", "timestamp", "linked"),
    (
        (0.851, box(), 1, 1_500, True),
        (0.849, box(), 1, 500, False),
        (1.0, box(0.46, 0.96), 1, 500, False),
        (1.0, box(), 2, 500, False),
        (1.0, box(), 1, 1_501, False),
    ),
)
def test_both_descriptor_and_geometry_class_and_time_gates_are_required(
    cosine: float, right_box: core.NormalizedBox, class_id: int, timestamp: int, linked: bool
) -> None:
    frames = (
        crops(record("a", 0)),
        crops(
            record("b", timestamp),
            ((cosine, math.sqrt(1.0 - cosine**2)),),
            (right_box,),
            (class_id,),
        ),
    )
    assert len(core.associate_tracklets(query(), frames).tracklets) == (1 if linked else 2)


def test_occlusion_empty_frame_and_partial_unmatched_do_not_reacquire_old_track() -> None:
    frames = (
        crops(record("a", 0), ((1.0, 0.0), (0.0, 1.0))),
        crops(record("b", 500), ((0.0, 1.0),)),
        crops(record("c", 1_000), ((1.0, 0.0), (0.0, 1.0))),
        crops(record("d", 1_200), ()),
        crops(record("e", 1_400)),
    )
    assert support(core.associate_tracklets(query(), frames)) == (
        (("a", 0),),
        (("a", 1), ("b", 0), ("c", 1)),
        (("c", 0),),
        (("e", 0),),
    )


def test_recorded_gap_and_sequence_boundary_reset_with_observation_evidence_preserved() -> None:
    frames = (
        crops(record("a", 0)),
        crops(record("b", 500)),
        crops(record("c", 1_000, sequence="next")),
        crops(record("d", 1_500, sequence="next")),
    )
    gap = core.CoverageGap("s", 100, 400)
    result = core.associate_tracklets(query(), frames, (gap,))
    assert support(result) == ((("a", 0),), (("b", 0),), (("c", 0), ("d", 0)))
    assert core.UnknownGap("s", 100, 400, core.GapReason.RECORDED_GAP) in result.unknown_gaps
    assert core.UnknownGap("s", 500, 1_000, core.GapReason.SEQUENCE_BOUNDARY) in result.unknown_gaps
    assert sum(len(t.observations) for t in result.tracklets) == 4


def test_same_source_and_hash_exclusions_do_not_bridge_the_missing_frame() -> None:
    q = query()
    for excluded in (
        record("source", 500),
        replace(record("copy", 500), content_sha256=q.source_content_sha256),
    ):
        result = core.associate_tracklets(
            q, (crops(record("a", 0)), crops(excluded), crops(record("b", 1_000)))
        )
        assert support(result) == ((("a", 0),), (("b", 0),))
        assert all(g.reason is core.GapReason.EXCLUDED_FRAME for g in result.unknown_gaps)


def test_stream_isolation_and_future_exclusion_before_ambiguity_checks() -> None:
    q = replace(
        query(streams=("s", "t")),
        cutoffs=(core.StreamCutoff("s", 1_000), core.StreamCutoff("t", 500)),
    )
    frames = (
        crops(record("a", 0)),
        crops(record("a", 0, "t")),
        crops(record("b", 500)),
        crops(record("b", 500, "t")),
        crops(record("future-collision", 1_000), ((1.0, 0.0), (1.0, 0.0))),
    )
    result = core.associate_tracklets(q, frames)
    assert support(result) == ((("a", 0), ("b", 0)), (("a", 0),))
    assert tuple(t.stream_id for t in result.tracklets) == ("s", "t")
    past = core.associate_tracklets(q, frames[:3])
    assert past.tracklets == result.tracklets
    assert past.unknown_gaps == result.unknown_gaps
    assert all(g.end_ms < 1_000 for g in result.unknown_gaps)


def test_coverage_is_clipped_to_cutoff_even_with_no_proposals() -> None:
    gaps = (core.CoverageGap("s", 100, 2_000), core.CoverageGap("s", 2_500, 3_000))
    result = core.associate_tracklets(query(cutoff=1_000), (), gaps)
    assert result.unknown_gaps == (core.UnknownGap("s", 100, 1_000, core.GapReason.RECORDED_GAP),)


def test_duplicate_and_time_inconsistency_rejected_for_tracklets() -> None:
    a, b = crops(record("a", 0)), crops(record("b", 500))
    for frames in ((a, a), (b, a), (a, crops(record("other", 0)))):
        with pytest.raises(ValueError):
            core.associate_tracklets(query(), frames)
    for gaps in (
        (core.CoverageGap("s", 1, 100),) * 2,
        (core.CoverageGap("s", 1, 100), core.CoverageGap("s", 50, 150)),
        (core.CoverageGap("s", 1, 600),),
        (core.CoverageGap("other", 1, 100),),
    ):
        with pytest.raises(ValueError):
            core.associate_tracklets(query(), (a, b), gaps)


def test_frame_and_window_caps_precede_array_scans(monkeypatch: pytest.MonkeyPatch) -> None:
    q = query()
    indexed = semantic(record("a", 0), 1.0)
    frames = tuple(crops(record(str(i), i)) for i in range(65))

    def forbidden(*args: object) -> None:
        pytest.fail("value scanning before count bound")

    monkeypatch.setattr(core, "_unit_rows", forbidden)
    with pytest.raises(ValueError, match="oversized"):
        core.rank_semantic(q, (indexed,) * (core.MAX_FRAMES + 1))
    with pytest.raises(ValueError, match="64 supplied"):
        core.associate_tracklets(q, frames)


def test_window_cap_accepts_64_and_counts_future_frames() -> None:
    frames = tuple(crops(record(str(i), i), ()) for i in range(65))
    assert core.associate_tracklets(query(cutoff=1), frames[:64]).tracklets == ()
    with pytest.raises(ValueError, match="64 supplied"):
        core.associate_tracklets(query(cutoff=1), frames)


@pytest.mark.parametrize("bound", ("MAX_VECTOR_ELEMENTS", "MAX_OBSERVATIONS"))
def test_aggregate_storage_and_observation_caps_precede_array_scans(
    bound: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    q = query()
    frames = (crops(record("a", 0)), crops(record("b", 500)))
    monkeypatch.setattr(core, bound, 1)

    def forbidden(*args: object) -> None:
        pytest.fail("scanning before aggregate bound")

    monkeypatch.setattr(core, "_unit_rows", forbidden)
    with pytest.raises(ValueError, match="aggregate"):
        core.associate_tracklets(q, frames)


def test_scoring_caps_cover_semantic_instance_and_pairwise_work_before_first_dot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = run()
    q = query()
    pair = (crops(record("a", 0)), crops(record("b", 500)))
    monkeypatch.setattr(core, "MAX_SCORING_VECTOR_ELEMENTS", 1)

    def forbidden(*args: object) -> None:
        pytest.fail("dot product before aggregate scoring bound")

    monkeypatch.setattr(core, "_cosine", forbidden)
    monkeypatch.setattr(core, "_cosines", forbidden)
    with pytest.raises(ValueError, match="scalar element"):
        core.rank_semantic(q, result.semantic.frames)
    with pytest.raises(ValueError, match="scalar element"):
        core.rerank_shortlist(result.semantic, result.crops, 2)
    with pytest.raises(ValueError, match="scalar element"):
        core.associate_tracklets(q, pair)


def test_scoring_budget_counts_all_query_crops_and_all_proposal_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    q = replace(query(), instance_vectors=matrix(((1.0, 0.0), (0.0, 1.0))))
    frame = record("a", 0)
    ranking = core.rank_semantic(q, (semantic(frame, 1.0),))
    first = crops(frame, ((1.0, 0.0), (0.0, 1.0)))
    second = crops(record("b", 500), ((1.0, 0.0), (0.0, 1.0)))
    monkeypatch.setattr(core, "MAX_SCORING_VECTOR_ELEMENTS", 9)
    # One semantic vector (2) + 2 query crops * 2 proposals * dimension 2 = 10.
    with pytest.raises(ValueError, match="scalar element"):
        core.rerank_shortlist(ranking, (first,), 1)
    monkeypatch.setattr(core, "MAX_SCORING_VECTOR_ELEMENTS", 10)
    core.rerank_shortlist(ranking, (first,), 1)
    monkeypatch.setattr(core, "MAX_SCORING_VECTOR_ELEMENTS", 7)
    with pytest.raises(ValueError, match="scalar element"):
        core.associate_tracklets(q, (first, second))
    monkeypatch.setattr(core, "MAX_SCORING_VECTOR_ELEMENTS", 8)
    assert len(core.associate_tracklets(q, (first, second)).tracklets) == 2


def test_matrix_query_and_region_shape_caps_are_exact() -> None:
    empty = matrix(())
    assert empty.rows == 0 and empty.array().shape == (0, 2)
    for args in ((b"", 0, 0), (b"", True, 2), (b"", 65, 2), (bytearray(8), 1, 2)):
        with pytest.raises(ValueError):
            core.UnitMatrix(*cast(tuple[bytes, int, int], args))
    with pytest.raises(ValueError):
        replace(query(), instance_vectors=empty)
    with pytest.raises(ValueError):
        replace(query(), instance_vectors=matrix(((1.0, 0.0),) * 33))
    with pytest.raises(ValueError):
        core.UnitMatrix.from_array(np.zeros((65, 2), dtype=np.float32))
    with pytest.raises(ValueError):
        core.UnitMatrix.from_array(np.zeros((1, 8_193), dtype=np.float32))


def test_iou_is_actual_union_geometry() -> None:
    assert core.box_iou(box(), box()) == 1.0
    assert core.box_iou(box(0.0, 0.5), box(0.25, 0.75)) == pytest.approx(1.0 / 3.0)
    assert core.box_iou(box(0.0, 0.4), box(0.6, 1.0)) == 0.0


def test_valid_tiny_boxes_do_not_underflow_to_zero_union() -> None:
    tiny = float.fromhex("0x0.0000000000001p-1022")
    square = core.NormalizedBox(0.0, 0.0, tiny, tiny)
    assert core.box_iou(square, square) == 1.0
    wide = core.NormalizedBox(0.0, 0.0, 1.0, tiny)
    tall = core.NormalizedBox(0.0, 0.0, tiny, 1.0)
    assert math.isfinite(core.box_iou(wide, tall))


def test_tracklet_validation_recomputes_descriptors_links_support_and_unknown_gaps() -> None:
    frames = (crops(record("a", 0)), crops(record("b", 500)))
    result = core.associate_tracklets(query(), frames)
    assert core.validate_tracklet_result(result) is result
    changed = replace(frames[1], vectors=matrix(((0.0, 1.0),)))
    with pytest.raises(ValueError, match="recomputed"):
        core.validate_tracklet_result(replace(result, frames=(frames[0], changed)))
    with pytest.raises(ValueError, match="recomputed"):
        core.validate_tracklet_result(replace(result, unknown_gaps=()))
    link = replace(result.tracklets[0].links[0], cosine=0.9, joint_score=0.95)
    track = replace(result.tracklets[0], links=(link,))
    with pytest.raises(ValueError, match="recomputed"):
        core.validate_tracklet_result(replace(result, tracklets=(track,)))
    with pytest.raises(ValueError, match="recomputed"):
        core.validate_tracklet_result(replace(result, query=query(cutoff=500)))
    first = replace(result.tracklets[0].observations[0], box=box(0.1, 0.6))
    track = replace(result.tracklets[0], observations=(first, result.tracklets[0].observations[1]))
    with pytest.raises(ValueError, match="recomputed"):
        core.validate_tracklet_result(replace(result, tracklets=(track,)))


def test_real_retained_vector_bound_uses_scalar_elements_with_shared_byte_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 65 references to a 64x8192 crop matrix exceed 33,554,432 scalar elements,
    # even though immutable byte storage is shared and consumes only 2 MiB here.
    direction = np.full(8_192, 1.0 / math.sqrt(8_192), dtype=np.float32)
    descriptor = core.UnitVector.from_array(direction)
    q = replace(query(), instance_vectors=core.UnitMatrix(descriptor.data, 1, 8_192))
    descriptors = core.UnitMatrix(descriptor.data * 64, 64, 8_192)
    frames = tuple(record(str(i), i) for i in range(65))
    ranking = core.rank_semantic(q, tuple(semantic(f, 1.0) for f in frames))
    crop_frames = tuple(
        core.FrameCrops(
            f,
            q.instance_space,
            descriptors,
            tuple(
                core.Observation("s", f.frame_id, f.timestamp_ms, i, 1, box()) for i in range(64)
            ),
        )
        for f in frames
    )

    def forbidden(*args: object) -> None:
        pytest.fail("scanning before actual scalar element bound")

    monkeypatch.setattr(core, "_unit_rows", forbidden)
    with pytest.raises(ValueError, match="aggregate"):
        core.rerank_shortlist(ranking, crop_frames, 65)
