// SPDX-License-Identifier: AGPL-3.0-only
package contract

import (
	"net/http"
	"testing"
)

func TestCheckResponseDistinguishesUnknownPathsFromUnsupportedMethods(t *testing.T) {
	const archive = "11111111-1111-1111-1111-111111111111"
	body := []byte(`{"error":{"code":"invalid_request","message":"Request could not be completed.","retryable":false}}`)
	headers := http.Header{"Content-Type": []string{"application/json"}, "Cache-Control": []string{"no-store"}, "X-Content-Type-Options": []string{"nosniff"}}
	tests := []struct {
		name   string
		method string
		path   string
		status int
		valid  bool
	}{
		{"ingestion known path returns 405", "POST", "/healthz", http.StatusMethodNotAllowed, true},
		{"ingestion known path rejects 404", "POST", "/healthz", http.StatusNotFound, false},
		{"ingestion unknown path returns 404", "GET", "/unknown", http.StatusNotFound, true},
		{"ingestion unknown path rejects 405", "GET", "/unknown", http.StatusMethodNotAllowed, false},
		{"retrieval known path returns 405", "GET", "/v1/archives/" + archive + "/search", http.StatusMethodNotAllowed, true},
		{"retrieval known path rejects 404", "GET", "/v1/archives/" + archive + "/search", http.StatusNotFound, false},
		{"retrieval unknown path returns 404", "GET", "/v1/archives/" + archive + "/search/unknown", http.StatusNotFound, true},
		{"retrieval unknown path rejects 405", "GET", "/v1/archives/" + archive + "/search/unknown", http.StatusMethodNotAllowed, false},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			err := CheckResponse(tc.method, tc.path, tc.status, headers, body)
			if (err == nil) != tc.valid {
				t.Fatalf("valid=%t, error=%v", tc.valid, err)
			}
		})
	}
}
