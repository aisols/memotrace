// SPDX-License-Identifier: AGPL-3.0-only
package inference

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
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
	if mode == "ignore-stop" {
		signal.Ignore(syscall.SIGTERM)
	}
	for _, e := range os.Environ() {
		if strings.HasPrefix(e, "MEMOTRACE_") || strings.HasPrefix(e, "AWS_") || strings.HasPrefix(e, "PGPASSWORD=") {
			os.Exit(9)
		}
	}
	if os.Getenv("HF_HUB_OFFLINE") != "1" || os.Getenv("UV_OFFLINE") != "1" {
		os.Exit(8)
	}
	if mode == "pdeath-parent" {
		if len(os.Args) == 0 {
			os.Exit(11)
		}
		pidFile := os.Args[len(os.Args)-1]
		exe, err := os.Executable()
		if err != nil {
			os.Exit(12)
		}
		w, err := New([]string{exe, "-test.run=^TestSyntheticWorkerProcess$", "--", "fixture=pdeath-child"}, time.Minute)
		if err != nil || w.start() != nil {
			os.Exit(13)
		}
		if err = os.WriteFile(pidFile, []byte(strconv.Itoa(w.cmd.Process.Pid)), 0600); err != nil {
			os.Exit(14)
		}
		os.Exit(0) // Deliberately bypass Worker.Close to exercise Pdeathsig.
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
		if mode == "inference-failed" && req["op"] != "describe" {
			_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"id": req["id"], "ok": false, "error": "inference_failed"})
			continue
		}
		if mode == "input-failed" && req["op"] == "query_image" {
			_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"id": req["id"], "ok": false, "error": "input_failed"})
			continue
		}
		if mode == "input-failed-extra" {
			_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"id": req["id"], "ok": false, "error": "input_failed", "extra": true})
			continue
		}
		text, _ := req["text"].(string)
		if mode == "token-limit" && req["op"] == "text" && len(strings.Fields(text)) > 64 {
			_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"id": req["id"], "ok": false, "error": "invalid_request"})
			continue
		}
		if mode == "reject-query" && req["op"] != "describe" {
			_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"id": req["id"], "ok": false, "error": "invalid_request"})
			continue
		}
		if mode == "invalid-extra" {
			_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"id": req["id"], "ok": false, "error": "invalid_request", "extra": true})
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
	if mode == "ignore-stop" {
		for {
			time.Sleep(time.Hour)
		}
	}
	os.Exit(0)
}

func TestCloseRequestsGracefulStopAndReportsEscalation(t *testing.T) {
	for _, tc := range []struct {
		mode    string
		wantErr bool
	}{{"ok", false}, {"ignore-stop", true}} {
		t.Run(tc.mode, func(t *testing.T) {
			w := testWorker(t, tc.mode, 2*time.Second)
			if _, err := w.Describe(context.Background()); err != nil {
				t.Fatal(err)
			}
			pid := w.cmd.Process.Pid
			err := w.Close()
			if errors.Is(err, ErrWorker) != tc.wantErr {
				t.Fatal("incorrect shutdown result", err)
			}
			if w.cmd != nil || processGroupAlive(pid) {
				t.Fatal("worker process group survived close")
			}
		})
	}
}

func TestAbruptParentDeathKillsWorker(t *testing.T) {
	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	home := t.TempDir()
	pidFile := filepath.Join(t.TempDir(), "worker-pid")
	parent := exec.Command(exe, "-test.run=^TestSyntheticWorkerProcess$", "--", "fixture=pdeath-parent", pidFile)
	parent.Env = environment(home)
	parent.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err = parent.Run(); err != nil {
		t.Fatal("parent fixture failed", err)
	}
	raw, err := os.ReadFile(pidFile)
	if err != nil {
		t.Fatal(err)
	}
	pid, err := strconv.Atoi(string(raw))
	if err != nil {
		t.Fatal(err)
	}
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		err = syscall.Kill(pid, 0)
		if errors.Is(err, syscall.ESRCH) {
			return
		}
		state, readErr := os.ReadFile(filepath.Join("/proc", strconv.Itoa(pid), "stat"))
		if readErr == nil {
			fields := strings.Fields(string(state))
			if len(fields) > 2 && fields[2] == "Z" {
				return
			}
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("worker survived abrupt parent death")
}

func TestQueryWorkerInvalidRequestRetainsProcessAndDependsOnOperation(t *testing.T) {
	w := testWorker(t, "reject-query", 2*time.Second)
	d, err := w.Describe(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	pid := w.cmd.Process.Pid
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
		if w.cmd == nil || w.cmd.Process.Pid != pid {
			t.Fatal("valid invalid_request restarted worker")
		}
		if _, err = w.Describe(context.Background()); err != nil {
			t.Fatal("worker did not recover after invalid request", err)
		}
	}
}

func TestOverTokenizedTextDoesNotRestartWorker(t *testing.T) {
	w := testWorker(t, "token-limit", 2*time.Second)
	d, err := w.Describe(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	pid := w.cmd.Process.Pid
	text := strings.Repeat("word ", 65)
	if _, err = w.Query(context.Background(), retrieval.Query{Text: &text}, nil, d); err == nil {
		t.Fatal("over-tokenized text accepted")
	} else {
		var pe *protocol.Error
		if !errors.As(err, &pe) || pe.Code != "invalid_request" {
			t.Fatal("incorrect over-tokenized text error", err)
		}
	}
	text = "subsequent valid request"
	if _, err = w.Query(context.Background(), retrieval.Query{Text: &text}, nil, d); err != nil {
		t.Fatal("worker did not recover after over-tokenized text", err)
	}
	if w.cmd == nil || w.cmd.Process.Pid != pid {
		t.Fatal("over-tokenized text restarted worker")
	}
}

func TestInputFailureDoesNotRestartWorker(t *testing.T) {
	w := testWorker(t, "input-failed", 2*time.Second)
	d, err := w.Describe(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	pid := w.cmd.Process.Pid
	if _, err = w.Query(context.Background(), retrieval.Query{}, []byte{1}, d); err == nil {
		t.Fatal("failed input accepted")
	} else {
		var pe *protocol.Error
		if !errors.As(err, &pe) || pe.Code != "unavailable" {
			t.Fatal("incorrect failed-input public mapping", err)
		}
	}
	text := "healthy subsequent request"
	if _, err = w.Query(context.Background(), retrieval.Query{Text: &text}, nil, d); err != nil {
		t.Fatal("worker did not recover after failed input", err)
	}
	if w.cmd == nil || w.cmd.Process.Pid != pid {
		t.Fatal("failed input restarted worker")
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
	for _, mode := range []string{"death", "malformed", "invalid-extra", "input-failed-extra", "wrong-id", "oversize", "hang"} {
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
	for _, mode := range []string{"wrong-model", "wrong-norm", "inference-failed"} {
		t.Run(mode, func(t *testing.T) {
			w := testWorker(t, mode, 2*time.Second)
			d, e := w.Describe(context.Background())
			if e != nil {
				t.Fatal(e)
			}
			if _, e = w.Query(context.Background(), retrieval.Query{Text: &text}, nil, d); e == nil {
				t.Fatal("invalid query result accepted")
			}
			if w.cmd != nil {
				t.Fatal("invalid result process retained")
			}
			w.argv[len(w.argv)-1] = "fixture=ok"
			if _, e = w.Describe(context.Background()); e != nil {
				t.Fatal("restart after inference failure failed", e)
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
