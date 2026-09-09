// SPDX-License-Identifier: AGPL-3.0-only
package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"image"
	"image/jpeg"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"memotrace/server/internal/archive"
	"memotrace/server/internal/contract"
	"memotrace/server/internal/postgres"
	"memotrace/server/internal/protocol"
)

type harness struct {
	t     *testing.T
	api   *API
	admin *pgx.Conn
	root  string
}

func setup(t *testing.T) *harness {
	t.Helper()
	adminDSN, dsn := os.Getenv("MEMOTRACE_TEST_ADMIN_DSN"), os.Getenv("MEMOTRACE_TEST_DSN")
	if adminDSN == "" || dsn == "" {
		if os.Getenv("MEMOTRACE_REQUIRE_POSTGRES") == "1" {
			t.Fatal("required disposable PostgreSQL DSNs missing")
		}
		t.Skip("local unit run: use bash scripts/verify.sh for required PostgreSQL suite")
	}
	ctx := context.Background()
	if err := postgres.Migrate(ctx, adminDSN, "memotrace_runtime"); err != nil {
		t.Fatal(err)
	}
	db, err := postgres.Open(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(db.Close)
	admin, err := pgx.Connect(ctx, adminDSN)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { admin.Close(ctx) })
	root := t.TempDir()
	if err := os.Chmod(root, 0700); err != nil {
		t.Fatal(err)
	}
	files, err := archive.Open(root)
	if err != nil {
		t.Fatal(err)
	}
	h := &harness{t: t, api: New(db, files), admin: admin, root: root}
	t.Cleanup(func() { h.api.Files.Close() })
	return h
}
func (h *harness) sql(q string, args ...any) {
	h.t.Helper()
	if _, err := h.admin.Exec(context.Background(), q, args...); err != nil {
		h.t.Fatal(err)
	}
}
func (h *harness) owner() string {
	h.t.Helper()
	o, a := protocol.NewID(), protocol.NewID()
	h.sql("INSERT INTO mt.owners(id) VALUES($1)", o)
	h.sql("INSERT INTO mt.archives(id,owner_id) VALUES($1,$2)", a, o)
	return a
}
func (h *harness) invite(a string, expires time.Time) string {
	token := protocol.NewToken()
	h.sql("INSERT INTO mt.invitations(token_hash,archive_id,expires_at) VALUES($1,$2,$3)", protocol.Hash([]byte(token)), a, expires)
	return token
}
func encode(v any) []byte { b, _ := json.Marshal(v); return b }
func (h *harness) request(method, path, token, media string, body []byte, status int, def string) *httptest.ResponseRecorder {
	h.t.Helper()
	r := httptest.NewRequest(method, path, bytes.NewReader(body))
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	if media != "" {
		r.Header.Set("Content-Type", media)
	}
	w := httptest.NewRecorder()
	h.api.ServeHTTP(w, r)
	if w.Code != status {
		h.t.Fatalf("%s %s: got %d want %d; %s", method, path, w.Code, status, w.Body.String())
	}
	if err := contract.CheckResponse(method, path, w.Code, w.Header(), w.Body.Bytes()); err != nil {
		h.t.Fatal("actual HTTP exchange differs from canonical OpenAPI:", err)
	}
	if w.Header().Get("Cache-Control") != "no-store" || w.Header().Get("X-Content-Type-Options") != "nosniff" {
		h.t.Fatal("privacy headers missing")
	}
	if status >= 400 {
		wantCode := def
		if wantCode == "" {
			wantCode = map[int]string{400: "invalid_request", 401: "unauthorized", 404: "not_found", 405: "invalid_request", 413: "payload_too_large", 415: "unsupported_media_type", 503: "unavailable"}[status]
		}
		if wantCode == "" {
			h.t.Fatal("ambiguous error status requires an explicit expected code")
		}
		assertError(h.t, w.Body.Bytes(), wantCode)
		def = "Error"
		if strings.Contains(w.Body.String(), token) && token != "" {
			h.t.Fatal("credential leaked")
		}
	}
	if def == "Receipt" {
		parts := strings.Split(path, "/")
		h.assertReceipt(w.Body.Bytes(), parts[3], parts[5])
	}
	if def != "" {
		if err := contract.Validate(def, w.Body.Bytes()); err != nil {
			h.t.Fatalf("actual handler violates %s: %v", def, err)
		}
	}
	return w
}
func (h *harness) pair(a string) protocol.PairResponse {
	token := h.invite(a, time.Now().Add(time.Minute))
	req := encode(protocol.PairRequest{InvitationToken: token, DeviceName: "synthetic camera"})
	if err := contract.Validate("PairRequest", req); err != nil {
		h.t.Fatal(err)
	}
	w := h.request("POST", "/v1/pairing/redeem", "", "application/json", req, 201, "PairResponse")
	var p protocol.PairResponse
	if err := json.Unmarshal(w.Body.Bytes(), &p); err != nil {
		h.t.Fatal(err)
	}
	return p
}
func synthetic() ([]byte, protocol.Metadata) {
	var b bytes.Buffer
	_ = jpeg.Encode(&b, image.NewRGBA(image.Rect(0, 0, 4, 3)), nil)
	data := append([]byte{255, 216, 255, 225, 0, 10, 'E', 'x', 'i', 'f', 0, 0, 0, 0}, b.Bytes()[2:]...)
	wall := int64(0)
	return data, protocol.Metadata{FrameID: protocol.NewID(), RequestWallMS: &wall, SHA256: protocol.Hash(data), ByteLength: int64(len(data))}
}
func base(a string) string        { return "/v1/archives/" + a + "/frames" }
func original(a, f string) string { return base(a) + "/" + f + "/original" }
func receipt(a, f string) string  { return base(a) + "/" + f + "/receipt" }
func (h *harness) register(p protocol.PairResponse, m ...protocol.Metadata) *httptest.ResponseRecorder {
	h.t.Helper()
	b := encode(protocol.ManifestRequest{Frames: m})
	if err := contract.Validate("ManifestRequest", b); err != nil {
		h.t.Fatal(err)
	}
	w := h.request("POST", base(p.ArchiveID), p.DeviceToken, "application/json", b, 200, "ManifestResponse")
	var result protocol.ManifestResponse
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		h.t.Fatal(err)
	}
	if len(result.Frames) != len(m) {
		h.t.Fatal("manifest response cardinality differs")
	}
	for i, expected := range m {
		if result.Frames[i].FrameID != expected.FrameID {
			h.t.Fatal("manifest response identity/order differs")
		}
		var stored protocol.Metadata
		var raw []byte
		if err := h.admin.QueryRow(context.Background(), "SELECT metadata FROM mt.frames WHERE archive_id=$1 AND id=$2", p.ArchiveID, expected.FrameID).Scan(&raw); err != nil {
			h.t.Fatal(err)
		}
		if err := json.Unmarshal(raw, &stored); err != nil {
			h.t.Fatal(err)
		}
		if !bytes.Equal(encode(expected), encode(stored)) {
			h.t.Fatal("registration changed immutable metadata")
		}
		if r := result.Frames[i].Receipt; r != nil {
			h.assertReceipt(encode(r), p.ArchiveID, expected.FrameID)
		}
	}
	return w
}

