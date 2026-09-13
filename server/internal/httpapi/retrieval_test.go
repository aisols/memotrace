// SPDX-License-Identifier: AGPL-3.0-only
package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"memotrace/server/internal/contract"
	"memotrace/server/internal/postgres"
	"memotrace/server/internal/protocol"
	"memotrace/server/internal/retrieval"
	"memotrace/server/internal/search"
)

// Deliberately synthetic test-only worker; production has no fabricated fallback.
type syntheticSearchWorker struct {
	scores     map[string]float32
	bad        bool
	afterQuery func()
}

func (w *syntheticSearchWorker) Describe(context.Context) (retrieval.Description, error) {
	return retrieval.Description{ModelFingerprint: strings.Repeat("a", 64), Dimension: 2, ModelID: "synthetic-test-only", ModelRevision: "1", InputResolution: 224, PreprocessingVersion: "test-v1", Policies: map[string]string{"full": strings.Repeat("b", 64), "overlap": strings.Repeat("c", 64)}}, nil
}
func (w *syntheticSearchWorker) Image(_ context.Context, b []byte, mode string, d retrieval.Description) (retrieval.ImageResult, error) {
	if w.bad {
		return retrieval.ImageResult{ModelFingerprint: "malformed"}, nil
	}
	x := w.scores[protocol.Hash(b)]
	v := []float32{x, float32(math.Sqrt(1 - float64(x)*float64(x)))}
	out := retrieval.ImageResult{ModelFingerprint: d.ModelFingerprint, PolicyFingerprint: d.Policies[mode], Width: 4, Height: 3, Vectors: []retrieval.Vector{{Kind: "full", Box: retrieval.Box{0, 0, 1, 1}, Embedding: v}}}
	if mode == "overlap" {
		out.Vectors[0].Embedding = []float32{0, 1}
		out.Vectors = append(out.Vectors, retrieval.Vector{Kind: "crop", Box: retrieval.Box{.125, 0, .875, 1}, Embedding: v})
	}
	return out, nil
}
func (w *syntheticSearchWorker) Query(context.Context, retrieval.Query, []byte, retrieval.Description) ([]float32, error) {
	if w.afterQuery != nil {
		w.afterQuery()
	}
	return []float32{1, 0}, nil
}

