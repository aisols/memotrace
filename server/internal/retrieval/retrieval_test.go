// SPDX-License-Identifier: AGPL-3.0-only
package retrieval

import (
	"encoding/json"
	"math"
	"strings"
	"testing"

	"memotrace/server/internal/protocol"
)

func ptr[T any](v T) *T { return &v }
func TestDecimalStrictRequestsAndLegacyIntegers(t *testing.T) {
	base := `{"generation_id":"` + strings.Repeat("a", 64) + `","query":{"text":"отвёртка 📷"}`
	for _, suffix := range []string{`}`, `,"min_score":0.125,"limit":2.0e1}`, `,"timeline":{"kind":"sequence","sequence_id":"clip"},"before_ms":9007199254740991.0}`, `,"before_ms":null,"timeline":null}`} {
		if _, err := DecodeRequest([]byte(base+suffix), false); err != nil {
			t.Fatal(suffix, err)
		}
	}
	image := `{"generation_id":"` + strings.Repeat("a", 64) + `","query":{"asset_id":"` + protocol.NewID() + `","box":[0.125,0.25,0.75,1]},"min_score":-0.125}`
	for _, v := range []string{"1.00000000000000000000001", "-1.00000000000000000000001", "1e9999999999999999999999999"} {
		if _, e := DecodeRequest([]byte(base+`,"min_score":`+v+`}`), false); e == nil {
			t.Fatal("decimal endpoint rounded into range", v)
		}
	}
	for _, v := range []string{"-1e-9999", "1.0000000000000000001"} {
		raw := `{"generation_id":"` + strings.Repeat("a", 64) + `","query":{"asset_id":"` + protocol.NewID() + `","box":[` + v + `,0,1,1]}}`
		if _, e := DecodeRequest([]byte(raw), false); e == nil {
			t.Fatal("box endpoint rounded into range", v)
		}
	}
	r, err := DecodeRequest([]byte(image), true)
	if err != nil || r.Query.Box[0] != "0.125" || *r.MinScore != "-0.125" {
		t.Fatal(r, err)
	}
	for _, suffix := range []string{`,"LIMIT":2}`, `,"limit":null}`, `,"min_score":null}`, `,"min_score":1.01}`, `,"min_score":1e9999}`, `,"min_score":"0.5"}`, `,"limit":1.1}`, `,"gap_ms":0}`, `,"timeline":{"kind":"wall","sequence_id":null}}`, `,"timeline":{"kind":"wall","sequence_id":"x"}}`, `,"timeline":{"kind":"sequence"}}`, `,"before_ms":1}`, `,"before_ms":1,"timeline":null}`, `,"query":{"text":"duplicate"}}`, `} {}`, `,"unknown":{"nested":1}}`} {
		if _, err := DecodeRequest([]byte(base+suffix), false); err == nil {
			t.Fatal("accepted", suffix)
		}
	}
	for _, q := range []string{`null`, `{}`, `{"text":null}`, `{"text":""}`, `{"text":"\ud800"}`, `{"text":"\u0000"}`, `{"text":"a","box":[0,0,1,1]}`, `{"asset_id":"` + protocol.NewID() + `","box":[0,0,1]}`, `{"asset_id":"` + protocol.NewID() + `","box":[0.5,0,0.4,1]}`, `{"asset_id":"` + protocol.NewID() + `","box":null}`} {
		b := `{"generation_id":"` + strings.Repeat("a", 64) + `","query":` + q + `}`
		if _, e := DecodeRequest([]byte(b), false); e == nil {
			t.Fatal("accepted", q)
		}
	}
	if _, e := DecodeRequest([]byte(base+`}`), true); e == nil {
		t.Fatal("history threshold optional")
	}
	if _, e := DecodeRequest([]byte(base+`,"min_score":0,"gap_ms":3600000.0}`), true); e != nil {
		t.Fatal(e)
	}
	var legacy protocol.ManifestRequest
	if e := protocol.StrictJSON([]byte(`{"frames":[]}`), &legacy); e != nil {
		t.Fatal(e)
	}
	if e := protocol.StrictJSON([]byte(`{"frames":[{"frame_id":"`+protocol.NewID()+`","request_wall_ms":1.25,"sha256":"`+strings.Repeat("a", 64)+`","byte_length":4}]}`), &legacy); e == nil {
		t.Fatal("legacy fractional integer accepted")
	}
}
func TestHistoryCompleteFirstLastEvidenceBudgetAndClocks(t *testing.T) {
	hits := []Hit{{AssetID: "middle", Score: .9, ObservedAtMS: ptr(int64(200))}, {AssetID: "late", Score: .8, ObservedAtMS: ptr(int64(300))}, {AssetID: "early", Score: .7, ObservedAtMS: ptr(int64(100))}, {AssetID: "unknown", Score: .6}}
	r := Request{Timeline: &Timeline{Kind: "wall"}, Limit: ptr(1), GapMS: ptr(int64(150))}
	out := History("archive", r, Coverage{AssetsTotal: 4, AssetsIndexed: 4}, hits)
	if !out.HistoryAvailable || *out.FirstObservedMS != 100 || *out.LastObservedMS != 300 || !out.Truncated || len(out.Observations) != 1 || out.Observations[0].StartMS != 100 || out.Observations[0].EndMS != 300 || len(out.Observations[0].Evidence) != 1 || out.Observations[0].Evidence[0].AssetID != "middle" {
		t.Fatalf("incomplete history: %+v", out)
	}
	r.Timeline = nil
	out = History("archive", r, Coverage{AssetsTotal: 4, AssetsIndexed: 4}, hits)
	if out.HistoryAvailable || out.FirstObservedMS != nil || len(out.Observations) != 0 || len(out.UnsequencedHits) != 1 {
		t.Fatal("invented timeline", out)
	}
	r.Limit = ptr(100)
	out = History("archive", r, Coverage{AssetsTotal: 5, AssetsIndexed: 4, Pending: 1}, hits)
	if !out.Truncated {
		t.Fatal("partial coverage hidden")
	}
	r.Timeline = &Timeline{Kind: "sequence", SequenceID: ptr("A")}
	r.GapMS = ptr(int64(0))
	hits[0].SequenceID = ptr("A")
	hits[0].SequencePositionMS = ptr(int64(9))
	hits[1].SequenceID = ptr("B")
	hits[1].SequencePositionMS = ptr(int64(1))
	out = History("archive", r, Coverage{AssetsTotal: 4, AssetsIndexed: 4}, hits)
	if *out.FirstObservedMS != 9 || *out.LastObservedMS != 9 || len(out.UnsequencedHits) != 3 || len(out.Observations) != 1 {
		t.Fatal("mixed clocks", out)
	}
	r.BeforeMS = ptr(int64(9))
	if Eligible(hits[0], r, "") || Eligible(hits[1], r, "") || Eligible(hits[3], r, "") {
		t.Fatal("cutoff not exclusive/comparable")
	}
	r.BeforeMS = ptr(int64(10))
	if !Eligible(hits[0], r, "") {
		t.Fatal("lost prefix")
	}
	r.BeforeMS = nil
	r.Query.AssetID = ptr("source")
	h := Hit{AssetID: "alias", SHA256: "source-hash"}
	if Eligible(h, r, "source-hash") {
		t.Fatal("source hash alias leaked")
	}
	h.AssetID = "source"
	h.SHA256 = "other"
	if Eligible(h, r, "") {
		t.Fatal("source leaked")
	}
}
func TestWorkerGeometryModelAndVectorGuards(t *testing.T) {
	d := Description{ModelFingerprint: strings.Repeat("a", 64), Dimension: 2, ModelID: "synthetic-test-only", ModelRevision: "1", InputResolution: 224, PreprocessingVersion: "1", Policies: map[string]string{"full": strings.Repeat("b", 64), "overlap": strings.Repeat("c", 64)}}
	if !d.Valid() {
		t.Fatal("fixture")
	}
	r := ImageResult{ModelFingerprint: d.ModelFingerprint, PolicyFingerprint: d.Policies["overlap"], Width: 4, Height: 3, Vectors: []Vector{{Kind: "full", Box: Box{0, 0, 1, 1}, Embedding: []float32{1, 0}}, {Kind: "crop", Box: Box{.25, 0, 1, 1}, Embedding: []float32{.6, .8}}}}
	if !r.Valid(d, "overlap") {
		t.Fatal("valid vector rejected")
	}
	b, _ := json.Marshal(r)
	mutations := []func(*ImageResult){func(r *ImageResult) { r.ModelFingerprint = "bad" }, func(r *ImageResult) { r.PolicyFingerprint = d.Policies["full"] }, func(r *ImageResult) { r.Width = 16385 }, func(r *ImageResult) { r.Width = 10000; r.Height = 10000 }, func(r *ImageResult) { r.Vectors[0].Embedding = []float32{0, 0} }, func(r *ImageResult) { r.Vectors[0].Embedding = []float32{1} }, func(r *ImageResult) { r.Vectors[0].Embedding[0] = float32(math.Inf(1)) }, func(r *ImageResult) { r.Vectors[1].Box[0] = math.NaN() }, func(r *ImageResult) { r.Vectors[1].Box[0] = 1 }, func(r *ImageResult) { r.Vectors[1].Kind = "detector" }, func(r *ImageResult) { r.Vectors = append(r.Vectors, r.Vectors[1]) }, func(r *ImageResult) { r.Vectors[0].Kind = "crop" }}
	for _, mutate := range mutations {
		var v ImageResult
		_ = json.Unmarshal(b, &v)
		mutate(&v)
		if v.Valid(d, "overlap") {
			t.Fatal("bad result accepted", v)
		}
	}
	if Cosine([]float32{1, 0}, []float32{0, 1}) != 0 || Cosine([]float32{1, 0}, []float32{-1, 0}) != -1 {
		t.Fatal("not cosine")
	}
	h := Ranked(map[string]Hit{"b": {AssetID: "b", Score: .5}, "a": {AssetID: "a", Score: .5}})
	if h[0].AssetID != "a" {
		t.Fatal("unstable ties")
	}
}

