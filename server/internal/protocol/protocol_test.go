// SPDX-License-Identifier: AGPL-3.0-only
package protocol

import (
	"bytes"
	"encoding/json"
	"image"
	"image/jpeg"
	"strings"
	"testing"
)

func ptr[T any](v T) *T { return &v }
func valid() Metadata {
	return Metadata{FrameID: NewID(), RequestWallMS: ptr(int64(0)), SHA256: Hash([]byte("fixture")), ByteLength: 1}
}
func TestIdentifiersAndCredentials(t *testing.T) {
	for range 20 {
		if !UUID(NewID()) || !Token(NewToken()) {
			t.Fatal("generator violates wire encoding")
		}
	}
	for _, s := range []string{"../secret", "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA", "", strings.Repeat("0", 36)} {
		if UUID(s) {
			t.Fatal(s)
		}
	}
	if !UUID("00000000-0000-0000-0000-000000000000") {
		t.Fatal("UUID version restricted")
	}
	for _, s := range []string{"", strings.Repeat("A", 42), strings.Repeat("A", 42) + "B", strings.Repeat("A", 43) + "="} {
		if Token(s) {
			t.Fatal("noncanonical token")
		}
	}
}
func TestMetadataLegacyProfileBoundsAndBatch(t *testing.T) {
	m := valid()
	if err := m.Validate(); err != nil {
		t.Fatal(err)
	}
	m.SessionID = ptr(NewID())
	m.RequestElapsedMS = ptr(MaxTime)
	m.SavedWallMS = ptr(int64(0))
	m.CaptureSettings = ptr(strings.Repeat("я", 2048))
	m.Profile = &Profile{ID: strings.Repeat("я", 64), RequestedWidth: 16384, RequestedHeight: 1, JPEGQuality: 100, NegotiatedWidth: ptr(1), NegotiatedHeight: ptr(16384)}
	if err := m.Validate(); err != nil {
		t.Fatal(err)
	}
	cases := []func(*Metadata){
		func(m *Metadata) { m.FrameID = "../x" }, func(m *Metadata) { m.RequestWallMS = nil }, func(m *Metadata) { m.RequestWallMS = ptr(int64(-1)) }, func(m *Metadata) { m.RequestWallMS = ptr(MaxTime + 1) },
		func(m *Metadata) { m.SHA256 = strings.Repeat("A", 64) }, func(m *Metadata) { m.ByteLength = 0 }, func(m *Metadata) { m.ByteLength = MaxBytes + 1 }, func(m *Metadata) { m.RequestElapsedMS = ptr(int64(-1)) }, func(m *Metadata) { m.SavedWallMS = ptr(MaxTime + 1) },
		func(m *Metadata) { m.SessionID = ptr("x") }, func(m *Metadata) { m.CaptureSettings = ptr(strings.Repeat("я", 2049)) },
		func(m *Metadata) { m.Profile = &Profile{} }, func(m *Metadata) { m.Profile.JPEGQuality = 101 }, func(m *Metadata) { m.Profile.RequestedWidth = 0 }, func(m *Metadata) { m.Profile.NegotiatedHeight = ptr(0) }, func(m *Metadata) { m.Profile.NegotiatedWidth = ptr(16385) },
	}
	for i, mutate := range cases {
		copy := m
		p := *m.Profile
		copy.Profile = &p
		mutate(&copy)
		if copy.Validate() == nil {
			t.Fatalf("invalid case %d accepted", i)
		}
	}
	if (ManifestRequest{Frames: []Metadata{valid()}}).Validate() != nil {
		t.Fatal("valid batch rejected")
	}
	for _, batch := range []ManifestRequest{{}, {Frames: []Metadata{m, m}}, {Frames: make([]Metadata, 101)}, {Frames: []Metadata{{}}}} {
		if batch.Validate() == nil {
			t.Fatal("invalid batch accepted")
		}
	}
	for _, p := range []PairRequest{{NewToken(), "я"}, {NewToken(), strings.Repeat("я", 80)}} {
		if p.Validate() != nil {
			t.Fatal("valid device name")
		}
	}
	for _, p := range []PairRequest{{NewToken(), ""}, {NewToken(), strings.Repeat("я", 81)}, {"bad", "name"}} {
		if p.Validate() == nil {
			t.Fatal("invalid pairing accepted")
		}
	}
}
func TestStrictJSONAndNullNormalization(t *testing.T) {
	m := valid()
	b, _ := json.Marshal(ManifestRequest{Frames: []Metadata{m}})
	var a ManifestRequest
	if err := StrictJSON(b, &a); err != nil {
		t.Fatal(err)
	}
	null := strings.Replace(string(b), `"byte_length":1`, `"byte_length":1,"session_id":null,"request_elapsed_ms":null,"saved_wall_ms":null,"capture_settings":null,"profile":null`, 1)
	var c ManifestRequest
	if err := StrictJSON([]byte(null), &c); err != nil {
		t.Fatal(err)
	}
	aa, _ := json.Marshal(a)
	cc, _ := json.Marshal(c)
	if !bytes.Equal(aa, cc) {
		t.Fatal("null did not normalize")
	}
	for _, bad := range []string{`null`, `{`, `[]`, `{} {}`, `{"frames":[],"frames":[]}`, `{"frames":[],"owner_id":null}`, `{"Frames":[]}`, `{"FRAMES":null}`, `{"frames":[null]}`, `{"frames":false}`, `{"frames":[}`, string([]byte{'{', 255, '}'})} {
		var m ManifestRequest
		err := StrictJSON([]byte(bad), &m)
		if err == nil {
			err = m.Validate()
		}
		if err == nil {
			t.Fatalf("accepted %q", bad)
		}
	}
	// Unknown nested fields and duplicate fields never enter persisted metadata.
	for _, bad := range []string{strings.Replace(string(b), `"byte_length":1`, `"byte_length":1,"device_id":"x"`, 1), strings.Replace(string(b), `"byte_length":1`, `"byte_length":1,"byte_length":2`, 1), strings.Replace(string(b), `"byte_length":1`, `"byte_length":1.5`, 1)} {
		var m ManifestRequest
		if StrictJSON([]byte(bad), &m) == nil {
			t.Fatal("invalid nested metadata accepted")
		}
	}
}
func TestJPEGHeaderIntegrityAndLimits(t *testing.T) {
	var out bytes.Buffer
	if err := jpeg.Encode(&out, image.NewRGBA(image.Rect(0, 0, 3, 2)), nil); err != nil {
		t.Fatal(err)
	}
	// Synthetic APP1 segment tests exact preservation including EXIF-like bytes.
	b := append([]byte{255, 216, 255, 225, 0, 10, 'E', 'x', 'i', 'f', 0, 0, 0, 0}, out.Bytes()[2:]...)
	m := valid()
	m.ByteLength = int64(len(b))
	m.SHA256 = Hash(b)
	if err := CheckImage(bytes.NewReader(b), int64(len(b)), Hash(b), m); err != nil {
		t.Fatal(err)
	}
	if err := CheckImage(bytes.NewReader(b), int64(len(b))-1, Hash(b), m); err == nil {
		t.Fatal("length mismatch accepted")
	}
	if err := CheckImage(bytes.NewReader(b), int64(len(b)), Hash([]byte("other")), m); err == nil {
		t.Fatal("hash mismatch accepted")
	}
	badCases := [][]byte{{1}, {1, 2, 3, 4}, {255, 216, 0, 0}, {255, 216, 255, 217}, b[:len(b)-1]}
	for _, dims := range [][2]int{{0, 1}, {16385, 1}, {7000, 6000}} {
		c := append([]byte(nil), b...)
		i := bytes.Index(c, []byte{255, 192})
		if i < 0 {
			t.Fatal("fixture SOF missing")
		}
		c[i+5] = byte(dims[1] >> 8)
		c[i+6] = byte(dims[1])
		c[i+7] = byte(dims[0] >> 8)
		c[i+8] = byte(dims[0])
		badCases = append(badCases, c)
	}
	for _, bad := range badCases {
		m.ByteLength = int64(len(bad))
		m.SHA256 = Hash(bad)
		if err := CheckImage(bytes.NewReader(bad), int64(len(bad)), Hash(bad), m); err == nil {
			t.Fatal("invalid image accepted")
		}
	}
}
func TestErrorStatusAndRetryPolicy(t *testing.T) {
	for code, status := range map[string]int{"invalid_request": 400, "unauthorized": 401, "not_found": 404, "conflict": 409, "not_committed": 409, "integrity_error": 409, "checksum_mismatch": 422, "invalid_image": 422, "payload_too_large": 413, "unsupported_media_type": 415, "unavailable": 503} {
		e := E(code)
		if e.Error() != code || Status(code) != status || e.Retryable != (code == "unavailable" || code == "checksum_mismatch" || code == "not_committed") {
			t.Fatal(code)
		}
	}
}