func assertError(t *testing.T, body []byte, want string) {
	t.Helper()
	var result struct {
		Error protocol.Error `json:"error"`
	}
	if err := json.Unmarshal(body, &result); err != nil {
		t.Fatal(err)
	}
	if result.Error.Code != want {
		t.Fatalf("error code: got %q want %q", result.Error.Code, want)
	}
	if result.Error.Retryable != (want == "unavailable" || want == "checksum_mismatch" || want == "not_committed") {
		t.Fatal("error retry policy differs")
	}
}

func (h *harness) assertReceipt(body []byte, archiveID, frameID string) {
	h.t.Helper()
	var got protocol.Receipt
	if err := json.Unmarshal(body, &got); err != nil {
		h.t.Fatal(err)
	}
	var raw []byte
	var committed time.Time
	if err := h.admin.QueryRow(context.Background(), "SELECT metadata,committed_at FROM mt.frames WHERE archive_id=$1 AND id=$2", archiveID, frameID).Scan(&raw, &committed); err != nil {
		h.t.Fatal(err)
	}
	var m protocol.Metadata
	if err := json.Unmarshal(raw, &m); err != nil {
		h.t.Fatal(err)
	}
	want := protocol.Receipt{ContractVersion: protocol.Version, ArchiveID: archiveID, FrameID: frameID, SHA256: m.SHA256, ByteLength: m.ByteLength, CommittedAt: committed.UTC().Format(time.RFC3339Nano), Integrity: "sha256-byte-length-jpeg-header", State: "archive_committed"}
	if got != want {
		h.t.Fatalf("receipt differs from registered identity/content and persisted commit: got %+v want %+v", got, want)
	}
}
func (h *harness) count(table, a, f string) int {
	h.t.Helper()
	col := "id"
	if table == "jobs" {
		col = "frame_id"
	}
	var n int
	if err := h.admin.QueryRow(context.Background(), "SELECT count(*) FROM mt."+table+" WHERE archive_id=$1 AND "+col+"=$2", a, f).Scan(&n); err != nil {
		h.t.Fatal(err)
	}
	return n
}

