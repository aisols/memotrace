// SPDX-License-Identifier: AGPL-3.0-only
package retrieval

import (
	"encoding/json"

	"memotrace/server/internal/protocol"
	"memotrace/server/internal/strictjson"
)

func DecodeRequest(b []byte, history bool) (Request, error) {
	r := Request{}
	v, err := strictjson.Value(b)
	if err != nil {
		return r, err
	}
	m, ok := v.(map[string]any)
	if !ok {
		return r, protocol.E("invalid_request")
	}
	for _, key := range []string{"generation_id", "query"} {
		if m[key] == nil {
			return r, protocol.E("invalid_request")
		}
	}
	for _, key := range []string{"limit", "min_score", "gap_ms"} {
		if x, ok := m[key]; ok && x == nil {
			return r, protocol.E("invalid_request")
		}
	}
	if !history {
		if _, ok := m["gap_ms"]; ok {
			return r, protocol.E("invalid_request")
		}
	}
	q, ok := m["query"].(map[string]any)
	if !ok {
		return r, protocol.E("invalid_request")
	}
	for _, v := range q {
		if v == nil {
			return r, protocol.E("invalid_request")
		}
	}
	// Scores require exact range checks before float conversion. Query boxes keep
	// their decimal lexemes through IPC and Python's exact pixel rasterization.
	if n, ok := m["min_score"].(json.Number); ok && !unitDecimal(n, true) {
		return r, protocol.E("invalid_request")
	}
	if box, ok := q["box"].([]any); ok {
		for _, v := range box {
			n, ok := v.(json.Number)
			if !ok || !unitDecimal(n, false) {
				return r, protocol.E("invalid_request")
			}
		}
	}
	if t, ok := m["timeline"].(map[string]any); ok {
		if t["kind"] == nil {
			return r, protocol.E("invalid_request")
		}
		if x, ok := t["sequence_id"]; ok && x == nil {
			return r, protocol.E("invalid_request")
		}
	}
	if err = strictjson.Assign(v, &r); err != nil {
		return r, err
	}
	return r, r.Validate(history)
}
