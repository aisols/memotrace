// SPDX-License-Identifier: AGPL-3.0-only
package postgres

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"memotrace/server/internal/protocol"
)

//go:embed migration.sql
var migration string

type Store struct{ Pool *pgxpool.Pool }
type Scope struct{ OwnerID, ArchiveID, DeviceID string }
type Frame struct {
	Metadata            protocol.Metadata
	CommittedAt         *time.Time
	RegisteringDeviceID string
}

func Open(ctx context.Context, dsn string) (*Store, error) {
	c, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return nil, err
	}
	c.MaxConns = 12
	c.MinConns = 0
	c.ConnConfig.ConnectTimeout = 5 * time.Second
	c.ConnConfig.RuntimeParams["statement_timeout"] = "15000"
	c.ConnConfig.RuntimeParams["lock_timeout"] = "10000"
	c.ConnConfig.RuntimeParams["idle_in_transaction_session_timeout"] = "30000"
	c.ConnConfig.RuntimeParams["synchronous_commit"] = "on"
	p, err := pgxpool.NewWithConfig(ctx, c)
	if err != nil {
		return nil, err
	}
	s := &Store{Pool: p}
	if err := s.Validate(ctx); err != nil {
		p.Close()
		return nil, err
	}
	return s, nil
}
func (s *Store) Close() { s.Pool.Close() }
func (s *Store) Validate(ctx context.Context) error {
	var unsafe bool
	err := s.Pool.QueryRow(ctx, `SELECT EXISTS (
 SELECT 1 FROM pg_roles r WHERE pg_has_role(current_user,r.oid,'MEMBER') AND
 (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR
 r.rolname IN ('pg_read_all_data','pg_write_all_data','pg_read_server_files','pg_write_server_files','pg_execute_server_program','pg_signal_backend') OR EXISTS
 (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='mt' AND c.relowner=r.oid)
 OR EXISTS (SELECT 1 FROM pg_namespace n WHERE n.nspname='mt' AND n.nspowner=r.oid)))`).Scan(&unsafe)
	if err != nil {
		return err
	}
	if unsafe {
		return errors.New("unsafe runtime database role")
	}
	var protected int
	if err := s.Pool.QueryRow(ctx, `SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='mt' AND c.relname IN ('owners','archives','frames','jobs') AND c.relrowsecurity`).Scan(&protected); err != nil {
		return err
	}
	if protected != 4 {
		return errors.New("required content RLS is missing")
	}
	for _, table := range []string{"devices", "invitations"} {
		var exposed bool
		if err := s.Pool.QueryRow(ctx, `SELECT has_table_privilege(current_user,$1,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')`, "mt."+table).Scan(&exposed); err != nil {
			return err
		}
		if exposed {
			return errors.New("runtime has direct bootstrap table privileges")
		}
	}
	var version int
	if err := s.Pool.QueryRow(ctx, "SELECT version FROM mt.schema_version").Scan(&version); err != nil {
		return err
	}
	if version != 1 {
		return errors.New("unsupported database version")
	}
	for _, setting := range []string{"fsync", "full_page_writes", "synchronous_commit"} {
		var value string
		if err := s.Pool.QueryRow(ctx, "SHOW "+setting).Scan(&value); err != nil {
			return err
		}
		if value != "on" {
			return errors.New("unsafe database durability setting")
		}
	}
	return nil
}

func Migrate(ctx context.Context, dsn, runtimeRole string) error {
	if runtimeRole == "" {
		return errors.New("runtime role required")
	}
	c, err := pgx.Connect(ctx, dsn)
	if err != nil {
		return err
	}
	defer c.Close(ctx)
	tx, err := c.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if _, err = tx.Exec(ctx, "SELECT pg_advisory_xact_lock(630282933)"); err != nil {
		return err
	}
	var safe bool
	if err = tx.QueryRow(ctx, `SELECT NOT (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolname=current_user OR pg_has_role(oid,(SELECT oid FROM pg_roles WHERE rolname=current_user),'MEMBER')) FROM pg_roles WHERE rolname=$1`, runtimeRole).Scan(&safe); err != nil {
		return err
	}
	if !safe {
		return errors.New("unsafe runtime role")
	}
	var exists bool
	if err = tx.QueryRow(ctx, "SELECT to_regnamespace('mt') IS NOT NULL").Scan(&exists); err != nil {
		return err
	}
	if !exists {
		if _, err = tx.Exec(ctx, migration); err != nil {
			return err
		}
	} else {
		var v int
		if err = tx.QueryRow(ctx, "SELECT version FROM mt.schema_version").Scan(&v); err != nil {
			return err
		}
		if v != 1 {
			return errors.New("unsupported database version")
		}
	}
	r := pgx.Identifier{runtimeRole}.Sanitize()
	for _, q := range []string{
		"GRANT USAGE ON SCHEMA mt TO " + r,
		"GRANT SELECT ON mt.schema_version,mt.owners,mt.archives,mt.frames,mt.jobs TO " + r,
		"GRANT INSERT ON mt.frames,mt.jobs TO " + r,
		"GRANT UPDATE(committed_at) ON mt.frames TO " + r,
		"GRANT EXECUTE ON FUNCTION mt.authenticate(text),mt.redeem(text,uuid,text,text),mt.recovery_owners(),mt.recovery_archive_owner(uuid) TO " + r,
	} {
		if _, err = tx.Exec(ctx, q); err != nil {
			return err
		}
	}
	return tx.Commit(ctx)
}

