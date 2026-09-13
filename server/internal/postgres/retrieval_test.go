// SPDX-License-Identifier: AGPL-3.0-only
package postgres

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"image"
	"image/jpeg"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"memotrace/server/internal/archive"
	"memotrace/server/internal/protocol"
	"memotrace/server/internal/retrieval"
)

func database(t *testing.T) (*Store, *pgx.Conn) {
	t.Helper()
	adminDSN, dsn := os.Getenv("MEMOTRACE_TEST_ADMIN_DSN"), os.Getenv("MEMOTRACE_TEST_DSN")
	if adminDSN == "" || dsn == "" {
		if os.Getenv("MEMOTRACE_REQUIRE_POSTGRES") == "1" {
			t.Fatal("required disposable PostgreSQL missing")
		}
		t.Skip("run bash scripts/verify.sh for disposable PostgreSQL")
	}
	ctx := context.Background()
	if e := Migrate(ctx, adminDSN, "memotrace_runtime"); e != nil {
		t.Fatal(e)
	}
	s, e := Open(ctx, dsn)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(s.Close)
	c, e := pgx.Connect(ctx, adminDSN)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { c.Close(ctx) })
	return s, c
}
func execSQL(t *testing.T, c *pgx.Conn, q string, args ...any) {
	t.Helper()
	if _, e := c.Exec(context.Background(), q, args...); e != nil {
		t.Fatal(e)
	}
}
func ownerAccess(t *testing.T, c *pgx.Conn) (Access, string) {
	t.Helper()
	o, a := protocol.NewID(), protocol.NewID()
	execSQL(t, c, "INSERT INTO mt.owners(id) VALUES($1)", o)
	execSQL(t, c, "INSERT INTO mt.archives(id,owner_id) VALUES($1,$2)", a, o)
	return Access{ArchiveID: a, Operator: true}, o
}
func syntheticDescription() retrieval.Description {
	return retrieval.Description{ModelFingerprint: strings.Repeat("a", 64), Dimension: 2, ModelID: "synthetic-test-only", ModelRevision: "1", InputResolution: 224, PreprocessingVersion: "1", Policies: map[string]string{"full": strings.Repeat("b", 64), "overlap": strings.Repeat("c", 64)}}
}
func syntheticResult(d retrieval.Description) retrieval.ImageResult {
	return retrieval.ImageResult{ModelFingerprint: d.ModelFingerprint, PolicyFingerprint: d.Policies["full"], Width: 4, Height: 3, Vectors: []retrieval.Vector{{Kind: "full", Box: retrieval.Box{0, 0, 1, 1}, Embedding: []float32{1, 0}}}}
}
func addDataset(t *testing.T, c *pgx.Conn, a Access, owner string) string {
	t.Helper()
	id := protocol.NewID()
	execSQL(t, c, `INSERT INTO mt.assets(archive_id,id,owner_id,source_kind,dataset_name,dataset_version,item_id,sha256,byte_length,provenance) VALUES($1,$2,$3,'dataset','synthetic','1',$5,$4,10,'{}')`, a.ArchiveID, id, owner, protocol.Hash([]byte(id)), id)
	return id
}
func TestPersistentLeasesRetriesFencingAtomicResultsAndRLS(t *testing.T) {
	s, admin := database(t)
	ctx := context.Background()
	a, owner := ownerAccess(t, admin)
	id := addDataset(t, admin, a, owner)
	d := syntheticDescription()
	g, e := s.PrepareIndex(ctx, a, d, "full")
	if e != nil {
		t.Fatal(e)
	}
	if _, e = s.PrepareIndex(ctx, a, d, "full"); e != nil {
		t.Fatal(e)
	}
	claim, e := s.ClaimIndex(ctx, a, g)
	if e != nil || claim.Attempt != 1 || claim.Asset.Hit.AssetID != id {
		t.Fatal(claim, e)
	}
	var leaseSeconds float64
	if e = admin.QueryRow(ctx, `SELECT extract(epoch FROM (lease_until-clock_timestamp())) FROM mt.index_jobs WHERE archive_id=$1 AND generation_id=$2 AND asset_id=$3`, a.ArchiveID, g.ID, id).Scan(&leaseSeconds); e != nil || leaseSeconds < 590 || leaseSeconds > 600 {
		t.Fatal("claim did not grant the documented ten-minute lease", leaseSeconds, e)
	}
	if _, e = s.ClaimIndex(ctx, a, g); !errors.Is(e, ErrNoJob) {
		t.Fatal("duplicate lease", e)
	}
	// Equality is expired: replacement and completion both use the same strict
	// lease boundary, so a result cannot commit at lease_until.
	execSQL(t, admin, "UPDATE mt.index_jobs SET lease_until=clock_timestamp() WHERE archive_id=$1", a.ArchiveID)
	newClaim, e := s.ClaimIndex(ctx, a, g)
	if e != nil || newClaim.Attempt != 2 || newClaim.Token == claim.Token {
		t.Fatal(newClaim, e)
	}
	if e = s.CompleteIndex(ctx, a, claim, syntheticResult(d)); !errors.Is(e, ErrFence) {
		t.Fatal("stale result accepted", e)
	}
	if e = s.FailIndex(ctx, a, claim); !errors.Is(e, ErrFence) {
		t.Fatal("stale failure accepted", e)
	}
	malformed := syntheticResult(d)
	malformed.Vectors[0].Embedding = []float32{0, 0}
	if e = s.CompleteIndex(ctx, a, newClaim, malformed); e == nil {
		t.Fatal("malformed result accepted")
	}
	if e = s.FailIndex(ctx, a, newClaim); e != nil {
		t.Fatal(e)
	}
	third, e := s.ClaimIndex(ctx, a, g)
	if e != nil || third.Attempt != 3 {
		t.Fatal(third, e)
	}
	// A real deferred SQL failure proves vectors and completion share COMMIT.
	execSQL(t, admin, `CREATE FUNCTION mt.test_index_commit_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic commit fault'; END $$`)
	execSQL(t, admin, `CREATE CONSTRAINT TRIGGER test_index_commit_failure AFTER INSERT ON mt.regions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION mt.test_index_commit_failure()`)
	e = s.CompleteIndex(ctx, a, third, syntheticResult(d))
	execSQL(t, admin, "DROP TRIGGER test_index_commit_failure ON mt.regions")
	execSQL(t, admin, "DROP FUNCTION mt.test_index_commit_failure()")
	if e == nil {
		t.Fatal("commit fault not observed")
	}
	var n int
	var state string
	if e = admin.QueryRow(ctx, "SELECT count(*) FROM mt.regions WHERE archive_id=$1", a.ArchiveID).Scan(&n); e != nil || n != 0 {
		t.Fatal("partial vectors persisted", n, e)
	}
	if e = s.CompleteIndex(ctx, a, third, syntheticResult(d)); e != nil {
		t.Fatal(e)
	}
	if e = s.CompleteIndex(ctx, a, third, syntheticResult(d)); !errors.Is(e, ErrFence) {
		t.Fatal("completed claim reused", e)
	}
	if e = admin.QueryRow(ctx, "SELECT state FROM mt.index_jobs WHERE archive_id=$1", a.ArchiveID).Scan(&state); e != nil || state != "complete" {
		t.Fatal(state, e)
	}
	tx, _, e := s.BeginAccess(ctx, a, true)
	if e != nil {
		t.Fatal(e)
	}
	coverage, e := Coverage(ctx, tx, a.ArchiveID, g.ID)
	tx.Rollback(ctx)
	if e != nil || coverage.AssetsIndexed != 1 || coverage.RegionsIndexed != 1 {
		t.Fatal(coverage, e)
	}
	other, otherOwner := ownerAccess(t, admin)
	addDataset(t, admin, other, otherOwner)
	for _, table := range []string{"assets", "index_generations", "index_jobs", "regions"} {
		if e = s.Pool.QueryRow(ctx, "SELECT count(*) FROM mt."+table+" WHERE archive_id=$1", a.ArchiveID).Scan(&n); e != nil || n != 0 {
			t.Fatal("unscoped content leaked", table, n, e)
		}
		tx, _, e := s.BeginAccess(ctx, other, false)
		if e != nil {
			t.Fatal(e)
		}
		e = tx.QueryRow(ctx, "SELECT count(*) FROM mt."+table+" WHERE archive_id=$1", a.ArchiveID).Scan(&n)
		tx.Rollback(ctx)
		if e != nil || n != 0 {
			t.Fatal("cross-owner content leaked", table, n, e)
		}
	}
	tx, _, e = s.BeginAccess(ctx, other, false)
	if e != nil {
		t.Fatal(e)
	}
	_, e = tx.Exec(ctx, `INSERT INTO mt.assets(archive_id,id,owner_id,source_kind,dataset_name,dataset_version,item_id,sha256,byte_length,provenance) VALUES($1,$2,$3,'dataset','synthetic','1','forbidden',$4,10,'{}')`, a.ArchiveID, protocol.NewID(), owner, strings.Repeat("a", 64))
	tx.Rollback(ctx)
	if e == nil {
		t.Fatal("cross-owner insertion accepted")
	}
	// Expired final attempt is persisted as failed, not permanently stuck leased.
	badID := addDataset(t, admin, a, owner)
	if _, e = s.PrepareIndex(ctx, a, d, "full"); e != nil {
		t.Fatal(e)
	}
	execSQL(t, admin, "UPDATE mt.index_jobs SET state='leased',attempts=3,lease_token=$3,lease_until=clock_timestamp()-interval '1 second' WHERE archive_id=$1 AND asset_id=$2", a.ArchiveID, badID, protocol.NewID())
	if _, e = s.ClaimIndex(ctx, a, g); !errors.Is(e, ErrNoJob) {
		t.Fatal(e)
	}
	if e = admin.QueryRow(ctx, "SELECT state FROM mt.index_jobs WHERE archive_id=$1 AND asset_id=$2", a.ArchiveID, badID).Scan(&state); e != nil || state != "failed" {
		t.Fatal("exhausted lease not failed", state, e)
	}
}