func TestPairingSingleUseExpiredConcurrentAndRevoked(t *testing.T) {
	h := setup(t)
	a := h.owner()
	token := h.invite(a, time.Now().Add(time.Minute))
	b := encode(protocol.PairRequest{InvitationToken: token, DeviceName: "camera"})
	h.request("POST", "/v1/pairing/redeem", "", "application/json", b, 201, "PairResponse")
	h.request("POST", "/v1/pairing/redeem", "", "application/json", b, 401, "")
	for _, tok := range []string{protocol.NewToken(), h.invite(a, time.Now().Add(-time.Second)), "invalid"} {
		h.request("POST", "/v1/pairing/redeem", "", "application/json", encode(protocol.PairRequest{InvitationToken: tok, DeviceName: "camera"}), 401, "")
	}
	token = h.invite(a, time.Now().Add(time.Minute))
	b = encode(protocol.PairRequest{InvitationToken: token, DeviceName: "camera"})
	var wg sync.WaitGroup
	codes := make(chan int, 2)
	for range 2 {
		wg.Go(func() {
			r := httptest.NewRequest("POST", "/v1/pairing/redeem", bytes.NewReader(b))
			r.Header.Set("Content-Type", "application/json")
			w := httptest.NewRecorder()
			h.api.ServeHTTP(w, r)
			codes <- w.Code
		})
	}
	wg.Wait()
	close(codes)
	success, denied := 0, 0
	for code := range codes {
		if code == 201 {
			success++
		}
		if code == 401 {
			denied++
		}
	}
	if success != 1 || denied != 1 {
		t.Fatalf("single use race: %d %d", success, denied)
	}
	p := h.pair(a)
	h.sql("UPDATE mt.devices SET revoked=true WHERE id=$1", p.DeviceID)
	_, m := synthetic()
	h.request("POST", base(a), p.DeviceToken, "application/json", encode(protocol.ManifestRequest{Frames: []protocol.Metadata{m}}), 401, "")
	var raw int
	if err := h.admin.QueryRow(context.Background(), "SELECT count(*) FROM mt.invitations WHERE token_hash=$1", token).Scan(&raw); err != nil || raw != 0 {
		t.Fatal("raw invitation persisted", err)
	}
}

