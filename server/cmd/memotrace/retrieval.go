// SPDX-License-Identifier: AGPL-3.0-only
package main

import (
	"context"
	"errors"
	"io"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"memotrace/server/internal/archive"
	"memotrace/server/internal/inference"
	"memotrace/server/internal/postgres"
	"memotrace/server/internal/protocol"
	"memotrace/server/internal/retrieval"
	"memotrace/server/internal/search"
	"memotrace/server/internal/strictjson"
)

func configuredWorker(raw string, timeout time.Duration) (*inference.Worker, error) {
	if raw == "" {
		return nil, nil
	}
	if len(raw) > 32768 {
		return nil, protocol.E("invalid_request")
	}
	var argv []string
	if err := strictjson.Decode([]byte(raw), &argv); err != nil {
		return nil, err
	}
	return inference.New(argv, timeout)
}
func retrievalCommand(command, archiveID, root, manifest, mode string, maxJobs int, request, argv string, timeout time.Duration, output func(any) error) error {
	if !protocol.UUID(archiveID) || os.Getenv("MEMOTRACE_DSN") == "" {
		return errors.New("archive and runtime DSN required")
	}
	var result any
	var postOutputErr error
	// Keep signal cancellation through work and cleanup, but release it and all
	// operation resources before writing to caller-owned, potentially blocking output.
	err := func() error {
		ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
		defer stop()
		ctx, cancel := context.WithTimeout(ctx, 24*time.Hour)
		defer cancel()
		// Read and validate before taking the data-root lock or opening the database.
		// A writer holding stdin open cannot monopolize an archive while supplying JSON.
		var query retrieval.Request
		if command == "search" || command == "history" {
			b, err := readRetrievalRequest(ctx, request, 30*time.Second)
			if err != nil {
				return err
			}
			query, err = retrieval.DecodeRequest(b, command == "history")
			if err != nil {
				return err
			}
		}
		files, err := archive.Open(root)
		if err != nil {
			return err
		}
		defer files.Close()
		db, err := postgres.Open(ctx, os.Getenv("MEMOTRACE_DSN"))
		if err != nil {
			return err
		}
		defer db.Close()
		w, err := configuredWorker(argv, timeout)
		if err != nil {
			return err
		}
		if w != nil {
			defer w.Close()
		}
		var worker search.Worker
		if w != nil {
			worker = w
		}
		s := search.New(db, files, worker)
		a := postgres.Access{ArchiveID: archiveID, Operator: true}
		switch command {
		case "dataset-import":
			out, e := s.Import(ctx, a, manifest)
			result = out
			return e
		case "index":
			out, e := s.Index(ctx, a, mode, maxJobs)
			result = out
			if e == nil && out.Coverage.Failed > 0 {
				postOutputErr = errors.New("index contains failed assets")
			}
			return e
		case "search", "history":
			out, e := s.Run(ctx, a, query, command == "history")
			result = out
			return e
		}
		return errors.New("unknown retrieval command")
	}()
	if err != nil {
		return err
	}
	if err = output(result); err != nil {
		return err
	}
	return postOutputErr
}

func readRetrievalRequest(ctx context.Context, path string, timeout time.Duration) ([]byte, error) {
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	stdin := path == "-"
	if stdin {
		// Reopen our Linux stdin with O_NONBLOCK so pipes/terminals are registered
		// with Go's poller. Closing a raw blocking inherited fd need not wake read.
		path = "/proc/self/fd/" + strconv.FormatUint(uint64(os.Stdin.Fd()), 10)
	}
	f, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() && (!stdin || info.Mode()&(os.ModeNamedPipe|os.ModeCharDevice) == 0) {
		return nil, errors.New("request file must be regular; use stdin for a stream")
	}
	stopClose := context.AfterFunc(ctx, func() { _ = f.Close() })
	defer stopClose()
	b, err := io.ReadAll(io.LimitReader(f, protocol.MaxJSON+1))
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if err != nil {
		return nil, err
	}
	if len(b) > protocol.MaxJSON {
		return nil, protocol.E("payload_too_large")
	}
	return b, nil
}
