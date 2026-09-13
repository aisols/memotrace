// SPDX-License-Identifier: AGPL-3.0-only
package contract

import (
	"bytes"
	"encoding/json"
	"reflect"

	"github.com/santhosh-tekuri/jsonschema/v6"
	"memotrace/server/internal/retrieval"
)

// ValidateWithRequest supplements instance-local conformance with the actual
// request's generation, limit, threshold, source asset, clock/cutoff and gap. It
// cannot infer omitted corpus content or identical-byte aliases; DB/IPC tests own
// those checks. This helper is only consumed by component conformance tests.
func ValidateWithRequest(def string, body, request []byte) error {
	if def != "SearchResponse" && def != "HistoryResponse" {
		return semanticError()
	}
	if err := Validate(def, body); err != nil {
		return err
	}
	reqDef := "SearchRequest"
	if def == "HistoryResponse" {
		reqDef = "HistoryRequest"
	}
	if err := Validate(reqDef, request); err != nil {
		return err
	}
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(body))
	if err != nil {
		return err
	}
	response := v.(map[string]any)
	v, err = jsonschema.UnmarshalJSON(bytes.NewReader(request))
	if err != nil {
		return err
	}
	req := v.(map[string]any)
	if response["generation_id"] != req["generation_id"] {
		return semanticError()
	}
	timeline, _ := req["timeline"].(map[string]any)
	var hits []any
	if def == "HistoryResponse" {
		if !reflect.DeepEqual(response["timeline"], req["timeline"]) {
			return semanticError()
		}
		hits = append(hits, response["unsequenced_hits"].([]any)...)
		for _, value := range response["observations"].([]any) {
			hits = append(hits, value.(map[string]any)["evidence"].([]any)...)
		}
		if err := requestedGap(response, req, timeline); err != nil {
			return err
		}
	} else {
		hits = response["hits"].([]any)
	}
	limit := int64(20)
	if value, ok := req["limit"]; ok {
		limit, err = semanticInt(value)
		if err != nil {
			return err
		}
	}
	if int64(len(hits)) > limit {
		return semanticError()
	}
	threshold := json.Number("-1")
	if value, ok := req["min_score"]; ok {
		threshold = value.(json.Number)
	}
	source := req["query"].(map[string]any)["asset_id"]
	var cutoff *int64
	if value := req["before_ms"]; value != nil {
		n, err := semanticInt(value)
		if err != nil {
			return err
		}
		cutoff = &n
	}
	for _, value := range hits {
		h := value.(map[string]any)
		if h["asset_id"] == source {
			return semanticError()
		}
		cmp, ok := retrieval.CompareNumbers(h["score"].(json.Number), threshold)
		if !ok || cmp < 0 {
			return semanticError()
		}
		if cutoff != nil {
			clock, err := selectedClock(h, timeline)
			if err != nil {
				return err
			}
			if clock == nil {
				return semanticError()
			}
			n, err := semanticInt(clock)
			if err != nil {
				return err
			}
			if n >= *cutoff {
				return semanticError()
			}
		}
	}
	if cutoff != nil && def == "HistoryResponse" && response["history_available"].(bool) {
		last, err := semanticInt(response["last_observed_ms"])
		if err != nil {
			return err
		}
		if last >= *cutoff {
			return semanticError()
		}
	}
	return nil
}
func requestedGap(response, req map[string]any, timeline map[string]any) error {
	gap := int64(30000)
	if value, ok := req["gap_ms"]; ok {
		var err error
		gap, err = semanticInt(value)
		if err != nil {
			return err
		}
	}
	var previousEnd *int64
	for _, value := range response["observations"].([]any) {
		o := value.(map[string]any)
		start, err := semanticInt(o["start_ms"])
		if err != nil {
			return err
		}
		end, err := semanticInt(o["end_ms"])
		if err != nil {
			return err
		}
		if gap == 0 && start != end || previousEnd != nil && start-*previousEnd <= gap {
			return semanticError()
		}
		previousEnd = &end
		if !response["truncated"].(bool) {
			var previousTime *int64
			for _, value := range o["evidence"].([]any) {
				clock, err := selectedClock(value.(map[string]any), timeline)
				if err != nil {
					return err
				}
				ms, err := semanticInt(clock)
				if err != nil {
					return err
				}
				if previousTime != nil && ms-*previousTime > gap {
					return semanticError()
				}
				previousTime = &ms
			}
		}
	}
	return nil
}