func (s *Store) Begin(ctx context.Context, token, archive string) (pgx.Tx, Scope, error) {
	tx, err := s.Pool.Begin(ctx)
	if err != nil {
		return nil, Scope{}, err
	}
	var sc Scope
	err = tx.QueryRow(ctx, "SELECT owner_id::text,archive_id::text,device_id::text FROM mt.authenticate($1)", protocol.Hash([]byte(token))).Scan(&sc.OwnerID, &sc.ArchiveID, &sc.DeviceID)
	if errors.Is(err, pgx.ErrNoRows) {
		err = protocol.E("unauthorized")
	}
	if err == nil && archive != sc.ArchiveID {
		err = protocol.E("not_found")
	}
	if err == nil {
		_, err = tx.Exec(ctx, "SELECT set_config('mt.owner_id',$1,true)", sc.OwnerID)
	}
	if err != nil {
		tx.Rollback(ctx)
		return nil, Scope{}, err
	}
	return tx, sc, nil
}
func (s *Store) Pair(ctx context.Context, p protocol.PairRequest) (protocol.PairResponse, error) {
	r := protocol.PairResponse{ContractVersion: protocol.Version, DeviceID: protocol.NewID(), DeviceToken: protocol.NewToken()}
	tx, err := s.Pool.Begin(ctx)
	if err != nil {
		return r, err
	}
	defer tx.Rollback(ctx)
	err = tx.QueryRow(ctx, "SELECT owner_id::text,archive_id::text FROM mt.redeem($1,$2,$3,$4)", protocol.Hash([]byte(p.InvitationToken)), r.DeviceID, protocol.Hash([]byte(r.DeviceToken)), p.DeviceName).Scan(&r.OwnerID, &r.ArchiveID)
	if errors.Is(err, pgx.ErrNoRows) {
		return r, protocol.E("unauthorized")
	}
	if err != nil {
		return r, err
	}
	return r, tx.Commit(ctx)
}
func Get(ctx context.Context, tx pgx.Tx, archive, id string) (Frame, error) {
	var f Frame
	var b []byte
	err := tx.QueryRow(ctx, "SELECT metadata,committed_at,registering_device_id::text FROM mt.frames WHERE archive_id=$1 AND id=$2 FOR UPDATE", archive, id).Scan(&b, &f.CommittedAt, &f.RegisteringDeviceID)
	if errors.Is(err, pgx.ErrNoRows) {
		return f, protocol.E("not_found")
	}
	if err != nil {
		return f, err
	}
	err = json.Unmarshal(b, &f.Metadata)
	return f, err
}
func Receipt(archive string, f Frame) *protocol.Receipt {
	if f.CommittedAt == nil {
		return nil
	}
	return &protocol.Receipt{ContractVersion: protocol.Version, ArchiveID: archive, FrameID: f.Metadata.FrameID, SHA256: f.Metadata.SHA256, ByteLength: f.Metadata.ByteLength, CommittedAt: f.CommittedAt.UTC().Format(time.RFC3339Nano), Integrity: "sha256-byte-length-jpeg-header", State: "archive_committed"}
}
func (s *Store) Register(ctx context.Context, token, archive string, m protocol.ManifestRequest) (protocol.ManifestResponse, error) {
	out := protocol.ManifestResponse{ContractVersion: protocol.Version, Frames: make([]protocol.FrameState, 0, len(m.Frames))}
	tx, sc, err := s.Begin(ctx, token, archive)
	if err != nil {
		return out, err
	}
	defer tx.Rollback(ctx)
	// Global key order avoids deadlocks between overlapping batches. ON CONFLICT
	// handles registrations racing before the row exists; comparisons follow locks.
	frames := append([]protocol.Metadata(nil), m.Frames...)
	sort.Slice(frames, func(i, j int) bool { return frames[i].FrameID < frames[j].FrameID })
	states := map[string]protocol.FrameState{}
	for _, f := range frames {
		b, _ := json.Marshal(f)
		_, err = tx.Exec(ctx, `INSERT INTO mt.frames(archive_id,id,owner_id,registering_device_id,metadata) VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING`, archive, f.FrameID, sc.OwnerID, sc.DeviceID, b)
		if err != nil {
			return out, err
		}
		stored, err := Get(ctx, tx, archive, f.FrameID)
		if err != nil {
			return out, err
		}
		old, _ := json.Marshal(stored.Metadata)
		if string(old) != string(b) {
			return out, protocol.E("conflict")
		}
		state := "pending"
		receipt := Receipt(archive, stored)
		if receipt != nil {
			state = "committed"
		}
		states[f.FrameID] = protocol.FrameState{FrameID: f.FrameID, State: state, Receipt: receipt}
	}
	for _, f := range m.Frames {
		out.Frames = append(out.Frames, states[f.FrameID])
	}
	return out, tx.Commit(ctx)
}
func Complete(ctx context.Context, tx pgx.Tx, sc Scope, f Frame) (Frame, error) {
	if f.CommittedAt != nil {
		return f, nil
	}
	err := tx.QueryRow(ctx, "UPDATE mt.frames SET committed_at=clock_timestamp() WHERE archive_id=$1 AND id=$2 RETURNING committed_at", sc.ArchiveID, f.Metadata.FrameID).Scan(&f.CommittedAt)
	if err != nil {
		return f, err
	}
	_, err = tx.Exec(ctx, "INSERT INTO mt.jobs(archive_id,frame_id,owner_id) VALUES($1,$2,$3) ON CONFLICT DO NOTHING", sc.ArchiveID, f.Metadata.FrameID, sc.OwnerID)
	return f, err
}

