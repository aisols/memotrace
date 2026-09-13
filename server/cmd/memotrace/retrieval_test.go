// SPDX-License-Identifier: AGPL-3.0-only
package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"image"
	"image/jpeg"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"memotrace/server/internal/archive"
	"memotrace/server/internal/contract"
	"memotrace/server/internal/protocol"
	"memotrace/server/internal/retrieval"
	"memotrace/server/internal/search"
)

// Explicit test-binary-only JSONL fixture, never installed in the production CLI.
func TestCLISyntheticInferenceProcess(t *testing.T) {
	fixture, started, release := false, "", ""
	for i, arg := range os.Args {
		switch arg {
		case "synthetic-fixture":
			fixture = true
		case "synthetic-blocking-fixture":
			if len(os.Args) != i+3 {
				os.Exit(2)
			}
			fixture, started, release = true, os.Args[i+1], os.Args[i+2]
		}
	}
	if !fixture {
		return
	}
	for _, v := range os.Environ() {
		if strings.HasPrefix(v, "MEMOTRACE_") || strings.HasPrefix(v, "AWS_") {
			os.Exit(3)
		}
	}
	d := retrieval.Description{ModelFingerprint: strings.Repeat("a", 64), Dimension: 2, ModelID: "synthetic-test-only", ModelRevision: "1", InputResolution: 224, PreprocessingVersion: "1", Policies: map[string]string{"full": strings.Repeat("b", 64), "overlap": strings.Repeat("c", 64)}}
	s := bufio.NewScanner(os.Stdin)
	s.Buffer(make([]byte, 1024), 24*1024*1024)
	for s.Scan() {
		var req map[string]any
		if json.Unmarshal(s.Bytes(), &req) != nil {
			os.Exit(4)
		}
		var result any
		switch req["op"] {
		case "describe":
			result = d
		case "image":
			result = retrieval.ImageResult{ModelFingerprint: d.ModelFingerprint, PolicyFingerprint: d.Policies["full"], Width: 3, Height: 2, Vectors: []retrieval.Vector{{Kind: "full", Box: retrieval.Box{0, 0, 1, 1}, Embedding: []float32{1, 0}}}}
		default:
			if started != "" {
				marker := strconv.Itoa(os.Getpid()) + "\n" + os.Getenv("HOME")
				if os.WriteFile(started, []byte(marker), 0600) != nil {
					os.Exit(5)
				}
				deadline := time.Now().Add(10 * time.Second)
				for {
					if _, err := os.Stat(release); err == nil {
						break
					} else if !errors.Is(err, os.ErrNotExist) || time.Now().After(deadline) {
						os.Exit(6)
					}
					time.Sleep(5 * time.Millisecond)
				}
			}
			result = map[string]any{"model_fingerprint": d.ModelFingerprint, "embedding": []float32{1, 0}}
		}
		b, _ := json.Marshal(result)
		var out map[string]any
		_ = json.Unmarshal(b, &out)
		out["id"] = req["id"]
		out["ok"] = true
		_ = json.NewEncoder(os.Stdout).Encode(out)
	}
	os.Exit(0)
}

