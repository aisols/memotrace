// SPDX-License-Identifier: AGPL-3.0-only
package bootstrap

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/pem"
	"errors"
	"net"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"memotrace/server/internal/protocol"
)

func parseOrigin(origin string) (*url.URL, error) {
	if !strings.HasPrefix(origin, "https://") {
		return nil, errors.New("invalid HTTPS origin")
	}
	u, err := url.Parse(origin)
	if err != nil || u.Scheme != "https" || u.Host == "" || u.User != nil || u.RawQuery != "" || u.ForceQuery || u.Fragment != "" || u.RawFragment != "" || u.Path != "" || u.RawPath != "" {
		return nil, errors.New("invalid HTTPS origin")
	}
	if u.Hostname() == "" || strings.Contains(origin, "#") || strings.HasSuffix(u.Host, ":") {
		return nil, errors.New("invalid HTTPS origin")
	}
	host := u.Hostname()
	if net.ParseIP(host) == nil {
		if len(host) > 253 {
			return nil, errors.New("invalid HTTPS host")
		}
		for _, label := range strings.Split(host, ".") {
			if len(label) < 1 || len(label) > 63 || label[0] == '-' || label[len(label)-1] == '-' {
				return nil, errors.New("invalid HTTPS host")
			}
			for _, r := range label {
				if !(r >= 'A' && r <= 'Z' || r >= 'a' && r <= 'z' || r >= '0' && r <= '9' || r == '-') {
					return nil, errors.New("invalid HTTPS host")
				}
			}
		}
	}
	if port := u.Port(); port != "" {
		n, e := strconv.Atoi(port)
		if len(port) > 5 || e != nil || n < 1 || n > 65535 {
			return nil, errors.New("invalid HTTPS port")
		}
	}
	return u, nil
}

// Verify establishes trust from the explicitly out-of-band expected leaf pin.
// The certificate file supplies that trust anchor; ordinary x509 name/time/chain
// validation stays enabled for the live TLS connection.
func Verify(ctx context.Context, origin, certFile, expectedPin string) (string, error) {
	u, err := parseOrigin(origin)
	if err != nil {
		return "", err
	}
	b, err := os.ReadFile(certFile)
	if err != nil {
		return "", err
	}
	block, _ := pem.Decode(b)
	if block == nil || block.Type != "CERTIFICATE" {
		return "", errors.New("certificate required")
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return "", err
	}
	pin := protocol.Hash(cert.Raw)
	if expectedPin == "" || expectedPin != pin {
		return "", errors.New("out-of-band certificate pin mismatch")
	}
	if err = cert.VerifyHostname(u.Hostname()); err != nil {
		return "", err
	}
	roots := x509.NewCertPool()
	roots.AddCert(cert)
	if _, err = cert.Verify(x509.VerifyOptions{Roots: roots, DNSName: u.Hostname(), CurrentTime: time.Now()}); err != nil {
		return "", err
	}
	port := u.Port()
	if port == "" {
		port = "443"
	}
	d := tls.Dialer{NetDialer: &net.Dialer{Timeout: 5 * time.Second}, Config: &tls.Config{MinVersion: tls.VersionTLS12, RootCAs: roots, ServerName: u.Hostname(), VerifyConnection: func(cs tls.ConnectionState) error {
		if len(cs.PeerCertificates) == 0 || protocol.Hash(cs.PeerCertificates[0].Raw) != expectedPin {
			return errors.New("certificate pin mismatch")
		}
		return nil
	}}}
	c, err := d.DialContext(ctx, "tcp", net.JoinHostPort(u.Hostname(), port))
	if err != nil {
		return "", err
	}
	c.Close()
	return pin, nil
}
