// SPDX-License-Identifier: AGPL-3.0-only
package retrieval

import "testing"

func TestRankedOrdersByDescendingScore(t *testing.T) {
	hits := Ranked(map[string]Hit{
		"low":  {AssetID: "low", Score: -0.5},
		"high": {AssetID: "high", Score: 0.75},
		"mid":  {AssetID: "mid", Score: 0.25},
	})
	want := []string{"high", "mid", "low"}
	for i, id := range want {
		if hits[i].AssetID != id {
			t.Fatalf("rank %d = %q, want %q", i, hits[i].AssetID, id)
		}
	}
}

func TestBetterBreaksRegionTiesDeterministically(t *testing.T) {
	full := Hit{AssetID: "asset", Score: 0.5, Region: Region{Kind: "full", Box: Box{0, 0, 1, 1}}}
	crop := Hit{AssetID: "asset", Score: 0.5, Region: Region{Kind: "crop", Box: Box{0, 0, 1, 1}}}
	if !Better(full, crop) || Better(crop, full) {
		t.Fatal("full region was not preferred over crop")
	}

	boxA := Hit{AssetID: "asset", Score: 0.5, Region: Region{Kind: "crop", Box: Box{0.1, 0.2, 0.7, 0.9}}}
	boxB := Hit{AssetID: "asset", Score: 0.5, Region: Region{Kind: "crop", Box: Box{0.1, 0.2, 0.8, 0.9}}}
	if !Better(boxA, boxB) || Better(boxB, boxA) {
		t.Fatal("region boxes were not ordered lexicographically")
	}
}

func TestSearchLimitAndPartialCoverageTruncation(t *testing.T) {
	r := Request{Limit: ptr(2)}
	hits := []Hit{{AssetID: "first"}, {AssetID: "second"}, {AssetID: "third"}}
	out := Search("archive", r, Coverage{AssetsTotal: 3, AssetsIndexed: 3}, hits)
	if len(out.Hits) != 2 || out.Hits[0].AssetID != "first" || out.Hits[1].AssetID != "second" || !out.Truncated {
		t.Fatalf("limit not applied: %+v", out)
	}

	out = Search("archive", r, Coverage{AssetsTotal: 3, AssetsIndexed: 2, Pending: 1}, hits[:1])
	if len(out.Hits) != 1 || !out.Truncated {
		t.Fatalf("partial coverage not reported as truncated: %+v", out)
	}

	out = Search("archive", r, Coverage{AssetsTotal: 2, AssetsIndexed: 2}, hits[:2])
	if out.Truncated {
		t.Fatalf("complete response at the limit reported as truncated: %+v", out)
	}
}