func TestMigrationFromPopulatedV1PreservesOriginalAndOldWire(t *testing.T) {
	s, admin := database(t)
	s.Close()
	ctx := context.Background()
	// The full verifier serializes packages in its dedicated disposable database.
	// Preserve its existing schema while testing an actual committed v1 database.
	backup := "mt_saved_" + strings.ReplaceAll(protocol.NewID(), "-", "")
	execSQL(t, admin, "ALTER SCHEMA mt RENAME TO "+pgx.Identifier{backup}.Sanitize())
	t.Cleanup(func() {
		execSQL(t, admin, "DROP SCHEMA IF EXISTS mt CASCADE")
		execSQL(t, admin, "ALTER SCHEMA "+pgx.Identifier{backup}.Sanitize()+" RENAME TO mt")
	})
	execSQL(t, admin, migration)
	a, owner := ownerAccess(t, admin)
	device, id := protocol.NewID(), protocol.NewID()
	token := protocol.NewToken()
	execSQL(t, admin, "INSERT INTO mt.devices(id,owner_id,archive_id,token_hash,name) VALUES($1,$2,$3,$4,'synthetic')", device, owner, a.ArchiveID, protocol.Hash([]byte(token)))
	var encoded bytes.Buffer
	_ = jpeg.Encode(&encoded, image.NewRGBA(image.Rect(0, 0, 4, 3)), nil)
	b := encoded.Bytes()
	wall := int64(12345)
	m := protocol.Metadata{FrameID: id, RequestWallMS: &wall, SHA256: protocol.Hash(b), ByteLength: int64(len(b)), RequestElapsedMS: func() *int64 { x := int64(999); return &x }()}
	raw, _ := json.Marshal(m)
	execSQL(t, admin, "INSERT INTO mt.frames(archive_id,id,owner_id,registering_device_id,metadata,committed_at) VALUES($1,$2,$3,$4,$5,clock_timestamp())", a.ArchiveID, id, owner, device, raw)
	execSQL(t, admin, "INSERT INTO mt.jobs(archive_id,frame_id,owner_id) VALUES($1,$2,$3)", a.ArchiveID, id, owner)
	var oldRaw []byte
	var oldTime time.Time
	if e := admin.QueryRow(ctx, "SELECT metadata,committed_at FROM mt.frames WHERE archive_id=$1 AND id=$2", a.ArchiveID, id).Scan(&oldRaw, &oldTime); e != nil {
		t.Fatal(e)
	}
	root := t.TempDir()
	if e := os.Chmod(root, 0700); e != nil {
		t.Fatal(e)
	}
	f, e := archive.Open(root)
	if e != nil {
		t.Fatal(e)
	}
	defer f.Close()
	stage, e := f.Stage(bytes.NewReader(b), m)
	if e != nil {
		t.Fatal(e)
	}
	defer stage.Close()
	if e = f.Publish(stage, a.ArchiveID, m); e != nil {
		t.Fatal(e)
	}
	if e = Migrate(ctx, os.Getenv("MEMOTRACE_TEST_ADMIN_DSN"), "memotrace_runtime"); e != nil {
		t.Fatal(e)
	}
	db, e := Open(ctx, os.Getenv("MEMOTRACE_TEST_DSN"))
	if e != nil {
		t.Fatal(e)
	}
	defer db.Close()
	tx, _, e := db.Begin(ctx, token, a.ArchiveID)
	if e != nil {
		t.Fatal(e)
	}
	defer tx.Rollback(ctx)
	frame, e := Get(ctx, tx, a.ArchiveID, id)
	if e != nil {
		t.Fatal(e)
	}
	var assetID string
	if e = tx.QueryRow(ctx, "SELECT id::text FROM mt.assets WHERE archive_id=$1 AND frame_id=$2", a.ArchiveID, id).Scan(&assetID); e != nil {
		t.Fatal(e)
	}
	asset, e := AssetByID(ctx, tx, a.ArchiveID, assetID)
	if e != nil {
		t.Fatal(e)
	}
	if asset.Hit.ObservedAtMS == nil || *asset.Hit.ObservedAtMS != wall || asset.Hit.SequenceID != nil || asset.Hit.SequencePositionMS != nil {
		t.Fatal("fabricated session/clock", asset)
	}
	receipt := Receipt(a.ArchiveID, frame)
	if receipt.ContractVersion != "0.1.0" || receipt.CommittedAt != oldTime.UTC().Format(time.RFC3339Nano) {
		t.Fatal("wire/commit changed", receipt)
	}
	var newRaw []byte
	if e = tx.QueryRow(ctx, "SELECT metadata FROM mt.frames WHERE archive_id=$1 AND id=$2", a.ArchiveID, id).Scan(&newRaw); e != nil || !bytes.Equal(oldRaw, newRaw) {
		t.Fatal("v1 metadata changed", e)
	}
	got, e := f.Read(a.ArchiveID, m)
	if e != nil || !bytes.Equal(got, b) {
		t.Fatal("original changed", e)
	}
	if e = tx.Commit(ctx); e != nil {
		t.Fatal(e)
	}
	if e = Migrate(ctx, os.Getenv("MEMOTRACE_TEST_ADMIN_DSN"), "memotrace_runtime"); e != nil {
		t.Fatal("repeat v2 migration", e)
	}
}