func TestImageResultRejectsUnsupportedIndexingModes(t *testing.T) {
	d := Description{ModelFingerprint: strings.Repeat("a", 64), Dimension: 2, ModelID: "synthetic-test-only", ModelRevision: "1", InputResolution: 224, PreprocessingVersion: "1", Policies: map[string]string{"full": strings.Repeat("b", 64), "overlap": strings.Repeat("c", 64)}}
	r := ImageResult{ModelFingerprint: d.ModelFingerprint, PolicyFingerprint: "", Width: 4, Height: 3, Vectors: []Vector{{Kind: "full", Box: Box{0, 0, 1, 1}, Embedding: []float32{1, 0}}}}
	for _, mode := range []string{"", "unknown"} {
		if r.Valid(d, mode) {
			t.Fatalf("accepted unsupported mode %q with empty fingerprint", mode)
		}
	}
}

func TestDescriptionExactEquality(t *testing.T) {
	base := Description{ModelFingerprint: strings.Repeat("a", 64), Dimension: 2, ModelID: "synthetic-test-only", ModelRevision: "1", InputResolution: 224, PreprocessingVersion: "1", Policies: map[string]string{"full": strings.Repeat("b", 64), "overlap": strings.Repeat("c", 64)}}
	clone := func() Description {
		d := base
		d.Policies = map[string]string{"full": base.Policies["full"], "overlap": base.Policies["overlap"]}
		return d
	}
	if !base.Equal(clone()) {
		t.Fatal("equal descriptions differ")
	}
	mutations := []func(*Description){
		func(d *Description) { d.ModelFingerprint = strings.Repeat("d", 64) },
		func(d *Description) { d.Dimension++ },
		func(d *Description) { d.ModelID += "-changed" },
		func(d *Description) { d.ModelRevision += "-changed" },
		func(d *Description) { d.InputResolution = 384 },
		func(d *Description) { d.PreprocessingVersion += "-changed" },
		func(d *Description) { d.Policies["full"] = strings.Repeat("d", 64) },
		func(d *Description) { d.Policies["overlap"] = strings.Repeat("d", 64) },
		func(d *Description) { d.Policies["extra"] = strings.Repeat("d", 64) },
	}
	for i, mutate := range mutations {
		d := clone()
		mutate(&d)
		if base.Equal(d) || d.Equal(base) {
			t.Fatal("description mutation compared equal", i)
		}
	}
}
