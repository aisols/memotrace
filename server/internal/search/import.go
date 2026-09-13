// SPDX-License-Identifier: AGPL-3.0-only
package search

import (
	"context"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"

	"memotrace/server/internal/postgres"
	"memotrace/server/internal/protocol"
	"memotrace/server/internal/retrieval"
	"memotrace/server/internal/strictjson"
)

type DatasetInfo struct {
	Name    string `json:"name"`
	Version string `json:"version"`
	Source  string `json:"source"`
	License string `json:"license"`
}
type DatasetItem struct {
	ID                 string  `json:"id"`
	Path               string  `json:"path"`
	SHA256             string  `json:"sha256"`
	ByteLength         int64   `json:"byte_length"`
	ObservedAtMS       *int64  `json:"observed_at_ms"`
	SequenceID         *string `json:"sequence_id"`
	SequencePositionMS *int64  `json:"sequence_position_ms"`
}
type Manifest struct {
	Version string        `json:"version"`
	Dataset DatasetInfo   `json:"dataset"`
	Items   []DatasetItem `json:"items"`
}
type Imported struct {
	ItemID  string `json:"item_id"`
	AssetID string `json:"asset_id"`
	SHA256  string `json:"sha256"`
}
type ImportReport struct {
	ArchiveID      string     `json:"archive_id"`
	ManifestSHA256 string     `json:"manifest_sha256"`
	Items          []Imported `json:"items"`
}

func ReadManifest(path string) (Manifest, []byte, error) {
	var m Manifest
	f, err := os.Open(path)
	if err != nil {
		return m, nil, err
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, 4*1024*1024+1))
	if err != nil {
		return m, nil, err
	}
	if len(b) > 4*1024*1024 {
		return m, nil, protocol.E("payload_too_large")
	}
	v, err := strictjson.Value(b)
	if err != nil {
		return m, nil, err
	}
	object, ok := v.(map[string]any)
	if !ok || len(object) != 3 {
		return m, nil, protocol.E("invalid_request")
	}
	items, ok := object["items"].([]any)
	if !ok {
		return m, nil, protocol.E("invalid_request")
	}
	for _, raw := range items {
		item, ok := raw.(map[string]any)
		if !ok || len(item) != 7 {
			return m, nil, protocol.E("invalid_request")
		}
		for _, key := range []string{"id", "path", "sha256", "byte_length", "observed_at_ms", "sequence_id", "sequence_position_ms"} {
			if _, ok := item[key]; !ok {
				return m, nil, protocol.E("invalid_request")
			}
		}
	}
	if err = strictjson.Assign(v, &m); err != nil {
		return m, nil, err
	}
	if m.Version != "1" || !retrieval.Text(m.Dataset.Name, 256) || !retrieval.Text(m.Dataset.Version, 256) || !retrieval.Text(m.Dataset.Source, 2048) || !retrieval.Text(m.Dataset.License, 2048) || len(m.Items) < 1 || len(m.Items) > retrieval.MaxAssets {
		return m, nil, protocol.E("invalid_request")
	}
	seen := map[string]bool{}
	var total int64
	for _, i := range m.Items {
		total += i.ByteLength
		if !retrieval.DatasetIdentityValid(m.Dataset.Name, m.Dataset.Version, i.ID) || seen[i.ID] || !retrieval.Hash(i.SHA256) || i.ByteLength < 1 || i.ByteLength > protocol.MaxBytes || !retrieval.Time(i.ObservedAtMS) || !retrieval.Time(i.SequencePositionMS) || (i.SequenceID == nil) != (i.SequencePositionMS == nil) || i.SequenceID != nil && !retrieval.Text(*i.SequenceID, 256) || !safePath(i.Path) {
			return m, nil, protocol.E("invalid_request")
		}
		seen[i.ID] = true
	}
	if total > 512*1024*1024 {
		return m, nil, protocol.E("payload_too_large")
	}
	return m, b, nil
}
func safePath(p string) bool {
	if !retrieval.Text(p, 4096) || filepath.IsAbs(p) || strings.Contains(p, "\\") || filepath.Clean(p) != p || p == "." {
		return false
	}
	for _, part := range strings.Split(p, "/") {
		if part == ".." || part == "" {
			return false
		}
	}
	return true
}

