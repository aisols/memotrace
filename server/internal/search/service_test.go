// SPDX-License-Identifier: AGPL-3.0-only
package search

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"image"
	"image/jpeg"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"

	"github.com/jackc/pgx/v5"
	"memotrace/server/internal/archive"
	"memotrace/server/internal/postgres"
	"memotrace/server/internal/protocol"
	"memotrace/server/internal/retrieval"
)

type directWorker struct {
	description retrieval.Description
	vectors     map[string][]float32
	query       []float32
	queryCalls  int
	afterQuery  func()
}

func (w *directWorker) Describe(context.Context) (retrieval.Description, error) {
	return w.description, nil
}
func (w *directWorker) Image(_ context.Context, b []byte, mode string, d retrieval.Description) (retrieval.ImageResult, error) {
	v := append([]float32(nil), w.vectors[protocol.Hash(b)]...)
	if len(v) == 0 {
		v = []float32{1, 0}
	}
	return retrieval.ImageResult{ModelFingerprint: d.ModelFingerprint, PolicyFingerprint: d.Policies[mode], Width: 4, Height: 3, Vectors: []retrieval.Vector{{Kind: "full", Box: retrieval.Box{0, 0, 1, 1}, Embedding: v}}}, nil
}
func (w *directWorker) Query(context.Context, retrieval.Query, []byte, retrieval.Description) ([]float32, error) {
	w.queryCalls++
	if w.afterQuery != nil {
		w.afterQuery()
	}
	return append([]float32(nil), w.query...), nil
}

type searchFixture struct {
	service *Service
	db      *postgres.Store
	files   *archive.Files
	admin   *pgx.Conn
	access  postgres.Access
	owner   string
	root    string
}

func newSearchFixture(t *testing.T, worker *directWorker) *searchFixture {
	t.Helper()
	adminDSN, dsn := os.Getenv("MEMOTRACE_TEST_ADMIN_DSN"), os.Getenv("MEMOTRACE_TEST_DSN")
	if adminDSN == "" || dsn == "" {
		if os.Getenv("MEMOTRACE_REQUIRE_POSTGRES") == "1" {
			t.Fatal("required disposable PostgreSQL missing")
		}
		t.Skip("run bash scripts/verify.sh for disposable PostgreSQL")
	}
	ctx := context.Background()
	if err := postgres.Migrate(ctx, adminDSN, "memotrace_runtime"); err != nil {
		t.Fatal(err)
	}
	db, err := postgres.Open(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(db.Close)
	admin, err := pgx.Connect(ctx, adminDSN)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { admin.Close(ctx) })
	owner, archiveID := protocol.NewID(), protocol.NewID()
	searchExec(t, admin, "INSERT INTO mt.owners(id) VALUES($1)", owner)
	searchExec(t, admin, "INSERT INTO mt.archives(id,owner_id) VALUES($1,$2)", archiveID, owner)
	root := t.TempDir()
	if err = os.Chmod(root, 0700); err != nil {
		t.Fatal(err)
	}
	files, err := archive.Open(root)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { files.Close() })
	var inferenceWorker Worker
	if worker != nil {
		inferenceWorker = worker
	}
	return &searchFixture{service: New(db, files, inferenceWorker), db: db, files: files, admin: admin, access: postgres.Access{ArchiveID: archiveID, Operator: true}, owner: owner, root: root}
}

func searchDescription() retrieval.Description {
	return retrieval.Description{ModelFingerprint: strings.Repeat("a", 64), Dimension: 2, ModelID: "synthetic-test-only", ModelRevision: "1", InputResolution: 224, PreprocessingVersion: "1", Policies: map[string]string{"full": strings.Repeat("b", 64), "overlap": strings.Repeat("c", 64)}}
}

func searchJPEG(t *testing.T, marker byte) []byte {
	t.Helper()
	var encoded bytes.Buffer
	if err := jpeg.Encode(&encoded, image.NewRGBA(image.Rect(0, 0, 4, 3)), nil); err != nil {
		t.Fatal(err)
	}
	b := encoded.Bytes()
	return append([]byte{0xff, 0xd8, 0xff, 0xfe, 0, 3, marker}, b[2:]...)
}

func writeSearchManifest(t *testing.T, m Manifest, images map[string][]byte) string {
	t.Helper()
	dir := t.TempDir()
	for name, b := range images {
		if err := os.WriteFile(filepath.Join(dir, name), b, 0600); err != nil {
			t.Fatal(err)
		}
	}
	b, err := json.Marshal(m)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "manifest.json")
	if err = os.WriteFile(path, b, 0600); err != nil {
		t.Fatal(err)
	}
	return path
}

