// SPDX-License-Identifier: AGPL-3.0-only
package retrieval

import (
	"math"
	"sort"
)

// Clock selects only the explicitly requested clock. Other sequences cannot be
// compared to it. Unknown clocks remain ordinary unsequenced semantic candidates.
func Clock(h Hit, t *Timeline) *int64 {
	if t == nil {
		return nil
	}
	if t.Kind == "wall" {
		return h.ObservedAtMS
	}
	if h.SequenceID != nil && t.SequenceID != nil && *h.SequenceID == *t.SequenceID {
		return h.SequencePositionMS
	}
	return nil
}

// Eligible runs before scoring/aggregation, including identical-byte aliases of
// image-query sources. A cutoff cannot make unknown/other-clock times comparable.
func Eligible(h Hit, r Request, sourceHash string) bool {
	if r.Query.AssetID != nil && (h.AssetID == *r.Query.AssetID || h.SHA256 == sourceHash) {
		return false
	}
	if r.BeforeMS != nil {
		t := Clock(h, r.Timeline)
		return t != nil && *t < *r.BeforeMS
	}
	return true
}
func Cosine(a, b []float32) float64 {
	var dot, na, nb float64
	for i, x := range a {
		y := float64(b[i])
		xx := float64(x)
		dot += xx * y
		na += xx * xx
		nb += y * y
	}
	return math.Max(-1, math.Min(1, dot/math.Sqrt(na*nb)))
}
func Better(a, b Hit) bool {
	if a.Score != b.Score {
		return a.Score > b.Score
	}
	if a.AssetID != b.AssetID {
		return a.AssetID < b.AssetID
	}
	if a.Region.Kind != b.Region.Kind {
		return a.Region.Kind == "full"
	}
	for i, x := range a.Region.Box {
		if x != b.Region.Box[i] {
			return x < b.Region.Box[i]
		}
	}
	return false
}
func Ranked(best map[string]Hit) []Hit {
	h := make([]Hit, 0, len(best))
	for _, v := range best {
		h = append(h, v)
	}
	sort.Slice(h, func(i, j int) bool { return Better(h[i], h[j]) })
	return h
}
func Search(archive string, r Request, c Coverage, hits []Hit) SearchResponse {
	out := SearchResponse{Version, archive, r.GenerationID, c, hits, c.Partial() || len(hits) > r.ResultLimit()}
	if len(out.Hits) > r.ResultLimit() {
		out.Hits = out.Hits[:r.ResultLimit()]
	}
	return out
}

// History receives ALL qualified, asset-deduplicated matches in the complete
// bounded indexed corpus. First/last and groups never derive from a top-K prefix.
// Limit is a total evidence-hit budget, selected by score, across both outputs.
func History(archive string, r Request, c Coverage, hits []Hit) HistoryResponse {
	out := HistoryResponse{ContractVersion: Version, ArchiveID: archive, GenerationID: r.GenerationID, Coverage: c, Timeline: r.Timeline, Observations: []Observation{}, UnsequencedHits: []Hit{}, Interpretation: "candidate_observations", Truncated: c.Partial() || len(hits) > r.ResultLimit()}
	timed := []Hit{}
	selected := map[string]bool{}
	for i, h := range hits {
		if i < r.ResultLimit() {
			selected[h.AssetID] = true
		}
		if Clock(h, r.Timeline) != nil {
			timed = append(timed, h)
		} else if selected[h.AssetID] {
			out.UnsequencedHits = append(out.UnsequencedHits, h)
		}
	}
	if len(timed) == 0 {
		return out
	}
	out.HistoryAvailable = true
	sort.Slice(timed, func(i, j int) bool {
		a, b := *Clock(timed[i], r.Timeline), *Clock(timed[j], r.Timeline)
		if a != b {
			return a < b
		}
		return timed[i].AssetID < timed[j].AssetID
	})
	first, last := *Clock(timed[0], r.Timeline), *Clock(timed[len(timed)-1], r.Timeline)
	out.FirstObservedMS, out.LastObservedMS = &first, &last
	gap := int64(30000)
	if r.GapMS != nil {
		gap = *r.GapMS
	}
	groups := []Observation{}
	for _, h := range timed {
		t := *Clock(h, r.Timeline)
		if len(groups) == 0 || t-groups[len(groups)-1].EndMS > gap {
			groups = append(groups, Observation{StartMS: t, EndMS: t, MaxScore: h.Score, Evidence: []Hit{}})
		}
		g := &groups[len(groups)-1]
		g.EndMS = t
		g.MaxScore = math.Max(g.MaxScore, h.Score)
		if selected[h.AssetID] {
			g.Evidence = append(g.Evidence, h)
		}
	}
	for _, g := range groups {
		if len(g.Evidence) > 0 {
			out.Observations = append(out.Observations, g)
		}
	}
	return out
}
