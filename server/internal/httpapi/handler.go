// SPDX-License-Identifier: AGPL-3.0-only
package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"mime"
	"net/http"
	"strconv"
	"strings"
	"time"

	"memotrace/server/internal/archive"
	"memotrace/server/internal/postgres"
	"memotrace/server/internal/protocol"
)

type API struct {
	DB    *postgres.Store
	Files *archive.Files
	// BeforeCommit is available to in-package integration tests; CLI leaves nil.
	BeforeCommit func() error
	concurrency  chan struct{}
	pairing      chan struct{}
}

func New(db *postgres.Store, files *archive.Files) *API {
	return &API{DB: db, Files: files, concurrency: make(chan struct{}, 8), pairing: make(chan struct{}, 2)}
}
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
func writeError(w http.ResponseWriter, err error) {
	writeChallengeError(w, err, `Bearer realm="memotrace"`)
}
func writePairError(w http.ResponseWriter, err error) {
	writeChallengeError(w, err, `MemoTraceInvitation realm="memotrace-pairing"`)
}
func writeChallengeError(w http.ResponseWriter, err error, challenge string) {
	var e *protocol.Error
	if !errors.As(err, &e) {
		e = protocol.E("unavailable")
	}
	if e.Retryable {
		w.Header().Set("Retry-After", "2")
	}
	if e.Code == "unauthorized" {
		w.Header().Set("WWW-Authenticate", challenge)
	}
	writeJSON(w, protocol.Status(e.Code), map[string]any{"error": e})
}
func jsonBody(w http.ResponseWriter, r *http.Request, dst any) error {
	t, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || t != "application/json" {
		return protocol.E("unsupported_media_type")
	}
	r.Body = http.MaxBytesReader(w, r.Body, protocol.MaxJSON)
	b, err := io.ReadAll(r.Body)
	if err != nil {
		var large *http.MaxBytesError
		if errors.As(err, &large) {
			return protocol.E("payload_too_large")
		}
		return protocol.E("invalid_request")
	}
	return protocol.StrictJSON(b, dst)
}
func (a *API) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	if r.URL.Path == "/healthz" {
		if r.Method != "GET" {
			method(w, "GET")
			return
		}
		writeJSON(w, 200, map[string]string{"status": "ok", "contract_version": protocol.Version})
		return
	}
	select {
	case a.concurrency <- struct{}{}:
		defer func() { <-a.concurrency }()
	default:
		writeError(w, protocol.E("unavailable"))
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 90*time.Second)
	defer cancel()
	r = r.WithContext(ctx)
	if r.URL.Path == "/v1/pairing/redeem" {
		if r.Method != "POST" {
			method(w, "POST")
			return
		}
		select {
		case a.pairing <- struct{}{}:
			defer func() { <-a.pairing }()
		default:
			writeError(w, protocol.E("unavailable"))
			return
		}
		var p protocol.PairRequest
		if err := jsonBody(w, r, &p); err != nil {
			writePairError(w, err)
			return
		}
		if err := p.Validate(); err != nil {
			writePairError(w, err)
			return
		}
		out, err := a.DB.Pair(ctx, p)
		if err != nil {
			writePairError(w, err)
			return
		}
		writeJSON(w, 201, out)
		return
	}
	parts := strings.Split(r.URL.Path, "/")
	if len(parts) < 5 || parts[1] != "v1" || parts[2] != "archives" || parts[4] != "frames" || (len(parts) != 5 && len(parts) != 7) {
		writeError(w, protocol.E("not_found"))
		return
	}
	archiveID := parts[3]
	if !protocol.UUID(archiveID) {
		writeError(w, protocol.E("not_found"))
		return
	}
	if len(parts) == 7 && (!protocol.UUID(parts[5]) || (parts[6] != "receipt" && parts[6] != "original")) {
		writeError(w, protocol.E("not_found"))
		return
	}
	headers := r.Header.Values("Authorization")
	var scheme, token string
	if len(headers) == 1 {
		scheme, token, _ = strings.Cut(headers[0], " ")
		// RFC 6750 §2.1 uses 1*SP: consume only the remaining ASCII-space
		// separator, never tabs or trailing whitespace in the credential.
		token = strings.TrimLeft(token, " ")
	}
	if len(headers) != 1 || !strings.EqualFold(scheme, "Bearer") || !protocol.Token(token) {
		writeError(w, protocol.E("unauthorized"))
		return
	}
	// Authenticate even malformed metadata and unsupported methods on known routes.
	tx, _, err := a.DB.Begin(ctx, token, archiveID)
	if err != nil {
		writeError(w, err)
		return
	}
	_ = tx.Rollback(ctx)
	if len(parts) == 5 {
		if r.Method != "POST" {
			method(w, "POST")
			return
		}
		var m protocol.ManifestRequest
		if err = jsonBody(w, r, &m); err == nil {
			err = m.Validate()
		}
		if err != nil {
			writeError(w, err)
			return
		}
		out, err := a.DB.Register(ctx, token, archiveID, m)
		if err != nil {
			writeError(w, err)
			return
		}
		writeJSON(w, 200, out)
		return
	}
	frameID, resource := parts[5], parts[6]
	if resource == "original" && r.Method == "PUT" {
		a.upload(w, r, token, archiveID, frameID)
		return
	}
	if r.Method != "GET" {
		allowed := "GET"
		if resource == "original" {
			allowed = "GET, PUT"
		}
		method(w, allowed)
		return
	}
	tx, _, err = a.DB.Begin(ctx, token, archiveID)
	if err != nil {
		writeError(w, err)
		return
	}
	defer tx.Rollback(ctx)
	f, err := postgres.Get(ctx, tx, archiveID, frameID)
	if err != nil {
		writeError(w, err)
		return
	}
	receipt := postgres.Receipt(archiveID, f)
	if receipt == nil {
		writeError(w, protocol.E("not_committed"))
		return
	}
	if err = tx.Commit(ctx); err != nil {
		writeError(w, err)
		return
	}
	if resource == "receipt" {
		writeJSON(w, 200, receipt)
		return
	}
	b, err := a.Files.Read(archiveID, f.Metadata)
	if err != nil {
		writeError(w, err)
		return
	}
	w.Header().Set("Content-Type", "image/jpeg")
	w.Header().Set("Content-Length", strconv.Itoa(len(b)))
	w.WriteHeader(200)
	_, _ = w.Write(b)
}
func method(w http.ResponseWriter, allow string) {
	w.Header().Set("Allow", allow)
	writeJSON(w, 405, map[string]any{"error": protocol.E("invalid_request")})
}
func (a *API) upload(w http.ResponseWriter, r *http.Request, token, archiveID, frameID string) {
	media, params, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || media != "image/jpeg" || len(params) > 0 {
		writeError(w, protocol.E("unsupported_media_type"))
		return
	}
	if r.ContentLength > protocol.MaxBytes {
		writeError(w, protocol.E("payload_too_large"))
		return
	}
	ctx := r.Context()
	tx, _, err := a.DB.Begin(ctx, token, archiveID)
	if err != nil {
		writeError(w, err)
		return
	}
	f, err := postgres.Get(ctx, tx, archiveID, frameID)
	_ = tx.Rollback(ctx)
	if err != nil {
		writeError(w, err)
		return
	}
	stage, err := a.Files.Stage(r.Body, f.Metadata)
	if err != nil {
		writeError(w, err)
		return
	}
	defer stage.Close()
	// Recheck revocation after body streaming; authenticate holds a SHARE device
	// row lock until commit, serializing local revocation with the receipt boundary.
	tx, sc, err := a.DB.Begin(ctx, token, archiveID)
	if err != nil {
		writeError(w, err)
		return
	}
	defer tx.Rollback(ctx)
	f, err = postgres.Get(ctx, tx, archiveID, frameID)
	if err != nil {
		writeError(w, err)
		return
	}
	if err = a.Files.Publish(stage, archiveID, f.Metadata); err != nil {
		writeError(w, err)
		return
	}
	f, err = postgres.Complete(ctx, tx, sc, f)
	if err != nil {
		writeError(w, err)
		return
	}
	if a.BeforeCommit != nil {
		if err = a.BeforeCommit(); err != nil {
			writeError(w, err)
			return
		}
	}
	if err = tx.Commit(ctx); err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, 200, postgres.Receipt(archiveID, f))
}
