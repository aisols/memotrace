// SPDX-License-Identifier: AGPL-3.0-only
package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"memotrace/server/internal/contract"
	"memotrace/server/internal/protocol"
)

func textManifest(m protocol.Metadata, rawString string) []byte {
	placeholder := "text-placeholder"
	m.CaptureSettings = &placeholder
	m.Profile = &protocol.Profile{ID: placeholder, RequestedWidth: 1, RequestedHeight: 1, JPEGQuality: 1}
	b := encode(protocol.ManifestRequest{Frames: []protocol.Metadata{m}})
	return bytes.ReplaceAll(b, []byte(`"text-placeholder"`), []byte(rawString))
}
func (h *harness) storedText(archiveID, frameID string) (settings, profile string) {
	h.t.Helper()
	if err := h.admin.QueryRow(context.Background(), "SELECT metadata->>'capture_settings',metadata->'profile'->>'id' FROM mt.frames WHERE archive_id=$1 AND id=$2", archiveID, frameID).Scan(&settings, &profile); err != nil {
		h.t.Fatal(err)
	}
	return
}

func TestHTTPUnicodeScalarsRejectWithoutRowsAndPreserveImmutableText(t *testing.T) {
	h := setup(t)
	p := h.pair(h.owner())
	_, m := synthetic()
	badValues := []string{`"\ud800"`, `"\ud801"`, `"\udc00"`, `"\udfff"`, `"\ud800\ud800"`, `"\udc00\ud800"`, `"\ud800\\udc00"`, `"prefix\ud800suffix"`, `"\\\ud800"`}
	for _, value := range badValues {
		h.request("POST", base(p.ArchiveID), p.DeviceToken, "application/json", textManifest(m, value), 400, "invalid_request")
		if h.count("frames", p.ArchiveID, m.FrameID) != 0 {
			t.Fatal("unpaired surrogate registered a frame")
		}
	}
	for _, key := range []string{`"\ud800"`, `"\udc00"`} {
		b := bytes.Replace(textManifest(m, `"valid"`), []byte(`"capture_settings"`), []byte(key), 1)
		h.request("POST", base(p.ArchiveID), p.DeviceToken, "application/json", b, 400, "invalid_request")
		if h.count("frames", p.ArchiveID, m.FrameID) != 0 {
			t.Fatal("unpaired surrogate key registered a frame")
		}
	}
	// A genuine U+FFFD is a valid immutable value, distinct from malformed escapes.
	for _, value := range []string{`"�"`, `"\ufffd"`} {
		b := textManifest(m, value)
		if err := contract.Validate("ManifestRequest", b); err != nil {
			t.Fatal(err)
		}
		h.request("POST", base(p.ArchiveID), p.DeviceToken, "application/json", b, 200, "ManifestResponse")
	}
	for _, value := range badValues {
		h.request("POST", base(p.ArchiveID), p.DeviceToken, "application/json", textManifest(m, value), 400, "invalid_request")
	}
	h.request("POST", base(p.ArchiveID), p.DeviceToken, "application/json", textManifest(m, `"😀"`), 409, "conflict")
	settings, profile := h.storedText(p.ArchiveID, m.FrameID)
	if settings != "�" || profile != "�" {
		t.Fatal("replacement character metadata changed")
	}
	for _, tc := range []struct{ raw, repeat, want string }{
		{`"😀"`, `"\ud83d\ude00"`, "😀"}, {`"\\ud800"`, `"\u005cud800"`, `\ud800`},
		{`"quote\"\\ud800"`, `"quote\u0022\u005cud800"`, `quote"\ud800`},
		{`"e\u0301"`, `"é"`, "e\u0301"},
	} {
		_, frame := synthetic()
		for _, raw := range []string{tc.raw, tc.repeat} {
			b := textManifest(frame, raw)
			if err := contract.Validate("ManifestRequest", b); err != nil {
				t.Fatal(err)
			}
			h.request("POST", base(p.ArchiveID), p.DeviceToken, "application/json", b, 200, "ManifestResponse")
		}
		settings, profile = h.storedText(p.ArchiveID, frame.FrameID)
		if !bytes.Equal([]byte(settings), []byte(tc.want)) || !bytes.Equal([]byte(profile), []byte(tc.want)) {
			t.Fatal("valid Unicode text normalized or replaced")
		}
		h.request("POST", base(p.ArchiveID), p.DeviceToken, "application/json", textManifest(frame, `"�"`), 409, "conflict")
		got, _ := h.storedText(p.ArchiveID, frame.FrameID)
		if got != tc.want {
			t.Fatal("conflicting repeat overwrote text")
		}
	}
}

