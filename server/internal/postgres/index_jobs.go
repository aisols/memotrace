// SPDX-License-Identifier: AGPL-3.0-only
package postgres

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5"
	"memotrace/server/internal/protocol"
	"memotrace/server/internal/retrieval"
)

type Claim struct {
	Asset      Asset
	Generation Generation
	Token      string
	Attempt    int
}

var ErrNoJob = errors.New("no claimable index job")
var ErrFence = errors.New("index lease lost")

// Claims survive restarts; exhausted expired leases become failed. Worker errors
// consume attempts just like process death. No process-local completion state.
func (s *Store) ClaimIndex(ctx context.Context, a Access, g Generation) (Claim, error) {
	c := Claim{Generation: g, Token: protocol.NewID()}
	tx, _, err := s.BeginAccess(ctx, a, false)
	if err != nil {
		return c, err
	}
	defer tx.Rollback(ctx)
	_, err = tx.Exec(ctx, `UPDATE mt.index_jobs SET state='failed',lease_token=NULL,lease_until=NULL,error_code='attempts_exhausted' WHERE archive_id=$1 AND generation_id=$2 AND state='leased' AND lease_until<=clock_timestamp() AND attempts>=3`, a.ArchiveID, g.ID)
	if err != nil {
		return c, err
	}
	var id string
	err = tx.QueryRow(ctx, `WITH candidate AS (
 SELECT asset_id FROM mt.index_jobs WHERE archive_id=$1 AND generation_id=$2 AND attempts<3
 AND (state='pending' OR (state='leased' AND lease_until<=clock_timestamp())) ORDER BY asset_id FOR UPDATE SKIP LOCKED LIMIT 1)
 UPDATE mt.index_jobs j SET state='leased',attempts=attempts+1,lease_token=$3,lease_until=clock_timestamp()+interval '10 minutes',error_code=NULL
 FROM candidate c WHERE j.archive_id=$1 AND j.generation_id=$2 AND j.asset_id=c.asset_id RETURNING j.asset_id::text,j.attempts`, a.ArchiveID, g.ID, c.Token).Scan(&id, &c.Attempt)
	if errors.Is(err, pgx.ErrNoRows) {
		if e := tx.Commit(ctx); e != nil {
			return c, e
		}
		return c, ErrNoJob
	}
	if err != nil {
		return c, err
	}
	c.Asset, err = AssetByID(ctx, tx, a.ArchiveID, id)
	if err != nil {
		return c, err
	}
	return c, tx.Commit(ctx)
}
func fence(ctx context.Context, tx pgx.Tx, a Access, c Claim) error {
	var ok bool
	err := tx.QueryRow(ctx, `SELECT state='leased' AND lease_token=$4 AND lease_until>clock_timestamp() FROM mt.index_jobs WHERE archive_id=$1 AND generation_id=$2 AND asset_id=$3 FOR UPDATE`, a.ArchiveID, c.Generation.ID, c.Asset.Hit.AssetID, c.Token).Scan(&ok)
	if errors.Is(err, pgx.ErrNoRows) || err == nil && !ok {
		return ErrFence
	}
	return err
}
func (s *Store) FailIndex(ctx context.Context, a Access, c Claim) error {
	tx, _, err := s.BeginAccess(ctx, a, false)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if err = fence(ctx, tx, a, c); err != nil {
		return err
	}
	_, err = tx.Exec(ctx, `UPDATE mt.index_jobs SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,lease_token=NULL,lease_until=NULL,error_code='inference_failed' WHERE archive_id=$1 AND generation_id=$2 AND asset_id=$3`, a.ArchiveID, c.Generation.ID, c.Asset.Hit.AssetID)
	if err != nil {
		return err
	}
	return tx.Commit(ctx)
}
func (s *Store) CompleteIndex(ctx context.Context, a Access, c Claim, result retrieval.ImageResult) error {
	if !result.Valid(c.Generation.Description, c.Generation.Mode) {
		return protocol.E("invalid_request")
	}
	tx, sc, err := s.BeginAccess(ctx, a, false)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if err = fence(ctx, tx, a, c); err != nil {
		return err
	}
	g, err := GetGeneration(ctx, tx, a.ArchiveID, c.Generation.ID)
	if err != nil {
		return err
	}
	if !result.Valid(g.Description, g.Mode) {
		return protocol.E("invalid_request")
	}
	_, err = tx.Exec(ctx, `DELETE FROM mt.regions WHERE archive_id=$1 AND generation_id=$2 AND asset_id=$3`, a.ArchiveID, g.ID, c.Asset.Hit.AssetID)
	if err != nil {
		return err
	}
	for i, v := range result.Vectors {
		_, err = tx.Exec(ctx, `INSERT INTO mt.regions(archive_id,generation_id,asset_id,owner_id,ordinal,kind,box,embedding) VALUES($1,$2,$3,$4,$5,$6,$7,$8)`, a.ArchiveID, g.ID, c.Asset.Hit.AssetID, sc.OwnerID, i, v.Kind, v.Box[:], v.Embedding)
		if err != nil {
			return err
		}
	}
	// Recheck wall-clock expiry at the result boundary, including slow inserts.
	tag, err := tx.Exec(ctx, `UPDATE mt.index_jobs SET state='complete',lease_token=NULL,lease_until=NULL,error_code=NULL WHERE archive_id=$1 AND generation_id=$2 AND asset_id=$3 AND lease_token=$4 AND lease_until>clock_timestamp()`, a.ArchiveID, g.ID, c.Asset.Hit.AssetID, c.Token)
	if err != nil {
		return err
	}
	if tag.RowsAffected() != 1 {
		return ErrFence
	}
	return tx.Commit(ctx)
}
