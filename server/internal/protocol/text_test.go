// SPDX-License-Identifier: AGPL-3.0-only
package protocol

import (
	"encoding/json"
	"testing"
)

func TestStrictJSONRejectsUnpairedSurrogatesBeforeLossyDecode(t *testing.T) {
	for _, value := range []string{`"\ud800"`, `"\ud801"`, `"\udbff"`, `"\udc00"`, `"\udfff"`, `"\ud800x"`, `"\ud800\ud800"`, `"\udc00\ud800"`, `"\ud800\\udc00"`, `"\\\ud800"`, `"\ud83d\u0041"`, `"\ud83d\uDE0"`, `"\uDE0x"`, `"\uD80g"`, `"\uD8"`} {
		t.Run(value, func(t *testing.T) {
			for _, b := range []string{`{"invitation_token":"` + NewToken() + `","device_name":` + value + `}`, `{` + value + `:"key value"}`} {
				if validJSONScalars([]byte(b)) {
					t.Fatal("invalid scalar escaped scanner accepted", b)
				}
				var req PairRequest
				if err := StrictJSON([]byte(b), &req); err == nil || err.Error() != "invalid_request" {
					t.Fatal("lossy JSON accepted", err)
				}
			}
		})
	}
	for _, tc := range []struct{ raw, want string }{
		{`"\ufffd"`, "�"}, {`"�"`, "�"}, {`"😀"`, "😀"}, {`"\ud83d\ude00"`, "😀"}, {`"\uD83D\uDE00"`, "😀"},
		{`"\\ud800"`, `\ud800`}, {`"\\ud800\\udc00"`, `\ud800\udc00`}, {`"quoted\"\\ud800"`, `quoted"\ud800`},
		{`"\\\ud83d\ude00"`, `\😀`}, {`"\ud7ff\ue000"`, "\ud7ff\ue000"},
	} {
		t.Run(tc.raw, func(t *testing.T) {
			b := []byte(`{"invitation_token":"` + NewToken() + `","device_name":` + tc.raw + `}`)
			var req PairRequest
			if err := StrictJSON(b, &req); err != nil {
				t.Fatal(err)
			}
			if req.DeviceName != tc.want {
				t.Fatalf("scalar bytes changed: got %q want %q", req.DeviceName, tc.want)
			}
			if err := req.Validate(); err != nil {
				t.Fatal(err)
			}
		})
	}
	if validJSONScalars([]byte{'"', 0xed, 0xa0, 0x80, '"'}) {
		t.Fatal("UTF-8 encoding of surrogate accepted")
	}
	if validJSONScalars([]byte(`"\`)) {
		t.Fatal("dangling escape accepted")
	}
}

func TestCanonicalTextDomainExcludesNULWithoutStripping(t *testing.T) {
	for _, s := range []string{"\x00", "before\x00after", string([]byte{0xff})} {
		if validText(s) {
			t.Fatal("noncanonical text accepted")
		}
		if (PairRequest{InvitationToken: NewToken(), DeviceName: s}).Validate() == nil {
			t.Fatal("pairing accepted noncanonical text")
		}
		m := valid()
		m.CaptureSettings = &s
		if m.Validate() == nil {
			t.Fatal("settings accepted noncanonical text")
		}
		m.CaptureSettings = nil
		m.Profile = &Profile{ID: s, RequestedWidth: 1, RequestedHeight: 1, JPEGQuality: 1}
		if m.Validate() == nil {
			t.Fatal("profile accepted noncanonical text")
		}
	}
	for _, s := range []string{"", "�", "😀", `\u0000`, "e\u0301", "é"} {
		if !validText(s) {
			t.Fatalf("canonical text rejected: %q", s)
		}
	}
	// NUL is valid JSON syntax; field validation must reject it, not strip it.
	b, _ := json.Marshal(PairRequest{InvitationToken: NewToken(), DeviceName: "a\x00b"})
	var req PairRequest
	if err := StrictJSON(b, &req); err != nil {
		t.Fatal(err)
	}
	if req.DeviceName != "a\x00b" || req.Validate() == nil {
		t.Fatal("NUL was silently replaced/stripped")
	}
}
