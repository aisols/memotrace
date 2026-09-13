// SPDX-License-Identifier: AGPL-3.0-only
package contract

import (
	"net/http"
	"testing"
)

func TestCanonicalSnapshotHashesAndDefinitions(t *testing.T) {
	if err := CheckHashes(); err != nil {
		t.Fatal(err)
	}
	for _, def := range []string{"Health", "Invitation", "PairRequest", "PairResponse", "FrameMetadata", "ManifestRequest", "ManifestResponse", "Receipt", "Error"} {
		if _, err := Compile(def); err != nil {
			t.Fatalf("%s: %v", def, err)
		}
	}
	for _, def := range []string{"SearchRequest", "HistoryRequest", "SearchResponse", "HistoryResponse", "Hit", "Coverage", "Observation", "Box", "Timeline"} {
		if _, err := Compile(def); err != nil {
			t.Fatalf("retrieval %s: %v", def, err)
		}
	}
	for _, family := range []string{"ingestion", "retrieval"} {
		s, err := CompileFamily(family, "ContractVersion")
		if err != nil {
			t.Fatal(err)
		}
		version := "0.1.0"
		if family == "retrieval" {
			version = "0.2.0"
		}
		if err = s.Validate(version); err != nil {
			t.Fatal(err)
		}
	}
	if err := Validate("Health", []byte(`{"status":"ok","contract_version":"0.1.0","unexpected":true}`)); err == nil {
		t.Fatal("schema validator did not enforce additionalProperties")
	}
	if err := Validate("UTCDateTime", []byte(`"2026-02-30T00:00:00Z"`)); err == nil {
		t.Fatal("format checking disabled")
	}
}

func TestSnapshotProvenanceStatuses(t *testing.T) {
	for _, tc := range []struct {
		status string
		valid  bool
	}{
		{"unreleased-working-tree", true},
		{"unreleased-revision", true},
		{"released-revision", true},
		{"committed", false},
		{"", false},
	} {
		if got := validSnapshotProvenance(tc.status); got != tc.valid {
			t.Errorf("validSnapshotProvenance(%q) = %t, want %t", tc.status, got, tc.valid)
		}
	}
}

func TestOpenAPIRequiredChallengeHeadersAreActuallyChecked(t *testing.T) {
	body := []byte(`{"error":{"code":"unauthorized","message":"Request could not be completed.","retryable":false}}`)
	for _, tc := range []struct{ method, path, challenge string }{
		{"POST", "/v1/pairing/redeem", `MemoTraceInvitation realm="memotrace-pairing"`},
		{"GET", "/v1/archives/00000000-0000-0000-0000-000000000000/frames/00000000-0000-0000-0000-000000000001/receipt", `Bearer realm="memotrace"`},
	} {
		headers := http.Header{"Content-Type": []string{"application/json"}, "Cache-Control": []string{"no-store"}, "X-Content-Type-Options": []string{"nosniff"}}
		if CheckResponse(tc.method, tc.path, 401, headers, body) == nil {
			t.Fatal("missing OpenAPI-required challenge accepted")
		}
		headers.Set("WWW-Authenticate", "wrong realm")
		if CheckResponse(tc.method, tc.path, 401, headers, body) == nil {
			t.Fatal("wrong header constant accepted")
		}
		headers.Set("WWW-Authenticate", tc.challenge)
		if err := CheckResponse(tc.method, tc.path, 401, headers, body); err != nil {
			t.Fatal(err)
		}
	}
}
