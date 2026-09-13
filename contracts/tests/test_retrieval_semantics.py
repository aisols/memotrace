"""Raw-wire regressions for locally derivable retrieval response semantics.

SPDX-License-Identifier: AGPL-3.0-only
"""

from copy import deepcopy
from decimal import Decimal, localcontext
import unittest

from jsonschema.exceptions import ValidationError

from tools.contract import parse_json
from tools.retrieval import validate
from test_retrieval import CONTRACT, VALID, raw_document


def hit(number=1, *, wall=None, sequence=None, position=None):
    value = deepcopy(VALID["Hit"])
    asset = f"00000000-0000-0000-0000-{number:012x}"
    value.update(asset_id=asset, observed_at_ms=wall, sequence_id=sequence,
                 sequence_position_ms=position,
                 dataset={"name": "synthetic-clock-test", "version": "1", "item_id": str(number)},
                 original_path=VALID["OriginalPath"].replace(VALID["UUID"], asset))
    return value


def observation(start, end, *evidence):
    return {"start_ms": start, "end_ms": end, "max_score": max(h["score"] for h in evidence), "evidence": list(evidence)}


def history(timeline, observations=(), unsequenced=(), *, truncated=False, bounds=None):
    value = deepcopy(VALID["HistoryResponse"])
    value.update(timeline=timeline, observations=list(observations), unsequenced_hits=list(unsequenced), truncated=truncated)
    count = sum(len(o["evidence"]) for o in observations) + len(unsequenced)
    # An extra indexed asset can represent omitted evidence in truncated fixtures.
    indexed = max(1, count + int(truncated))
    value["coverage"] = {"assets_total": indexed, "assets_indexed": indexed, "pending": 0, "failed": 0, "regions_indexed": indexed}
    if bounds is None and observations:
        bounds = (min(o["start_ms"] for o in observations), max(o["end_ms"] for o in observations))
    value["history_available"] = bounds is not None
    value["first_observed_ms"], value["last_observed_ms"] = bounds if bounds is not None else (None, None)
    return value


def request(timeline=None, **fields):
    return {"generation_id": VALID["SHA256"], "query": {"text": "synthetic candidate"}, "min_score": 0, "timeline": timeline, **fields}


WALL = {"kind": "wall"}
SEQUENCE = {"kind": "sequence", "sequence_id": "sequence-a"}