func TestTwoOwnersExactBytesStableLostACKAndSameArchiveResume(t *testing.T) {
	h := setup(t)
	p, q := h.pair(h.owner()), h.pair(h.owner())
	data, m := synthetic()
	h.register(p, m)
	h.request("GET", "/healthz", "", "", nil, 200, "Health")
	h.request("GET", receipt(p.ArchiveID, m.FrameID), p.DeviceToken, "", nil, 409, "not_committed")
	h.request("GET", original(p.ArchiveID, m.FrameID), p.DeviceToken, "", nil, 409, "not_committed")
	for _, path := range []string{receipt(p.ArchiveID, m.FrameID), original(p.ArchiveID, m.FrameID), receipt(q.ArchiveID, m.FrameID)} {
		h.request("GET", path, q.DeviceToken, "", nil, 404, "")
	}
	h.request("PUT", original(p.ArchiveID, m.FrameID), q.DeviceToken, "image/jpeg", data, 404, "")
	h.request("POST", base(p.ArchiveID), q.DeviceToken, "application/json", encode(protocol.ManifestRequest{Frames: []protocol.Metadata{m}}), 404, "")
	resumed := h.pair(p.ArchiveID)
	first := h.request("PUT", original(p.ArchiveID, m.FrameID), resumed.DeviceToken, "image/jpeg", data, 200, "Receipt").Body.Bytes()
	// Treat first response as lost: lookup and full retry must reproduce its bytes.
	for _, got := range [][]byte{h.request("GET", receipt(p.ArchiveID, m.FrameID), p.DeviceToken, "", nil, 200, "Receipt").Body.Bytes(), h.request("PUT", original(p.ArchiveID, m.FrameID), p.DeviceToken, "image/jpeg", data, 200, "Receipt").Body.Bytes()} {
		if !bytes.Equal(first, got) {
			t.Fatal("historical receipt changed")
		}
	}
	w := h.request("GET", original(p.ArchiveID, m.FrameID), p.DeviceToken, "", nil, 200, "")
	if !bytes.Equal(data, w.Body.Bytes()) || w.Header().Get("Content-Type") != "image/jpeg" || w.Header().Get("Content-Length") == "" {
		t.Fatal("exact EXIF original response lost")
	}
	var registering, state string
	if err := h.admin.QueryRow(context.Background(), "SELECT registering_device_id::text FROM mt.frames WHERE archive_id=$1 AND id=$2", p.ArchiveID, m.FrameID).Scan(&registering); err != nil || registering != p.DeviceID {
		t.Fatal("registering device changed", err)
	}
	if h.count("jobs", p.ArchiveID, m.FrameID) != 1 {
		t.Fatal("duplicate jobs")
	}
	if err := h.admin.QueryRow(context.Background(), "SELECT state FROM mt.jobs WHERE archive_id=$1 AND frame_id=$2", p.ArchiveID, m.FrameID).Scan(&state); err != nil || state != "pending" {
		t.Fatal("fake completion", err)
	}
	h.request("PUT", original(p.ArchiveID, m.FrameID), p.DeviceToken, "image/jpeg", append([]byte(nil), data[:len(data)-1]...), 422, "checksum_mismatch")
	h.register(p, m)
	name, _ := archive.Name(p.ArchiveID, m.FrameID)
	if err := os.WriteFile(filepath.Join(h.root, name), []byte("damaged after receipt"), 0600); err != nil {
		t.Fatal(err)
	}
	h.request("GET", original(p.ArchiveID, m.FrameID), p.DeviceToken, "", nil, 409, "integrity_error")
	got := h.request("GET", receipt(p.ArchiveID, m.FrameID), p.DeviceToken, "", nil, 200, "Receipt").Body.Bytes()
	if !bytes.Equal(first, got) {
		t.Fatal("historical receipt unavailable after corruption")
	}
	h.request("PUT", original(p.ArchiveID, m.FrameID), p.DeviceToken, "image/jpeg", data, 409, "integrity_error")
	if err := os.Remove(filepath.Join(h.root, name)); err != nil {
		t.Fatal(err)
	}
	h.request("GET", original(p.ArchiveID, m.FrameID), p.DeviceToken, "", nil, 409, "integrity_error")
}