func TestExactVectorScopeGateWithoutAssetOverflow(t *testing.T) {
	s, admin := database(t)
	ctx := context.Background()
	a, owner := ownerAccess(t, admin)
	execSQL(t, admin, `INSERT INTO mt.assets(archive_id,id,owner_id,source_kind,dataset_name,dataset_version,item_id,sha256,byte_length,provenance)
 SELECT $1,('00000000-0000-0000-0000-'||lpad(i::text,12,'0'))::uuid,$2,'dataset','synthetic-scope','1',i::text,$3,10,'{}' FROM generate_series(1,782) i`, a.ArchiveID, owner, strings.Repeat("a", 64))
	g, e := s.PrepareIndex(ctx, a, syntheticDescription(), "full")
	if e != nil {
		t.Fatal(e)
	}
	execSQL(t, admin, "UPDATE mt.index_jobs SET state='complete' WHERE archive_id=$1", a.ArchiveID)
	execSQL(t, admin, `INSERT INTO mt.regions(archive_id,generation_id,asset_id,owner_id,ordinal,kind,box,embedding) SELECT archive_id,$2,id,owner_id,i,'crop',ARRAY[0,0,1,1]::double precision[],ARRAY[1,0]::real[] FROM mt.assets CROSS JOIN generate_series(0,63) i WHERE archive_id=$1`, a.ArchiveID, g.ID)
	tx, _, e := s.BeginAccess(ctx, a, true)
	if e != nil {
		t.Fatal(e)
	}
	defer tx.Rollback(ctx)
	c, e := Coverage(ctx, tx, a.ArchiveID, g.ID)
	var pe *protocol.Error
	if !errors.As(e, &pe) || pe.Code != "unavailable" || c.AssetsTotal != 782 || c.RegionsIndexed != 50048 {
		t.Fatal("vector gate missing", c, e)
	}
}