// Recover iterates in bounded pages while the caller holds the exclusive data-root
// lock. A bad known original blocks startup and remains preserved for diagnosis.
func (s *Store) Recover(ctx context.Context, publish func(string, protocol.Metadata) (bool, error)) error {
	rows, err := s.Pool.Query(ctx, "SELECT mt.recovery_owners()::text")
	if err != nil {
		return err
	}
	var owners []string
	for rows.Next() {
		var o string
		if err = rows.Scan(&o); err != nil {
			rows.Close()
			return err
		}
		owners = append(owners, o)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	for _, owner := range owners {
		cursorA, cursorF := "00000000-0000-0000-0000-000000000000", "00000000-0000-0000-0000-000000000000"
		first := true
		for {
			tx, err := s.Pool.Begin(ctx)
			if err != nil {
				return err
			}
			_, err = tx.Exec(ctx, "SELECT set_config('mt.owner_id',$1,true)", owner)
			if err != nil {
				tx.Rollback(ctx)
				return err
			}
			r, err := tx.Query(ctx, `SELECT archive_id::text,id::text FROM mt.frames WHERE committed_at IS NULL AND ($3 OR (archive_id,id)>($1::uuid,$2::uuid)) ORDER BY archive_id,id LIMIT 100`, cursorA, cursorF, first)
			if err != nil {
				tx.Rollback(ctx)
				return err
			}
			var ids [][2]string
			for r.Next() {
				var id [2]string
				err = r.Scan(&id[0], &id[1])
				if err != nil {
					break
				}
				ids = append(ids, id)
			}
			if err == nil {
				err = r.Err()
			}
			r.Close()
			if err != nil {
				tx.Rollback(ctx)
				return err
			}
			for _, id := range ids {
				f, e := Get(ctx, tx, id[0], id[1])
				if e != nil {
					err = e
					break
				}
				ok, e := publish(id[0], f.Metadata)
				if e != nil {
					err = e
					break
				}
				if ok {
					_, err = Complete(ctx, tx, Scope{OwnerID: owner, ArchiveID: id[0]}, f)
					if err != nil {
						break
					}
				}
				cursorA, cursorF = id[0], id[1]
			}
			if err != nil {
				tx.Rollback(ctx)
				return fmt.Errorf("recovery requires operator attention: %w", err)
			}
			if err = tx.Commit(ctx); err != nil {
				return err
			}
			first = false
			if len(ids) < 100 {
				break
			}
		}
	}
	return nil
}
