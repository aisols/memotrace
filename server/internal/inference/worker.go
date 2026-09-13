// SPDX-License-Identifier: AGPL-3.0-only
// Package inference manages the private, offline JSONL subprocess. It knows no DB.
package inference

import (
	"bufio"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"sync"
	"syscall"
	"time"

	"memotrace/server/internal/protocol"
	"memotrace/server/internal/retrieval"
	"memotrace/server/internal/strictjson"
)

const MaxInput = 24 * 1024 * 1024
const MaxOutput = 2 * 1024 * 1024
const shutdownTimeout = 2 * time.Second

var ErrWorker = errors.New("inference unavailable")
var errInput = errors.New("inference input unavailable")

type Worker struct {
	argv    []string
	gate    chan struct{}
	timeout time.Duration
	cmd     *exec.Cmd
	in      io.WriteCloser
	out     *bufio.Reader
	next    uint64
	closed  bool
}

// New accepts only trusted local operator argv, never a command from HTTP JSON.
// Requests are serialized. The service admits one inference request at a time;
// this worker has zero wait queue: busy returns unavailable.
func New(argv []string, timeout time.Duration) (*Worker, error) {
	if len(argv) == 0 || len(argv) > 64 || timeout <= 0 || timeout > 5*time.Minute {
		return nil, ErrWorker
	}
	for _, s := range argv {
		if !retrieval.Text(s, 4096) {
			return nil, ErrWorker
		}
	}
	path, err := exec.LookPath(argv[0])
	if err != nil {
		return nil, ErrWorker
	}
	path, err = filepath.Abs(path)
	if err != nil {
		return nil, ErrWorker
	}
	a := append([]string(nil), argv...)
	a[0] = path
	return &Worker{argv: a, gate: make(chan struct{}, 1), timeout: timeout}, nil
}

// Environment is an allowlist, not a secret-name denylist. HOME points to a fresh
// private temporary directory, preventing implicit credentials/config discovery.
func environment(home string) []string {
	return []string{"PATH=/usr/local/bin:/usr/bin:/bin", "HOME=" + home, "LANG=C.UTF-8", "PYTHONUNBUFFERED=1", "PYTHONDONTWRITEBYTECODE=1", "HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1", "HF_DATASETS_OFFLINE=1", "UV_OFFLINE=1", "UV_NO_SYNC=1", "UV_PYTHON_DOWNLOADS=never", "TOKENIZERS_PARALLELISM=false", "OMP_NUM_THREADS=4", "MKL_NUM_THREADS=4", "OPENBLAS_NUM_THREADS=4"}
}

// cappedLog consumes all stderr while retaining at most 8KiB, never emitting model
// paths, query text or child diagnostics in a public error or server log.
type cappedLog struct {
	mu sync.Mutex
	b  []byte
}

func (b *cappedLog) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	n := len(p)
	left := 8192 - len(b.b)
	if left > 0 {
		if len(p) > left {
			p = p[:left]
		}
		b.b = append(b.b, p...)
	}
	return n, nil
}

func (w *Worker) start() error {
	home, err := os.MkdirTemp("", "memotrace-worker-")
	if err != nil {
		return ErrWorker
	}
	c := exec.Command(w.argv[0], w.argv[1:]...)
	c.Env = environment(home)
	c.SysProcAttr = &syscall.SysProcAttr{Setpgid: true, Pdeathsig: syscall.SIGKILL}
	c.Stderr = &cappedLog{}
	c.WaitDelay = 2 * time.Second
	in, err := c.StdinPipe()
	if err != nil {
		os.RemoveAll(home)
		return ErrWorker
	}
	out, err := c.StdoutPipe()
	if err != nil {
		in.Close()
		os.RemoveAll(home)
		return ErrWorker
	}
	if err = c.Start(); err != nil {
		in.Close()
		out.Close()
		os.RemoveAll(home)
		return ErrWorker
	}
	w.cmd = c
	w.in = in
	w.out = bufio.NewReaderSize(out, MaxOutput+1)
	return nil
}

func processGroupAlive(pid int) bool {
	err := syscall.Kill(-pid, 0)
	return err == nil || errors.Is(err, syscall.EPERM)
}