func TestManifestAtomicityLegacyNormalizationAndStrictBounds(t *testing.T) {
	h := setup(t)
	p := h.pair(h.owner())
	_, m := synthetic()
	h.register(p, m)
	b := encode(protocol.ManifestRequest{Frames: []protocol.Metadata{m}})
	legacy := bytes.Replace(b, []byte(`"byte_length":`), []byte(`"session_id":null,"request_elapsed_ms":null,"saved_wall_ms":null,"capture_settings":null,"profile":null,"byte_length":`), 1)
	if err := contract.Validate("ManifestRequest", legacy); err != nil {
		t.Fatal(err)
	}
	h.request("POST", base(p.ArchiveID), p.DeviceToken, "application/json", legacy, 200, "ManifestResponse")
	integral := bytes.Replace(b, []byte(`"request_wall_ms":0`), []byte(`"request_wall_ms":0.0e1`), 1)
	if err := contract.Validate("ManifestRequest", integral); err != nil {
		t.Fatal(err)
	}
	h.request("POST", base(p.ArchiveID), p.DeviceToken, "application/json", integral, 200, "ManifestResponse")
	_, newFrame := synthetic()
	conflict := m
	conflict.SHA256 = strings.Repeat("0", 64)
	h.request("POST", base(p.ArchiveID), p.DeviceToken, "application/json", encode(protocol.ManifestRequest{Frames: []protocol.Metadata{newFrame, conflict}}), 409, "conflict")
	if h.count("frames", p.ArchiveID, newFrame.FrameID) != 0 {
		t.Fatal("partial batch persisted")
	}
	h.request("POST", base(p.ArchiveID), p.DeviceToken, "application/json", encode(protocol.ManifestRequest{Frames: []protocol.Metadata{m, m}}), 400, "")
	for _, bad := range [][]byte{[]byte(`{"frames":[]}`), []byte(`{"frames":[],"owner_id":"evil"}`), bytes.Replace(b, []byte(`"request_wall_ms":0`), []byte(`"request_wall_ms":null`), 1), bytes.Replace(b, []byte(`"request_wall_ms":0`), []byte(`"request_wall_ms":9007199254740992`), 1), bytes.Replace(b, []byte(`"frame_id"`), []byte(`"Frame_ID"`), 1)} {
		if contract.Validate("ManifestRequest", bad) == nil {
			t.Fatal("invalid corpus unexpectedly schema-valid")
		}
		h.request("POST", base(p.ArchiveID), p.DeviceToken, "application/json", bad, 400, "")
	}
	h.request("POST", base(p.ArchiveID), p.DeviceToken, "application/json", bytes.Repeat([]byte(" "), protocol.MaxJSON+1), 413, "")
	h.request("POST", base(p.ArchiveID), p.DeviceToken, "text/plain", b, 415, "")
	h.request("GET", base(p.ArchiveID), p.DeviceToken, "", nil, 405, "")
	h.request("GET", "/unknown", "", "", nil, 404, "")
	h.request("POST", base(p.ArchiveID), "", "application/json", b, 401, "")
	h.request("POST", base(p.ArchiveID), protocol.NewToken(), "application/json", b, 401, "")
	// Maximum-size valid profile, then missing/null negotiated values normalize.
	_, profile := synthetic()
	profile.Profile = &protocol.Profile{ID: strings.Repeat("я", 64), RequestedWidth: 16384, RequestedHeight: 16384, JPEGQuality: 100}
	settings := strings.Repeat("я", 2048)
	profile.CaptureSettings = &settings
	h.register(p, profile)
	profileJSON := encode(protocol.ManifestRequest{Frames: []protocol.Metadata{profile}})
	profileJSON = bytes.Replace(profileJSON, []byte(`"jpeg_quality":100`), []byte(`"jpeg_quality":100,"negotiated_width":null,"negotiated_height":null`), 1)
	h.request("POST", base(p.ArchiveID), p.DeviceToken, "application/json", profileJSON, 200, "ManifestResponse")
}

func TestUploadMalformedOversizedAndConcurrency(t *testing.T) {
	h := setup(t)
	p := h.pair(h.owner())
	data, m := synthetic()
	h.request("PUT", original(p.ArchiveID, m.FrameID), p.DeviceToken, "image/jpeg", data, 404, "")
	h.register(p, m)
	h.request("PUT", original(p.ArchiveID, m.FrameID), p.DeviceToken, "application/octet-stream", data, 415, "")
	h.request("PUT", original(p.ArchiveID, m.FrameID), p.DeviceToken, "image/jpeg", make([]byte, protocol.MaxBytes+1), 413, "")
	for _, bad := range [][]byte{data[:len(data)-1], append([]byte("x"), data[1:]...)} {
		h.request("PUT", original(p.ArchiveID, m.FrameID), p.DeviceToken, "image/jpeg", bad, 422, "checksum_mismatch")
	}
	invalid := []byte{255, 216, 255, 217}
	_, badMeta := synthetic()
	badMeta.SHA256 = protocol.Hash(invalid)
	badMeta.ByteLength = int64(len(invalid))
	h.register(p, badMeta)
	w := h.request("PUT", original(p.ArchiveID, badMeta.FrameID), p.DeviceToken, "image/jpeg", invalid, 422, "invalid_image")
	if !strings.Contains(w.Body.String(), "invalid_image") {
		t.Fatal("wrong validation depth")
	}
	var wg sync.WaitGroup
	replies := make(chan *httptest.ResponseRecorder, 4)
	for range 4 {
		wg.Go(func() {
			r := httptest.NewRequest("PUT", original(p.ArchiveID, m.FrameID), bytes.NewReader(data))
			r.Header.Set("Authorization", "Bearer "+p.DeviceToken)
			r.Header.Set("Content-Type", "image/jpeg")
			w := httptest.NewRecorder()
			h.api.ServeHTTP(w, r)
			replies <- w
		})
	}
	wg.Wait()
	close(replies)
	var first []byte
	for w := range replies {
		if w.Code != 200 {
			t.Fatal(w.Code, w.Body.String())
		}
		if err := contract.Validate("Receipt", w.Body.Bytes()); err != nil {
			t.Fatal(err)
		}
		h.assertReceipt(w.Body.Bytes(), p.ArchiveID, m.FrameID)
		if first == nil {
			first = append([]byte(nil), w.Body.Bytes()...)
		} else if !bytes.Equal(first, w.Body.Bytes()) {
			t.Fatal("concurrent receipt differs")
		}
	}
	if h.count("jobs", p.ArchiveID, m.FrameID) != 1 {
		t.Fatal("concurrent duplicate jobs")
	}
}

