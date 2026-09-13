// SPDX-License-Identifier: AGPL-3.0-only
package main

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"syscall"
	"testing"
	"time"

	"memotrace/server/internal/archive"
	"memotrace/server/internal/protocol"
)

func TestRetrievalCLIUnendedStdinSIGTERMReleasesRoot(t *testing.T) {
	for _, command := range []string{"search", "history"} {
		t.Run(command, func(t *testing.T) {
			root := t.TempDir()
			if err := os.Chmod(root, 0700); err != nil {
				t.Fatal(err)
			}
			cmd := cli(t, command, "--archive", protocol.NewID(), "--data-root", root)
			// Request input is checked before DB access; this regression needs no DB.
			cmd.Env = append(cmd.Env, "MEMOTRACE_DSN=postgres://unused:unused@127.0.0.1:1/unused?sslmode=disable")
			stdin, err := cmd.StdinPipe()
			if err != nil {
				t.Fatal(err)
			}
			defer stdin.Close()
			if err = cmd.Start(); err != nil {
				t.Fatal(err)
			}
			done := make(chan error, 1)
			go func() { done <- cmd.Wait() }()
			t.Cleanup(func() { _ = cmd.Process.Kill() })
			if _, err = stdin.Write([]byte(`{"generation_id":`)); err != nil {
				t.Fatal(err)
			}
			// Wait for the reopened pollable input fd, proving the process installed
			// its signal context and is waiting on our still-open stream.
			fdRoot := filepath.Join("/proc", strconv.Itoa(cmd.Process.Pid), "fd")
			ready := false
			deadline := time.Now().Add(3 * time.Second)
			for time.Now().Before(deadline) {
				pipe, _ := os.Readlink(filepath.Join(fdRoot, "0"))
				entries, _ := os.ReadDir(fdRoot)
				for _, entry := range entries {
					if entry.Name() == "0" {
						continue
					}
					target, _ := os.Readlink(filepath.Join(fdRoot, entry.Name()))
					if pipe != "" && target == pipe {
						ready = true
						break
					}
				}
				if ready {
					break
				}
				select {
				case err := <-done:
					t.Fatal("CLI exited before reading stdin", err)
				default:
				}
				time.Sleep(5 * time.Millisecond)
			}
			if !ready {
				t.Fatal("CLI did not start a cancelable request read")
			}
			f, err := archive.Open(root)
			if err != nil {
				t.Fatal("unfinished stdin retained root lock", err)
			}
			f.Close()
			if err = cmd.Process.Signal(syscall.SIGTERM); err != nil {
				t.Fatal(err)
			}
			select {
			case err = <-done:
				if err == nil {
					t.Fatal("canceled command succeeded")
				}
			case <-time.After(3 * time.Second):
				t.Fatal("SIGTERM left CLI stuck on unended stdin")
			}
			f, err = archive.Open(root)
			if err != nil {
				t.Fatal("root lock not reacquirable after SIGTERM", err)
			}
			f.Close()
		})
	}
}

func TestRetrievalRequestInputDeadlineAndRegularFileOnly(t *testing.T) {
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	defer w.Close()
	previous := os.Stdin
	os.Stdin = r
	defer func() { os.Stdin = previous }()
	started := time.Now()
	_, err = readRetrievalRequest(context.Background(), "-", 30*time.Millisecond)
	if !errors.Is(err, context.DeadlineExceeded) || time.Since(started) > time.Second {
		t.Fatal("open stdin ignored input deadline", err)
	}
	dir := t.TempDir()
	fifo := filepath.Join(dir, "request.fifo")
	if err = syscall.Mkfifo(fifo, 0600); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{fifo, dir, "/dev/zero"} {
		started = time.Now()
		if _, err = readRetrievalRequest(context.Background(), path, time.Second); err == nil || time.Since(started) > time.Second {
			t.Fatal("blocking/nonregular request file accepted", path, err)
		}
	}
	file := filepath.Join(dir, "request.json")
	if err = os.WriteFile(file, []byte(`{"query":{"text":"scissors"}}`), 0600); err != nil {
		t.Fatal(err)
	}
	b, err := readRetrievalRequest(context.Background(), file, time.Second)
	if err != nil || string(b) != `{"query":{"text":"scissors"}}` {
		t.Fatal("regular input changed", string(b), err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err = readRetrievalRequest(ctx, file, time.Second); !errors.Is(err, context.Canceled) {
		t.Fatal("canceled input accepted", err)
	}
}