func datasetManifest(name, version string, images ...[]byte) (Manifest, map[string][]byte) {
	m := Manifest{Version: "1", Dataset: DatasetInfo{Name: name, Version: version, Source: "synthetic-generated", License: "AGPL-3.0-only"}}
	files := make(map[string][]byte, len(images))
	for i, b := range images {
		name := string(rune('a'+i)) + ".jpg"
		files[name] = b
		m.Items = append(m.Items, DatasetItem{ID: string(rune('a' + i)), Path: name, SHA256: protocol.Hash(b), ByteLength: int64(len(b))})
	}
	return m, files
}

func searchExec(t *testing.T, c *pgx.Conn, query string, args ...any) {
	t.Helper()
	if _, err := c.Exec(context.Background(), query, args...); err != nil {
		t.Fatal(err)
	}
}

func requireProtocolError(t *testing.T, err error, code string) {
	t.Helper()
	var pe *protocol.Error
	if !errors.As(err, &pe) || pe.Code != code {
		t.Fatal("unexpected protocol error", err)
	}
}

func assetFiles(t *testing.T, root string) []string {
	t.Helper()
	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), "asset-") {
			names = append(names, entry.Name())
		}
	}
	return names
}

func TestServiceImportIndexRunMatchesSourceExclusionAndArchiveIsolation(t *testing.T) {
	d := searchDescription()
	first, distinct, otherBytes := searchJPEG(t, 1), searchJPEG(t, 2), searchJPEG(t, 3)
	w := &directWorker{description: d, vectors: map[string][]float32{}, query: []float32{1, 0}}
	w.vectors[protocol.Hash(first)] = []float32{1, 0}
	w.vectors[protocol.Hash(distinct)] = []float32{.8, .6}
	w.vectors[protocol.Hash(otherBytes)] = []float32{0, 1}
	f := newSearchFixture(t, w)
	ctx := context.Background()
	m, images := datasetManifest("direct-service", "1", first, first, distinct)
	imported, err := f.service.Import(ctx, f.access, writeSearchManifest(t, m, images))
	if err != nil || len(imported.Items) != 3 {
		t.Fatal("direct import failed", imported, err)
	}
	got, err := f.service.Original(ctx, f.access, imported.Items[0].AssetID)
	if err != nil || !bytes.Equal(got, first) {
		t.Fatal("imported original changed", err)
	}

	otherArchive := protocol.NewID()
	searchExec(t, f.admin, "INSERT INTO mt.archives(id,owner_id) VALUES($1,$2)", otherArchive, f.owner)
	otherAccess := postgres.Access{ArchiveID: otherArchive, Operator: true}
	otherManifest, otherImages := datasetManifest("same-owner-other-archive", "1", otherBytes)
	other, err := f.service.Import(ctx, otherAccess, writeSearchManifest(t, otherManifest, otherImages))
	if err != nil {
		t.Fatal(err)
	}
	otherIndex, err := f.service.Index(ctx, otherAccess, "full", 10)
	if err != nil || otherIndex.Completed != 1 {
		t.Fatal("other archive indexing failed", otherIndex, err)
	}
	if _, err = f.service.Original(ctx, f.access, other.Items[0].AssetID); err == nil {
		t.Fatal("same-owner archive asset crossed archive boundary")
	} else {
		requireProtocolError(t, err, "not_found")
	}

	indexed, err := f.service.Index(ctx, f.access, "full", 10)
	if err != nil || indexed.Completed != 3 || indexed.Coverage.AssetsIndexed != 3 {
		t.Fatal("direct indexing failed", indexed, err)
	}
	text := "synthetic query"
	r := retrieval.Request{GenerationID: indexed.GenerationID, Query: retrieval.Query{Text: &text}}
	value, err := f.service.Run(ctx, f.access, r, false)
	result, ok := value.(retrieval.SearchResponse)
	if err != nil || !ok || len(result.Hits) != 3 {
		t.Fatal("direct search failed", value, err)
	}
	for _, hit := range result.Hits {
		if hit.AssetID == other.Items[0].AssetID {
			t.Fatal("same-owner archive leaked through Run")
		}
	}

	r.Query = retrieval.Query{AssetID: &imported.Items[0].AssetID}
	value, err = f.service.Run(ctx, f.access, r, false)
	result, ok = value.(retrieval.SearchResponse)
	if err != nil || !ok || len(result.Hits) != 1 || result.Hits[0].AssetID != imported.Items[2].AssetID {
		t.Fatal("source asset or same-byte alias was not excluded", value, err)
	}
	tx, _, err := f.db.BeginAccess(ctx, f.access, true)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback(ctx)
	g, err := postgres.GetGeneration(ctx, tx, f.access.ArchiveID, indexed.GenerationID)
	if err != nil {
		t.Fatal(err)
	}
	hits, err := postgres.Matches(ctx, tx, f.access.ArchiveID, g, r, []float32{1, 0}, imported.Items[0].SHA256)
	if err != nil || len(hits) != 1 || hits[0].AssetID != imported.Items[2].AssetID {
		t.Fatal("direct Matches source exclusion failed", hits, err)
	}
	if err = tx.Commit(ctx); err != nil {
		t.Fatal(err)
	}

	queries := w.queryCalls
	r.GenerationID = strings.Repeat("f", 64)
	if _, err = f.service.Run(ctx, f.access, r, false); err == nil {
		t.Fatal("generation mismatch accepted")
	} else {
		requireProtocolError(t, err, "unavailable")
	}
	if w.queryCalls != queries {
		t.Fatal("generation mismatch reached query inference")
	}
}