type onRead struct {
	r    io.Reader
	once sync.Once
	f    func()
}

func (r *onRead) Read(b []byte) (int, error) { r.once.Do(r.f); return r.r.Read(b) }
func TestRevokedWhileStreamingCannotCommit(t *testing.T) {
	h := setup(t)
	p := h.pair(h.owner())
	data, m := synthetic()
	h.register(p, m)
	body := &onRead{r: bytes.NewReader(data), f: func() { h.sql("UPDATE mt.devices SET revoked=true WHERE id=$1", p.DeviceID) }}
	r := httptest.NewRequest("PUT", original(p.ArchiveID, m.FrameID), body)
	r.Header.Set("Authorization", "Bearer "+p.DeviceToken)
	r.Header.Set("Content-Type", "image/jpeg")
	w := httptest.NewRecorder()
	h.api.ServeHTTP(w, r)
	if w.Code != 401 {
		t.Fatal(w.Code, w.Body.String())
	}
	assertError(t, w.Body.Bytes(), "unauthorized")
	if err := contract.CheckResponse(r.Method, r.URL.Path, w.Code, w.Header(), w.Body.Bytes()); err != nil {
		t.Fatal(err)
	}
	if h.count("jobs", p.ArchiveID, m.FrameID) != 0 {
		t.Fatal("revoked upload committed")
	}
	name, _ := archive.Name(p.ArchiveID, m.FrameID)
	if _, err := os.Stat(filepath.Join(h.root, name)); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("revoked content published", err)
	}
}

func TestPendingPublishedFaultsRecoverAndDoNotLeak(t *testing.T) {
	for _, fault := range []string{"diskfull", "fileSync", "publish", "directorySync", "sqlCommit"} {
		t.Run(fault, func(t *testing.T) {
			h := setup(t)
			p := h.pair(h.owner())
			data, m := synthetic()
			h.register(p, m)
			fail := func() error { return syscall.ENOSPC }
			published := false
			switch fault {
			case "diskfull":
				h.api.Files.Faults.BeforeWrite = fail
			case "fileSync":
				h.api.Files.Faults.FileSync = fail
			case "publish":
				h.api.Files.Faults.Publish = fail
			case "directorySync":
				h.api.Files.Faults.DirectorySync = fail
				published = true
			case "sqlCommit":
				h.api.BeforeCommit = func() error { return errors.New("sensitive SQL/password/filesystem details") }
				published = true
			}
			w := h.request("PUT", original(p.ArchiveID, m.FrameID), p.DeviceToken, "image/jpeg", data, 503, "")
			if strings.Contains(w.Body.String(), "sensitive") || strings.Contains(w.Body.String(), "space") {
				t.Fatal("internal failure leaked")
			}
			h.request("GET", receipt(p.ArchiveID, m.FrameID), p.DeviceToken, "", nil, 409, "not_committed")
			if h.count("jobs", p.ArchiveID, m.FrameID) != 0 {
				t.Fatal("premature job")
			}
			h.api.Files.Close()
			files, err := archive.Open(h.root)
			if err != nil {
				t.Fatal(err)
			}
			h.api.Files = files
			h.api.BeforeCommit = nil
			if err = h.api.DB.Recover(context.Background(), files.Recover); err != nil {
				t.Fatal(err)
			}
			if published {
				h.request("GET", receipt(p.ArchiveID, m.FrameID), p.DeviceToken, "", nil, 200, "Receipt")
			} else {
				h.request("GET", receipt(p.ArchiveID, m.FrameID), p.DeviceToken, "", nil, 409, "not_committed")
			}
			h.request("PUT", original(p.ArchiveID, m.FrameID), p.DeviceToken, "image/jpeg", data, 200, "Receipt")
			if h.count("jobs", p.ArchiveID, m.FrameID) != 1 {
				t.Fatal("job not exactly once persisted")
			}
		})
	}
}

