// SPDX-License-Identifier: AGPL-3.0-only
package contract

import (
	"encoding/json"
	"fmt"
	"strings"

	"memotrace/server/internal/protocol"
	"memotrace/server/internal/retrieval"
)

// This conformance-only package is not imported by the production CLI/API. The
// genuine schema validator runs first. These instance-local comparisons implement
// requirements JSON Schema cannot express, independently of production History,
// Clock, ranking, filtering and response assembly. Corpus completeness remains an
// integration-test obligation, not something a single response can prove.
func retrievalSemantics(def string, v any) error {
	switch def {
	case "Box":
		return semanticBox(v)
	case "Region":
		return semanticBox(v.(map[string]any)["box"])
	case "Query", "ImageQuery", "SearchRequest", "HistoryRequest":
		m := v.(map[string]any)
		if q, ok := m["query"]; ok {
			m = q.(map[string]any)
		}
		if box, ok := m["box"]; ok {
			return semanticBox(box)
		}
	case "Hit":
		return semanticHit(v.(map[string]any), "")
	case "Coverage":
		_, err := semanticCoverage(v.(map[string]any))
		return err
	case "Observation":
		return semanticObservation(v.(map[string]any), "", nil, nil, nil, false)
	case "SearchResponse", "HistoryResponse":
		return semanticResponse(def, v.(map[string]any))
	}
	return nil
}
func semanticError() error { return fmt.Errorf("retrieval response violates instance-local semantics") }

func semanticBox(v any) error {
	b := v.([]any)
	for _, pair := range [][2]int{{0, 2}, {1, 3}} {
		cmp, ok := retrieval.CompareNumbers(b[pair[0]].(json.Number), b[pair[1]].(json.Number))
		if !ok || cmp >= 0 {
			return semanticError()
		}
	}
	return nil
}
func semanticInt(v any) (int64, error) {
	n, ok := v.(json.Number)
	if !ok {
		return 0, semanticError()
	}
	n, err := protocol.IntegralNumber(n)
	if err != nil {
		return 0, semanticError()
	}
	i, err := n.Int64()
	if err != nil {
		return 0, semanticError()
	}
	return i, nil
}
func semanticCoverage(c map[string]any) (bool, error) {
	values := map[string]int64{}
	for _, name := range []string{"assets_total", "assets_indexed", "pending", "failed", "regions_indexed"} {
		n, err := semanticInt(c[name])
		if err != nil {
			return false, err
		}
		values[name] = n
	}
	if values["assets_total"] != values["assets_indexed"]+values["pending"]+values["failed"] || values["regions_indexed"] < values["assets_indexed"] || values["assets_indexed"] == 0 && values["regions_indexed"] != 0 {
		return false, semanticError()
	}
	return values["pending"] != 0 || values["failed"] != 0, nil
}
func semanticHit(h map[string]any, archive string) error {
	if err := semanticBox(h["region"].(map[string]any)["box"]); err != nil {
		return err
	}
	p := strings.Split(h["original_path"].(string), "/")
	if p[6] != h["asset_id"] || archive != "" && p[3] != archive {
		return semanticError()
	}
	return nil
}

