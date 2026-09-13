// SPDX-License-Identifier: AGPL-3.0-only
package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"memotrace/server/internal/inference"
	"memotrace/server/internal/postgres"
	"memotrace/server/internal/protocol"
	"memotrace/server/internal/search"
)

// Optional genuine Python decode/preprocessing interoperability; the ordinary Go
// gate remains autonomous/model-free. This fixture imports the actual component
// worker/decoder, never weights. A marker proves inference was not attempted for
// bad entropy; valid exact query boxes must produce the expected touched pixels.
func TestHTTPPythonDecodeFailureAndExactQueryPixels(t *testing.T) {
	python := os.Getenv("MEMOTRACE_TEST_ML_PYTHON")
	if python == "" {
		t.Skip("explicit ML Python interpreter not supplied for decoder IPC check")
	}
	if !filepath.IsAbs(python) {
		t.Fatal("ML test Python must be absolute")
	}
	h := setup(t)
	a := h.owner()
	p := h.pair(a)
	ctx := context.Background()
	imp, _, _ := datasetFixture(t, h, a, []float32{1, 1, .8})
	idx, err := h.api.Search.Index(ctx, postgres.Access{ArchiveID: a, Operator: true}, "overlap", 100)
	if err != nil {
		t.Fatal(err)
	}
	b, m := synthetic()
	sos := bytes.Index(b, []byte{255, 218})
	if sos < 0 {
		t.Fatal("SOS missing")
	}
	end := sos + 2 + int(b[sos+2])*256 + int(b[sos+3])
	b = append(b[:end], 255, 192, 0, 0, 255, 217)
	m.SHA256 = protocol.Hash(b)
	m.ByteLength = int64(len(b))
	h.register(p, m)
	h.request("PUT", original(a, m.FrameID), p.DeviceToken, "image/jpeg", b, 200, "Receipt")
	var badAsset string
	if err = h.admin.QueryRow(ctx, "SELECT id::text FROM mt.assets WHERE archive_id=$1 AND frame_id=$2", a, m.FrameID).Scan(&badAsset); err != nil {
		t.Fatal(err)
	}
	ml, err := filepath.Abs("../../ml")
	if err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(t.TempDir(), "decoder-inference-marker")
	const fixture = `
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from memotrace_ml.images import Policy
from memotrace_ml.model import UnsupportedText
from memotrace_ml.worker import Worker, serve
class TestEncoder:
    model_fingerprint = 'a'*64
    dimension = 2
    input_resolution = 224
    preprocessing_version = 'test-v1'
    def images(self, images):
        Path(sys.argv[2]).write_text(str([image.size for image in images]))
        if len(images) != 1 or images[0].size != (1,3):
            raise AssertionError('test must receive exactly the touched pixel column')
        return [[1.0,0.0]]
    def text(self, text):
        Path(sys.argv[2]).write_text('text-encoder-called')
        raise UnsupportedText('unsupported test text')
class DecoderFixture(Worker):
    def describe(self):
        return dict(model_fingerprint='a'*64,dimension=2,model_id='synthetic-test-only',model_revision='1',input_resolution=224,preprocessing_version='test-v1',policies=dict(full='b'*64,overlap='c'*64))
serve(DecoderFixture(TestEncoder(), Policy()), sys.stdin.buffer, sys.stdout.buffer)
`
	w, err := inference.New([]string{python, "-c", fixture, ml, marker}, 10*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Close()
	h.api.Search = search.New(h.api.DB, h.api.Files, w)
	request := map[string]any{"generation_id": idx.GenerationID, "query": map[string]any{"asset_id": badAsset}}
	response := h.request("POST", searchPath(a), p.DeviceToken, "application/json", encode(request), 503, "")
	if _, err = os.Stat(marker); !os.IsNotExist(err) {
		t.Fatal("invalid JPEG reached encoder", err)
	}
	for _, private := range []string{marker, ml, python, badAsset, p.DeviceToken, "entropy", "decode", "Traceback"} {
		if strings.Contains(response.Body.String(), private) {
			t.Fatal("private decoder details leaked")
		}
	}
	request["query"] = map[string]any{"text": "unsupported"}
	h.request("POST", searchPath(a), p.DeviceToken, "application/json", encode(request), 400, "")
	if got, err := os.ReadFile(marker); err != nil || string(got) != "text-encoder-called" {
		t.Fatal("ordinary unsupported text did not reach test encoder", string(got), err)
	}
	if err = os.Remove(marker); err != nil {
		t.Fatal(err)
	}
	for _, control := range []string{"\x7f", "\u0080", "\u009f"} {
		request["query"] = map[string]any{"text": "visible" + control}
		h.request("POST", searchPath(a), p.DeviceToken, "application/json", encode(request), 400, "")
		if _, err = os.Stat(marker); !os.IsNotExist(err) {
			t.Fatal("Unicode control reached encoder", err)
		}
	}
	for _, box := range []string{`[0,0,1e-400,1]`, `[0.5,0,0.50000000000000001,1]`} {
		request["query"] = map[string]any{"asset_id": imp.Items[0].AssetID, "box": json.RawMessage(box)}
		h.request("POST", searchPath(a), p.DeviceToken, "application/json", encode(request), 200, "SearchResponse")
		got, err := os.ReadFile(marker)
		if err != nil || string(got) != "[(1, 3)]" {
			t.Fatal("query endpoints did not rasterize to the touched pixels", string(got), err)
		}
		if err = os.Remove(marker); err != nil {
			t.Fatal(err)
		}
	}
}
