// SPDX-License-Identifier: AGPL-3.0-only
package postgres

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/jackc/pgx/v5"
	"memotrace/server/internal/protocol"
	"memotrace/server/internal/retrieval"
)

// Access.Operator is reserved for local CLI operations using the pre-existing
// scoped-recovery capability. HTTP always uses a bearer token, never this flag.
type Access struct {
	ArchiveID, Token string
	Operator         bool
}

func (s *Store) BeginAccess(ctx context.Context, a Access, snapshot bool) (pgx.Tx, Scope, error) {
	opts := pgx.TxOptions{}
	if snapshot {
		opts.IsoLevel = pgx.RepeatableRead
	}
	tx, err := s.Pool.BeginTx(ctx, opts)
	if err != nil {
		return nil, Scope{}, err
	}
	sc := Scope{ArchiveID: a.ArchiveID}
	if !protocol.UUID(a.ArchiveID) {
		err = protocol.E("not_found")
	} else if a.Operator {
		err = tx.QueryRow(ctx, "SELECT owner_id::text FROM (SELECT mt.recovery_archive_owner($1) AS owner_id) o WHERE owner_id IS NOT NULL", a.ArchiveID).Scan(&sc.OwnerID)
		if errors.Is(err, pgx.ErrNoRows) {
			err = protocol.E("not_found")
		}
	} else {
		err = tx.QueryRow(ctx, "SELECT owner_id::text,archive_id::text,device_id::text FROM mt.authenticate($1)", protocol.Hash([]byte(a.Token))).Scan(&sc.OwnerID, &sc.ArchiveID, &sc.DeviceID)
		if errors.Is(err, pgx.ErrNoRows) {
			err = protocol.E("unauthorized")
		}
		if err == nil && sc.ArchiveID != a.ArchiveID {
			err = protocol.E("not_found")
		}
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

type Asset struct {
	Hit        retrieval.Hit
	ByteLength int64
	Provenance []byte
}

const assetColumns = `a.id::text,a.source_kind,a.frame_id::text,a.dataset_name,a.dataset_version,a.item_id,a.sha256,a.byte_length,a.observed_at_ms,a.sequence_id,a.sequence_position_ms,a.provenance`

func scanAsset(row pgx.Row) (Asset, error) {
	var a Asset
	var name, version, item *string
	err := row.Scan(&a.Hit.AssetID, &a.Hit.SourceKind, &a.Hit.FrameID, &name, &version, &item, &a.Hit.SHA256, &a.ByteLength, &a.Hit.ObservedAtMS, &a.Hit.SequenceID, &a.Hit.SequencePositionMS, &a.Provenance)
	if errors.Is(err, pgx.ErrNoRows) {
		return a, protocol.E("not_found")
	}
	if name != nil && version != nil && item != nil {
		a.Hit.Dataset = &retrieval.Dataset{Name: *name, Version: *version, ItemID: *item}
	}
	return a, err
}
func AssetByID(ctx context.Context, tx pgx.Tx, archive, id string) (Asset, error) {
	a, err := scanAsset(tx.QueryRow(ctx, "SELECT "+assetColumns+" FROM mt.assets a WHERE a.archive_id=$1 AND a.id=$2", archive, id))
	a.Hit.OriginalPath = "/v1/archives/" + archive + "/search/assets/" + id + "/original"
	return a, err
}
func AssetsCount(ctx context.Context, tx pgx.Tx, archive string) (int, error) {
	var n int
	err := tx.QueryRow(ctx, "SELECT count(*) FROM mt.assets WHERE archive_id=$1", archive).Scan(&n)
	if err == nil && n > retrieval.MaxAssets {
		err = protocol.E("unavailable")
	}
	return n, err
}

type Generation struct {
	ID, Mode    string
	Description retrieval.Description
}

func GetGeneration(ctx context.Context, tx pgx.Tx, archive, id string) (Generation, error) {
	g := Generation{ID: id}
	var b []byte
	var model, policy string
	var dimension int
	err := tx.QueryRow(ctx, "SELECT mode,description,model_fingerprint,policy_fingerprint,dimension FROM mt.index_generations WHERE archive_id=$1 AND id=$2", archive, id).Scan(&g.Mode, &b, &model, &policy, &dimension)
	if errors.Is(err, pgx.ErrNoRows) {
		return g, protocol.E("unavailable")
	}
	if err != nil {
		return g, err
	}
	if json.Unmarshal(b, &g.Description) != nil || !g.Description.Valid() || (g.Mode != "full" && g.Mode != "overlap") || g.Description.Generation(g.Mode) != g.ID || model != g.Description.ModelFingerprint || policy != g.Description.Policies[g.Mode] || dimension != g.Description.Dimension {
		return g, protocol.E("unavailable")
	}
	return g, nil
}
func (s *Store) PrepareIndex(ctx context.Context, a Access, d retrieval.Description, mode string) (Generation, error) {
	g := Generation{ID: d.Generation(mode), Mode: mode, Description: d}
	if !d.Valid() || (mode != "full" && mode != "overlap") {
		return g, protocol.E("invalid_request")
	}
	tx, sc, err := s.BeginAccess(ctx, a, false)
	if err != nil {
		return g, err
	}
	defer tx.Rollback(ctx)
	if _, err = AssetsCount(ctx, tx, a.ArchiveID); err != nil {
		return g, err
	}
	b, _ := json.Marshal(d)
	_, err = tx.Exec(ctx, `INSERT INTO mt.index_generations(archive_id,id,owner_id,model_fingerprint,policy_fingerprint,dimension,mode,description) VALUES($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT DO NOTHING`, a.ArchiveID, g.ID, sc.OwnerID, d.ModelFingerprint, d.Policies[mode], d.Dimension, mode, b)
	if err != nil {
		return g, err
	}
	old, err := GetGeneration(ctx, tx, a.ArchiveID, g.ID)
	if err != nil {
		return g, err
	}
	oldb, _ := json.Marshal(old.Description)
	if old.Mode != mode || string(oldb) != string(b) {
		return g, protocol.E("conflict")
	}
	_, err = tx.Exec(ctx, `INSERT INTO mt.index_jobs(archive_id,generation_id,asset_id,owner_id) SELECT archive_id,$2,id,owner_id FROM mt.assets WHERE archive_id=$1 ON CONFLICT DO NOTHING`, a.ArchiveID, g.ID)
	if err != nil {
		return g, err
	}
	return g, tx.Commit(ctx)
}
func Coverage(ctx context.Context, tx pgx.Tx, archive, generation string) (retrieval.Coverage, error) {
	c := retrieval.Coverage{}
	err := tx.QueryRow(ctx, `SELECT count(*),count(*) FILTER(WHERE j.state='complete'),count(*) FILTER(WHERE j.state IS NULL OR j.state IN ('pending','leased')),count(*) FILTER(WHERE j.state='failed') FROM mt.assets a LEFT JOIN mt.index_jobs j ON j.archive_id=a.archive_id AND j.asset_id=a.id AND j.generation_id=$2 WHERE a.archive_id=$1`, archive, generation).Scan(&c.AssetsTotal, &c.AssetsIndexed, &c.Pending, &c.Failed)
	if err != nil {
		return c, err
	}
	err = tx.QueryRow(ctx, `SELECT count(*) FROM mt.regions WHERE archive_id=$1 AND generation_id=$2`, archive, generation).Scan(&c.RegionsIndexed)
	if err == nil && (c.AssetsTotal > retrieval.MaxAssets || c.RegionsIndexed > retrieval.MaxVectors) {
		err = protocol.E("unavailable")
	}
	return c, err
}

// Matches streams every region in the bounded snapshot. Source/cutoff filtering
// is before scoring and max-per-asset aggregation, never a top-N pre-scan.
func Matches(ctx context.Context, tx pgx.Tx, archive string, g Generation, r retrieval.Request, q []float32, sourceHash string) ([]retrieval.Hit, error) {
	if !retrieval.Unit(q, g.Description.Dimension) {
		return nil, protocol.E("unavailable")
	}
	qualifies := r.ScoreFilter()
	rows, err := tx.Query(ctx, `SELECT a.id::text,a.source_kind,a.frame_id::text,a.dataset_name,a.dataset_version,a.item_id,a.sha256,a.observed_at_ms,a.sequence_id,a.sequence_position_ms,r.kind,r.box,r.embedding
 FROM mt.regions r JOIN mt.assets a ON a.archive_id=r.archive_id AND a.id=r.asset_id
 JOIN mt.index_jobs j ON j.archive_id=r.archive_id AND j.generation_id=r.generation_id AND j.asset_id=r.asset_id
 WHERE r.archive_id=$1 AND r.generation_id=$2 AND j.state='complete' ORDER BY a.id,r.ordinal`, archive, g.ID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	best := map[string]retrieval.Hit{}
	count := 0
	for rows.Next() {
		count++
		if count > retrieval.MaxVectors {
			return nil, protocol.E("unavailable")
		}
		var h retrieval.Hit
		var name, version, item *string
		var box []float64
		var v []float32
		if err = rows.Scan(&h.AssetID, &h.SourceKind, &h.FrameID, &name, &version, &item, &h.SHA256, &h.ObservedAtMS, &h.SequenceID, &h.SequencePositionMS, &h.Region.Kind, &box, &v); err != nil {
			return nil, err
		}
		if len(box) != 4 || !retrieval.Unit(v, g.Description.Dimension) {
			return nil, protocol.E("unavailable")
		}
		copy(h.Region.Box[:], box)
		if !h.Region.Box.Valid() {
			return nil, protocol.E("unavailable")
		}
		if name != nil && version != nil && item != nil {
			h.Dataset = &retrieval.Dataset{Name: *name, Version: *version, ItemID: *item}
		}
		h.OriginalPath = "/v1/archives/" + archive + "/search/assets/" + h.AssetID + "/original"
		if !retrieval.Eligible(h, r, sourceHash) {
			continue
		}
		h.Score = retrieval.Cosine(q, v)
		if !qualifies(h.Score) {
			continue
		}
		old, ok := best[h.AssetID]
		if !ok || retrieval.Better(h, old) {
			best[h.AssetID] = h
		}
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	return retrieval.Ranked(best), nil
}