// nil means no comparable timestamp in precisely this selected clock. In
// particular a known time in a different sequence is still unsequenced here.
func selectedClock(h map[string]any, timeline map[string]any) (any, error) {
	if timeline == nil {
		return nil, nil
	}
	var value any
	switch timeline["kind"] {
	case "wall":
		value = h["observed_at_ms"]
	case "sequence":
		if h["sequence_id"] == timeline["sequence_id"] {
			value = h["sequence_position_ms"]
		}
	}
	if value != nil {
		if _, err := semanticInt(value); err != nil {
			return nil, err
		}
	}
	return value, nil
}
func semanticObservation(o map[string]any, archive string, timeline map[string]any, first, last *int64, complete bool) error {
	start, err := semanticInt(o["start_ms"])
	if err != nil {
		return err
	}
	end, err := semanticInt(o["end_ms"])
	if err != nil {
		return err
	}
	if start > end || first != nil && (*first > start || end > *last) {
		return semanticError()
	}
	var firstTime, lastTime *int64
	previousID := ""
	maxMatchesEvidence := false
	for _, value := range o["evidence"].([]any) {
		h := value.(map[string]any)
		if err := semanticHit(h, archive); err != nil {
			return err
		}
		cmp, ok := retrieval.CompareNumbers(o["max_score"].(json.Number), h["score"].(json.Number))
		if !ok || cmp < 0 {
			return semanticError()
		}
		if cmp == 0 {
			maxMatchesEvidence = true
		}
		if timeline != nil {
			clock, err := selectedClock(h, timeline)
			if err != nil {
				return err
			}
			if clock == nil {
				return semanticError()
			}
			ms, err := semanticInt(clock)
			if err != nil {
				return err
			}
			if ms < start || ms > end {
				return semanticError()
			}
			id := h["asset_id"].(string)
			if lastTime != nil && (ms < *lastTime || ms == *lastTime && id < previousID) {
				return semanticError()
			}
			if firstTime == nil {
				firstTime = &ms
			}
			lastTime = &ms
			previousID = id
		}
	}
	if complete && (!maxMatchesEvidence || firstTime == nil || start != *firstTime || end != *lastTime) {
		return semanticError()
	}
	return nil
}
func semanticResponse(def string, r map[string]any) error {
	partial, err := semanticCoverage(r["coverage"].(map[string]any))
	if err != nil {
		return err
	}
	if partial && !r["truncated"].(bool) {
		return semanticError()
	}
	archive := r["archive_id"].(string)
	var hits []any
	if def == "SearchResponse" {
		hits = r["hits"].([]any)
	} else {
		timeline, _ := r["timeline"].(map[string]any)
		historyAvailable := r["history_available"].(bool)
		var first, last *int64
		if historyAvailable {
			f, err := semanticInt(r["first_observed_ms"])
			if err != nil {
				return err
			}
			l, err := semanticInt(r["last_observed_ms"])
			if err != nil {
				return err
			}
			if f > l {
				return semanticError()
			}
			first, last = &f, &l
		}
		// A truncated response may retain first/last from omitted timed matches,
		// with only higher-scoring unsequenced evidence selected by the hit budget.
		hits = append(hits, r["unsequenced_hits"].([]any)...)
		for _, value := range hits {
			clock, err := selectedClock(value.(map[string]any), timeline)
			if err != nil {
				return err
			}
			if clock != nil {
				return semanticError()
			}
		}
		observations := r["observations"].([]any)
		var previousEnd *int64
		for _, value := range observations {
			o := value.(map[string]any)
			if timeline == nil {
				return semanticError()
			}
			if err := semanticObservation(o, archive, timeline, first, last, !r["truncated"].(bool)); err != nil {
				return err
			}
			start, err := semanticInt(o["start_ms"])
			if err != nil {
				return err
			}
			end, err := semanticInt(o["end_ms"])
			if err != nil {
				return err
			}
			if previousEnd != nil && *previousEnd >= start {
				return semanticError()
			}
			previousEnd = &end
			hits = append(hits, o["evidence"].([]any)...)
		}
		if historyAvailable && len(hits) == 0 {
			return semanticError()
		}
		if first != nil && !r["truncated"].(bool) {
			if len(observations) == 0 {
				return semanticError()
			}
			start, err := semanticInt(observations[0].(map[string]any)["start_ms"])
			if err != nil {
				return err
			}
			end, err := semanticInt(observations[len(observations)-1].(map[string]any)["end_ms"])
			if err != nil {
				return err
			}
			if start != *first || end != *last {
				return semanticError()
			}
		}
	}
	if len(hits) > 100 {
		return semanticError()
	}
	seen := map[string]bool{}
	for _, value := range hits {
		h := value.(map[string]any)
		if err := semanticHit(h, archive); err != nil {
			return err
		}
		id := h["asset_id"].(string)
		if seen[id] {
			return semanticError()
		}
		seen[id] = true
	}
	return nil
}
