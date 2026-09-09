// SPDX-License-Identifier: AGPL-3.0-only
package bootstrap

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"io"
	"log"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"memotrace/server/internal/protocol"
)

func certificate(t *testing.T, expired bool) (tls.Certificate, string, string) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	end := now.Add(time.Hour)
	if expired {
		end = now.Add(-time.Minute)
	}
	template := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "synthetic localhost"}, DNSNames: []string{"localhost"}, IPAddresses: []net.IP{net.ParseIP("127.0.0.1")}, NotBefore: now.Add(-time.Hour), NotAfter: end, KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}}
	der, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	keyDER, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		t.Fatal(err)
	}
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyDER})
	pair, err := tls.X509KeyPair(certPEM, keyPEM)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "cert.pem")
	if err = os.WriteFile(path, certPEM, 0600); err != nil {
		t.Fatal(err)
	}
	return pair, path, protocol.Hash(der)
}
func TestTrustedTLSBootstrapPinOriginNameAndValidity(t *testing.T) {
	pair, path, pin := certificate(t, false)
	server := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(200) }))
	server.Config.ErrorLog = log.New(io.Discard, "", 0)
	server.TLS = &tls.Config{MinVersion: tls.VersionTLS12, Certificates: []tls.Certificate{pair}}
	server.StartTLS()
	defer server.Close()
	if got, err := Verify(context.Background(), server.URL, path, pin); err != nil || got != pin {
		t.Fatal("trusted bootstrap failed", err)
	}
	host, port, err := net.SplitHostPort(strings.TrimPrefix(server.URL, "https://"))
	if err != nil {
		t.Fatal(err)
	}
	for _, origin := range []string{strings.Replace(server.URL, "https://", "HTTPS://", 1), strings.Replace(server.URL, "https://", "Https://", 1), "https://" + net.JoinHostPort(host, strings.Repeat("0", 6-len(port))+port)} {
		if _, err := Verify(context.Background(), origin, path, pin); err == nil {
			t.Fatal("noncanonical live origin accepted")
		}
	}
	for _, origin := range []string{"http://localhost", server.URL + "/", server.URL + "/path", server.URL + "?token=secret", server.URL + "#fragment", "https://user:pass@localhost", strings.Replace(server.URL, "127.0.0.1", "wrong.invalid", 1), "https://localhost:0"} {
		if _, err := Verify(context.Background(), origin, path, pin); err == nil {
			t.Fatal("invalid origin/name accepted", origin)
		}
	}
	for _, wrong := range []string{"", strings.Repeat("0", 64)} {
		if _, err := Verify(context.Background(), server.URL, path, wrong); err == nil {
			t.Fatal("untrusted pin accepted")
		}
	}
	_, expiredPath, expiredPin := certificate(t, true)
	if _, err := Verify(context.Background(), server.URL, expiredPath, expiredPin); err == nil {
		t.Fatal("expired certificate accepted")
	}
	// Correctly pinned local certificate but a different live leaf must fail normal
	// verification, before any invitation can be inserted.
	_, otherPath, otherPin := certificate(t, false)
	if _, err := Verify(context.Background(), server.URL, otherPath, otherPin); err == nil {
		t.Fatal("live certificate replacement accepted")
	}
}

func TestOriginRawSchemeAndPortDigitBounds(t *testing.T) {
	for _, origin := range []string{"https://localhost", "https://localhost:1", "https://localhost:00001", "https://localhost:00443", "https://localhost:65535", "https://[::1]:00443"} {
		u, err := parseOrigin(origin)
		if err != nil || u.String() != origin {
			t.Fatal("valid origin rejected or normalized", origin, u, err)
		}
	}
	for _, origin := range []string{"HTTPS://localhost", "Https://localhost", "https://localhost:000001", "https://localhost:065535", "https://localhost:000000443", "https://localhost:65536", "https://localhost:00000", "https://localhost:", "https://localhost:+443", "https://localhost:-1"} {
		if _, err := parseOrigin(origin); err == nil {
			t.Fatal("invalid origin accepted", origin)
		}
	}
}