func TestDatasetIdentityByteCheckBoundary(t *testing.T) {
	_, admin := database(t)
	ctx := context.Background()
	a, owner := ownerAccess(t, admin)
	name := strings.Repeat("\U0001f600", 255)
	version := "\u00e9"
	item := "\u00e9"
	if len(name)+len(version)+len(item) != retrieval.MaxDatasetIdentityBytes {
		t.Fatal("boundary fixture changed")
	}
	execSQL(t, admin, `INSERT INTO mt.assets(archive_id,id,owner_id,source_kind,dataset_name,dataset_version,item_id,sha256,byte_length,provenance) VALUES($1,$2,$3,'dataset',$4,$5,$6,$7,10,'{}')`, a.ArchiveID, protocol.NewID(), owner, name, version, item, strings.Repeat("a", 64))
	oversized := "\u754c"
	if len(name)+len(version)+len(oversized) != retrieval.MaxDatasetIdentityBytes+1 {
		t.Fatal("oversized fixture changed")
	}
	if _, err := admin.Exec(ctx, `INSERT INTO mt.assets(archive_id,id,owner_id,source_kind,dataset_name,dataset_version,item_id,sha256,byte_length,provenance) VALUES($1,$2,$3,'dataset',$4,$5,$6,$7,10,'{}')`, a.ArchiveID, protocol.NewID(), owner, name, version, oversized, strings.Repeat("b", 64)); err == nil {
		t.Fatal("database accepted oversized UTF-8 dataset identity")
	}
	var count int
	if err := admin.QueryRow(ctx, "SELECT count(*) FROM mt.assets WHERE archive_id=$1", a.ArchiveID).Scan(&count); err != nil || count != 1 {
		t.Fatal("dataset identity CHECK left a rejected row", count, err)
	}
}