// Import runs only under Files' exclusive root lock (CLI requires stop service).
// All rows commit atomically after exact bytes are durably published. A failed
// transaction can leave unreferenced preserved artifacts, never acknowledged rows
// without bytes. Retrying a committed manifest returns the same asset IDs.
func (s *Service) Import(ctx context.Context, a postgres.Access, path string) (ImportReport, error) {
	out := ImportReport{ArchiveID: a.ArchiveID, Items: []Imported{}}
	m, raw, err := ReadManifest(path)
	if err != nil {
		return out, err
	}
	out.ManifestSHA256 = protocol.Hash(raw)
	root, err := os.OpenRoot(filepath.Dir(path))
	if err != nil {
		return out, err
	}
	defer root.Close()
	tx, sc, err := s.DB.BeginAccess(ctx, a, false)
	if err != nil {
		return out, err
	}
	defer tx.Rollback(ctx)
	// Serialize experimental imports for one archive, including independent roots.
	if _, err = tx.Exec(ctx, "SELECT pg_advisory_xact_lock(hashtextextended($1,630282934))", a.ArchiveID); err != nil {
		return out, err
	}
	if _, err = postgres.AssetsCount(ctx, tx, a.ArchiveID); err != nil {
		return out, err
	}
	for _, item := range m.Items {
		if err = ctx.Err(); err != nil {
			return out, err
		}
		f, e := root.OpenFile(item.Path, os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
		if e != nil {
			return out, e
		}
		st, e := f.Stat()
		if e != nil || !st.Mode().IsRegular() {
			f.Close()
			return out, protocol.E("invalid_request")
		}
		b, e := io.ReadAll(io.LimitReader(f, protocol.MaxBytes+1))
		f.Close()
		if e != nil {
			return out, e
		}
		if int64(len(b)) != item.ByteLength || protocol.Hash(b) != item.SHA256 {
			return out, protocol.E("checksum_mismatch")
		}
		id := protocol.NewID()
		provenance, _ := json.Marshal(map[string]any{"dataset": m.Dataset, "manifest_sha256": out.ManifestSHA256, "item": item})
		_, err = tx.Exec(ctx, `INSERT INTO mt.assets(archive_id,id,owner_id,source_kind,dataset_name,dataset_version,item_id,sha256,byte_length,observed_at_ms,sequence_id,sequence_position_ms,provenance) VALUES($1,$2,$3,'dataset',$4,$5,$6,$7,$8,$9,$10,$11,$12) ON CONFLICT(archive_id,dataset_name,dataset_version,item_id) DO NOTHING`, a.ArchiveID, id, sc.OwnerID, m.Dataset.Name, m.Dataset.Version, item.ID, item.SHA256, item.ByteLength, item.ObservedAtMS, item.SequenceID, item.SequencePositionMS, provenance)
		if err != nil {
			return out, err
		}
		var equal bool
		err = tx.QueryRow(ctx, `SELECT id::text,provenance=$5::jsonb FROM mt.assets WHERE archive_id=$1 AND dataset_name=$2 AND dataset_version=$3 AND item_id=$4`, a.ArchiveID, m.Dataset.Name, m.Dataset.Version, item.ID, provenance).Scan(&id, &equal)
		if err != nil {
			return out, err
		}
		if !equal {
			return out, protocol.E("conflict")
		}
		if err = s.Files.PublishDataset(a.ArchiveID, id, item.SHA256, b); err != nil {
			return out, err
		}
		out.Items = append(out.Items, Imported{item.ID, id, item.SHA256})
	}
	if _, err = postgres.AssetsCount(ctx, tx, a.ArchiveID); err != nil {
		return out, err
	}
	return out, tx.Commit(ctx)
}
