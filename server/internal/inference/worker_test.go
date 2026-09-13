// SPDX-License-Identifier: AGPL-3.0-only
package inference

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"

	"memotrace/server/internal/protocol"
	"memotrace/server/internal/retrieval"
)

// This subprocess exists only in a *_test.go binary. It is explicitly synthetic,
// never selectable by a production fallback/environment switch.
func TestSyntheticWorkerProcess(t *testing.T) {
	mode := ""
	for _, a := range os.Args {
		if strings.HasPrefix(a, "fixture=") {
			mode = strings.TrimPrefix(a, "fixture=")
		}
	}
	if mode == "" {
		return
	}
	for _, e := range os.Environ() {
		if strings.HasPrefix(e, "MEMOTRACE_") || strings.HasPrefix(e, "AWS_") || strings.HasPrefix(e, "PGPASSWORD=") {
			os.Exit(9)
		}
	}
	if os.Getenv("HF_HUB_OFFLINE") != "1" || os.Getenv("UV_OFFLINE") != "1" {
		os.Exit(8)
	}
	s := bufio.NewScanner(os.Stdin)
	s.Buffer(make([]byte, 4096), MaxInput)
	for s.Scan() {
		var req map[string]any
		d := json.NewDecoder(strings.NewReader(s.Text()))
		d.UseNumber()
		_ = d.Decode(&req)
		switch mode {
		case "death":
			os.Exit(7)
		case "hang":
			time.Sleep(time.Minute)
		case "oversize":
			fmt.Print(strings.Repeat("x", MaxOutput+1))
			os.Stdout.Sync()
			time.Sleep(time.Minute)
		case "malformed":
			fmt.Println(`{"id":"1","id":"1","ok":true}`)
			continue
		case "stderr":
			fmt.Fprint(os.Stderr, strings.Repeat("private-diagnostic", 10000))
		}
		out := map[string]any{"id": req["id"], "ok": true, "model_fingerprint": strings.Repeat("a", 64)}
		if mode == "wrong-id" {
			out["id"] = "wrong"
		}
		if mode == "rejected" {
			_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"id": req["id"], "ok": false, "error": "invalid_request"})
			continue
		}
		if mode == "reject-query" && req["op"] != "describe" {
			_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"id": req["id"], "ok": false, "error": "invalid_request"})
			continue
		}
		if mode == "exact-box" && req["op"] == "query_image" {
			box, _ := json.Marshal(req["box"])
			if string(box) != `[0,0,1e-400,1]` && string(box) != `[0.5,0,0.50000000000000001,1]` {
				os.Exit(10)
			}
		}
		switch req["op"] {
		case "describe":
			out["dimension"] = 2
			out["model_id"] = "synthetic-test-only"
			out["model_revision"] = "1"
			out["input_resolution"] = 224
			out["preprocessing_version"] = "1"
			out["policies"] = map[string]string{"full": strings.Repeat("b", 64), "overlap": strings.Repeat("c", 64)}
		case "text", "query_image":
			out["embedding"] = []float32{1, 0}
			if mode == "wrong-model" {
				out["model_fingerprint"] = strings.Repeat("d", 64)
			}
			if mode == "wrong-norm" {
				out["embedding"] = []float32{2, 0}
			}
		case "image":
			out["policy_fingerprint"] = strings.Repeat("b", 64)
			out["width"] = 4
			out["height"] = 3
			out["vectors"] = []retrieval.Vector{{Kind: "full", Box: retrieval.Box{0, 0, 1, 1}, Embedding: []float32{1, 0}}}
		}
		_ = json.NewEncoder(os.Stdout).Encode(out)
	}
	os.Exit(0)
}