func prepareCLIRetrieval(t *testing.T, archiveID, root string) (string, []byte) {
	t.Helper()
	source := t.TempDir()
	var imageBytes bytes.Buffer
	_ = jpeg.Encode(&imageBytes, image.NewRGBA(image.Rect(0, 0, 3, 2)), nil)
	item := search.DatasetItem{ID: "synthetic", Path: "image.jpg", SHA256: protocol.Hash(imageBytes.Bytes()), ByteLength: int64(imageBytes.Len())}
	manifest := search.Manifest{Version: "1", Dataset: search.DatasetInfo{Name: "synthetic-test-only", Version: "1", Source: "generated", License: "AGPL-3.0-only"}, Items: []search.DatasetItem{item}}
	b, _ := json.Marshal(manifest)
	path := filepath.Join(source, "manifest.json")
	for name, data := range map[string][]byte{path: b, filepath.Join(source, item.Path): imageBytes.Bytes()} {
		if err := os.WriteFile(name, data, 0600); err != nil {
			t.Fatal(err)
		}
	}
	imported, err := cli(t, "dataset-import", "--archive", archiveID, "--data-root", root, "--manifest", path).Output()
	if err != nil {
		t.Fatal("dataset-import CLI", err)
	}
	var imp search.ImportReport
	if err = json.Unmarshal(imported, &imp); err != nil || len(imp.Items) != 1 {
		t.Fatal("import output", err)
	}
	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	argvBytes, _ := json.Marshal([]string{exe, "-test.run=^TestCLISyntheticInferenceProcess$", "--", "synthetic-fixture"})
	argv := string(argvBytes)
	indexed, err := cli(t, "index", "--archive", archiveID, "--data-root", root, "--worker-argv", argv, "--mode", "full").Output()
	if err != nil {
		t.Fatal("index CLI", err)
	}
	var idx search.IndexReport
	if err = json.Unmarshal(indexed, &idx); err != nil || idx.Completed != 1 || idx.Coverage.AssetsIndexed != 1 {
		t.Fatal("index output", err)
	}
	req, _ := json.Marshal(map[string]any{"generation_id": idx.GenerationID, "query": map[string]any{"text": "отвёртка"}, "min_score": .125})
	for _, command := range []string{"search", "history"} {
		c := cli(t, command, "--archive", archiveID, "--data-root", root, "--worker-argv", argv)
		c.Stdin = bytes.NewReader(req)
		out, e := c.Output()
		if e != nil {
			t.Fatal(command, "CLI", e)
		}
		def := "SearchResponse"
		if command == "history" {
			def = "HistoryResponse"
		}
		if e = contract.Validate(def, out); e != nil {
			t.Fatal(command, "contract", e)
		}
		if command == "history" {
			var h retrieval.HistoryResponse
			_ = json.Unmarshal(out, &h)
			if h.HistoryAvailable || len(h.UnsequencedHits) != 1 || h.FirstObservedMS != nil {
				t.Fatal("CLI invented history", h)
			}
		}
	}
	return argv, req
}

