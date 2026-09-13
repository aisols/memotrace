// SPDX-License-Identifier: AGPL-3.0-only
package contract

import (
	"os"
	"path/filepath"
	"testing"
)

// Explicit external-artifact verification, separate from ordinary offline tests.
// Input is the actual CLI/TLS response output of scripts/retrieval-smoke.py.
func TestExternalGenuineRetrievalEvidence(t *testing.T) {
	root := os.Getenv("MEMOTRACE_RETRIEVAL_EVIDENCE_DIR")
	if root == "" {
		t.Skip("explicit genuine-model evidence directory not supplied")
	}
	for _, tc := range []struct{ name, def string }{{"cli-full-en", "SearchResponse"}, {"cli-full-ru", "SearchResponse"}, {"cli-overlap-en", "SearchResponse"}, {"cli-overlap-ru", "SearchResponse"}, {"cli-history", "HistoryResponse"}, {"http-search", "SearchResponse"}, {"http-history", "HistoryResponse"}} {
		b, e := os.ReadFile(filepath.Join(root, tc.name+".json"))
		if e != nil {
			t.Fatal(e)
		}
		if e = Validate(tc.def, b); e != nil {
			t.Fatal(tc.name, e)
		}
	}
}
