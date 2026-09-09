// SPDX-License-Identifier: AGPL-3.0-only
package main

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5"
	"memotrace/server/internal/archive"
	"memotrace/server/internal/bootstrap"
	"memotrace/server/internal/httpapi"
	"memotrace/server/internal/postgres"
	"memotrace/server/internal/protocol"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "memotrace: command failed; check configuration and documented prerequisites")
		os.Exit(1)
	}
}
func run(args []string) error {
	if len(args) == 0 {
		return errors.New("command required")
	}
	f := flag.NewFlagSet(args[0], flag.ContinueOnError)
	role := f.String("runtime-role", "memotrace_runtime", "nonprivileged pre-created PostgreSQL role")
	archiveID := f.String("archive", "", "archive UUID")
	deviceID := f.String("device", "", "device UUID")
	origin := f.String("server-url", "https://localhost:8443", "HTTPS origin")
	cert := f.String("cert", "", "PEM TLS certificate path")
	key := f.String("key", "", "PEM TLS private key path")
	pin := f.String("expected-pin", "", "trusted out-of-band SHA256 DER leaf pin (required for invite)")
	ttl := f.Duration("ttl", 10*time.Minute, "invitation lifetime, whole seconds 1..600")
	listen := f.String("listen", "127.0.0.1:8443", "TLS bind address")
	root := f.String("data-root", "", "existing absolute private data-root directory")
	if err := f.Parse(args[1:]); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return nil
		}
		return err
	}
	if f.NArg() != 0 {
		return errors.New("unexpected arguments")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	adminDSN := os.Getenv("MEMOTRACE_ADMIN_DSN")
	output := func(v any) error { return json.NewEncoder(os.Stdout).Encode(v) }
	switch args[0] {
	case "migrate":
		if adminDSN == "" {
			return errors.New("admin DSN required")
		}
		return postgres.Migrate(ctx, adminDSN, *role)
	case "serve":
		return serve(os.Getenv("MEMOTRACE_DSN"), *root, *listen, *cert, *key)
	case "create-archive", "invite", "revoke-device":
		if adminDSN == "" {
			return errors.New("admin DSN required")
		}
	default:
		return errors.New("unknown command")
	}
	var fingerprint string
	if args[0] == "invite" {
		if !protocol.UUID(*archiveID) || *ttl < time.Second || *ttl > 10*time.Minute || *ttl%time.Second != 0 {
			return errors.New("invalid invitation arguments")
		}
		var err error
		fingerprint, err = bootstrap.Verify(ctx, *origin, *cert, *pin)
		if err != nil {
			return err
		}
	}
	c, err := pgx.Connect(ctx, adminDSN)
	if err != nil {
		return err
	}
	defer c.Close(ctx)
	tx, err := c.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if _, err = tx.Exec(ctx, "SET LOCAL synchronous_commit=on"); err != nil {
		return err
	}
	switch args[0] {
	case "create-archive":
		o, a := protocol.NewID(), protocol.NewID()
		if _, err = tx.Exec(ctx, "INSERT INTO mt.owners(id) VALUES($1)", o); err != nil {
			return err
		}
		if _, err = tx.Exec(ctx, "INSERT INTO mt.archives(id,owner_id) VALUES($1,$2)", a, o); err != nil {
			return err
		}
		if err = tx.Commit(ctx); err != nil {
			return err
		}
		return output(map[string]string{"owner_id": o, "archive_id": a})
	case "invite":
		token := protocol.NewToken()
		expires := invitationExpiry(time.Now(), *ttl)
		if _, err = tx.Exec(ctx, "INSERT INTO mt.invitations(token_hash,archive_id,expires_at) VALUES($1,$2,$3)", protocol.Hash([]byte(token)), *archiveID, expires); err != nil {
			return err
		}
		if !expires.After(time.Now()) {
			return errors.New("invitation expired before commit")
		}
		if err = tx.Commit(ctx); err != nil {
			return err
		}
		if !expires.After(time.Now()) {
			return errors.New("invitation expired before output")
		}
		return output(protocol.Invitation{ContractVersion: protocol.Version, ServerURL: *origin, TLSCertificateSHA256: fingerprint, InvitationToken: token, ExpiresAt: expires.Format(time.RFC3339Nano), ArchiveID: *archiveID})
	case "revoke-device":
		if !protocol.UUID(*deviceID) {
			return errors.New("invalid device UUID")
		}
		r, err := tx.Exec(ctx, "UPDATE mt.devices SET revoked=true WHERE id=$1", *deviceID)
		if err != nil {
			return err
		}
		if r.RowsAffected() != 1 {
			return errors.New("unknown device")
		}
		return tx.Commit(ctx)
	}
	return errors.New("unknown command")
}

func invitationExpiry(now time.Time, ttl time.Duration) time.Time {
	return now.UTC().Truncate(time.Microsecond).Add(ttl)
}

func serve(dsn, root, listen, cert, key string) error {
	if dsn == "" || cert == "" || key == "" {
		return errors.New("runtime DSN and TLS keypair required")
	}
	keyInfo, err := os.Stat(key)
	if err != nil {
		return err
	}
	if !keyInfo.Mode().IsRegular() || keyInfo.Mode().Perm()&0077 != 0 {
		return errors.New("private key permissions")
	}
	pair, err := tls.LoadX509KeyPair(cert, key)
	if err != nil {
		return err
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	files, err := archive.Open(root)
	if err != nil {
		return err
	}
	defer files.Close()
	startup, cancel := context.WithTimeout(ctx, 10*time.Minute)
	defer cancel()
	db, err := postgres.Open(startup, dsn)
	if err != nil {
		return err
	}
	defer db.Close()
	if err = db.Recover(startup, files.Recover); err != nil {
		return err
	}
	unknown, stages, err := files.Audit(func(a, f string) (bool, error) { return db.Known(startup, a, f) })
	if err != nil {
		return err
	}
	if unknown > 0 || stages > 0 {
		fmt.Fprintf(os.Stderr, "memotrace: preserved unrecognized entries=%d, incomplete staging entries=%d; operator inspection required\n", unknown, stages)
	}
	api := httpapi.New(db, files)
	srv := &http.Server{Addr: listen, Handler: api, TLSConfig: &tls.Config{MinVersion: tls.VersionTLS12, Certificates: []tls.Certificate{pair}}, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 90 * time.Second, WriteTimeout: 100 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 8192, ErrorLog: log.New(io.Discard, "", 0)}
	finished := make(chan error, 1)
	listener, err := net.Listen("tcp", listen)
	if err != nil {
		return err
	}
	go func() { finished <- srv.ServeTLS(httpapi.LimitConnections(listener, 32), "", "") }()
	select {
	case err = <-finished:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	case <-ctx.Done():
		shutdown, cancel := context.WithTimeout(context.Background(), 105*time.Second)
		defer cancel()
		if err = srv.Shutdown(shutdown); err != nil {
			_ = srv.Close()
			return err
		}
		err = <-finished
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	}
}