func TestActualSQLCommitFailureRollsForward(t *testing.T) {
	h := setup(t)
	p := h.pair(h.owner())
	data, m := synthetic()
	h.register(p, m)
	h.sql(`CREATE FUNCTION mt.test_commit_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private SQL details'; END $$`)
	h.sql(`CREATE CONSTRAINT TRIGGER injected_failure AFTER INSERT ON mt.jobs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION mt.test_commit_failure()`)
	t.Cleanup(func() {
		h.sql("DROP TRIGGER IF EXISTS injected_failure ON mt.jobs")
		h.sql("DROP FUNCTION IF EXISTS mt.test_commit_failure()")
	})
	w := h.request("PUT", original(p.ArchiveID, m.FrameID), p.DeviceToken, "image/jpeg", data, 503, "")
	if strings.Contains(w.Body.String(), "private SQL") {
		t.Fatal("SQL error leaked")
	}
	if h.count("jobs", p.ArchiveID, m.FrameID) != 0 {
		t.Fatal("failed SQL txn left job")
	}
	h.sql("DROP TRIGGER injected_failure ON mt.jobs")
	if err := h.api.DB.Recover(context.Background(), h.api.Files.Recover); err != nil {
		t.Fatal(err)
	}
	h.request("GET", receipt(p.ArchiveID, m.FrameID), p.DeviceToken, "", nil, 200, "Receipt")
}

func TestRLSMissingContextPoolReuseAndUnsafeRuntimeRole(t *testing.T) {
	h := setup(t)
	p, q := h.pair(h.owner()), h.pair(h.owner())
	_, m := synthetic()
	h.register(p, m)
	ctx := context.Background()
	for range 15 {
		tx, _, err := h.api.DB.Begin(ctx, q.DeviceToken, q.ArchiveID)
		if err != nil {
			t.Fatal(err)
		}
		var n int
		if err = tx.QueryRow(ctx, "SELECT count(*) FROM mt.frames WHERE archive_id=$1", p.ArchiveID).Scan(&n); err != nil || n != 0 {
			t.Fatal("RLS isolation failed", err)
		}
		tx.Rollback(ctx)
	}
	for _, table := range []string{"owners", "archives", "frames", "jobs"} {
		var n int
		if err := h.api.DB.Pool.QueryRow(ctx, "SELECT count(*) FROM mt."+table).Scan(&n); err != nil || n != 0 {
			t.Fatal("unscoped RLS access", table, n, err)
		}
	}
	if _, err := h.api.DB.Pool.Exec(ctx, "SELECT * FROM mt.devices"); err == nil {
		t.Fatal("runtime can enumerate tokens")
	}
	if _, err := h.api.DB.Pool.Exec(ctx, "UPDATE mt.frames SET metadata='{}'"); err == nil {
		t.Fatal("runtime can mutate immutable metadata")
	}
	if _, err := h.api.DB.Pool.Exec(ctx, `INSERT INTO mt.frames(archive_id,id,owner_id,registering_device_id,metadata) VALUES($1,$2,$3,$4,$5)`, p.ArchiveID, protocol.NewID(), p.OwnerID, p.DeviceID, encode(m)); err == nil {
		t.Fatal("unscoped content insertion bypassed RLS")
	}
	if bad, err := postgres.Open(ctx, os.Getenv("MEMOTRACE_TEST_ADMIN_DSN")); err == nil {
		bad.Close()
		t.Fatal("super/owner runtime accepted")
	}
}