func datasetFixture(t *testing.T, h *harness, a string, scores []float32) (search.ImportReport, *syntheticSearchWorker, string) {
	t.Helper()
	root := t.TempDir()
	worker := &syntheticSearchWorker{scores: map[string]float32{}}
	m := search.Manifest{Version: "1", Dataset: search.DatasetInfo{Name: "synthetic-public-test", Version: "1", Source: "synthetic-generated", License: "AGPL-3.0-only"}}
	b, _ := synthetic()
	for i, score := range scores {
		// A legal COM segment makes distinct exact originals without changing pixels.
		data := append([]byte{255, 216, 255, 254, 0, 3, byte(i)}, b[2:]...)
		if i == 1 {
			data = append([]byte{255, 216, 255, 254, 0, 3, 0}, b[2:]...)
		}
		name := fmt.Sprintf("%d.jpg", i)
		if err := os.WriteFile(filepath.Join(root, name), data, 0600); err != nil {
			t.Fatal(err)
		}
		item := search.DatasetItem{ID: fmt.Sprint(i), Path: name, SHA256: protocol.Hash(data), ByteLength: int64(len(data))}
		m.Items = append(m.Items, item)
		worker.scores[item.SHA256] = score
	}
	path := filepath.Join(root, "manifest.json")
	if err := os.WriteFile(path, encode(m), 0600); err != nil {
		t.Fatal(err)
	}
	s := search.New(h.api.DB, h.api.Files, worker)
	h.api.Search = s
	out, err := s.Import(context.Background(), postgres.Access{ArchiveID: a, Operator: true}, path)
	if err != nil {
		t.Fatal(err)
	}
	return out, worker, path
}
func searchPath(a string) string  { return "/v1/archives/" + a + "/search" }
func historyPath(a string) string { return "/v1/archives/" + a + "/history" }
func TestRetrievalHTTPUnknownHistoryDedupAliasesTenantAndOriginals(t *testing.T) {
	h := setup(t)
	a := h.owner()
	p := h.pair(a)
	other := h.pair(h.owner())
	ctx := context.Background()
	imp, w, path := datasetFixture(t, h, a, []float32{1, 1, .8, .7})
	repeat, e := h.api.Search.Import(ctx, postgres.Access{ArchiveID: a, Operator: true}, path)
	if e != nil || !bytes.Equal(encode(imp), encode(repeat)) {
		t.Fatal("import not idempotent", e)
	}
	var n int
	if e = h.admin.QueryRow(ctx, "SELECT count(*) FROM mt.frames WHERE archive_id=$1", a).Scan(&n); e != nil || n != 0 {
		t.Fatal("fabricated legacy captures", n, e)
	}
	d, _ := w.Describe(ctx)
	request := map[string]any{"generation_id": d.Generation("overlap"), "query": map[string]any{"text": "отвёртка"}, "min_score": .5}
	h.request("POST", searchPath(a), p.DeviceToken, "application/json", encode(request), 503, "")
	index, e := h.api.Search.Index(ctx, postgres.Access{ArchiveID: a, Operator: true}, "overlap", 100)
	if e != nil || index.Completed != 4 || index.Coverage.RegionsIndexed != 8 {
		t.Fatal(index, e)
	}
	res := h.request("POST", searchPath(a), p.DeviceToken, "application/json", encode(request), 200, "SearchResponse")
	var found retrieval.SearchResponse
	_ = json.Unmarshal(res.Body.Bytes(), &found)
	if len(found.Hits) != 4 || found.Truncated {
		t.Fatal("region duplicates or false truncation", found)
	}
	for _, hit := range found.Hits {
		if hit.Region.Kind != "crop" || hit.Region.Box[0] != .125 || hit.ObservedAtMS != nil {
			t.Fatal("lost floating region or invented time", hit)
		}
	}
	res = h.request("POST", historyPath(a), p.DeviceToken, "application/json", encode(request), 200, "HistoryResponse")
	var history retrieval.HistoryResponse
	_ = json.Unmarshal(res.Body.Bytes(), &history)
	if history.HistoryAvailable || history.FirstObservedMS != nil || history.LastObservedMS != nil || len(history.Observations) != 0 || len(history.UnsequencedHits) != 4 {
		t.Fatal("invented Open-Images-style history", history)
	}
	request["query"] = map[string]any{"asset_id": imp.Items[0].AssetID, "box": []float64{.125, 0, .875, 1}}
	res = h.request("POST", searchPath(a), p.DeviceToken, "application/json", encode(request), 200, "SearchResponse")
	_ = json.Unmarshal(res.Body.Bytes(), &found)
	if len(found.Hits) != 2 {
		t.Fatal("source/alias regions leaked", found)
	}
	for _, hit := range found.Hits {
		if hit.SHA256 == imp.Items[0].SHA256 {
			t.Fatal("self leak")
		}
	}
	for _, id := range []string{imp.Items[0].AssetID, protocol.NewID()} {
		url := searchPath(a) + "/assets/" + id + "/original"
		h.request("GET", url, other.DeviceToken, "", nil, 404, "")
	}
	url := searchPath(a) + "/assets/" + imp.Items[0].AssetID + "/original"
	res = h.request("GET", url, p.DeviceToken, "", nil, 200, "")
	if protocol.Hash(res.Body.Bytes()) != imp.Items[0].SHA256 {
		t.Fatal("original changed")
	}
	h.request("POST", searchPath(a), other.DeviceToken, "application/json", encode(request), 404, "")
	h.request("POST", searchPath(a), "", "application/json", encode(request), 401, "")
	otherImp, _, _ := datasetFixture(t, h, other.ArchiveID, []float32{1})
	h.api.Search = search.New(h.api.DB, h.api.Files, w)
	request["query"] = map[string]any{"asset_id": otherImp.Items[0].AssetID}
	h.request("POST", searchPath(a), p.DeviceToken, "application/json", encode(request), 404, "")
	request["query"] = map[string]any{"text": "scissors"}
	w.afterQuery = func() { h.sql("UPDATE mt.devices SET revoked=true WHERE id=$1", p.DeviceID) }
	h.request("POST", searchPath(a), p.DeviceToken, "application/json", encode(request), 401, "")
}

