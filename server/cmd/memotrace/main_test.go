// SPDX-License-Identifier: AGPL-3.0-only
package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"image"
	"image/jpeg"
	"io"
	"math/big"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"memotrace/server/internal/archive"
	"memotrace/server/internal/contract"
	"memotrace/server/internal/protocol"
)

func TestCLIHelper(t *testing.T) {
	raw := os.Getenv("MEMOTRACE_CLI_TEST_ARGS")
	if raw == "" {
		return
	}
	var args []string
	if json.Unmarshal([]byte(raw), &args) != nil {
		os.Exit(2)
	}
	if run(args) != nil {
		os.Exit(1)
	}
	os.Exit(0)
}
func cli(t *testing.T, args ...string) *exec.Cmd {
	t.Helper()
	b, _ := json.Marshal(args)
	c := exec.Command(os.Args[0], "-test.run=^TestCLIHelper$")
	c.Env = append(os.Environ(), "MEMOTRACE_CLI_TEST_ARGS="+string(b), "MEMOTRACE_ADMIN_DSN="+os.Getenv("MEMOTRACE_TEST_ADMIN_DSN"), "MEMOTRACE_DSN="+os.Getenv("MEMOTRACE_TEST_DSN"))
	return c
}
func TestCLICompleteTLSLifecycleAndShutdown(t *testing.T) {
	if os.Getenv("MEMOTRACE_TEST_ADMIN_DSN") == "" {
		if os.Getenv("MEMOTRACE_REQUIRE_POSTGRES") == "1" {
			t.Fatal("required PostgreSQL missing")
		}
		t.Skip("use bash scripts/verify.sh for PostgreSQL/CLI tests")
	}
	root := t.TempDir()
	if err := os.Chmod(root, 0700); err != nil {
		t.Fatal(err)
	}
	if b, err := cli(t, "migrate").CombinedOutput(); err != nil {
		t.Fatal("migrate", err, string(b))
	}
	if err := cli(t, "migrate").Run(); err != nil {
		t.Fatal("repeat migration", err)
	}
	b, err := cli(t, "create-archive").Output()
	if err != nil {
		t.Fatal(err)
	}
	var ids map[string]string
	if err = json.Unmarshal(b, &ids); err != nil {
		t.Fatal(err)
	}
	private, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	tmpl := &x509.Certificate{SerialNumber: big.NewInt(2), NotBefore: time.Now().Add(-time.Minute), NotAfter: time.Now().Add(time.Hour), IPAddresses: []net.IP{net.ParseIP("127.0.0.1")}, KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &private.PublicKey, private)
	if err != nil {
		t.Fatal(err)
	}
	keyDER, err := x509.MarshalPKCS8PrivateKey(private)
	if err != nil {
		t.Fatal(err)
	}
	tlsDir := t.TempDir()
	certPath, keyPath := filepath.Join(tlsDir, "cert.pem"), filepath.Join(tlsDir, "key.pem")
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	if err = os.WriteFile(certPath, certPEM, 0600); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(keyPath, pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyDER}), 0600); err != nil {
		t.Fatal(err)
	}
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := l.Addr().String()
	l.Close()
	origin := "https://" + addr
	server := cli(t, "serve", "--listen", addr, "--data-root", root, "--cert", certPath, "--key", keyPath)
	var stderr bytes.Buffer
	server.Stderr = &stderr
	if err = server.Start(); err != nil {
		t.Fatal(err)
	}
	waited := false
	defer func() {
		if !waited {
			_ = server.Process.Kill()
			_ = server.Wait()
		}
	}()
	roots := x509.NewCertPool()
	roots.AppendCertsFromPEM(certPEM)
	transport := &http.Transport{TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS12, RootCAs: roots}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: 2 * time.Second}
	ready := false
	for range 100 {
		res, e := client.Get(origin + "/healthz")
		if e == nil {
			body, _ := io.ReadAll(res.Body)
			res.Body.Close()
			if e = contract.CheckResponse("GET", "/healthz", res.StatusCode, res.Header, body); e != nil {
				t.Fatal(e)
			}
			ready = true
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	if !ready {
		t.Fatal("TLS serve did not become ready")
	}
	t.Run("canonical_invitation_origin_and_TTL", func(t *testing.T) {
		admin, err := pgx.Connect(context.Background(), os.Getenv("MEMOTRACE_TEST_ADMIN_DSN"))
		if err != nil {
			t.Fatal(err)
		}
		defer admin.Close(context.Background())
		count := func() int {
			t.Helper()
			var n int
			if err := admin.QueryRow(context.Background(), "SELECT count(*) FROM mt.invitations WHERE archive_id=$1", ids["archive_id"]).Scan(&n); err != nil {
				t.Fatal(err)
			}
			return n
		}
		issueArgs := func(url, ttl string) []string {
			return []string{"invite", "--archive", ids["archive_id"], "--server-url", url, "--cert", certPath, "--expected-pin", protocol.Hash(der), "--ttl", ttl}
		}
		host, port, err := net.SplitHostPort(addr)
		if err != nil {
			t.Fatal(err)
		}
		longPort := "https://" + net.JoinHostPort(host, strings.Repeat("0", 6-len(port))+port)
		for _, tc := range []struct{ url, ttl string }{
			{strings.Replace(origin, "https://", "HTTPS://", 1), "10m"}, {strings.Replace(origin, "https://", "Https://", 1), "10m"}, {longPort, "10m"},
			{"https://" + net.JoinHostPort(host, "65536"), "10m"}, {"https://" + net.JoinHostPort(host, "00000"), "10m"},
			{origin, "500ms"}, {origin, "1500ms"}, {origin, "1.5s"}, {origin, "0s"}, {origin, "-1s"}, {origin, "601s"}, {origin, "600.5s"},
		} {
			before := count()
			out, err := cli(t, issueArgs(tc.url, tc.ttl)...).Output()
			if err == nil || len(out) != 0 {
				t.Fatal("invalid origin/TTL issued an invitation")
			}
			if count() != before {
				t.Fatal("invalid origin/TTL inserted an invitation")
			}
		}
		// Read stdout immediately, before the race runtime's subprocess-exit delay:
		// a 1s invitation may legitimately expire later in delivery or use.
		short := cli(t, issueArgs(origin, "1s")...)
		stdout, err := short.StdoutPipe()
		if err != nil {
			t.Fatal(err)
		}
		before := time.Now()
		if err = short.Start(); err != nil {
			t.Fatal(err)
		}
		waited := false
		defer func() {
			if !waited {
				_ = short.Process.Kill()
				_ = short.Wait()
			}
		}()
		out, err := bufio.NewReader(stdout).ReadBytes('\n')
		received := time.Now()
		if err != nil {
			t.Fatal("short invitation output", err)
		}
		if err = contract.Validate("Invitation", out); err != nil {
			t.Fatal("short CLI invitation differs from canonical schema", err)
		}
		var invitation protocol.Invitation
		if err = json.Unmarshal(out, &invitation); err != nil {
			t.Fatal(err)
		}
		expires, err := time.Parse(time.RFC3339Nano, invitation.ExpiresAt)
		if err != nil {
			t.Fatal(err)
		}
		if !expires.After(received) || expires.Before(before.Add(time.Second-time.Microsecond)) || expires.After(received.Add(time.Second)) {
			t.Fatal("short whole-second TTL is expired or truncated")
		}
		var stored time.Time
		if err = admin.QueryRow(context.Background(), "SELECT expires_at FROM mt.invitations WHERE token_hash=$1", protocol.Hash([]byte(invitation.InvitationToken))).Scan(&stored); err != nil {
			t.Fatal(err)
		}
		if !stored.Equal(expires) || stored.UTC().Format(time.RFC3339Nano) != invitation.ExpiresAt || expires.Nanosecond()%1000 != 0 {
			t.Fatal("CLI expiry differs from exact persisted microsecond expiry")
		}
		if invitation.ServerURL != origin || invitation.ArchiveID != ids["archive_id"] || invitation.TLSCertificateSHA256 != protocol.Hash(der) {
			t.Fatal("CLI invitation identity/bootstrap fields differ")
		}
		err = short.Wait()
		waited = true
		if err != nil {
			t.Fatal(err)
		}
	})
	for _, args := range [][]string{{"invite", "--archive", ids["archive_id"], "--server-url", origin, "--cert", certPath, "--expected-pin", protocol.Hash(der), "--ttl", "11m"}, {"invite", "--archive", ids["archive_id"], "--server-url", origin, "--cert", certPath, "--expected-pin", "wrong"}} {
		if cli(t, args...).Run() == nil {
			t.Fatal("invalid invitation trust/TTL accepted")
		}
	}
	b, err = cli(t, "invite", "--archive", ids["archive_id"], "--server-url", origin, "--cert", certPath, "--expected-pin", protocol.Hash(der)).Output()
	if err != nil {
		t.Fatal("invite", err)
	}
	if err = contract.Validate("Invitation", b); err != nil {
		t.Fatal("actual CLI invitation violates canonical schema", err)
	}
	var invitation protocol.Invitation
	_ = json.Unmarshal(b, &invitation)
	do := func(method, path, token, media string, body []byte, status int) []byte {
		t.Helper()
		req, e := http.NewRequest(method, origin+path, bytes.NewReader(body))
		if e != nil {
			t.Fatal(e)
		}
		if token != "" {
			req.Header.Set("Authorization", "Bearer "+token)
		}
		if media != "" {
			req.Header.Set("Content-Type", media)
		}
		res, e := client.Do(req)
		if e != nil {
			t.Fatal(e)
		}
		defer res.Body.Close()
		out, e := io.ReadAll(res.Body)
		if e != nil {
			t.Fatal(e)
		}
		if res.StatusCode != status {
			t.Fatal(method, path, res.StatusCode, string(out))
		}
		if e = contract.CheckResponse(method, path, status, res.Header, out); e != nil {
			t.Fatal(e)
		}
		return out
	}
	pairBody, _ := json.Marshal(protocol.PairRequest{InvitationToken: invitation.InvitationToken, DeviceName: "synthetic CLI camera"})
	var p protocol.PairResponse
	_ = json.Unmarshal(do("POST", "/v1/pairing/redeem", "", "application/json", pairBody, 201), &p)
	var imageBytes bytes.Buffer
	_ = jpeg.Encode(&imageBytes, image.NewRGBA(image.Rect(0, 0, 3, 2)), nil)
	wall := int64(1)
	m := protocol.Metadata{FrameID: protocol.NewID(), RequestWallMS: &wall, SHA256: protocol.Hash(imageBytes.Bytes()), ByteLength: int64(imageBytes.Len())}
	manifest, _ := json.Marshal(protocol.ManifestRequest{Frames: []protocol.Metadata{m}})
	path := "/v1/archives/" + p.ArchiveID + "/frames"
	do("POST", path, p.DeviceToken, "application/json", manifest, 200)
	path += "/" + m.FrameID + "/original"
	do("PUT", path, p.DeviceToken, "image/jpeg", imageBytes.Bytes(), 200)
	if !bytes.Equal(do("GET", path, p.DeviceToken, "", nil, 200), imageBytes.Bytes()) {
		t.Fatal("TLS exact bytes changed")
	}
	if err = cli(t, "revoke-device", "--device", p.DeviceID).Run(); err != nil {
		t.Fatal(err)
	}
	do("GET", path, p.DeviceToken, "", nil, 401)
	if err = server.Process.Signal(syscall.SIGTERM); err != nil {
		t.Fatal(err)
	}
	err = server.Wait()
	waited = true
	if err != nil {
		t.Fatal("graceful shutdown", err, stderr.String())
	}
	if stderr.Len() != 0 {
		t.Fatal("unexpected lifecycle logging", stderr.String())
	}
	files, err := archive.Open(root)
	if err != nil {
		t.Fatal("shutdown lock leak", err)
	}
	files.Close()
}

func TestInvitationTTLValidatedBeforeDatabaseAccess(t *testing.T) {
	t.Setenv("MEMOTRACE_ADMIN_DSN", "not-a-database-dsn")
	for _, ttl := range []string{"500ms", "1500ms", "0s", "-1s", "601s"} {
		err := run([]string{"invite", "--archive", protocol.NewID(), "--ttl", ttl})
		if err == nil || err.Error() != "invalid invitation arguments" {
			t.Fatal("invalid TTL reached bootstrap/database", ttl, err)
		}
	}
}

func TestInvitationExpiryPreservesSubsecondTimeAtMicrosecondPrecision(t *testing.T) {
	now := time.Date(2026, 9, 9, 12, 34, 56, 350123456, time.FixedZone("synthetic", 2*60*60))
	for _, tc := range []struct {
		ttl  time.Duration
		want string
	}{{time.Second, "2026-09-09T10:34:57.350123Z"}, {600 * time.Second, "2026-09-09T10:44:56.350123Z"}} {
		if got := invitationExpiry(now, tc.ttl).Format(time.RFC3339Nano); got != tc.want {
			t.Fatal("TTL subsecond/UTC boundary changed", got, tc.want)
		}
	}
}