func TestProcessCrashAfterPublicationBeforeCommit(t *testing.T) {
	h := setup(t)
	p := h.pair(h.owner())
	_, m := synthetic()
	h.register(p, m)
	h.api.Files.Close()
	cfg := map[string]string{"root": h.root, "archive": p.ArchiveID, "frame": m.FrameID, "token": p.DeviceToken}
	cmd := exec.Command(os.Args[0], "-test.run=^TestCrashHelper$")
	cmd.Env = append(os.Environ(), "MEMOTRACE_CRASH_HELPER="+string(encode(cfg)))
	err := cmd.Run()
	var exit *exec.ExitError
	if !errors.As(err, &exit) || exit.ExitCode() != 86 {
		t.Fatal("crash hook not reached", err)
	}
	files, err := archive.Open(h.root)
	if err != nil {
		t.Fatal("process death did not release lock", err)
	}
	h.api.Files = files
	if h.count("jobs", p.ArchiveID, m.FrameID) != 0 {
		t.Fatal("pre-crash transaction committed")
	}
	if err = h.api.DB.Recover(context.Background(), files.Recover); err != nil {
		t.Fatal(err)
	}
	h.request("GET", receipt(p.ArchiveID, m.FrameID), p.DeviceToken, "", nil, 200, "Receipt")
	data, _ := synthetic()
	w := h.request("GET", original(p.ArchiveID, m.FrameID), p.DeviceToken, "", nil, 200, "")
	if !bytes.Equal(data, w.Body.Bytes()) {
		t.Fatal("crash recovery byte mismatch")
	}
}
func TestCrashHelper(t *testing.T) {
	b := os.Getenv("MEMOTRACE_CRASH_HELPER")
	if b == "" {
		return
	}
	var c map[string]string
	if err := json.Unmarshal([]byte(b), &c); err != nil {
		t.Fatal(err)
	}
	db, err := postgres.Open(context.Background(), os.Getenv("MEMOTRACE_TEST_DSN"))
	if err != nil {
		t.Fatal(err)
	}
	files, err := archive.Open(c["root"])
	if err != nil {
		t.Fatal(err)
	}
	a := New(db, files)
	a.BeforeCommit = func() error { os.Exit(86); return nil }
	data, _ := synthetic()
	r := httptest.NewRequest("PUT", original(c["archive"], c["frame"]), bytes.NewReader(data))
	r.Header.Set("Authorization", "Bearer "+c["token"])
	r.Header.Set("Content-Type", "image/jpeg")
	a.ServeHTTP(httptest.NewRecorder(), r)
	t.Fatal("crash not reached")
}

func TestAdmissionConcurrencyBound(t *testing.T) {
	h := setup(t)
	for range cap(h.api.concurrency) {
		h.api.concurrency <- struct{}{}
	}
	h.request(http.MethodPost, "/v1/pairing/redeem", "", "application/json", []byte(`{}`), 503, "")
}

func TestBatchOrderDistinctEvidenceAndMalformedBatchRollback(t *testing.T) {
	h := setup(t)
	p := h.pair(h.owner())
	data, first := synthetic()
	_, second := synthetic()
	w := h.register(p, second, first)
	var result protocol.ManifestResponse
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if result.Frames[0].FrameID != second.FrameID || result.Frames[1].FrameID != first.FrameID {
		t.Fatal("batch response reordered")
	}
	for _, m := range []protocol.Metadata{first, second} {
		h.request("PUT", original(p.ArchiveID, m.FrameID), p.DeviceToken, "image/jpeg", data, 200, "Receipt")
		if h.count("jobs", p.ArchiveID, m.FrameID) != 1 {
			t.Fatal("distinct evidence job missing")
		}
	}
	name1, _ := archive.Name(p.ArchiveID, first.FrameID)
	name2, _ := archive.Name(p.ArchiveID, second.FrameID)
	a, err := os.Stat(filepath.Join(h.root, name1))
	if err != nil {
		t.Fatal(err)
	}
	b, err := os.Stat(filepath.Join(h.root, name2))
	if err != nil {
		t.Fatal(err)
	}
	if os.SameFile(a, b) {
		t.Fatal("distinct evidence physically deduplicated")
	}
	_, fresh := synthetic()
	bad := first
	bad.ByteLength = 0
	h.request("POST", base(p.ArchiveID), p.DeviceToken, "application/json", encode(protocol.ManifestRequest{Frames: []protocol.Metadata{fresh, bad}}), 400, "")
	if h.count("frames", p.ArchiveID, fresh.FrameID) != 0 {
		t.Fatal("invalid batch partially persisted")
	}
}

func TestCorruptPendingRecoveryBlocksAndPreservesEvidence(t *testing.T) {
	h := setup(t)
	p := h.pair(h.owner())
	data, m := synthetic()
	h.register(p, m)
	h.api.BeforeCommit = func() error { return syscall.EIO }
	h.request("PUT", original(p.ArchiveID, m.FrameID), p.DeviceToken, "image/jpeg", data, 503, "")
	name, _ := archive.Name(p.ArchiveID, m.FrameID)
	path := filepath.Join(h.root, name)
	damaged := []byte("synthetic damaged evidence")
	if err := os.WriteFile(path, damaged, 0600); err != nil {
		t.Fatal(err)
	}
	if err := h.api.DB.Recover(context.Background(), h.api.Files.Recover); err == nil {
		t.Fatal("corrupt pending recovery succeeded")
	}
	if h.count("jobs", p.ArchiveID, m.FrameID) != 0 {
		t.Fatal("corrupt pending was committed")
	}
	got, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(got, damaged) {
		t.Fatal("corrupt evidence not preserved", err)
	}
}