func TestRunRequiresExactDescriptionBeforeAndAfterInference(t *testing.T) {
	base := searchDescription()
	w := &directWorker{description: base, vectors: map[string][]float32{}, query: []float32{1, 0}}
	f := newSearchFixture(t, w)
	ctx := context.Background()
	image := searchJPEG(t, 4)
	m, images := datasetManifest("description-identity", "1", image)
	if _, err := f.service.Import(ctx, f.access, writeSearchManifest(t, m, images)); err != nil {
		t.Fatal(err)
	}
	indexed, err := f.service.Index(ctx, f.access, "full", 10)
	if err != nil {
		t.Fatal(err)
	}
	text := "synthetic query"
	r := retrieval.Request{GenerationID: indexed.GenerationID, Query: retrieval.Query{Text: &text}}
	clone := func() retrieval.Description {
		d := base
		d.Policies = map[string]string{"full": base.Policies["full"], "overlap": base.Policies["overlap"]}
		return d
	}
	mutations := []struct {
		name   string
		mutate func(*retrieval.Description)
	}{
		{"dimension", func(d *retrieval.Description) { d.Dimension = 3 }},
		{"model_id", func(d *retrieval.Description) { d.ModelID += "-changed" }},
		{"model_revision", func(d *retrieval.Description) { d.ModelRevision += "-changed" }},
		{"input_resolution", func(d *retrieval.Description) { d.InputResolution = 384 }},
		{"preprocessing_version", func(d *retrieval.Description) { d.PreprocessingVersion += "-changed" }},
		{"non_selected_policy", func(d *retrieval.Description) { d.Policies["overlap"] = strings.Repeat("d", 64) }},
	}
	for _, tc := range mutations {
		t.Run(tc.name, func(t *testing.T) {
			d := clone()
			tc.mutate(&d)
			w.description = d
			before := w.queryCalls
			_, err := f.service.Run(ctx, f.access, r, false)
			requireProtocolError(t, err, "unavailable")
			if w.queryCalls != before {
				t.Fatal("description mismatch reached query inference")
			}
		})
	}

	w.description = clone()
	w.afterQuery = func() {
		stored := clone()
		stored.ModelID += "-changed-after-query"
		b, _ := json.Marshal(stored)
		searchExec(t, f.admin, "UPDATE mt.index_generations SET description=$3 WHERE archive_id=$1 AND id=$2", f.access.ArchiveID, indexed.GenerationID, b)
	}
	before := w.queryCalls
	_, err = f.service.Run(ctx, f.access, r, false)
	requireProtocolError(t, err, "unavailable")
	if w.queryCalls != before+1 {
		t.Fatal("after-inference identity test did not run query exactly once")
	}
}