func TestRetrievalCLISIGTERMWhileStdoutBlockedReleasesResources(t *testing.T) {
	if os.Getenv("MEMOTRACE_TEST_ADMIN_DSN") == "" {
		if os.Getenv("MEMOTRACE_REQUIRE_POSTGRES") == "1" {
			t.Fatal("required PostgreSQL missing")
		}
		t.Skip("use bash scripts/verify.sh for PostgreSQL/CLI tests")
	}
	root := t.TempDir()
	if err := os.Chmod(root, 0700); err != nil {
		t.Fatal(err)
	}
	if out, err := cli(t, "migrate").CombinedOutput(); err != nil {
		t.Fatal("migrate", err, string(out))
	}
	created, err := cli(t, "create-archive").Output()
	if err != nil {
		t.Fatal("create archive", err)
	}
	var ids map[string]string
	if err = json.Unmarshal(created, &ids); err != nil {
		t.Fatal(err)
	}
	_, request := prepareCLIRetrieval(t, ids["archive_id"], root)

	fixtureDir := t.TempDir()
	started, release := filepath.Join(fixtureDir, "started"), filepath.Join(fixtureDir, "release")
	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	workerBytes, _ := json.Marshal([]string{exe, "-test.run=^TestCLISyntheticInferenceProcess$", "--", "synthetic-blocking-fixture", started, release})
	applicationName := "memotrace-blocked-stdout-" + protocol.NewID()
	runtimeDSN, err := url.Parse(os.Getenv("MEMOTRACE_TEST_DSN"))
	if err != nil {
		t.Fatal(err)
	}
	query := runtimeDSN.Query()
	query.Set("application_name", applicationName)
	runtimeDSN.RawQuery = query.Encode()

	stdoutRead, stdoutWrite, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer stdoutRead.Close()
	defer stdoutWrite.Close()
	stdoutFD := int(stdoutWrite.Fd())
	if err = syscall.SetNonblock(stdoutFD, true); err != nil {
		t.Fatal(err)
	}
	filler := make([]byte, 4096)
	filled := 0
	for {
		n, writeErr := syscall.Write(stdoutFD, filler)
		filled += n
		if writeErr == nil {
			continue
		}
		if errors.Is(writeErr, syscall.EINTR) {
			continue
		}
		if errors.Is(writeErr, syscall.EAGAIN) {
			break
		}
		t.Fatal(writeErr)
	}
	if filled == 0 {
		t.Fatal("stdout pipe could not be filled")
	}
	if err = syscall.SetNonblock(stdoutFD, false); err != nil {
		t.Fatal(err)
	}

	cmd := cli(t, "search", "--archive", ids["archive_id"], "--data-root", root, "--worker-argv", string(workerBytes))
	cmd.Stdin = bytes.NewReader(request)
	cmd.Stdout = stdoutWrite
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	for i, value := range cmd.Env {
		if strings.HasPrefix(value, "MEMOTRACE_DSN=") {
			cmd.Env[i] = "MEMOTRACE_DSN=" + runtimeDSN.String()
		}
	}
	if err = cmd.Start(); err != nil {
		t.Fatal(err)
	}
	if err = stdoutWrite.Close(); err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	waited, workerPID := false, 0
	t.Cleanup(func() {
		_ = os.WriteFile(release, nil, 0600)
		if !waited {
			_ = cmd.Process.Signal(syscall.SIGTERM)
			select {
			case <-done:
			case <-time.After(time.Second):
				_ = cmd.Process.Kill()
				<-done
			}
		}
		if workerPID != 0 {
			cmdline, _ := os.ReadFile(filepath.Join("/proc", strconv.Itoa(workerPID), "cmdline"))
			if bytes.Contains(cmdline, []byte(started)) && bytes.Contains(cmdline, []byte(release)) {
				_ = syscall.Kill(workerPID, syscall.SIGKILL)
			}
		}
	})

	var workerHome string
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		marker, readErr := os.ReadFile(started)
		if readErr == nil {
			parts := strings.Split(string(marker), "\n")
			if len(parts) == 2 {
				workerPID, err = strconv.Atoi(parts[0])
				workerHome = parts[1]
				if err == nil && workerPID > 0 && workerHome != "" {
					break
				}
			}
		}
		select {
		case err = <-done:
			waited = true
			t.Fatal("CLI exited before worker query", err, stderr.String())
		default:
		}
		time.Sleep(5 * time.Millisecond)
	}
	if workerPID == 0 || workerHome == "" {
		t.Fatal("CLI did not reach the worker query")
	}

	observer, err := pgx.Connect(context.Background(), os.Getenv("MEMOTRACE_TEST_ADMIN_DSN"))
	if err != nil {
		t.Fatal(err)
	}
	defer observer.Close(context.Background())
	var sessions int
	if err = observer.QueryRow(context.Background(), "SELECT count(*) FROM pg_stat_activity WHERE application_name=$1", applicationName).Scan(&sessions); err != nil || sessions != 1 {
		t.Fatal("retrieval database session was not active during work", sessions, err)
	}
	if err = os.WriteFile(release, nil, 0600); err != nil {
		t.Fatal(err)
	}

	blocked := false
	deadline = time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		tasks, _ := os.ReadDir(filepath.Join("/proc", strconv.Itoa(cmd.Process.Pid), "task"))
		for _, task := range tasks {
			wchan, _ := os.ReadFile(filepath.Join("/proc", strconv.Itoa(cmd.Process.Pid), "task", task.Name(), "wchan"))
			if strings.Contains(string(wchan), "pipe_write") {
				blocked = true
				break
			}
		}
		if blocked {
			break
		}
		select {
		case err = <-done:
			waited = true
			t.Fatal("CLI exited instead of blocking on full stdout", err, stderr.String())
		default:
		}
		time.Sleep(5 * time.Millisecond)
	}
	if !blocked {
		t.Fatal("CLI did not block writing to the full stdout pipe")
	}

	files, lockErr := archive.Open(root)
	if lockErr == nil {
		defer files.Close()
	}
	_, workerErr := os.Stat(filepath.Join("/proc", strconv.Itoa(workerPID)))
	_, homeErr := os.Stat(workerHome)
	if err = observer.QueryRow(context.Background(), "SELECT count(*) FROM pg_stat_activity WHERE application_name=$1", applicationName).Scan(&sessions); err != nil {
		t.Fatal(err)
	}
	databaseReleased := sessions == 0

	signaled := time.Now()
	if err = cmd.Process.Signal(syscall.SIGTERM); err != nil {
		t.Fatal(err)
	}
	select {
	case err = <-done:
		waited = true
	case <-time.After(3 * time.Second):
		t.Fatal("SIGTERM did not promptly terminate CLI blocked on stdout")
	}
	status, ok := cmd.ProcessState.Sys().(syscall.WaitStatus)
	if err == nil || !ok || status.Signal() != syscall.SIGTERM {
		t.Fatal("blocked CLI did not exit from SIGTERM", err)
	}
	if time.Since(signaled) > 3*time.Second {
		t.Fatal("blocked CLI exit exceeded deadline")
	}
	if lockErr != nil {
		t.Fatal("archive lock remained held during stdout output", lockErr)
	}
	if !errors.Is(workerErr, os.ErrNotExist) {
		t.Fatal("inference worker remained alive during stdout output", workerErr)
	}
	if !errors.Is(homeErr, os.ErrNotExist) {
		t.Fatal("inference worker temporary directory remained during stdout output", homeErr)
	}
	if !databaseReleased {
		t.Fatal("database session remained open during stdout output")
	}
}
