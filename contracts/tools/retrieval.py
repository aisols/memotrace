"""Supplemental instance-local retrieval invariants, not a search implementation.

JSON Schema handles structure and bounds. These checks express comparisons it
cannot express. Request context optionally checks returned cutoff/threshold/limit
consistency. Actual authorization, ranking, omitted evidence, timestamp provenance
and index snapshot truth remain server integration-test obligations.

SPDX-License-Identifier: AGPL-3.0-only
"""

from decimal import Decimal
import math

from tools.contract import Contract, walk


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _box(box):
    _require(box[0] < box[2] and box[1] < box[3], "Box must have positive width and height")


def _hit(hit, archive_id=None):
    _box(hit["region"]["box"])
    path = hit["original_path"].split("/")
    _require(path[6] == hit["asset_id"], "Original path asset identity mismatch")
    if archive_id is not None:
        _require(path[3] == archive_id, "Original path archive identity mismatch")


def _coverage(coverage):
    _require(coverage["assets_total"] == sum(coverage[key] for key in ("assets_indexed", "pending", "failed")), "Coverage partition mismatch")
    _require(coverage["regions_indexed"] >= coverage["assets_indexed"], "Indexed assets require regions")
    _require(coverage["assets_indexed"] != 0 or coverage["regions_indexed"] == 0, "Regions require indexed assets")


def _clock(hit, timeline):
    if timeline is None:
        return None
    if timeline["kind"] == "wall":
        return hit["observed_at_ms"]
    if hit["sequence_id"] == timeline["sequence_id"]:
        return hit["sequence_position_ms"]
    return None


def _observation(observation, archive_id=None):
    _require(observation["start_ms"] <= observation["end_ms"], "Observation time bounds reversed")
    _require(observation["max_score"] >= max(hit["score"] for hit in observation["evidence"]), "Observation score below evidence")
    for hit in observation["evidence"]:
        _hit(hit, archive_id)


def _history(history, request):
    timeline = history["timeline"]
    for hit in history["unsequenced_hits"]:
        _require(_clock(hit, timeline) is None, "Selected-clock evidence cannot be unsequenced")
    if history["history_available"]:
        _require(history["first_observed_ms"] <= history["last_observed_ms"], "History time bounds reversed")
    previous_end = None
    gap = request.get("gap_ms", 30000) if request is not None else None
    for observation in history["observations"]:
        _observation(observation, history["archive_id"])
        start, end = observation["start_ms"], observation["end_ms"]
        _require(history["first_observed_ms"] <= start <= end <= history["last_observed_ms"], "Observation outside history bounds")
        if gap == 0:
            _require(start == end, "Zero-gap observation must have one timestamp")
        if previous_end is not None:
            _require(previous_end < start, "Observation groups overlap or are out of order")
            if gap is not None:
                _require(start - previous_end > gap, "Observation groups must be separated by more than gap_ms")
        previous_end = end
        times = []
        keys = []
        for hit in observation["evidence"]:
            time = _clock(hit, timeline)
            _require(time is not None, "Observation evidence lacks the selected clock")
            _require(start <= time <= end, "Evidence timestamp outside observation bounds")
            times.append(time)
            keys.append((time, hit["asset_id"]))
        _require(keys == sorted(keys), "Observation evidence is not in chronological order")
        if not history["truncated"]:
            _require(start == times[0] and end == times[-1], "Untruncated observation bounds must match evidence")
            _require(observation["max_score"] == max(hit["score"] for hit in observation["evidence"]), "Untruncated observation score must match evidence")
            if gap is not None:
                _require(all(right - left <= gap for left, right in zip(times, times[1:])), "Untruncated observation spans a gap_ms break")
    if history["history_available"] and not history["truncated"]:
        _require(history["first_observed_ms"] == history["observations"][0]["start_ms"]
                 and history["last_observed_ms"] == history["observations"][-1]["end_ms"], "Untruncated history bounds must match observations")


def _request_context(definition, response, hits, request):
    _require(response["generation_id"] == request["generation_id"], "Response generation differs from request")
    _require(len(hits) <= request.get("limit", 20), "Evidence exceeds requested limit")
    timeline = request.get("timeline")
    if definition == "HistoryResponse":
        _require(response["timeline"] == timeline, "Response timeline differs from request")
    cutoff = request.get("before_ms")
    for hit in hits:
        _require(hit["score"] >= request.get("min_score", -1), "Evidence below requested threshold")
        _require(hit["asset_id"] != request["query"].get("asset_id"), "Query source asset included in evidence")
        if cutoff is not None:
            time = _clock(hit, timeline)
            _require(time is not None and time < cutoff, "Evidence does not satisfy exclusive cutoff")
    if definition == "HistoryResponse" and cutoff is not None and response["history_available"]:
        _require(response["last_observed_ms"] < cutoff, "History bounds do not satisfy exclusive cutoff")


def validate(definition, instance, contract=None, *, request=None):
    """Validate a retrieval definition plus finite numbers and local relationships.

    Use tools.contract.parse_json for lossless wire decoding first. In-memory
    float/Decimal non-finites are rejected here even though they are not JSON.
    Optional request is a decoded SearchRequest/HistoryRequest for the matching
    response family, not raw bytes. Its schema/geometry are validated too. Without
    it there is no inference about cutoff, threshold, limit or selected gap.
    Supplemental semantic errors deliberately omit all supplied content.
    """
    for _, value in walk(instance):
        if isinstance(value, Decimal):
            _require(value.is_finite(), "Non-finite number")
        elif isinstance(value, float):
            _require(math.isfinite(value), "Non-finite number")
    contract = contract or Contract(family="retrieval")
    if contract.family != "retrieval":
        raise ValueError("Retrieval family required")
    contract.validator(definition).validate(instance)
    if request is not None:
        _require(definition in {"SearchResponse", "HistoryResponse"}, "Request context requires a retrieval response")
        validate(definition.replace("Response", "Request"), request, contract)
    if definition == "Box":
        _box(instance)
    elif definition == "Region":
        _box(instance["box"])
    elif definition in {"Query", "ImageQuery", "SearchRequest", "HistoryRequest"}:
        query = instance.get("query", instance)
        if "box" in query:
            _box(query["box"])
    elif definition == "Coverage":
        _coverage(instance)
    elif definition == "Hit":
        _hit(instance)
    elif definition == "Observation":
        _observation(instance)
    elif definition in {"SearchResponse", "HistoryResponse"}:
        _coverage(instance["coverage"])
        _require(instance["truncated"] or instance["coverage"]["pending"] == instance["coverage"]["failed"] == 0,
                 "Incomplete index coverage requires truncated true")
        hits = instance.get("hits", instance.get("unsequenced_hits", []))[:]
        if definition == "HistoryResponse":
            _history(instance, request)
            for observation in instance["observations"]:
                hits.extend(observation["evidence"])
        _require(len(hits) <= 100, "Total evidence exceeds public limit")
        _require(len({hit["asset_id"] for hit in hits}) == len(hits), "Duplicate asset evidence")
        for hit in hits:
            _hit(hit, instance["archive_id"])
        if request is not None:
            _request_context(definition, instance, hits, request)