class RetrievalSemanticTests(unittest.TestCase):
    def check_wire(self, definition, value, *, context=None):
        decoded = parse_json(raw_document(value).encode("utf-8"))
        validate(definition, decoded, CONTRACT, request=context)
        self.assertEqual(decoded, value)
        return decoded

    def reject_semantic_wire(self, definition, value, message, *, context=None):
        decoded = parse_json(raw_document(value).encode("utf-8"))
        # These must get past the genuine canonical schema to test the supplement.
        CONTRACT.validator(definition).validate(decoded)
        with self.assertRaisesRegex(ValueError, message):
            validate(definition, decoded, CONTRACT, request=context)

    def test_review_unknown_times_cannot_support_wall_observation(self):
        value = history(WALL, [observation(1000, 1000, deepcopy(VALID["Hit"]))])
        self.reject_semantic_wire("HistoryResponse", value, "lacks the selected clock")

    def test_review_wall_timed_hit_cannot_hide_in_unsequenced_history(self):
        value = history(WALL, unsequenced=[hit(wall=1000)])
        self.reject_semantic_wire("HistoryResponse", value, "cannot be unsequenced")

    def test_review_evidence_clock_must_fit_observation(self):
        value = history(WALL, [observation(1000, 1000, hit(wall=9000))])
        self.reject_semantic_wire("HistoryResponse", value, "outside observation bounds")

    def test_review_partial_coverage_cannot_claim_untruncated(self):
        coverage = {"assets_total": 2, "assets_indexed": 1, "pending": 1, "failed": 0, "regions_indexed": 1}
        value = history(WALL, [observation(1000, 1000, hit(wall=1000))])
        value["coverage"] = coverage
        self.reject_semantic_wire("HistoryResponse", value, "Incomplete index coverage")

    def test_coverage_partition_and_truncation_cross_both_responses(self):
        for definition in ("SearchResponse", "HistoryResponse"):
            for pending, failed in ((0, 0), (1, 0), (0, 1), (1, 1)):
                value = deepcopy(VALID[definition])
                value["coverage"] = {"assets_total": 1 + pending + failed, "assets_indexed": 1, "pending": pending, "failed": failed, "regions_indexed": 1}
                for truncated in (False, True):
                    value["truncated"] = truncated
                    with self.subTest(definition=definition, pending=pending, failed=failed, truncated=truncated):
                        if (pending or failed) and not truncated:
                            self.reject_semantic_wire(definition, value, "Incomplete index coverage")
                        else:
                            self.check_wire(definition, value)
                value["coverage"]["assets_total"] += 1
                self.reject_semantic_wire(definition, value, "Coverage partition mismatch")
        for indexed, regions in ((0, 1), (2, 1)):
            value = {"assets_total": indexed, "assets_indexed": indexed, "pending": 0, "failed": 0, "regions_indexed": regions}
            self.reject_semantic_wire("Coverage", value, "(Regions require|assets require regions)")

    def test_wall_clock_does_not_fall_back_to_sequence_position(self):
        value = hit(sequence="sequence-a", position=1000)
        self.reject_semantic_wire("HistoryResponse", history(WALL, [observation(1000, 1000, value)]), "lacks the selected clock")
        self.check_wire("HistoryResponse", history(WALL, unsequenced=[value]))
        self.check_wire("HistoryResponse", history(SEQUENCE, [observation(1000, 1000, value)]))

    def test_sequence_clock_requires_exact_sequence_identity_not_wall_fallback(self):
        for sequence in (None, "sequence-b", "SEQUENCE-A"):
            value = hit(wall=1000, sequence=sequence, position=1000 if sequence is not None else None)
            with self.subTest(sequence=sequence):
                self.reject_semantic_wire("HistoryResponse", history(SEQUENCE, [observation(1000, 1000, value)]), "lacks the selected clock")
                self.check_wire("HistoryResponse", history(SEQUENCE, unsequenced=[value]))
                self.check_wire("HistoryResponse", history(WALL, [observation(1000, 1000, value)]))

    def test_selected_sequence_position_cannot_hide_as_unsequenced(self):
        value = hit(wall=None, sequence="sequence-a", position=0)
        self.reject_semantic_wire("HistoryResponse", history(SEQUENCE, unsequenced=[value]), "cannot be unsequenced")
        self.check_wire("HistoryResponse", history(SEQUENCE, [observation(0, 0, value)]))

    def test_null_timeline_keeps_known_source_clocks_unsequenced(self):
        self.check_wire("HistoryResponse", history(None, unsequenced=[hit(wall=1000, sequence="sequence-a", position=2000)]))

    def test_truncated_history_can_return_only_unsequenced_evidence(self):
        for timeline in (WALL, SEQUENCE):
            value = history(timeline, unsequenced=[hit()], truncated=True, bounds=(0, 9007199254740991))
            self.check_wire("HistoryResponse", value)
            self.check_wire("HistoryResponse", value, context=request(timeline, limit=1))
        # A different sequence remains unsequenced in the requested clock.
        value = history(SEQUENCE, unsequenced=[hit(wall=1000, sequence="sequence-b", position=50)], truncated=True, bounds=(0, 5000))
        self.check_wire("HistoryResponse", value)

    def test_evidence_bounds_are_inclusive_and_use_only_selected_clock(self):
        for timeline in (WALL, SEQUENCE):
            for time in (999, 1000, 2000, 2001):
                value = hit(wall=time if timeline == WALL else 9999, sequence="sequence-a", position=time if timeline == SEQUENCE else 9999)
                response = history(timeline, [observation(1000, 2000, value)], truncated=True)
                with self.subTest(timeline=timeline, time=time):
                    if 1000 <= time <= 2000:
                        self.check_wire("HistoryResponse", response)
                    else:
                        self.reject_semantic_wire("HistoryResponse", response, "outside observation bounds")

    def test_observation_groups_cannot_overlap_touch_or_run_backwards(self):
        first = observation(1000, 2000, hit(1, wall=1000))
        for start in (999, 1500, 2000):
            second = observation(start, 3000, hit(2, wall=start))
            value = history(WALL, [first, second], truncated=True)
            with self.subTest(start=start):
                self.reject_semantic_wire("HistoryResponse", value, "overlap or are out of order")
        second = observation(2001, 3000, hit(2, wall=3000))
        self.check_wire("HistoryResponse", history(WALL, [first, second], truncated=True))
        self.reject_semantic_wire("HistoryResponse", history(WALL, [second, first], truncated=True), "overlap or are out of order")

    def test_evidence_order_is_chronological_with_asset_id_ties(self):
        for evidence in ((hit(1, wall=2000), hit(2, wall=1000)), (hit(2, wall=1000), hit(1, wall=1000))):
            value = history(WALL, [observation(1000, 2000, *evidence)], truncated=True)
            self.reject_semantic_wire("HistoryResponse", value, "not in chronological order")
        self.check_wire("HistoryResponse", history(WALL, [observation(1000, 1000, hit(1, wall=1000), hit(2, wall=1000))]))

    def test_first_last_enclose_returned_groups_even_when_truncated(self):
        group = observation(1000, 2000, hit(1, wall=1000), hit(2, wall=2000))
        for bounds in ((1001, 2000), (1000, 1999), (2000, 1000)):
            value = history(WALL, [group], truncated=True, bounds=bounds)
            self.reject_semantic_wire("HistoryResponse", value, "(outside history bounds|History time bounds reversed)")
        self.check_wire("HistoryResponse", history(WALL, [group], truncated=True, bounds=(0, 9007199254740991)))

    def test_untruncated_bounds_and_max_score_must_match_all_returned_evidence(self):
        good = history(WALL, [observation(1000, 1000, hit(wall=1000))])
        self.check_wire("HistoryResponse", good)
        cases = []
        first = deepcopy(good)
        first["first_observed_ms"] = 0
        cases.append((first, "history bounds must match"))
        last = deepcopy(good)
        last["last_observed_ms"] = 9000
        cases.append((last, "history bounds must match"))
        group = deepcopy(first)
        group["observations"][0]["start_ms"] = 0
        cases.append((group, "observation bounds must match"))
        score = deepcopy(good)
        score["observations"][0]["max_score"] = 1
        cases.append((score, "observation score must match"))
        for value, message in cases:
            self.reject_semantic_wire("HistoryResponse", value, message)
            value["truncated"] = True
            self.check_wire("HistoryResponse", value)

    def test_request_context_applies_exclusive_cutoff_to_hits_and_complete_bounds(self):
        for timeline in (WALL, SEQUENCE):
            context = request(timeline, before_ms=1000)
            for time in (999, 1000, 1001):
                candidate = hit(wall=time, sequence="sequence-a", position=time)
                for definition in ("HistoryResponse", "SearchResponse"):
                    response = history(timeline, [observation(time, time, candidate)]) if definition == "HistoryResponse" else {**VALID["SearchResponse"], "hits": [candidate]}
                    with self.subTest(timeline=timeline, time=time, definition=definition):
                        self.check_wire(definition, response)
                        if time < 1000:
                            self.check_wire(definition, response, context=context)
                        else:
                            self.reject_semantic_wire(definition, response, "exclusive cutoff", context=context)
            # Hidden complete history bounds are also after cutoff, despite valid selected evidence.
            response = history(timeline, [observation(999, 999, hit(wall=999, sequence="sequence-a", position=999))], truncated=True, bounds=(0, 1000))
            self.reject_semantic_wire("HistoryResponse", response, "History bounds", context=context)
        empty = history(WALL)
        self.check_wire("HistoryResponse", empty, context=request(WALL, before_ms=0))

    def test_cutoff_excludes_unknown_or_other_sequence_even_with_known_wall_time(self):
        for candidate in (hit(), hit(wall=1, sequence="sequence-b", position=1)):
            response = history(SEQUENCE, unsequenced=[candidate])
            self.check_wire("HistoryResponse", response)
            self.check_wire("HistoryResponse", response, context=request(SEQUENCE, before_ms=None))
            self.reject_semantic_wire("HistoryResponse", response, "exclusive cutoff", context=request(SEQUENCE, before_ms=1000))

    def test_context_matches_timeline_generation_threshold_limit_and_source(self):
        response = history(WALL, [observation(1000, 1000, hit(wall=1000))])
        self.check_wire("HistoryResponse", response, context=request(WALL, min_score=Decimal("0.75")))
        for context, message in ((request(SEQUENCE), "timeline differs"), (request(None), "timeline differs"),
                                 (request(WALL, generation_id="f" * 64), "generation differs"),
                                 (request(WALL, min_score=Decimal("0.75000000000000001")), "below requested threshold"),
                                 (request(WALL, query={"asset_id": hit()["asset_id"]}), "source asset")):
            self.reject_semantic_wire("HistoryResponse", response, message, context=context)
        two = history(WALL, [observation(1000, 1000, hit(1, wall=1000), hit(2, wall=1000))])
        self.reject_semantic_wire("HistoryResponse", two, "requested limit", context=request(WALL, limit=1))
        self.check_wire("HistoryResponse", two, context=request(WALL, limit=2))

    def test_request_schema_and_exact_box_semantics_are_validated_before_context_use(self):
        response = history(WALL)
        for context in (request(WALL, min_score=None), request(WALL, limit=0), request(None, before_ms=1)):
            with self.assertRaises(ValidationError):
                self.check_wire("HistoryResponse", response, context=context)
        with self.assertRaisesRegex(ValueError, "positive width"):
            self.check_wire("HistoryResponse", response, context=request(WALL, query={"asset_id": VALID["UUID"], "box": [0, 0, 0, 1]}))
        with self.assertRaisesRegex(ValueError, "requires a retrieval response"):
            self.check_wire("Box", [0, 0, 1, 1], context=request())

    def test_gap_context_does_not_guess_unavailable_request_or_hidden_evidence(self):
        first = observation(0, 0, hit(1, wall=0))
        second = observation(1000, 1000, hit(2, wall=1000))
        separate = history(WALL, [first, second])
        self.check_wire("HistoryResponse", separate)  # Request may have selected gap_ms=0.
        self.check_wire("HistoryResponse", separate, context=request(WALL, gap_ms=999))
        self.reject_semantic_wire("HistoryResponse", separate, "separated by more than gap_ms", context=request(WALL, gap_ms=1000))
        self.reject_semantic_wire("HistoryResponse", separate, "separated by more than gap_ms", context=request(WALL))
        joined = history(WALL, [observation(0, 1000, hit(1, wall=0), hit(2, wall=1000))])
        self.check_wire("HistoryResponse", joined, context=request(WALL, gap_ms=1000))
        self.reject_semantic_wire("HistoryResponse", joined, "spans a gap_ms break", context=request(WALL, gap_ms=999))
        # Omitted hits can bridge the selected evidence's time gap.
        joined["truncated"] = True
        self.check_wire("HistoryResponse", joined, context=request(WALL, gap_ms=999))
        # No hidden bridge can connect unequal timestamps when gap_ms is zero.
        self.reject_semantic_wire("HistoryResponse", joined, "Zero-gap observation", context=request(WALL, gap_ms=0))
        equal = history(WALL, [observation(0, 0, hit(1, wall=0), hit(2, wall=0))], truncated=True)
        self.check_wire("HistoryResponse", equal, context=request(WALL, gap_ms=0))

    def test_raw_malicious_time_values_are_neither_coerced_nor_invented(self):
        response = history(WALL, [observation(1000, 1000, hit(wall=1000))])
        response["observations"][0]["evidence"][0]["observed_at_ms"] = "RAW_TIME"
        raw = raw_document(response)
        for literal in ("null", "9000", '"1970-01-01T00:00:01Z"', '"1000"', "true", "1000.00000000000000001", "1e-400", "9007199254740991.1"):
            with self.subTest(literal=literal), self.assertRaises((ValidationError, ValueError)):
                validate("HistoryResponse", parse_json(raw.replace('"RAW_TIME"', literal)), CONTRACT)
        for literal in ("NaN", "Infinity", '"\\ud800"'):
            with self.subTest(literal=literal), self.assertRaises(ValueError):
                parse_json(raw.replace('"RAW_TIME"', literal))
        duplicate = raw.replace('"observed_at_ms":"RAW_TIME"', '"observed_at_ms":null,"\\u006fbserved_at_ms":1000')
        with self.assertRaises(ValueError):
            parse_json(duplicate)

    def test_exact_positive_boxes_survive_until_pixel_covering_rounding(self):
        for literal in ("[0,0,1e-400,1]", "[0.5,0,0.50000000000000001,1]"):
            with self.subTest(literal=literal), localcontext() as context:
                context.prec = 2
                box = parse_json(literal)
                self.assertLess(box[0], box[2])
                self.assertEqual(float(box[0]), float(box[2]))  # Binary64 is not the acceptance domain.
                self.check_wire("Box", box)
                self.check_wire("ImageQuery", {"asset_id": VALID["UUID"], "box": box})
                query = request(WALL, query={"asset_id": VALID["UUID"], "box": box})
                self.check_wire("HistoryRequest", query)
                self.check_wire("HistoryResponse", history(WALL), context=query)
                candidate = hit()
                candidate["region"]["box"] = box
                self.check_wire("Hit", candidate)
        for literal in ("[0,0,0,1]", "[0.5,0,0.49999999999999999,1]", "[0,0,1.00000000000000001,1]"):
            with self.subTest(literal=literal), self.assertRaises((ValidationError, ValueError)):
                validate("Box", parse_json(literal), CONTRACT)