func TestImportDatasetIdentityUTF8BoundaryRejectsBeforePublication(t *testing.T) {
	f := newSearchFixture(t, nil)
	ctx := context.Background()
	image := searchJPEG(t, 5)
	name := strings.Repeat("\U0001f600", 255)
	version, acceptedID := "\u00e9", "\u00e9"
	m, images := datasetManifest(name, version, image)
	m.Items[0].ID = acceptedID
	if len(name)+len(version)+len(acceptedID) != retrieval.MaxDatasetIdentityBytes {
		t.Fatal("accepted UTF-8 boundary fixture changed")
	}
	accepted, err := f.service.Import(ctx, f.access, writeSearchManifest(t, m, images))
	if err != nil || len(accepted.Items) != 1 {
		t.Fatal("accepted UTF-8 boundary failed", accepted, err)
	}
	if _, err = f.service.Original(ctx, f.access, accepted.Items[0].AssetID); err != nil {
		t.Fatal("accepted boundary artifact was not published", err)
	}
	beforeFiles := assetFiles(t, f.root)
	var beforeRows int
	if err = f.admin.QueryRow(ctx, "SELECT count(*) FROM mt.assets WHERE archive_id=$1", f.access.ArchiveID).Scan(&beforeRows); err != nil {
		t.Fatal(err)
	}
	m.Items[0].ID = "\u754c"
	if len(name)+len(version)+len(m.Items[0].ID) != retrieval.MaxDatasetIdentityBytes+1 {
		t.Fatal("oversized UTF-8 boundary fixture changed")
	}
	if _, err = f.service.Import(ctx, f.access, writeSearchManifest(t, m, images)); err == nil {
		t.Fatal("oversized UTF-8 dataset identity imported")
	} else {
		requireProtocolError(t, err, "invalid_request")
	}
	var afterRows int
	if err = f.admin.QueryRow(ctx, "SELECT count(*) FROM mt.assets WHERE archive_id=$1", f.access.ArchiveID).Scan(&afterRows); err != nil || afterRows != beforeRows {
		t.Fatal("rejected identity published a row", beforeRows, afterRows, err)
	}
	afterFiles := assetFiles(t, f.root)
	if len(afterFiles) != len(beforeFiles) {
		t.Fatal("rejected identity published an artifact", beforeFiles, afterFiles)
	}
}

func TestImportDatasetDurabilityFailuresNeverCommitRows(t *testing.T) {
	for _, point := range []string{"write", "file_sync", "publish", "directory_sync"} {
		t.Run(point, func(t *testing.T) {
			f := newSearchFixture(t, nil)
			image := searchJPEG(t, 6)
			m, images := datasetManifest("durability-"+point, "1", image)
			failure := func() error { return syscall.ENOSPC }
			switch point {
			case "write":
				f.files.Faults.BeforeWrite = failure
			case "file_sync":
				f.files.Faults.FileSync = failure
			case "publish":
				f.files.Faults.Publish = failure
			case "directory_sync":
				f.files.Faults.DirectorySync = failure
			}
			if _, err := f.service.Import(context.Background(), f.access, writeSearchManifest(t, m, images)); !errors.Is(err, syscall.ENOSPC) {
				t.Fatal("durability fault was not returned", err)
			}
			var count int
			if err := f.admin.QueryRow(context.Background(), "SELECT count(*) FROM mt.assets WHERE archive_id=$1", f.access.ArchiveID).Scan(&count); err != nil || count != 0 {
				t.Fatal("durability failure committed a dataset row", count, err)
			}
			wantArtifacts := 0
			if point == "directory_sync" {
				wantArtifacts = 1
			}
			if got := len(assetFiles(t, f.root)); got != wantArtifacts {
				t.Fatal("unexpected preserved artifact count", got, wantArtifacts)
			}
		})
	}

	t.Run("database_commit", func(t *testing.T) {
		f := newSearchFixture(t, nil)
		searchExec(t, f.admin, `CREATE FUNCTION mt.test_dataset_commit_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic dataset commit fault'; END $$`)
		searchExec(t, f.admin, `CREATE CONSTRAINT TRIGGER test_dataset_commit_failure AFTER INSERT ON mt.assets DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION mt.test_dataset_commit_failure()`)
		t.Cleanup(func() {
			searchExec(t, f.admin, "DROP TRIGGER IF EXISTS test_dataset_commit_failure ON mt.assets")
			searchExec(t, f.admin, "DROP FUNCTION IF EXISTS mt.test_dataset_commit_failure()")
		})
		image := searchJPEG(t, 7)
		m, images := datasetManifest("durability-database", "1", image)
		if _, err := f.service.Import(context.Background(), f.access, writeSearchManifest(t, m, images)); err == nil {
			t.Fatal("deferred database commit failure was not returned")
		}
		var count int
		if err := f.admin.QueryRow(context.Background(), "SELECT count(*) FROM mt.assets WHERE archive_id=$1", f.access.ArchiveID).Scan(&count); err != nil || count != 0 {
			t.Fatal("database commit failure left a dataset row", count, err)
		}
		if got := len(assetFiles(t, f.root)); got != 1 {
			t.Fatal("published bytes were not truthfully preserved after commit failure", got)
		}
	})
}