func awaitProcessGroup(pid int, done <-chan struct{}, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for {
		finished := false
		select {
		case <-done:
			finished = true
		default:
		}
		if finished && !processGroupAlive(pid) {
			return true
		}
		if !time.Now().Before(deadline) {
			return false
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func (w *Worker) clear() {
	for _, s := range w.cmd.Env {
		if len(s) > 5 && s[:5] == "HOME=" {
			_ = os.RemoveAll(s[5:])
		}
	}
	w.cmd = nil
	w.in = nil
	w.out = nil
}

func (w *Worker) stop() {
	if w.cmd == nil {
		return
	}
	_ = syscall.Kill(-w.cmd.Process.Pid, syscall.SIGKILL)
	_ = w.in.Close()
	_ = w.cmd.Wait()
	w.clear()
}
func (w *Worker) Close() error {
	w.gate <- struct{}{}
	defer func() { <-w.gate }()
	w.closed = true
	if w.cmd == nil {
		return nil
	}
	pid := w.cmd.Process.Pid
	_ = syscall.Kill(-pid, syscall.SIGTERM)
	_ = w.in.Close()
	cmd := w.cmd
	done := make(chan struct{})
	go func() {
		_ = cmd.Wait()
		close(done)
	}()
	if awaitProcessGroup(pid, done, shutdownTimeout) {
		w.clear()
		return nil
	}
	_ = syscall.Kill(-pid, syscall.SIGKILL)
	_ = awaitProcessGroup(pid, done, shutdownTimeout)
	w.clear()
	return ErrWorker
}

func (w *Worker) call(ctx context.Context, request map[string]any, dst any) error {
	select {
	case w.gate <- struct{}{}:
		defer func() { <-w.gate }()
	default:
		return ErrWorker
	}
	if w.closed {
		return ErrWorker
	}
	ctx, cancel := context.WithTimeout(ctx, w.timeout)
	defer cancel()
	if err := ctx.Err(); err != nil {
		return ErrWorker
	}
	if w.cmd == nil {
		if err := w.start(); err != nil {
			return err
		}
	}
	w.next++
	id := strconv.FormatUint(w.next, 10)
	request["id"] = id
	b, err := json.Marshal(request)
	if err != nil || len(b)+1 > MaxInput {
		return ErrWorker
	}
	b = append(b, '\n')
	type result struct {
		b   []byte
		err error
	}
	done := make(chan result, 1)
	in, out := w.in, w.out
	go func() {
		_, e := in.Write(b)
		if e != nil {
			done <- result{err: e}
			return
		}
		line, e := out.ReadSlice('\n')
		if len(line) > MaxOutput {
			e = ErrWorker
		}
		done <- result{b: append([]byte(nil), line...), err: e}
	}()
	var got result
	select {
	case got = <-done:
	case <-ctx.Done():
		w.stop()
		<-done
		return ErrWorker
	}
	if got.err != nil {
		w.stop()
		return ErrWorker
	}
	v, err := strictjson.Value(got.b)
	m, ok := v.(map[string]any)
	if err == nil && ok && m["id"] == id && m["ok"] == false && len(m) == 3 {
		switch m["error"] {
		case "invalid_request":
			return protocol.E("invalid_request")
		case "input_failed":
			return errInput
		}
	}
	if err != nil || !ok || m["id"] != id || m["ok"] != true {
		w.stop()
		return ErrWorker
	}
	delete(m, "id")
	delete(m, "ok")
	if err = strictjson.Assign(m, dst); err != nil {
		w.stop()
		return ErrWorker
	}
	return nil
}
func (w *Worker) Reset() { w.gate <- struct{}{}; defer func() { <-w.gate }(); w.stop() }
func (w *Worker) Describe(ctx context.Context) (retrieval.Description, error) {
	var d retrieval.Description
	err := w.call(ctx, map[string]any{"op": "describe"}, &d)
	if err == nil && !d.Valid() {
		w.Reset()
		err = ErrWorker
	}
	return d, err
}
func (w *Worker) Image(ctx context.Context, b []byte, mode string, d retrieval.Description) (retrieval.ImageResult, error) {
	var out retrieval.ImageResult
	if len(b) < 1 || len(b) > protocol.MaxBytes || (mode != "full" && mode != "overlap") {
		return out, ErrWorker
	}
	err := w.call(ctx, map[string]any{"op": "image", "image_base64": base64.StdEncoding.EncodeToString(b), "mode": mode}, &out)
	if err == nil && !out.Valid(d, mode) {
		w.Reset()
		err = ErrWorker
	}
	return out, err
}
func (w *Worker) Query(ctx context.Context, q retrieval.Query, b []byte, d retrieval.Description) ([]float32, error) {
	req := map[string]any{}
	if q.Text != nil {
		if !retrieval.Text(*q.Text, 2048) {
			return nil, protocol.E("invalid_request")
		}
		req["op"] = "text"
		req["text"] = *q.Text
	} else {
		if len(b) < 1 || len(b) > protocol.MaxBytes {
			return nil, ErrWorker
		}
		if q.Box != nil && !q.Box.Valid() {
			return nil, protocol.E("invalid_request")
		}
		req["op"] = "query_image"
		req["image_base64"] = base64.StdEncoding.EncodeToString(b)
		if q.Box != nil {
			req["box"] = q.Box
		}
	}
	var out struct {
		ModelFingerprint string    `json:"model_fingerprint"`
		Embedding        []float32 `json:"embedding"`
	}
	err := w.call(ctx, req, &out)
	// Geometry is already validated. A stored JPEG may satisfy ingestion's header
	// contract yet fail the worker's full entropy decode. That is unavailable
	// source content/inference, not an invalid public image-query request. Text
	// token/unsupported-input rejection keeps the explicit 400 contract meaning.
	if err != nil && q.Text == nil {
		return nil, protocol.E("unavailable")
	}
	if err == nil && (out.ModelFingerprint != d.ModelFingerprint || !retrieval.Unit(out.Embedding, d.Dimension)) {
		w.Reset()
		err = ErrWorker
	}
	return out.Embedding, err
}
