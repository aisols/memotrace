// SPDX-License-Identifier: AGPL-3.0-only
package httpapi

import (
	"errors"
	"io"
	"mime"
	"net/http"
	"strconv"
	"strings"

	"memotrace/server/internal/postgres"
	"memotrace/server/internal/protocol"
	"memotrace/server/internal/retrieval"
	"memotrace/server/internal/search"
)

func bearer(r *http.Request) (string, error) {
	h := r.Header.Values("Authorization")
	var scheme, token string
	if len(h) == 1 {
		scheme, token, _ = strings.Cut(h[0], " ")
		token = strings.TrimLeft(token, " ")
	}
	if len(h) != 1 || !strings.EqualFold(scheme, "Bearer") || !protocol.Token(token) {
		return "", protocol.E("unauthorized")
	}
	return token, nil
}
func (a *API) retrievalRoute(w http.ResponseWriter, r *http.Request, p []string) bool {
	if len(p) < 5 || p[1] != "v1" || p[2] != "archives" || (p[4] != "search" && p[4] != "history") {
		return false
	}
	original := len(p) == 8 && p[4] == "search" && p[5] == "assets" && p[7] == "original" && protocol.UUID(p[6])
	if !protocol.UUID(p[3]) || (len(p) != 5 && !original) {
		writeError(w, protocol.E("not_found"))
		return true
	}
	token, err := bearer(r)
	if err != nil {
		writeError(w, err)
		return true
	}
	tx, _, err := a.DB.Begin(r.Context(), token, p[3])
	if err != nil {
		writeError(w, err)
		return true
	}
	tx.Rollback(r.Context())
	want := "POST"
	if original {
		want = "GET"
	}
	if r.Method != want {
		method(w, want)
		return true
	}
	s := a.Search
	if s == nil {
		s = search.New(a.DB, a.Files, nil)
	}
	access := postgres.Access{ArchiveID: p[3], Token: token}
	if original {
		b, e := s.Original(r.Context(), access, p[6])
		if e != nil {
			writeError(w, e)
			return true
		}
		w.Header().Set("Content-Type", "image/jpeg")
		w.Header().Set("Content-Length", strconv.Itoa(len(b)))
		w.WriteHeader(200)
		_, _ = w.Write(b)
		return true
	}
	t, _, e := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if e != nil || t != "application/json" {
		writeError(w, protocol.E("unsupported_media_type"))
		return true
	}
	b, e := io.ReadAll(http.MaxBytesReader(w, r.Body, protocol.MaxJSON))
	if e != nil {
		var large *http.MaxBytesError
		if errors.As(e, &large) {
			writeError(w, protocol.E("payload_too_large"))
		} else {
			writeError(w, protocol.E("invalid_request"))
		}
		return true
	}
	history := p[4] == "history"
	req, e := retrieval.DecodeRequest(b, history)
	if e != nil {
		writeError(w, e)
		return true
	}
	out, e := s.Run(r.Context(), access, req, history)
	if e != nil {
		writeError(w, e)
		return true
	}
	writeJSON(w, 200, out)
	return true
}
