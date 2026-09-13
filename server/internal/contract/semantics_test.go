// SPDX-License-Identifier: AGPL-3.0-only
package contract

import (
	"bytes"
	"encoding/json"
	"net/http"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

const semanticArchive = "11111111-1111-1111-1111-111111111111"

func semanticFixture() map[string]any {
	const id = "22222222-2222-2222-2222-222222222222"
	hit := map[string]any{"asset_id": id, "source_kind": "dataset", "frame_id": nil, "dataset": map[string]any{"name": "synthetic", "version": "1", "item_id": "1"}, "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "score": .75, "region": map[string]any{"kind": "full", "box": []int{0, 0, 1, 1}}, "observed_at_ms": 1000, "sequence_id": nil, "sequence_position_ms": nil, "original_path": "/v1/archives/" + semanticArchive + "/search/assets/" + id + "/original"}
	return map[string]any{"contract_version": "0.2.0", "archive_id": semanticArchive, "generation_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "coverage": map[string]any{"assets_total": 1, "assets_indexed": 1, "pending": 0, "failed": 0, "regions_indexed": 1}, "timeline": map[string]any{"kind": "wall"}, "history_available": true, "observations": []any{map[string]any{"start_ms": 1000, "end_ms": 1000, "max_score": .75, "evidence": []any{hit}}}, "unsequenced_hits": []any{}, "first_observed_ms": 1000, "last_observed_ms": 1000, "truncated": false, "interpretation": "candidate_observations"}
}
func fixtureHit(r map[string]any) map[string]any {
	return r["observations"].([]any)[0].(map[string]any)["evidence"].([]any)[0].(map[string]any)
}
func oracleHTTP(t *testing.T, def string, r map[string]any, want bool) {
	t.Helper()
	b, err := json.Marshal(r)
	if err != nil {
		t.Fatal(err)
	}
	// Prove each counterexample passes the genuine structural schema, so an
	// actual semantic-oracle failure (not an unrelated schema error) is required.
	schema, err := Compile(def)
	if err != nil {
		t.Fatal(err)
	}
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		t.Fatal(err)
	}
	if err = schema.Validate(v); err != nil {
		t.Fatal("fixture not schema-valid", err)
	}
	if err = Validate(def, b); (err == nil) != want {
		t.Fatal("semantic Validate result", want, err)
	}
	headers := http.Header{"Content-Type": []string{"application/json"}, "Cache-Control": []string{"no-store"}, "X-Content-Type-Options": []string{"nosniff"}}
	path := "history"
	if def == "SearchResponse" {
		path = "search"
	}
	if err = CheckResponse("POST", "/v1/archives/"+semanticArchive+"/"+path, 200, headers, b); (err == nil) != want {
		t.Fatal("actual HTTP conformance result", want, err)
	}
}
func TestHTTPRetrievalResponseSemanticCounterexamples(t *testing.T) {
	oracleHTTP(t, "HistoryResponse", semanticFixture(), true)
	for name, mutate := range map[string]func(map[string]any){
		"wall group with unknown timestamps": func(r map[string]any) { fixtureHit(r)["observed_at_ms"] = nil },
		"evidence outside observation":       func(r map[string]any) { fixtureHit(r)["observed_at_ms"] = 9000 },
		"sequence group with other sequence": func(r map[string]any) {
			r["timeline"] = map[string]any{"kind": "sequence", "sequence_id": "A"}
			h := fixtureHit(r)
			h["sequence_id"] = "B"
			h["sequence_position_ms"] = 1000
		},
		"sequence group with only wall time": func(r map[string]any) { r["timeline"] = map[string]any{"kind": "sequence", "sequence_id": "A"} },
		"known wall hit called unsequenced": func(r map[string]any) {
			h := fixtureHit(r)
			r["unsequenced_hits"] = []any{h}
			r["observations"] = []any{}
			r["history_available"] = false
			r["first_observed_ms"] = nil
			r["last_observed_ms"] = nil
		},
		"known sequence hit called unsequenced": func(r map[string]any) {
			h := fixtureHit(r)
			h["sequence_id"] = "A"
			h["sequence_position_ms"] = 1000
			r["timeline"] = map[string]any{"kind": "sequence", "sequence_id": "A"}
			r["unsequenced_hits"] = []any{h}
			r["observations"] = []any{}
			r["truncated"] = true
		},
		"partial history hides truncation": func(r map[string]any) { c := r["coverage"].(map[string]any); c["assets_total"] = 2; c["pending"] = 1 },
		"score below evidence":             func(r map[string]any) { r["observations"].([]any)[0].(map[string]any)["max_score"] = .5 },
		"untruncated score above evidence": func(r map[string]any) { r["observations"].([]any)[0].(map[string]any)["max_score"] = .9 },
		"untruncated bounds exceed evidence": func(r map[string]any) {
			o := r["observations"].([]any)[0].(map[string]any)
			o["start_ms"] = 900
			o["end_ms"] = 1100
			r["first_observed_ms"] = 900
			r["last_observed_ms"] = 1100
		},
		"path points to another archive": func(r map[string]any) {
			fixtureHit(r)["original_path"] = "/v1/archives/33333333-3333-3333-3333-333333333333/search/assets/22222222-2222-2222-2222-222222222222/original"
		},
	} {
		t.Run(name, func(t *testing.T) { r := semanticFixture(); mutate(r); oracleHTTP(t, "HistoryResponse", r, false) })
	}
	r := semanticFixture()
	search := map[string]any{"contract_version": r["contract_version"], "archive_id": r["archive_id"], "generation_id": r["generation_id"], "coverage": map[string]any{"assets_total": 2, "assets_indexed": 1, "pending": 1, "failed": 0, "regions_indexed": 1}, "hits": []any{fixtureHit(r)}, "truncated": false}
	oracleHTTP(t, "SearchResponse", search, false)
	search["truncated"] = true
	oracleHTTP(t, "SearchResponse", search, true)
}
func TestLimitedHistoryWithOnlyUnsequencedEvidencePreservesTimedBounds(t *testing.T) {
	r := semanticFixture()
	h := fixtureHit(r)
	h["observed_at_ms"] = nil
	r["observations"] = []any{}
	r["unsequenced_hits"] = []any{h}
	r["truncated"] = true
	r["coverage"] = map[string]any{"assets_total": 2, "assets_indexed": 2, "pending": 0, "failed": 0, "regions_indexed": 2}
	oracleHTTP(t, "HistoryResponse", r, true)
	// A known timestamp in another sequence remains unsequenced in selected A.
	r["timeline"] = map[string]any{"kind": "sequence", "sequence_id": "A"}
	h["sequence_id"] = "B"
	h["sequence_position_ms"] = 10
	oracleHTTP(t, "HistoryResponse", r, true)
	// Explicitly absent timeline never silently chooses a non-null wall clock.
	r["timeline"] = nil
	r["history_available"] = false
	r["first_observed_ms"] = nil
	r["last_observed_ms"] = nil
	h["observed_at_ms"] = 1000
	oracleHTTP(t, "HistoryResponse", r, true)
}

func TestHistoryAvailableRequiresReturnedEvidence(t *testing.T) {
	r := semanticFixture()
	r["observations"] = []any{}
	r["unsequenced_hits"] = []any{}
	r["truncated"] = true
	oracleHTTP(t, "HistoryResponse", r, false)

	r["history_available"] = false
	r["first_observed_ms"] = nil
	r["last_observed_ms"] = nil
	r["truncated"] = false
	oracleHTTP(t, "HistoryResponse", r, true)
}

func TestRetrievalOracleChecksActualRequestContext(t *testing.T) {
	r := semanticFixture()
	body, _ := json.Marshal(r)
	request := map[string]any{"generation_id": r["generation_id"], "query": map[string]any{"text": "scissors"}, "min_score": .5, "timeline": r["timeline"], "before_ms": 1001, "gap_ms": 0, "limit": 1}
	check := func(want bool) {
		t.Helper()
		b, _ := json.Marshal(request)
		if err := ValidateWithRequest("HistoryResponse", body, b); (err == nil) != want {
			t.Fatal("request-aware conformance", want, err)
		}
	}
	check(true)
	request["before_ms"] = 1000
	check(false)
	request["before_ms"] = 1001
	request["min_score"] = .8
	check(false)
	request["min_score"] = .5
	request["generation_id"] = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
	check(false)
	request["generation_id"] = r["generation_id"]
	request["timeline"] = map[string]any{"kind": "sequence", "sequence_id": "A"}
	check(false)
	request["timeline"] = r["timeline"]
	request["query"] = map[string]any{"asset_id": fixtureHit(r)["asset_id"]}
	check(false)
}
