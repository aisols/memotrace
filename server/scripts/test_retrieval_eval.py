"""Synthetic tests for generic blind and staged retrieval evaluation."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from typing import cast

import numpy as np
import pytest
from numpy.typing import NDArray

from scripts import retrieval_eval_core as core
from scripts import retrieval_eval_metrics as metrics
from scripts import verify_retrieval_eval as verifier


def vector(*values: float) -> NDArray[np.float32]:
    return np.asarray(values, dtype=np.float32)


def region(offset: float = 0.0) -> core.Region:
    return core.Region((offset, 0.0, min(offset + 0.4, 1.0), 0.5))


def indexed_frame(
    frame_number: int,
    rows: tuple[tuple[float, ...], ...],
    regions: tuple[core.Region, ...] | None = None,
) -> core.IndexedFrame:
    selected = regions or tuple(region(index * 0.1) for index in range(len(rows)))
    return core.IndexedFrame(
        frame_number=frame_number,
        vectors=np.asarray(rows, dtype=np.float32),
        regions=selected,
    )


def raw_indexed_frame(
    frame_number: int,
    vectors: NDArray[np.float32],
    regions: tuple[core.Region, ...],
) -> core.IndexedFrame:
    frame = object.__new__(core.IndexedFrame)
    object.__setattr__(frame, "frame_number", frame_number)
    object.__setattr__(frame, "vectors", vectors)
    object.__setattr__(frame, "regions", regions)
    return frame


def raw_stream_gallery(stream_id: str, frames: tuple[core.IndexedFrame, ...]) -> core.StreamGallery:
    gallery = object.__new__(core.StreamGallery)
    object.__setattr__(gallery, "stream_id", stream_id)
    object.__setattr__(gallery, "frames", frames)
    return gallery


def completed_run() -> core.CompletedBlindRun:
    queries = (
        core.BlindQuery("query-alpha", "stream-neutral", 7),
        core.BlindQuery("query-beta", "stream-neutral", 5),
    )
    plan = core.plan_blind_gallery(queries, 2)
    embeddings = (
        core.QueryEmbedding("query-alpha", vector(1.0, 0.0)),
        core.QueryEmbedding("query-beta", vector(0.0, 1.0)),
    )
    full_gallery = (
        core.StreamGallery(
            "stream-neutral",
            (
                indexed_frame(0, ((0.5, 0.1), (0.5, 0.9))),
                indexed_frame(2, ((0.4, 0.8),)),
                indexed_frame(4, ((0.9, 0.2),)),
                indexed_frame(6, ((0.3, 0.7),)),
            ),
        ),
    )
    full = core.rank_full_plan(plan, embeddings, full_gallery)
    shortlists = core.plan_shortlists(plan, full, 2)
    overlap_gallery = (
        core.StreamGallery(
            "stream-neutral",
            (
                indexed_frame(0, ((0.1, 0.4),)),
                indexed_frame(2, ((0.2, 0.3),)),
                indexed_frame(4, ((0.05, 0.2),)),
            ),
        ),
    )
    return core.complete_staged_run(
        plan, embeddings, full_gallery, full, shortlists, overlap_gallery
    )


def with_completed_query(
    run: core.CompletedBlindRun, offset: int, query: core.CompletedQuery
) -> core.CompletedBlindRun:
    return replace(run, queries=(*run.queries[:offset], query, *run.queries[offset + 1 :]))


def test_exact_exclusive_gallery_cadence() -> None:
    assert core.candidate_frames(11, 5) == (0, 5, 10)
    assert core.candidate_frames(10, 5) == (0, 5)


@pytest.mark.parametrize(
    ("cutoff", "stride"),
    ((True, 1), (1, True), (0, 1), (-1, 1), (1, 0), (1, -1)),
)
def test_gallery_cadence_rejects_bool_zero_and_negative(cutoff: object, stride: object) -> None:
    with pytest.raises(ValueError):
        core.candidate_frames(cast(int, cutoff), cast(int, stride))


def test_gallery_cadence_is_bounded_before_allocation() -> None:
    with pytest.raises(ValueError):
        core.candidate_frames(core.MAX_FRAME_NUMBER, 1)
    with pytest.raises(ValueError):
        core.candidate_frames(1, core.MAX_FRAME_NUMBER + 1)


def test_sorted_stream_union_preserves_each_query_cutoff() -> None:
    plan = core.plan_blind_gallery(
        (
            core.BlindQuery("query-late", "stream-z", 11),
            core.BlindQuery("query-early", "stream-z", 10),
            core.BlindQuery("query-other", "stream-a", 6),
        ),
        5,
    )
    assert tuple(item.stream_id for item in plan.gallery_work) == ("stream-a", "stream-z")
    assert plan.gallery_work == (
        core.StreamFrames("stream-a", (0, 5)),
        core.StreamFrames("stream-z", (0, 5, 10)),
    )
    assert plan.queries[0].candidates == (0, 5, 10)
    assert plan.queries[1].candidates == (0, 5)


def test_exact_integer_rate_mapping_and_narrow_claim() -> None:
    assert core.map_evaluation_frame(9, Fraction(24, 1), Fraction(6, 1)) == 36
    assert core.map_evaluation_frame(0, Fraction(7, 2), Fraction(7, 2)) == 0
    assert "not by PTS or VFR" in (core.map_evaluation_frame.__doc__ or "")


@pytest.mark.parametrize(
    ("frame", "source", "annotation"),
    (
        (True, Fraction(8, 1), Fraction(4, 1)),
        (-1, Fraction(8, 1), Fraction(4, 1)),
        (1, cast(Fraction, 8), Fraction(4, 1)),
        (1, Fraction(8, 1), Fraction(0, 1)),
        (1, Fraction(7, 1), Fraction(2, 1)),
        (1, Fraction(core.MAX_RATE_COMPONENT + 1, 1), Fraction(1, 1)),
        (core.MAX_FRAME_NUMBER, Fraction(2, 1), Fraction(1, 1)),
    ),
)
def test_rate_mapping_rejects_invalid_nonintegral_and_overflow_claims(
    frame: object, source: Fraction, annotation: Fraction
) -> None:
    with pytest.raises(ValueError):
        core.map_evaluation_frame(cast(int, frame), source, annotation)


def test_max_region_first_tie_and_frame_tie_order() -> None:
    first = region(0.0)
    second = region(0.2)
    gallery = core.StreamGallery(
        "stream-score",
        (
            indexed_frame(0, ((0.4, 0.0), (0.4, 1.0)), (first, second)),
            indexed_frame(5, ((0.7, 0.0),)),
            indexed_frame(10, ((0.7, 0.0),)),
        ),
    )
    ranked = core.rank_candidates(vector(1.0, 0.0), gallery, (0, 5, 10))
    assert tuple(item.frame_number for item in ranked) == (5, 10, 0)
    assert ranked[2].region_index == 0
    assert ranked[2].region is first
    core.validate_full_ranking(ranked, (0, 5, 10))


def test_public_scoring_work_cap_is_exact_and_precedes_dot_products(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gallery = core.StreamGallery(
        "stream-work",
        (indexed_frame(0, ((1.0, 0.0), (0.5, 0.5))),),
    )
    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_SCORING_VECTOR_ELEMENTS", 4)
        assert core.rank_candidates(vector(1.0, 0.0), gallery, (0,))[0].frame_number == 0

    def unexpected_dot(*values: object) -> tuple[core.ScoredFrame, ...]:
        raise AssertionError("dot product path was reached")

    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_SCORING_VECTOR_ELEMENTS", 3)
        limited.setattr(core, "_rank_candidates_validated", unexpected_dot)
        with pytest.raises(ValueError):
            core.rank_candidates(vector(1.0, 0.0), gallery, (0,))


def test_plan_scoring_cap_counts_shared_gallery_work_for_every_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries = tuple(
        core.BlindQuery(f"query-work-{offset}", "stream-shared-work", 2) for offset in range(3)
    )
    plan = core.plan_blind_gallery(queries, 1)
    embeddings = tuple(core.QueryEmbedding(query.query_id, vector(1.0, 0.0)) for query in queries)
    galleries = (
        core.StreamGallery(
            "stream-shared-work",
            (
                indexed_frame(0, ((1.0, 0.0),)),
                indexed_frame(1, ((0.5, 0.0),)),
            ),
        ),
    )
    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_SCORING_VECTOR_ELEMENTS", 12)
        assert len(core.rank_full_plan(plan, embeddings, galleries)) == 3

    def unexpected_dot(*values: object) -> tuple[core.ScoredFrame, ...]:
        raise AssertionError("dot product path was reached")

    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_SCORING_VECTOR_ELEMENTS", 11)
        limited.setattr(core, "_rank_candidates_validated", unexpected_dot)
        with pytest.raises(ValueError):
            core.rank_full_plan(plan, embeddings, galleries)


def test_staged_and_recomputed_scoring_caps_precede_dot_products(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries = (
        core.BlindQuery("query-stage-work-a", "stream-stage-work", 1),
        core.BlindQuery("query-stage-work-b", "stream-stage-work", 1),
    )
    plan = core.plan_blind_gallery(queries, 1)
    embeddings = tuple(core.QueryEmbedding(query.query_id, vector(1.0)) for query in queries)
    full_galleries = (core.StreamGallery("stream-stage-work", (indexed_frame(0, ((1.0,),)),)),)
    full = core.rank_full_plan(plan, embeddings, full_galleries)
    shortlists = core.plan_shortlists(plan, full, 1)
    overlap_galleries = (
        core.StreamGallery("stream-stage-work", (indexed_frame(0, ((0.5,), (0.25,))),)),
    )
    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_SCORING_VECTOR_ELEMENTS", 4)
        run = core.complete_staged_run(
            plan,
            embeddings,
            full_galleries,
            full,
            shortlists,
            overlap_galleries,
        )

    def unexpected_dot(*values: object) -> tuple[core.ScoredFrame, ...]:
        raise AssertionError("dot product path was reached")

    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_SCORING_VECTOR_ELEMENTS", 3)
        limited.setattr(core, "_rank_candidates_validated", unexpected_dot)
        with pytest.raises(ValueError):
            core.complete_staged_run(
                plan,
                embeddings,
                full_galleries,
                full,
                shortlists,
                overlap_galleries,
            )
    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_SCORING_VECTOR_ELEMENTS", 1)
        limited.setattr(core, "_rank_candidates_validated", unexpected_dot)
        with pytest.raises(ValueError):
            core.validate_completed_blind_run(run)
    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_SCORING_VECTOR_ELEMENTS", 3)
        calls = 0
        original = core._rank_candidates_validated

        def counted_dot(*values: object) -> tuple[core.ScoredFrame, ...]:
            nonlocal calls
            calls += 1
            return original(
                cast(core.FloatVector, values[0]),
                cast(dict[int, core.IndexedFrame], values[1]),
                cast(tuple[int, ...], values[2]),
            )

        limited.setattr(core, "_rank_candidates_validated", counted_dot)
        with pytest.raises(ValueError):
            core.validate_completed_blind_run(run)
        assert calls == 2


def test_shared_gallery_is_finite_validated_once_per_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries = tuple(
        core.BlindQuery(f"query-scan-{offset}", "stream-scan", 1) for offset in range(4)
    )
    plan = core.plan_blind_gallery(queries, 1)
    embeddings = tuple(core.QueryEmbedding(query.query_id, vector(1.0)) for query in queries)
    galleries = (core.StreamGallery("stream-scan", (indexed_frame(0, ((1.0,),)),)),)
    calls = 0
    original = core._validate_gallery

    def counted(value: object) -> core.StreamGallery:
        nonlocal calls
        calls += 1
        return original(value)

    monkeypatch.setattr(core, "_validate_gallery", counted)
    core.rank_full_plan(plan, embeddings, galleries)
    assert calls == 1


def test_exact_top_k_overlap_union_and_prefix_only_rescoring() -> None:
    run = completed_run()
    alpha, beta = run.queries
    assert alpha.shortlist == (4, 0)
    assert beta.shortlist == (0, 2)
    assert run.overlap_gallery_work == (core.StreamFrames("stream-neutral", (0, 2, 4)),)
    assert run.full_gallery_work == (core.StreamFrames("stream-neutral", (0, 2, 4, 6)),)
    assert run.stride == 2
    assert run.top_k == 2
    assert tuple(item.frame_number for item in alpha.staged_ranking) == (0, 4, 2, 6)
    assert alpha.staged_ranking[1].score < alpha.staged_ranking[2].score
    assert alpha.staged_ranking[2:] == alpha.full_ranking[2:]
    assert alpha.staged_ranking[2] is alpha.full_ranking[2]
    assert alpha.staged_ranking[3] is alpha.full_ranking[3]
    assert set(item.frame_number for item in beta.staged_ranking[:2]) == {0, 2}
    assert beta.staged_ranking[2].frame_number == 4
    assert beta.staged_ranking[2] is beta.full_ranking[2]
    assert core.validate_completed_blind_run(run) is run


def test_top_k_is_exactly_minimum_of_limit_and_candidate_count() -> None:
    query = core.BlindQuery("query-small", "stream-small", 3)
    plan = core.plan_blind_gallery((query,), 2)
    embeddings = (core.QueryEmbedding(query.query_id, vector(1.0)),)
    galleries = (
        core.StreamGallery(
            query.stream_id,
            (indexed_frame(0, ((0.2,),)), indexed_frame(2, ((0.1,),))),
        ),
    )
    full = core.rank_full_plan(plan, embeddings, galleries)
    assert core.plan_shortlists(plan, full, 1).queries[0].frames == (0,)
    assert core.plan_shortlists(plan, full, 8).queries[0].frames == (0, 2)


def test_inputs_are_copied_to_read_only_float32_arrays() -> None:
    source_vector = vector(1.0, 2.0)
    source_matrix = np.asarray(((1.0, 0.0),), dtype=np.float32)
    embedding = core.QueryEmbedding("query-copy", source_vector)
    frame = core.IndexedFrame(0, source_matrix, (region(),))
    source_vector[0] = 9.0
    source_matrix[0, 0] = 9.0
    assert embedding.vector.tolist() == [1.0, 2.0]
    assert frame.vectors.tolist() == [[1.0, 0.0]]
    assert not embedding.vector.flags.writeable
    assert not frame.vectors.flags.writeable
    with pytest.raises(ValueError):
        embedding.vector.setflags(write=True)
    with pytest.raises(ValueError):
        frame.vectors.setflags(write=True)
    with pytest.raises(ValueError):
        embedding.vector[0] = 3.0
    with pytest.raises(ValueError):
        frame.vectors[0, 0] = 3.0
    assert embedding == core.QueryEmbedding("query-copy", vector(1.0, 2.0))
    assert frame == indexed_frame(0, ((1.0, 0.0),))
    assert embedding != object()
    assert frame != object()


@pytest.mark.parametrize("forbidden", ("\x00", "\x7f", "\u0085", "\ud800", "\u200b"))
def test_identifiers_reject_controls_surrogates_and_format_characters(forbidden: str) -> None:
    with pytest.raises(ValueError):
        core.BlindQuery(f"query{forbidden}", "stream", 1)
    with pytest.raises(ValueError):
        metrics.QueryAnnotations(
            f"query{forbidden}", Fraction(2, 1), (metrics.FrameInterval(0, 0),)
        )
    assert core.BlindQuery("query-cafe-例", "stream-δοκιμή", 1).cutoff_frame == 1
    assert (
        metrics.QueryAnnotations(
            "query-cafe-例", Fraction(2, 1), (metrics.FrameInterval(0, 0),)
        ).query_id
        == "query-cafe-例"
    )


def test_sensitive_dataclass_representations_are_constant_shape_and_redacted() -> None:
    secret_region = core.Region((0.314159, 0.2, 0.7, 0.9))
    secret_frame = core.IndexedFrame(
        17,
        np.asarray(((12345.5,),), dtype=np.float32),
        (secret_region,),
    )
    secret_gallery = core.StreamGallery("stream-repr-secret", (secret_frame,))
    secret_embedding = core.QueryEmbedding("query-repr-secret", vector(12345.5))
    secret_score = core.ScoredFrame(17, 0.875, 0, secret_region)
    run = completed_run()
    annotations = (
        metrics.QueryAnnotations("query-alpha", Fraction(4, 1), (metrics.FrameInterval(0, 0),)),
        metrics.QueryAnnotations("query-beta", Fraction(4, 1), (metrics.FrameInterval(0, 0),)),
    )
    evaluation = metrics.evaluate_blind_run(run, annotations, (1, 2))
    represented = (
        secret_region,
        secret_frame,
        secret_gallery,
        secret_embedding,
        secret_score,
        run,
        run.plan,
        run.plan.queries[0],
        run.queries[0],
        run.shortlists,
        annotations[0],
        annotations[0].positive_intervals[0],
        evaluation,
        evaluation.queries[0],
        evaluation.summary,
        evaluation.summary.full,
        evaluation.summary.full.at_k[0],
    )
    rendered = "\n".join(repr(value) for value in represented)
    for secret in (
        "stream-repr-secret",
        "query-repr-secret",
        "query-alpha",
        "12345.5",
        "0.314159",
        "0.875",
    ):
        assert secret not in rendered
    assert len(repr(run)) < 160


def test_zero_stride_huge_matrix_is_rejected_before_copy() -> None:
    scalar = np.zeros((1,), dtype=np.float32)
    huge = np.lib.stride_tricks.as_strided(
        scalar,
        shape=(core.MAX_REGIONS_PER_FRAME, core.MAX_VECTOR_DIMENSION),
        strides=(0, 0),
        writeable=False,
    )
    assert huge.size > core.MAX_VECTOR_ELEMENTS_PER_FRAME
    with pytest.raises(ValueError):
        core.IndexedFrame(0, huge, (region(),) * core.MAX_REGIONS_PER_FRAME)


def test_completed_provenance_rejects_toggleable_array_storage() -> None:
    run = completed_run()
    owning_vector = vector(1.0, 0.0)
    owning_vector.flags.writeable = False
    forged_embedding = object.__new__(core.QueryEmbedding)
    object.__setattr__(forged_embedding, "query_id", "query-alpha")
    object.__setattr__(forged_embedding, "vector", owning_vector)
    with pytest.raises(ValueError):
        core.validate_completed_blind_run(
            replace(run, embeddings=(forged_embedding, run.embeddings[1]))
        )
    owning_vector.setflags(write=True)

    owning_matrix = np.asarray(((0.5, 0.1), (0.5, 0.9)), dtype=np.float32)
    owning_matrix.flags.writeable = False
    source_frame = run.full_galleries[0].frames[0]
    forged_frame = object.__new__(core.IndexedFrame)
    object.__setattr__(forged_frame, "frame_number", source_frame.frame_number)
    object.__setattr__(forged_frame, "vectors", owning_matrix)
    object.__setattr__(forged_frame, "regions", source_frame.regions)
    forged_gallery = core.StreamGallery(
        run.full_galleries[0].stream_id,
        (forged_frame, *run.full_galleries[0].frames[1:]),
    )
    with pytest.raises(ValueError):
        core.validate_completed_blind_run(replace(run, full_galleries=(forged_gallery,)))
    owning_matrix.setflags(write=True)


def test_planner_allocation_bounds_are_checked_before_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries = (
        core.BlindQuery("query-bound-a", "stream-bound", 2),
        core.BlindQuery("query-bound-b", "stream-bound", 2),
    )
    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_TOTAL_CANDIDATES", 4)
        assert (
            sum(len(query.candidates) for query in core.plan_blind_gallery(queries, 1).queries) == 4
        )
        limited.setattr(core, "MAX_TOTAL_CANDIDATES", 3)
        with pytest.raises(ValueError):
            core.plan_blind_gallery(queries, 1)
    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_CANDIDATES_PER_QUERY", 2)
        with pytest.raises(ValueError):
            core.candidate_frames(3, 1)
        with pytest.raises(ValueError):
            core.plan_blind_gallery((core.BlindQuery("query-wide", "stream", 3),), 1)
    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_QUERY_COUNT", 1)
        with pytest.raises(ValueError):
            core.plan_blind_gallery(queries, 1)
    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_STREAM_COUNT", 1)
        with pytest.raises(ValueError):
            core.plan_blind_gallery(
                (
                    core.BlindQuery("query-stream-a", "stream-a", 1),
                    core.BlindQuery("query-stream-b", "stream-b", 1),
                ),
                1,
            )


def test_retained_plan_revalidates_all_aggregate_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = completed_run()
    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_CANDIDATES_PER_QUERY", 3)
        with pytest.raises(ValueError):
            core.validate_completed_blind_run(run)
    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_TOTAL_CANDIDATES", 6)
        with pytest.raises(ValueError):
            core.validate_completed_blind_run(run)
    two_stream_plan = core.plan_blind_gallery(
        (
            core.BlindQuery("query-stream-one", "stream-one", 1),
            core.BlindQuery("query-stream-two", "stream-two", 1),
        ),
        1,
    )
    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_STREAM_COUNT", 1)
        with pytest.raises(ValueError):
            core.rank_full_plan(two_stream_plan, (), ())


def test_aggregate_query_and_gallery_vector_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = core.plan_blind_gallery(
        (
            core.BlindQuery("query-vector-a", "stream-vector-a", 1),
            core.BlindQuery("query-vector-b", "stream-vector-b", 1),
        ),
        1,
    )
    embeddings = (
        core.QueryEmbedding("query-vector-a", vector(1.0)),
        core.QueryEmbedding("query-vector-b", vector(1.0)),
    )
    galleries = (
        core.StreamGallery("stream-vector-a", (indexed_frame(0, ((1.0,),)),)),
        core.StreamGallery("stream-vector-b", (indexed_frame(0, ((1.0,),)),)),
    )
    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_TOTAL_QUERY_VECTOR_ELEMENTS", 1)
        with pytest.raises(ValueError):
            core.rank_full_plan(plan, embeddings, galleries)
    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_TOTAL_QUERY_VECTOR_BYTES", 7)
        with pytest.raises(ValueError):
            core.rank_full_plan(plan, embeddings, galleries)
    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_TOTAL_GALLERY_VECTOR_ELEMENTS", 1)
        with pytest.raises(ValueError):
            core.rank_full_plan(plan, embeddings, galleries)
    two_frame_gallery = core.StreamGallery(
        "stream-vector-a",
        (indexed_frame(0, ((1.0,),)), indexed_frame(1, ((1.0,),))),
    )
    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_TOTAL_GALLERY_VECTOR_ELEMENTS", 1)
        with pytest.raises(ValueError):
            core.rank_candidates(vector(1.0), two_frame_gallery, (0,))
        with pytest.raises(ValueError):
            core.StreamGallery("stream-new", two_frame_gallery.frames)
    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_VECTOR_BYTES_PER_FRAME", 3)
        with pytest.raises(ValueError):
            indexed_frame(0, ((1.0,),))
    with monkeypatch.context() as limited:
        limited.setattr(core, "MAX_QUERY_VECTOR_BYTES", 3)
        with pytest.raises(ValueError):
            core.QueryEmbedding("query-byte-bound", vector(1.0))


def test_primitive_validation_rejects_exact_type_shape_value_and_box_errors() -> None:
    with pytest.raises(ValueError):
        core.BlindQuery("", "stream", 1)
    with pytest.raises(ValueError):
        core.BlindQuery("query", "stream\n", 1)
    with pytest.raises(ValueError):
        core.BlindQuery("query", "stream", cast(int, True))
    with pytest.raises(ValueError):
        core.Region(cast(core.NormalizedBox, (0, 0.0, 1.0, 1.0)))
    with pytest.raises(ValueError):
        core.Region((0.0, 0.0, float("nan"), 1.0))
    with pytest.raises(ValueError):
        core.Region((0.5, 0.0, 0.5, 1.0))
    with pytest.raises(ValueError):
        core.IndexedFrame(0, cast(NDArray[np.float32], [[1.0]]), (region(),))
    with pytest.raises(ValueError):
        core.IndexedFrame(0, np.asarray((1.0,), dtype=np.float32), (region(),))
    with pytest.raises(ValueError):
        core.IndexedFrame(0, np.asarray(((1.0,),), dtype=np.float64), (region(),))
    with pytest.raises(ValueError):
        core.IndexedFrame(0, np.asarray(((float("inf"),),), dtype=np.float32), (region(),))
    with pytest.raises(ValueError):
        core.IndexedFrame(0, np.empty((0, 1), dtype=np.float32), ())
    with pytest.raises(ValueError):
        core.IndexedFrame(0, np.asarray(((1.0,), (2.0,)), dtype=np.float32), (region(),))
    with pytest.raises(ValueError):
        core.QueryEmbedding("query", cast(NDArray[np.float32], [1.0]))
    with pytest.raises(ValueError):
        core.QueryEmbedding("query", np.asarray(((1.0,),), dtype=np.float32))
    with pytest.raises(ValueError):
        core.QueryEmbedding("query", np.asarray((float("nan"),), dtype=np.float32))


def test_gallery_validation_rejects_empty_duplicate_unsorted_and_mixed_dimensions() -> None:
    one = indexed_frame(1, ((1.0,),))
    two = indexed_frame(2, ((1.0, 0.0),))
    with pytest.raises(ValueError):
        core.StreamGallery("stream", ())
    with pytest.raises(ValueError):
        core.StreamGallery("stream", cast(tuple[core.IndexedFrame, ...], (object(),)))
    with pytest.raises(ValueError):
        core.StreamGallery("stream", (one, one))
    with pytest.raises(ValueError):
        core.StreamGallery("stream", (two, one))
    with pytest.raises(ValueError):
        core.StreamGallery("stream", (one, two))


def test_ranking_revalidates_forged_gallery_structure() -> None:
    one = indexed_frame(0, ((1.0,),))
    two_rows = indexed_frame(0, ((1.0,), (0.5,)))
    mixed = indexed_frame(1, ((1.0, 0.0),))
    invalid_galleries = (
        raw_stream_gallery("stream", cast(tuple[core.IndexedFrame, ...], (object(),))),
        raw_stream_gallery(
            "stream",
            (
                raw_indexed_frame(
                    0,
                    one.vectors,
                    cast(tuple[core.Region, ...], (object(),)),
                ),
            ),
        ),
        raw_stream_gallery("stream", (raw_indexed_frame(0, two_rows.vectors, (region(),)),)),
        raw_stream_gallery("stream", (mixed, one)),
        raw_stream_gallery("stream", (one, mixed)),
    )
    for gallery in invalid_galleries:
        with pytest.raises(ValueError):
            core.rank_candidates(vector(1.0), gallery, (0,))


def test_planning_rejects_invalid_collection_and_duplicate_query_ids() -> None:
    with pytest.raises(ValueError):
        core.plan_blind_gallery(cast(tuple[core.BlindQuery, ...], []), 1)
    with pytest.raises(ValueError):
        core.plan_blind_gallery((), 1)
    with pytest.raises(ValueError):
        core.plan_blind_gallery(cast(tuple[core.BlindQuery, ...], (object(),)), 1)
    with pytest.raises(ValueError):
        core.plan_blind_gallery(
            (
                core.BlindQuery("query-duplicate", "stream-a", 2),
                core.BlindQuery("query-duplicate", "stream-b", 2),
            ),
            1,
        )


def test_ranking_rejects_missing_duplicate_dimension_and_nonfinite_scores() -> None:
    gallery = core.StreamGallery("stream", (indexed_frame(0, ((1.0,),)),))
    with pytest.raises(ValueError):
        core.rank_candidates(vector(1.0), gallery, (0, 0))
    with pytest.raises(ValueError):
        core.rank_candidates(vector(1.0), gallery, (0, 1))
    with pytest.raises(ValueError):
        core.rank_candidates(vector(1.0, 0.0), gallery, (0,))
    with pytest.raises(ValueError):
        core.rank_candidates(vector(1.0), cast(core.StreamGallery, object()), (0,))
    maximum = np.finfo(np.float32).max
    overflow_gallery = core.StreamGallery(
        "stream", (indexed_frame(0, ((float(maximum), float(maximum)),)),)
    )
    with np.errstate(over="ignore"), pytest.raises(ValueError):
        core.rank_candidates(vector(float(maximum), float(maximum)), overflow_gallery, (0,))


def test_complete_ranking_validation_rejects_bad_entries_membership_and_order() -> None:
    selected = region()
    first = core.ScoredFrame(0, 0.5, 0, selected)
    second = core.ScoredFrame(1, 0.4, 0, selected)
    with pytest.raises(ValueError):
        core.validate_full_ranking(cast(tuple[core.ScoredFrame, ...], (object(),)), (0,))
    with pytest.raises(ValueError):
        core.validate_full_ranking((first, first), (0, 1))
    with pytest.raises(ValueError):
        core.validate_full_ranking((second, first), (0, 1))
    with pytest.raises(ValueError):
        core.validate_full_ranking((replace(first, score=float("nan")),), (0,))
    with pytest.raises(ValueError):
        core.validate_full_ranking((replace(first, score=float(np.finfo(np.float64).max)),), (0,))
    with pytest.raises(ValueError):
        core.validate_full_ranking((replace(first, score=0.1),), (0,))
    with pytest.raises(ValueError):
        core.validate_full_ranking((replace(first, region_index=-1),), (0,))
    with pytest.raises(ValueError):
        core.validate_full_ranking((replace(first, region=cast(core.Region, object())),), (0,))
    with pytest.raises(ValueError):
        core.validate_full_ranking((), ())
    with pytest.raises(ValueError):
        core.validate_full_ranking((first,), (cast(int, True),))


def test_rank_full_requires_exact_embedding_and_gallery_sets() -> None:
    plan = core.plan_blind_gallery((core.BlindQuery("query", "stream", 2),), 1)
    embedding = core.QueryEmbedding("query", vector(1.0))
    gallery = core.StreamGallery(
        "stream", (indexed_frame(0, ((1.0,),)), indexed_frame(1, ((0.5,),)))
    )
    with pytest.raises(ValueError):
        core.rank_full_plan(plan, (), (gallery,))
    with pytest.raises(ValueError):
        core.rank_full_plan(plan, cast(tuple[core.QueryEmbedding, ...], (object(),)), (gallery,))
    with pytest.raises(ValueError):
        core.rank_full_plan(plan, (embedding, embedding), (gallery,))
    with pytest.raises(ValueError):
        core.rank_full_plan(plan, (embedding,), ())
    with pytest.raises(ValueError):
        core.rank_full_plan(plan, (embedding,), cast(tuple[core.StreamGallery, ...], (object(),)))
    with pytest.raises(ValueError):
        core.rank_full_plan(plan, (embedding,), (gallery, gallery))
    with pytest.raises(ValueError):
        core.rank_full_plan(
            plan,
            (embedding,),
            (core.StreamGallery("stream", (indexed_frame(0, ((1.0,),)),)),),
        )


def test_malformed_generated_plans_rankings_and_shortlists_are_rejected() -> None:
    plan = core.plan_blind_gallery((core.BlindQuery("query", "stream", 2),), 1)
    embedding = core.QueryEmbedding("query", vector(1.0))
    gallery = core.StreamGallery(
        "stream", (indexed_frame(0, ((1.0,),)), indexed_frame(1, ((0.5,),)))
    )
    full = core.rank_full_plan(plan, (embedding,), (gallery,))
    with pytest.raises(ValueError):
        core.rank_full_plan(cast(core.BlindPlan, object()), (embedding,), (gallery,))
    with pytest.raises(ValueError):
        core.rank_full_plan(replace(plan, queries=()), (embedding,), (gallery,))
    with pytest.raises(ValueError):
        core.rank_full_plan(
            replace(plan, queries=(plan.queries[0], plan.queries[0])),
            (embedding,),
            (gallery,),
        )
    with pytest.raises(ValueError):
        core.rank_full_plan(
            replace(
                plan,
                queries=(replace(plan.queries[0], candidates=(0,)),),
            ),
            (embedding,),
            (gallery,),
        )
    with pytest.raises(ValueError):
        core.rank_full_plan(replace(plan, gallery_work=()), (embedding,), (gallery,))
    with pytest.raises(ValueError):
        core.rank_full_plan(
            replace(
                plan,
                gallery_work=(
                    core.StreamFrames("stream-z", (0,)),
                    core.StreamFrames("stream-a", (0,)),
                ),
            ),
            (embedding,),
            (gallery,),
        )
    with pytest.raises(ValueError):
        core.rank_full_plan(
            replace(plan, gallery_work=(core.StreamFrames("stream", (0,)),)),
            (embedding,),
            (gallery,),
        )
    with pytest.raises(ValueError):
        core.plan_shortlists(plan, cast(tuple[core.QueryRanking, ...], (object(),)), 1)
    with pytest.raises(ValueError):
        core.plan_shortlists(plan, (replace(full[0], query_id="query-other"),), 1)
    with pytest.raises(ValueError):
        core.plan_shortlists(plan, (replace(full[0], stream_id="stream-other"),), 1)
    shortlists = core.plan_shortlists(plan, full, 1)
    overlap = (core.StreamGallery("stream", (indexed_frame(0, ((0.2,),)),)),)
    with pytest.raises(ValueError):
        core.complete_staged_run(
            plan,
            (embedding,),
            (gallery,),
            full,
            cast(core.ShortlistPlan, object()),
            overlap,
        )
    with pytest.raises(ValueError):
        core.complete_staged_run(
            plan,
            (embedding,),
            (gallery,),
            full,
            replace(
                shortlists,
                queries=cast(tuple[core.QueryShortlist, ...], (object(),)),
            ),
            overlap,
        )
    with pytest.raises(ValueError):
        core.complete_staged_run(
            plan,
            (embedding,),
            (gallery,),
            full,
            replace(
                shortlists,
                queries=(replace(shortlists.queries[0], query_id="query-other"),),
            ),
            overlap,
        )
    with pytest.raises(ValueError):
        core.complete_staged_run(
            plan,
            (embedding,),
            (gallery,),
            full,
            replace(
                shortlists,
                queries=(replace(shortlists.queries[0], frames=(1,)),),
            ),
            overlap,
        )
    with pytest.raises(ValueError):
        core.complete_staged_run(
            plan,
            (embedding,),
            (gallery,),
            full,
            replace(shortlists, overlap_work=(core.StreamFrames("stream", (1,)),)),
            overlap,
        )


def test_malformed_completed_blind_runs_are_rejected() -> None:
    run = completed_run()
    alpha, beta = run.queries
    malformed_runs = (
        cast(core.CompletedBlindRun, object()),
        replace(run, queries=()),
        replace(run, queries=(alpha, alpha)),
        replace(run, queries=(replace(alpha, candidates=(0,)), beta)),
        replace(run, queries=(replace(alpha, shortlist=(0, 4)), beta)),
        replace(
            run,
            queries=(
                replace(
                    alpha,
                    staged_ranking=cast(
                        tuple[core.ScoredFrame, ...],
                        (object(), *alpha.staged_ranking[1:]),
                    ),
                ),
                beta,
            ),
        ),
        replace(
            run,
            queries=(
                replace(
                    alpha,
                    staged_ranking=(
                        alpha.staged_ranking[0],
                        alpha.staged_ranking[0],
                        *alpha.staged_ranking[2:],
                    ),
                ),
                beta,
            ),
        ),
        replace(
            run,
            queries=(
                replace(
                    alpha,
                    staged_ranking=(
                        alpha.staged_ranking[1],
                        alpha.staged_ranking[0],
                        *alpha.staged_ranking[2:],
                    ),
                ),
                beta,
            ),
        ),
        replace(
            run,
            queries=(
                replace(
                    alpha,
                    staged_ranking=(
                        *alpha.staged_ranking[:2],
                        replace(alpha.staged_ranking[2], score=-0.8),
                        alpha.staged_ranking[3],
                    ),
                ),
                beta,
            ),
        ),
        replace(
            run,
            plan=replace(
                run.plan,
                gallery_work=(core.StreamFrames("stream-neutral", (0,)),),
            ),
        ),
        replace(
            run,
            shortlists=replace(
                run.shortlists,
                overlap_work=(core.StreamFrames("stream-neutral", (0,)),),
            ),
        ),
    )
    for malformed in malformed_runs:
        with pytest.raises(ValueError):
            core.validate_completed_blind_run(malformed)


def test_completed_run_recomputes_score_region_index_region_and_order_provenance() -> None:
    run = completed_run()
    alpha = run.queries[0]
    first, tied = alpha.full_ranking[:2]
    forged_score = with_completed_query(
        run,
        0,
        replace(
            alpha,
            full_ranking=(replace(first, score=0.8), *alpha.full_ranking[1:]),
        ),
    )
    alternate_region = run.full_galleries[0].frames[0].regions[1]
    forged_index = with_completed_query(
        run,
        0,
        replace(
            alpha,
            full_ranking=(
                first,
                replace(tied, region_index=1, region=alternate_region),
                *alpha.full_ranking[2:],
            ),
        ),
    )
    forged_equal_region = with_completed_query(
        run,
        0,
        replace(
            alpha,
            full_ranking=(
                replace(first, region=core.Region(first.region.box)),
                *alpha.full_ranking[1:],
            ),
        ),
    )
    forged_order = with_completed_query(
        run,
        0,
        replace(
            alpha,
            full_ranking=(
                alpha.full_ranking[1],
                alpha.full_ranking[0],
                *alpha.full_ranking[2:],
            ),
        ),
    )
    cloned_tail = replace(alpha.staged_ranking[2])
    forged_tail_identity = with_completed_query(
        run,
        0,
        replace(
            alpha,
            staged_ranking=(
                *alpha.staged_ranking[:2],
                cloned_tail,
                alpha.staged_ranking[3],
            ),
        ),
    )
    for forged in (
        forged_score,
        forged_index,
        forged_equal_region,
        forged_order,
        forged_tail_identity,
    ):
        with pytest.raises(ValueError):
            core.validate_completed_blind_run(forged)


def test_post_join_looking_rerank_and_metrics_join_are_rejected() -> None:
    run = completed_run()
    alpha = run.queries[0]
    promoted = replace(alpha.full_ranking[1], score=1.0)
    changed_query = replace(
        alpha,
        full_ranking=(promoted, alpha.full_ranking[0], *alpha.full_ranking[2:]),
        shortlist=(0, 4),
    )
    changed_shortlists = replace(
        run.shortlists,
        queries=(
            replace(run.shortlists.queries[0], frames=(0, 4)),
            run.shortlists.queries[1],
        ),
    )
    forged = replace(with_completed_query(run, 0, changed_query), shortlists=changed_shortlists)
    annotations = (
        metrics.QueryAnnotations("query-alpha", Fraction(4, 1), (metrics.FrameInterval(0, 0),)),
        metrics.QueryAnnotations("query-beta", Fraction(4, 1), (metrics.FrameInterval(0, 0),)),
    )
    with pytest.raises(ValueError):
        core.validate_completed_blind_run(forged)
    with pytest.raises(ValueError):
        metrics.evaluate_blind_run(forged, annotations, (1,))


def test_staged_prefix_score_index_and_equal_region_forgeries_are_rejected() -> None:
    run = completed_run()
    alpha = run.queries[0]
    prefix = alpha.staged_ranking[0]
    forged_prefixes = (
        replace(prefix, score=float(np.float32(0.125))),
        replace(prefix, region_index=1),
        replace(prefix, region=core.Region(prefix.region.box)),
    )
    annotations = (
        metrics.QueryAnnotations("query-alpha", Fraction(4, 1), (metrics.FrameInterval(0, 0),)),
        metrics.QueryAnnotations("query-beta", Fraction(4, 1), (metrics.FrameInterval(0, 0),)),
    )
    for forged_prefix in forged_prefixes:
        forged = with_completed_query(
            run,
            0,
            replace(
                alpha,
                staged_ranking=(forged_prefix, *alpha.staged_ranking[1:]),
            ),
        )
        with pytest.raises(ValueError):
            core.validate_completed_blind_run(forged)
        with pytest.raises(ValueError):
            metrics.evaluate_blind_run(forged, annotations, (1,))


def test_label_changes_after_completion_cannot_change_blind_outputs() -> None:
    run = completed_run()
    original_full = run.queries[0].full_ranking
    original_shortlist = run.queries[0].shortlist
    annotation_rows = [
        metrics.QueryAnnotations("query-alpha", Fraction(4, 1), (metrics.FrameInterval(0, 2),)),
        metrics.QueryAnnotations("query-beta", Fraction(4, 1), (metrics.FrameInterval(1, 1),)),
    ]
    first = metrics.evaluate_blind_run(run, tuple(annotation_rows), (1, 2, 3))
    annotation_rows[0] = metrics.QueryAnnotations(
        "query-alpha", Fraction(4, 1), (metrics.FrameInterval(3, 3),)
    )
    second = metrics.evaluate_blind_run(run, tuple(annotation_rows), (1, 2, 3))
    assert first != second
    assert run.queries[0].full_ranking is original_full
    assert run.queries[0].shortlist is original_shortlist


def test_post_ranking_metrics_capture_miss_and_captured_denominators() -> None:
    run = completed_run()
    evaluation = metrics.evaluate_blind_run(
        run,
        (
            metrics.QueryAnnotations("query-alpha", Fraction(4, 1), (metrics.FrameInterval(0, 2),)),
            metrics.QueryAnnotations("query-beta", Fraction(4, 1), (metrics.FrameInterval(1, 1),)),
        ),
        (1, 2, 3),
    )
    alpha, beta = evaluation.queries
    assert alpha.captured_positive_frames == (0, 2)
    assert alpha.full.conditional is not None
    assert alpha.full.conditional.average_precision == pytest.approx(7 / 12)
    assert alpha.full.conditional.reciprocal_rank == 0.5
    assert alpha.full.conditional.at_k[1] == metrics.ConditionalAtK(2, 1, 0.5)
    assert alpha.staged.conditional is not None
    assert alpha.staged.conditional.average_precision == pytest.approx(5 / 6)
    assert beta.captured_positive_frames == ()
    assert beta.nearest_cadence_distance_frames == 1
    assert beta.nearest_cadence_distance_seconds == 0.25
    assert beta.full.conditional is None
    assert beta.staged.conditional is None
    assert all(value.hit == 0 for value in beta.full.end_to_end_at_k)
    assert evaluation.summary.query_count == 2
    assert evaluation.summary.captured_query_count == 1
    assert evaluation.summary.capture_coverage == 0.5
    assert evaluation.summary.full.conditional_query_count == 1
    assert evaluation.summary.full.conditional_mean_average_precision == pytest.approx(7 / 12)
    assert evaluation.summary.full.at_k[1].conditional_mean_recall == 0.5
    assert evaluation.summary.full.at_k[1].end_to_end_mean_hit == 0.5
    assert evaluation.summary.staged.at_k[0].end_to_end_mean_hit == 0.5


@pytest.mark.parametrize(
    ("candidates", "intervals", "expected_captured", "expected_nearest"),
    (
        ((0, 5, 10), ((0, 0), (10, 10)), (0, 10), 0),
        ((0, 10), ((4, 6),), (), 4),
        ((1, 2), ((5, 7),), (), 3),
        ((8, 10), ((3, 4),), (), 4),
        ((2, 5, 8), ((1, 2), (5, 6)), (2, 5), 0),
    ),
)
def test_linear_interval_sweep_exact_edges_between_before_after_and_capture(
    candidates: tuple[int, ...],
    intervals: tuple[tuple[int, int], ...],
    expected_captured: tuple[int, ...],
    expected_nearest: int,
) -> None:
    captured, nearest, comparisons = metrics._sweep_candidates_and_intervals(
        candidates,
        tuple(metrics.FrameInterval(start, end) for start, end in intervals),
    )
    assert captured == expected_captured
    assert nearest == expected_nearest
    assert comparisons <= (2 * len(candidates)) + len(intervals)


def test_interval_sweep_comparison_count_is_linear_on_adversarial_interleaving() -> None:
    candidates = tuple(range(0, 2_000, 2))
    intervals = tuple(metrics.FrameInterval(frame, frame) for frame in range(1, 2_000, 2))
    captured, nearest, comparisons = metrics._sweep_candidates_and_intervals(candidates, intervals)
    assert captured == ()
    assert nearest == 1
    assert comparisons == 2_999
    assert comparisons <= (2 * len(candidates)) + len(intervals)


def test_annotation_join_rejects_missing_extra_and_duplicate_query_ids() -> None:
    run = completed_run()
    alpha = metrics.QueryAnnotations("query-alpha", Fraction(3, 1), (metrics.FrameInterval(0, 0),))
    beta = metrics.QueryAnnotations("query-beta", Fraction(3, 1), (metrics.FrameInterval(0, 0),))
    extra = metrics.QueryAnnotations("query-extra", Fraction(3, 1), (metrics.FrameInterval(0, 0),))
    with pytest.raises(ValueError):
        metrics.evaluate_blind_run(run, (alpha,), (1,))
    with pytest.raises(ValueError):
        metrics.evaluate_blind_run(run, (alpha, beta, extra), (1,))
    with pytest.raises(ValueError):
        metrics.evaluate_blind_run(run, (alpha, alpha), (1,))
    with pytest.raises(ValueError):
        metrics.evaluate_blind_run(
            run, cast(tuple[metrics.QueryAnnotations, ...], (object(), object())), (1,)
        )
    with pytest.raises(ValueError):
        metrics.evaluate_blind_run(run, cast(tuple[metrics.QueryAnnotations, ...], []), (1,))


def test_annotation_and_metric_cutoff_validation_is_explicit_and_bounded() -> None:
    with pytest.raises(ValueError):
        metrics.FrameInterval(cast(int, True), 1)
    with pytest.raises(ValueError):
        metrics.FrameInterval(2, 1)
    with pytest.raises(ValueError):
        metrics.QueryAnnotations("", Fraction(2, 1), (metrics.FrameInterval(0, 0),))
    with pytest.raises(ValueError):
        metrics.QueryAnnotations("query", cast(Fraction, 2), (metrics.FrameInterval(0, 0),))
    with pytest.raises(ValueError):
        metrics.QueryAnnotations("query", Fraction(0, 1), (metrics.FrameInterval(0, 0),))
    with pytest.raises(ValueError):
        metrics.QueryAnnotations("query", Fraction(2, 1), ())
    with pytest.raises(ValueError):
        metrics.QueryAnnotations(
            "query",
            Fraction(2, 1),
            (metrics.FrameInterval(2, 2), metrics.FrameInterval(0, 0)),
        )
    with pytest.raises(ValueError):
        metrics.QueryAnnotations(
            "query",
            Fraction(2, 1),
            (metrics.FrameInterval(0, 1), metrics.FrameInterval(1, 2)),
        )
    run = completed_run()
    annotations = (
        metrics.QueryAnnotations("query-alpha", Fraction(2, 1), (metrics.FrameInterval(0, 0),)),
        metrics.QueryAnnotations("query-beta", Fraction(2, 1), (metrics.FrameInterval(0, 0),)),
    )
    with pytest.raises(ValueError):
        metrics.evaluate_blind_run(run, annotations, ())
    with pytest.raises(ValueError):
        metrics.evaluate_blind_run(run, annotations, (cast(int, True),))
    with pytest.raises(ValueError):
        metrics.evaluate_blind_run(run, annotations, (2, 1))
    with pytest.raises(ValueError):
        metrics.evaluate_blind_run(run, annotations, (1, 1))
    leaking = (
        metrics.QueryAnnotations("query-alpha", Fraction(2, 1), (metrics.FrameInterval(7, 7),)),
        annotations[1],
    )
    with pytest.raises(ValueError):
        metrics.evaluate_blind_run(run, leaking, (1,))


def test_metric_allocation_bounds_reject_before_output_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = completed_run()
    annotations = (
        metrics.QueryAnnotations("query-alpha", Fraction(2, 1), (metrics.FrameInterval(0, 0),)),
        metrics.QueryAnnotations("query-beta", Fraction(2, 1), (metrics.FrameInterval(0, 0),)),
    )
    with monkeypatch.context() as limited:
        limited.setattr(metrics, "MAX_INTERVALS_PER_QUERY", 1)
        with pytest.raises(ValueError):
            metrics.QueryAnnotations(
                "query-intervals",
                Fraction(2, 1),
                (metrics.FrameInterval(0, 0), metrics.FrameInterval(2, 2)),
            )
    with monkeypatch.context() as limited:
        limited.setattr(metrics, "MAX_TOTAL_INTERVALS", 1)
        with pytest.raises(ValueError):
            metrics.evaluate_blind_run(run, annotations, (1,))
    with monkeypatch.context() as limited:
        limited.setattr(metrics, "MAX_QUERY_COUNT", 1)
        with pytest.raises(ValueError):
            metrics.evaluate_blind_run(run, annotations, (1,))
    with monkeypatch.context() as limited:
        limited.setattr(metrics, "MAX_METRIC_CUTOFF_COUNT", 1)
        with pytest.raises(ValueError):
            metrics.evaluate_blind_run(run, annotations, (1, 2))
    with monkeypatch.context() as limited:
        limited.setattr(metrics, "MAX_METRIC_AT_K_RECORDS", 9)
        with pytest.raises(ValueError):
            metrics.evaluate_blind_run(run, annotations, (1,))
    with pytest.raises(ValueError):
        metrics.evaluate_blind_run(run, annotations, (core.MAX_CANDIDATES_PER_QUERY + 1,))


def coverage_document(
    *,
    statements: object = 2,
    covered_statements: object = 2,
    branches: object = 1,
    covered_branches: object = 1,
) -> dict[str, object]:
    return {
        "files": {
            "source.py": {
                "summary": {
                    "num_statements": statements,
                    "covered_lines": covered_statements,
                    "num_branches": branches,
                    "covered_branches": covered_branches,
                }
            }
        }
    }


def test_coverage_report_validation_accepts_only_exact_runtime_checked_counts() -> None:
    assert verifier.validate_coverage_report(coverage_document(), ("source.py",)) == (
        verifier.CoverageCounts("source.py", 2, 2, 1, 1),
    )
    malformed: tuple[object, ...] = (
        [],
        {},
        {"files": []},
        {"files": {}},
        {"files": {"source.py": {"summary": {}}, "extra.py": {"summary": {}}}},
        {"files": {"source.py": []}},
        {"files": {"source.py": {"summary": []}}},
        coverage_document(statements=True),
        coverage_document(statements=-1),
        coverage_document(statements=0, covered_statements=0),
        coverage_document(statements=2, covered_statements=1),
        coverage_document(statements=1, covered_statements=2),
        coverage_document(branches=0, covered_branches=1),
    )
    for document in malformed:
        with pytest.raises(ValueError):
            verifier.validate_coverage_report(document, ("source.py",))
    with pytest.raises(ValueError):
        verifier.validate_coverage_report(coverage_document(), ())
    with pytest.raises(ValueError):
        verifier.validate_coverage_report(coverage_document(), ("source.py", "source.py"))