func TestRetrievalHTTPCompleteCutoffHistoryPartialAndGenerationSeparation(t *testing.T) {
	h := setup(t)
	a := h.owner()
	p := h.pair(a)
	ctx := context.Background()
	imp, w, _ := datasetFixture(t, h, a, []float32{1, 1, .6, .9, .8, .7, .95})
	// These explicit synthetic clocks are test evidence only, not dataset inference.
	for i, ms := range map[int]int64{2: 100, 3: 200, 4: 300} {
		h.sql("UPDATE mt.assets SET observed_at_ms=$3,sequence_id='A',sequence_position_ms=$3 WHERE archive_id=$1 AND id=$2", a, imp.Items[i].AssetID, ms)
	}
	h.sql("UPDATE mt.assets SET sequence_id='B',sequence_position_ms=1 WHERE archive_id=$1 AND id=$2", a, imp.Items[6].AssetID)
	idx, e := h.api.Search.Index(ctx, postgres.Access{ArchiveID: a, Operator: true}, "overlap", 100)
	if e != nil {
		t.Fatal(e)
	}
	r := map[string]any{"generation_id": idx.GenerationID, "query": map[string]any{"asset_id": imp.Items[0].AssetID}, "min_score": .5, "limit": 1, "timeline": map[string]any{"kind": "wall"}, "before_ms": 301, "gap_ms": 150}
	res := h.request("POST", historyPath(a), p.DeviceToken, "application/json", encode(r), 200, "HistoryResponse")
	var out retrieval.HistoryResponse
	_ = json.Unmarshal(res.Body.Bytes(), &out)
	if !out.HistoryAvailable || *out.FirstObservedMS != 100 || *out.LastObservedMS != 300 || !out.Truncated || len(out.Observations) != 1 || len(out.Observations[0].Evidence) != 1 || out.Observations[0].Evidence[0].AssetID != imp.Items[3].AssetID || out.Observations[0].StartMS != 100 || out.Observations[0].EndMS != 300 {
		t.Fatal("history truncated before complete bounds", out)
	}
	r["before_ms"] = 200
	res = h.request("POST", historyPath(a), p.DeviceToken, "application/json", encode(r), 200, "HistoryResponse")
	_ = json.Unmarshal(res.Body.Bytes(), &out)
	if *out.FirstObservedMS != 100 || *out.LastObservedMS != 100 || out.Truncated {
		t.Fatal("exclusive cutoff before rank/group failed", out)
	}
	r["timeline"] = map[string]any{"kind": "sequence", "sequence_id": "B"}
	r["before_ms"] = 2
	res = h.request("POST", historyPath(a), p.DeviceToken, "application/json", encode(r), 200, "HistoryResponse")
	_ = json.Unmarshal(res.Body.Bytes(), &out)
	if *out.FirstObservedMS != 1 || len(out.Observations) != 1 || out.Observations[0].Evidence[0].AssetID != imp.Items[6].AssetID {
		t.Fatal("mixed clocks", out)
	}
	full, e := h.api.Search.Index(ctx, postgres.Access{ArchiveID: a, Operator: true}, "full", 100)
	if e != nil || full.GenerationID == idx.GenerationID || full.Coverage.RegionsIndexed != 7 {
		t.Fatal("mixed generations", full, e)
	}
	// New committed frame is an asset with its actual supplied request time. It
	// makes the previous generation partial without inventing a vector/job success.
	b, m := synthetic()
	h.register(p, m)
	h.request("PUT", original(a, m.FrameID), p.DeviceToken, "image/jpeg", b, 200, "Receipt")
	res = h.request("POST", historyPath(a), p.DeviceToken, "application/json", encode(r), 200, "HistoryResponse")
	_ = json.Unmarshal(res.Body.Bytes(), &out)
	if !out.Truncated || out.Coverage.Pending != 1 || out.Coverage.AssetsTotal != 8 {
		t.Fatal("partial coverage hidden", out)
	}
	w.bad = true
	retry, e := h.api.Search.Index(ctx, postgres.Access{ArchiveID: a, Operator: true}, "overlap", 3)
	if e != nil || retry.FailedAttempts != 3 || retry.Coverage.Failed != 1 {
		t.Fatal("malformed worker attempts not persisted", retry, e)
	}
	w.bad = false
	retry, e = h.api.Search.Index(ctx, postgres.Access{ArchiveID: a, Operator: true}, "overlap", 3)
	if e != nil || retry.Completed != 0 || retry.Coverage.Failed != 1 {
		t.Fatal("terminal failure automatically reset", retry, e)
	}
	// Scope gates operate before ranking even when the requested cutoff is tiny.
	h.sql(`INSERT INTO mt.assets(archive_id,id,owner_id,source_kind,dataset_name,dataset_version,item_id,sha256,byte_length,provenance)
 SELECT $1,('00000000-0000-0000-0000-'||lpad(i::text,12,'0'))::uuid,owner_id,'dataset','scope-gate','1',i::text,$2,10,'{}' FROM mt.archives CROSS JOIN generate_series(1,5001) i WHERE id=$1`, a, strings.Repeat("d", 64))
	h.request("POST", historyPath(a), p.DeviceToken, "application/json", encode(r), 503, "")
}
func TestRetrievalHTTPStrictContractDecimalsAndDisabledIngestionCompatibility(t *testing.T) {
	h := setup(t)
	a := h.owner()
	p := h.pair(a)
	base := `{"generation_id":"` + strings.Repeat("a", 64) + `","query":{"text":"scissors"}`
	valid := []byte(base + `,"min_score":0.125,"limit":2e1}`)
	if e := contract.Validate("SearchRequest", valid); e != nil {
		t.Fatal(e)
	}
	h.request("POST", searchPath(a), p.DeviceToken, "application/json", valid, 503, "")
	for _, box := range []string{`[0,0,1e-400,1]`, `[0.5,0,0.50000000000000001,1]`} {
		raw := []byte(`{"generation_id":"` + strings.Repeat("a", 64) + `","query":{"asset_id":"` + protocol.NewID() + `","box":` + box + `}}`)
		if e := contract.Validate("SearchRequest", raw); e != nil {
			t.Fatal("canonical positive subpixel box rejected", e)
		}
		h.request("POST", searchPath(a), p.DeviceToken, "application/json", raw, 503, "")
	}
	for _, suffix := range []string{`,"limit":null}`, `,"min_score":null}`, `,"min_score":1.1}`, `,"before_ms":10}`, `,"gap_ms":0}`, `,"query":{"text":"duplicate"}}`, `,"LIMIT":2}`} {
		h.request("POST", searchPath(a), p.DeviceToken, "application/json", []byte(base+suffix), 400, "")
	}
	h.request("POST", historyPath(a), p.DeviceToken, "application/json", []byte(base+`}`), 400, "")
	h.request("GET", searchPath(a), p.DeviceToken, "", nil, 405, "")
	h.request("POST", searchPath(a), p.DeviceToken, "text/plain", valid, 415, "")
	h.request("POST", searchPath(a), p.DeviceToken, "application/json", bytes.Repeat([]byte(" "), protocol.MaxJSON+1), 413, "")
	// Existing New remains ingestion-only and reports unchanged health/pair/receipt.
	b, m := synthetic()
	h.register(p, m)
	h.request("PUT", original(a, m.FrameID), p.DeviceToken, "image/jpeg", b, 200, "Receipt")
	h.request("GET", "/healthz", "", "", nil, 200, "Health")
	var assetID string
	if e := h.admin.QueryRow(context.Background(), "SELECT id::text FROM mt.assets WHERE archive_id=$1 AND frame_id=$2", a, m.FrameID).Scan(&assetID); e != nil {
		t.Fatal(e)
	}
	url := searchPath(a) + "/assets/" + assetID + "/original"
	h.request("GET", url, p.DeviceToken, "", nil, 200, "")
	if e := os.Remove(filepath.Join(h.root, a+"_"+m.FrameID+".jpg")); e != nil {
		t.Fatal(e)
	}
	h.request("GET", url, p.DeviceToken, "", nil, 409, "integrity_error")
}

