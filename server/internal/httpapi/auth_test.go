// SPDX-License-Identifier: AGPL-3.0-only
package httpapi

import (
	"bytes"
	"net/http/httptest"
	"testing"
	"time"

	"memotrace/server/internal/contract"
	"memotrace/server/internal/protocol"
)

func TestHTTPAuthSchemeCaseTokenExactnessAndChallenges(t *testing.T) {
	h := setup(t)
	p := h.pair(h.owner())
	data, m := synthetic()
	h.register(p, m)
	h.request("PUT", original(p.ArchiveID, m.FrameID), p.DeviceToken, "image/jpeg", data, 200, "Receipt")
	path := receipt(p.ArchiveID, m.FrameID)
	check := func(headers []string, status int) {
		t.Helper()
		r := httptest.NewRequest("GET", path, nil)
		for _, header := range headers {
			r.Header.Add("Authorization", header)
		}
		w := httptest.NewRecorder()
		h.api.ServeHTTP(w, r)
		if w.Code != status {
			t.Fatalf("auth case returned %d want %d", w.Code, status)
		}
		if err := contract.CheckResponse("GET", path, w.Code, w.Header(), w.Body.Bytes()); err != nil {
			t.Fatal(err)
		}
		if status == 401 {
			assertError(t, w.Body.Bytes(), "unauthorized")
			if got := w.Header().Values("WWW-Authenticate"); len(got) != 1 || got[0] != `Bearer realm="memotrace"` {
				t.Fatal("protected challenge differs", got)
			}
			if bytes.Contains(w.Body.Bytes(), []byte(p.DeviceToken)) {
				t.Fatal("credential in error")
			}
		} else if status == 200 {
			h.assertReceipt(w.Body.Bytes(), p.ArchiveID, m.FrameID)
			if w.Header().Get("WWW-Authenticate") != "" {
				t.Fatal("success emitted challenge")
			}
		} else {
			assertError(t, w.Body.Bytes(), "not_found")
		}
	}
	for _, scheme := range []string{"Bearer", "bearer", "BEARER", "bEaReR"} {
		for _, separator := range []string{" ", "  ", "        "} {
			check([]string{scheme + separator + p.DeviceToken}, 200)
		}
	}
	other := h.pair(h.owner())
	check([]string{"bEaReR    " + other.DeviceToken}, 404)
	changed := "A" + p.DeviceToken[1:]
	if changed == p.DeviceToken {
		changed = "B" + p.DeviceToken[1:]
	}
	for _, headers := range [][]string{nil, {"Bearer invalid"}, {"Bearer " + protocol.NewToken()}, {"bearer " + changed}, {"Basic " + p.DeviceToken}, {"Bearer " + p.DeviceToken + " "}, {"Bearer  " + p.DeviceToken + "\t"}, {"Bearer\t" + p.DeviceToken}, {"Bearer \t" + p.DeviceToken}, {"Bearer" + p.DeviceToken}, {"Bearer   "}, {" Bearer " + p.DeviceToken}, {"Bearer " + p.DeviceToken, "Bearer  " + p.DeviceToken}, {"bearer " + p.DeviceToken, "BEARER invalid"}, {"Bearer " + p.DeviceToken + ", Bearer " + p.DeviceToken}} {
		check(headers, 401)
	}
	h.sql("UPDATE mt.devices SET revoked=true WHERE id=$1", p.DeviceID)
	for _, scheme := range []string{"Bearer", "bearer", "BEARER", "bEaReR"} {
		for _, separator := range []string{" ", "  ", "        "} {
			check([]string{scheme + separator + p.DeviceToken}, 401)
		}
	}
}

func TestHTTPInvitationUnauthorizedChallenge(t *testing.T) {
	h := setup(t)
	a := h.owner()
	consumed := h.invite(a, time.Now().Add(time.Minute))
	body := encode(protocol.PairRequest{InvitationToken: consumed, DeviceName: "synthetic"})
	h.request("POST", "/v1/pairing/redeem", "", "application/json", body, 201, "PairResponse")
	for _, token := range []string{"invalid", protocol.NewToken(), consumed, h.invite(a, time.Now().Add(-time.Second))} {
		w := h.request("POST", "/v1/pairing/redeem", "", "application/json", encode(protocol.PairRequest{InvitationToken: token, DeviceName: "synthetic"}), 401, "unauthorized")
		if got := w.Header().Values("WWW-Authenticate"); len(got) != 1 || got[0] != `MemoTraceInvitation realm="memotrace-pairing"` {
			t.Fatal("invitation challenge differs", got)
		}
		if bytes.Contains(w.Body.Bytes(), []byte(token)) {
			t.Fatal("invitation in error")
		}
	}
}