func TestHTTPNULAndSurrogatePairingDoNotConsumeInvitation(t *testing.T) {
	h := setup(t)
	a := h.owner()
	token := h.invite(a, time.Now().Add(time.Minute))
	for _, name := range []string{`"before\u0000after"`, `"\ud800"`, `"\ud801"`, `"\udc00"`, `"\ud800\\udc00"`} {
		b := []byte(`{"invitation_token":"` + token + `","device_name":` + name + `}`)
		if strings.Contains(name, `\u0000`) && contract.Validate("PairRequest", b) == nil {
			t.Fatal("canonical schema accepted NUL")
		}
		w := h.request("POST", "/v1/pairing/redeem", "", "application/json", b, 400, "invalid_request")
		if bytes.Contains(w.Body.Bytes(), []byte(token)) {
			t.Fatal("pairing error leaked invitation")
		}
		var consumed bool
		var devices int
		if err := h.admin.QueryRow(context.Background(), "SELECT consumed FROM mt.invitations WHERE token_hash=$1", protocol.Hash([]byte(token))).Scan(&consumed); err != nil {
			t.Fatal(err)
		}
		if err := h.admin.QueryRow(context.Background(), "SELECT count(*) FROM mt.devices WHERE archive_id=$1", a).Scan(&devices); err != nil {
			t.Fatal(err)
		}
		if consumed || devices != 0 {
			t.Fatal("invalid text consumed invitation or created device")
		}
	}
	for _, name := range []string{"�", "😀", `\ud800`} {
		b := encode(protocol.PairRequest{InvitationToken: token, DeviceName: name})
		if err := contract.Validate("PairRequest", b); err != nil {
			t.Fatal(err)
		}
		w := h.request("POST", "/v1/pairing/redeem", "", "application/json", b, 201, "PairResponse")
		var p protocol.PairResponse
		if err := json.Unmarshal(w.Body.Bytes(), &p); err != nil {
			t.Fatal(err)
		}
		var stored string
		if err := h.admin.QueryRow(context.Background(), "SELECT name FROM mt.devices WHERE id=$1", p.DeviceID).Scan(&stored); err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal([]byte(stored), []byte(name)) {
			t.Fatal("device name changed")
		}
		token = h.invite(a, time.Now().Add(time.Minute))
	}
}

func TestHTTPNULBatchRegistrationIsAtomic(t *testing.T) {
	h := setup(t)
	p := h.pair(h.owner())
	for _, field := range []string{"capture_settings", "profile.id"} {
		_, fresh := synthetic()
		_, bad := synthetic()
		nul := "before\x00after"
		if field == "capture_settings" {
			bad.CaptureSettings = &nul
		} else {
			bad.Profile = &protocol.Profile{ID: nul, RequestedWidth: 1, RequestedHeight: 1, JPEGQuality: 1}
		}
		b := encode(protocol.ManifestRequest{Frames: []protocol.Metadata{fresh, bad}})
		if contract.Validate("ManifestRequest", b) == nil {
			t.Fatal("canonical schema accepted NUL", field)
		}
		h.request("POST", base(p.ArchiveID), p.DeviceToken, "application/json", b, 400, "invalid_request")
		if h.count("frames", p.ArchiveID, fresh.FrameID) != 0 || h.count("frames", p.ArchiveID, bad.FrameID) != 0 {
			t.Fatal("NUL batch partially registered")
		}
	}
}