func TestMigrationBlocksFrameWriterUntilTriggerIsInstalled(t *testing.T) {
	admin := v1Database(t)
	ctx := context.Background()
	a, owner := ownerAccess(t, admin)
	device, frame := protocol.NewID(), protocol.NewID()
	execSQL(t, admin, "INSERT INTO mt.devices(id,owner_id,archive_id,token_hash,name) VALUES($1,$2,$3,$4,'synthetic')", device, owner, a.ArchiveID, protocol.Hash([]byte(protocol.NewToken())))
	raw, _ := json.Marshal(protocol.Metadata{FrameID: frame, SHA256: strings.Repeat("a", 64), ByteLength: 10})
	execSQL(t, admin, "INSERT INTO mt.frames(archive_id,id,owner_id,registering_device_id,metadata) VALUES($1,$2,$3,$4,$5)", a.ArchiveID, frame, owner, device, raw)

	blocker := testAdminConnection(t)
	blockerTx, err := blocker.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer blockerTx.Rollback(ctx)
	if _, err = blockerTx.Exec(ctx, "LOCK TABLE mt.schema_version IN ACCESS SHARE MODE"); err != nil {
		t.Fatal(err)
	}
	migrationCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	migrated := make(chan error, 1)
	go func() { migrated <- Migrate(migrationCtx, os.Getenv("MEMOTRACE_TEST_ADMIN_DSN"), "memotrace_runtime") }()

	observer := testAdminConnection(t)
	waitForDatabaseCondition(t, observer, `SELECT EXISTS(SELECT 1 FROM pg_locks WHERE relation=to_regclass('mt.frames') AND mode='ShareRowExclusiveLock' AND granted)`)
	writer := testAdminConnection(t)
	var writerPID int
	if err = writer.QueryRow(ctx, "SELECT pg_backend_pid()").Scan(&writerPID); err != nil {
		t.Fatal(err)
	}
	written := make(chan error, 1)
	go func() {
		_, e := writer.Exec(migrationCtx, "UPDATE mt.frames SET committed_at=clock_timestamp() WHERE archive_id=$1 AND id=$2", a.ArchiveID, frame)
		written <- e
	}()
	waitForDatabaseCondition(t, observer, `SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=$1 AND relation=to_regclass('mt.frames') AND mode='RowExclusiveLock' AND NOT granted)`, writerPID)
	select {
	case err = <-written:
		t.Fatal("frame writer was not blocked by migration", err)
	default:
	}
	if err = blockerTx.Commit(ctx); err != nil {
		t.Fatal(err)
	}
	select {
	case err = <-migrated:
		if err != nil {
			t.Fatal(err)
		}
	case <-migrationCtx.Done():
		t.Fatal("migration did not finish", migrationCtx.Err())
	}
	select {
	case err = <-written:
		if err != nil {
			t.Fatal(err)
		}
	case <-migrationCtx.Done():
		t.Fatal("blocked frame writer did not resume", migrationCtx.Err())
	}
	var count int
	if err = admin.QueryRow(ctx, "SELECT count(*) FROM mt.assets WHERE archive_id=$1 AND frame_id=$2", a.ArchiveID, frame).Scan(&count); err != nil || count != 1 {
		t.Fatal("concurrent committed frame was not represented exactly once", count, err)
	}
	execSQL(t, admin, "UPDATE mt.frames SET committed_at=clock_timestamp() WHERE archive_id=$1 AND id=$2", a.ArchiveID, frame)
	if err = admin.QueryRow(ctx, "SELECT count(*) FROM mt.assets WHERE archive_id=$1 AND frame_id=$2", a.ArchiveID, frame).Scan(&count); err != nil || count != 1 {
		t.Fatal("frame trigger duplicated an existing asset", count, err)
	}
}