func TestQueryWorkerRejectionDependsOnOperation(t *testing.T) {
	w := testWorker(t, "reject-query", 2*time.Second)
	d, err := w.Describe(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	text := "unsupported text"
	for _, tc := range []struct {
		query retrieval.Query
		body  []byte
		code  string
	}{{retrieval.Query{Text: &text}, nil, "invalid_request"}, {retrieval.Query{}, []byte{1}, "unavailable"}} {
		_, err = w.Query(context.Background(), tc.query, tc.body, d)
		var pe *protocol.Error
		if !errors.As(err, &pe) || pe.Code != tc.code {
			t.Fatal("incorrect operation error", err, tc.code)
		}
		if w.cmd != nil {
			t.Fatal("rejected process retained")
		}
	}
}

func TestQueryDecimalEndpointsReachJSONLUnchanged(t *testing.T) {
	w := testWorker(t, "exact-box", 2*time.Second)
	d, err := w.Describe(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	for _, box := range []retrieval.QueryBox{{"0", "0", "1e-400", "1"}, {"0.5", "0", "0.50000000000000001", "1"}} {
		if _, err = w.Query(context.Background(), retrieval.Query{Box: &box}, []byte{1}, d); err != nil {
			t.Fatal("decimal box changed across private IPC", err)
		}
	}
	bad := retrieval.QueryBox{"0", "0", "0", "1"}
	if _, err = w.Query(context.Background(), retrieval.Query{Box: &bad}, []byte{1}, d); err == nil {
		t.Fatal("invalid box reached worker")
	}
}
func testWorker(t *testing.T, mode string, timeout time.Duration) *Worker {
	t.Helper()
	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	w, err := New([]string{exe, "-test.run=^TestSyntheticWorkerProcess$", "--", "fixture=" + mode}, timeout)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { w.Close() })
	return w
}
func TestRealSubprocessIPCEnvironmentBoundsFailureAndRestart(t *testing.T) {
	t.Setenv("MEMOTRACE_ADMIN_DSN", "must-not-be-in-child")
	t.Setenv("AWS_SECRET_ACCESS_KEY", "must-not-be-in-child")
	t.Setenv("PGPASSWORD", "must-not-be-in-child")
	w := testWorker(t, "stderr", 2*time.Second)
	d, err := w.Describe(context.Background())
	if err != nil || !d.Valid() {
		t.Fatal(d, err)
	}
	text := "отвёртка"
	if _, err = w.Query(context.Background(), retrieval.Query{Text: &text}, nil, d); err != nil {
		t.Fatal(err)
	}
	if _, err = w.Image(context.Background(), []byte{1}, "full", d); err != nil {
		t.Fatal(err)
	}
	for _, mode := range []string{"death", "malformed", "wrong-id", "oversize", "hang"} {
		t.Run(mode, func(t *testing.T) {
			w := testWorker(t, mode, 150*time.Millisecond)
			if _, err := w.Describe(context.Background()); err == nil {
				t.Fatal("bad worker accepted")
			}
			if w.cmd != nil {
				t.Fatal("failed process retained")
			}
			// Replace only test argv after failure; next call must spawn a fresh process.
			w.argv[len(w.argv)-1] = "fixture=ok"
			w.timeout = 2 * time.Second
			if _, err := w.Describe(context.Background()); err != nil {
				t.Fatal("restart failed", err)
			}
		})
	}
	for _, mode := range []string{"wrong-model", "wrong-norm", "rejected"} {
		t.Run(mode, func(t *testing.T) {
			w := testWorker(t, mode, 2*time.Second)
			d, e := w.Describe(context.Background())
			if mode == "rejected" {
				if e == nil {
					t.Fatal("rejected accepted")
				}
				return
			}
			if e != nil {
				t.Fatal(e)
			}
			if _, e = w.Query(context.Background(), retrieval.Query{Text: &text}, nil, d); e == nil {
				t.Fatal("invalid query result accepted")
			}
			if w.cmd != nil {
				t.Fatal("invalid result process retained")
			}
		})
	}
}
func TestCancellationKillsWorkerAndBusyAdmission(t *testing.T) {
	w := testWorker(t, "hang", time.Minute)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { _, e := w.Describe(ctx); done <- e }()
	deadline := time.Now().Add(time.Second)
	for len(w.gate) == 0 && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if _, e := w.Describe(context.Background()); e == nil {
		t.Fatal("unbounded busy admission")
	}
	cancel()
	select {
	case e := <-done:
		if e == nil {
			t.Fatal("cancellation accepted")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("worker cancellation stuck")
	}
	if w.cmd != nil {
		t.Fatal("canceled process retained")
	}
	b := &cappedLog{}
	p := []byte(strings.Repeat("x", 20000))
	if n, e := b.Write(p); n != len(p) || e != nil || len(b.b) != 8192 {
		t.Fatal("stderr unbounded")
	}
}