func TestMathematicalIntegerJSONWithoutFloatRounding(t *testing.T) {
	for input, want := range map[string]string{"1.0": "1", "1e3": "1000", "10e-1": "1", "9007199254740991.000": "9007199254740991", "-0e9999999999999999999": "0", "-10.0": "-10"} {
		got, err := integral(json.Number(input))
		if err != nil || string(got) != want {
			t.Fatal(input, got, err)
		}
	}
	for _, input := range []string{"1.5", "9007199254740991.1", "1e-1000000000", "1e9999999999999999999", "10000000000000000", "1e999", "1e-999"} {
		if _, err := integral(json.Number(input)); err == nil {
			t.Fatal("noninteger/oversized accepted", input)
		}
	}
	for _, input := range []string{`{"invitation_token":null,"device_name":"x"}`, `{"device_name":"x"}`, `{"invitation_token":"x","device_name":null}`, strings.Repeat("[", 17) + strings.Repeat("]", 17)} {
		var p PairRequest
		if StrictJSON([]byte(input), &p) == nil {
			t.Fatal("malformed required field accepted")
		}
	}
	m := valid()
	b, _ := json.Marshal(ManifestRequest{Frames: []Metadata{m}})
	b = bytes.Replace(b, []byte(`"request_wall_ms":0`), []byte(`"request_wall_ms":1e3`), 1)
	var req ManifestRequest
	if err := StrictJSON(b, &req); err != nil || *req.Frames[0].RequestWallMS != 1000 {
		t.Fatal("integral wire representation rejected", err)
	}
}