func TestMigrationFailureRollsBackV2SchemaAndCanRetry(t *testing.T) {
	admin := v1Database(t)
	ctx := context.Background()
	a, owner := ownerAccess(t, admin)
	device, frame := protocol.NewID(), protocol.NewID()
	execSQL(t, admin, "INSERT INTO mt.devices(id,owner_id,archive_id,token_hash,name) VALUES($1,$2,$3,$4,'synthetic')", device, owner, a.ArchiveID, protocol.Hash([]byte(protocol.NewToken())))
	raw := []byte(`{"sha256":"` + strings.Repeat("a", 64) + `","byte_length":"not-an-integer"}`)
	execSQL(t, admin, "INSERT INTO mt.frames(archive_id,id,owner_id,registering_device_id,metadata,committed_at) VALUES($1,$2,$3,$4,$5,clock_timestamp())", a.ArchiveID, frame, owner, device, raw)
	if err := Migrate(ctx, os.Getenv("MEMOTRACE_TEST_ADMIN_DSN"), "memotrace_runtime"); err == nil {
		t.Fatal("malformed v1 backfill unexpectedly migrated")
	}
	var version int
	var absent bool
	if err := admin.QueryRow(ctx, "SELECT version FROM mt.schema_version").Scan(&version); err != nil || version != 1 {
		t.Fatal("failed migration changed schema version", version, err)
	}
	if err := admin.QueryRow(ctx, "SELECT to_regclass('mt.assets') IS NULL AND NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='mt.frames'::regclass AND tgname='frame_asset')").Scan(&absent); err != nil || !absent {
		t.Fatal("failed migration left v2 schema objects", absent, err)
	}
	valid, _ := json.Marshal(protocol.Metadata{FrameID: frame, SHA256: strings.Repeat("a", 64), ByteLength: 10})
	execSQL(t, admin, "UPDATE mt.frames SET metadata=$3 WHERE archive_id=$1 AND id=$2", a.ArchiveID, frame, valid)
	if err := Migrate(ctx, os.Getenv("MEMOTRACE_TEST_ADMIN_DSN"), "memotrace_runtime"); err != nil {
		t.Fatal("migration could not retry after rollback", err)
	}
	var count int
	if err := admin.QueryRow(ctx, "SELECT count(*) FROM mt.assets WHERE archive_id=$1 AND frame_id=$2", a.ArchiveID, frame).Scan(&count); err != nil || count != 1 {
		t.Fatal("successful retry did not backfill once", count, err)
	}
}

func v1Database(t *testing.T) *pgx.Conn {
	t.Helper()
	s, admin := database(t)
	s.Close()
	backup := "mt_saved_" + strings.ReplaceAll(protocol.NewID(), "-", "")
	execSQL(t, admin, "ALTER SCHEMA mt RENAME TO "+pgx.Identifier{backup}.Sanitize())
	t.Cleanup(func() {
		execSQL(t, admin, "DROP SCHEMA IF EXISTS mt CASCADE")
		execSQL(t, admin, "ALTER SCHEMA "+pgx.Identifier{backup}.Sanitize()+" RENAME TO mt")
	})
	execSQL(t, admin, migration)
	return admin
}

func testAdminConnection(t *testing.T) *pgx.Conn {
	t.Helper()
	c, err := pgx.Connect(context.Background(), os.Getenv("MEMOTRACE_TEST_ADMIN_DSN"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { c.Close(context.Background()) })
	return c
}

func waitForDatabaseCondition(t *testing.T, c *pgx.Conn, query string, args ...any) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		var ready bool
		if err := c.QueryRow(context.Background(), query, args...).Scan(&ready); err != nil {
			t.Fatal(err)
		}
		if ready {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("database condition was not observed")
}