func TestHTTPExactPositiveSubnormalThresholdExcludesZeroScore(t *testing.T) {
	h := setup(t)
	a := h.owner()
	p := h.pair(a)
	ctx := context.Background()
	imp, _, _ := datasetFixture(t, h, a, []float32{0, 0, .8})
	idx, err := h.api.Search.Index(ctx, postgres.Access{ArchiveID: a, Operator: true}, "full", 100)
	if err != nil {
		t.Fatal(err)
	}
	req := map[string]any{"generation_id": idx.GenerationID, "query": map[string]any{"text": "scissors"}, "min_score": json.RawMessage(`1e-400`)}
	w := h.request("POST", searchPath(a), p.DeviceToken, "application/json", encode(req), 200, "SearchResponse")
	var result retrieval.SearchResponse
	if err = json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if len(result.Hits) != 1 || result.Hits[0].AssetID != imp.Items[2].AssetID {
		t.Fatal("tiny positive threshold rounded to zero", result)
	}
}

func TestDatasetImportIntegrityRollbackTraversalAndPrivateNamespace(t *testing.T) {
	h := setup(t)
	a := h.owner()
	ctx := context.Background()
	imp, _, path := datasetFixture(t, h, a, []float32{1, .8})
	raw, e := os.ReadFile(path)
	if e != nil {
		t.Fatal(e)
	}
	var m search.Manifest
	_ = json.Unmarshal(raw, &m)
	var before int
	if e = h.admin.QueryRow(ctx, "SELECT count(*) FROM mt.assets WHERE archive_id=$1", a).Scan(&before); e != nil {
		t.Fatal(e)
	}
	// A failure on item two rolls back the new first row after publication.
	m.Dataset.Version = "2"
	m.Items[1].SHA256 = strings.Repeat("f", 64)
	if e = os.WriteFile(path, encode(m), 0600); e != nil {
		t.Fatal(e)
	}
	if _, e = h.api.Search.Import(ctx, postgres.Access{ArchiveID: a, Operator: true}, path); e == nil {
		t.Fatal("hash mismatch imported")
	}
	var after int
	if e = h.admin.QueryRow(ctx, "SELECT count(*) FROM mt.assets WHERE archive_id=$1", a).Scan(&after); e != nil || after != before {
		t.Fatal("partial import", before, after, e)
	}
	_ = json.Unmarshal(raw, &m)
	m.Items[0].Path = "../outside.jpg"
	if e = os.WriteFile(path, encode(m), 0600); e != nil {
		t.Fatal(e)
	}
	if _, e = h.api.Search.Import(ctx, postgres.Access{ArchiveID: a, Operator: true}, path); e == nil {
		t.Fatal("traversal imported")
	}
	_ = json.Unmarshal(raw, &m)
	m.Dataset.Version = "symlink"
	m.Items = m.Items[:1]
	m.Items[0].Path = "link.jpg"
	outside := filepath.Join(t.TempDir(), "outside.jpg")
	b, e := os.ReadFile(filepath.Join(filepath.Dir(path), "0.jpg"))
	if e != nil {
		t.Fatal(e)
	}
	if e = os.WriteFile(outside, b, 0600); e != nil {
		t.Fatal(e)
	}
	if e = os.Symlink(outside, filepath.Join(filepath.Dir(path), "link.jpg")); e != nil {
		t.Fatal(e)
	}
	if e = os.WriteFile(path, encode(m), 0600); e != nil {
		t.Fatal(e)
	}
	if _, e = h.api.Search.Import(ctx, postgres.Access{ArchiveID: a, Operator: true}, path); e == nil {
		t.Fatal("symlink escaped manifest root")
	}
	if _, e = os.Stat(filepath.Join(h.root, "asset-"+a+"_"+imp.Items[0].AssetID+".jpg")); e != nil {
		t.Fatal("private namespace missing", e)
	}
	if _, e = os.Stat(filepath.Join(h.root, a+"_"+imp.Items[0].AssetID+".jpg")); !os.IsNotExist(e) {
		t.Fatal("dataset reused frame namespace")
	}
	// A device can choose a frame UUID equal to an exposed dataset asset UUID.
	// Server-generated frame-asset identity must prevent hiding that committed frame.
	p := h.pair(a)
	image, mdata := synthetic()
	mdata.FrameID = imp.Items[0].AssetID
	h.register(p, mdata)
	h.request("PUT", original(a, mdata.FrameID), p.DeviceToken, "image/jpeg", image, 200, "Receipt")
	var frameAssetID string
	if e = h.admin.QueryRow(ctx, "SELECT id::text FROM mt.assets WHERE archive_id=$1 AND frame_id=$2", a, mdata.FrameID).Scan(&frameAssetID); e != nil || frameAssetID == mdata.FrameID {
		t.Fatal("frame/dataset identity collision", e)
	}
	h.request("GET", searchPath(a)+"/assets/"+frameAssetID+"/original", p.DeviceToken, "", nil, 200, "")
}
