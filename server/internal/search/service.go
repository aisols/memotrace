// SPDX-License-Identifier: AGPL-3.0-only
// Package search orchestrates authenticated persistence and an inference-only
// worker. Exact cosine is deliberately a bounded quality baseline, not ANN.
package search

import (
	"context"
	"errors"
	"time"

	"memotrace/server/internal/archive"
	"memotrace/server/internal/postgres"
	"memotrace/server/internal/protocol"
	"memotrace/server/internal/retrieval"
)

type Worker interface {
	Describe(context.Context) (retrieval.Description, error)
	Image(context.Context, []byte, string, retrieval.Description) (retrieval.ImageResult, error)
	Query(context.Context, retrieval.Query, []byte, retrieval.Description) ([]float32, error)
}
type Service struct {
	DB     *postgres.Store
	Files  *archive.Files
	Worker Worker
	slots  chan struct{}
}

func New(db *postgres.Store, files *archive.Files, worker Worker) *Service {
	return &Service{DB: db, Files: files, Worker: worker, slots: make(chan struct{}, 1)}
}

func (s *Service) Original(ctx context.Context, a postgres.Access, id string) ([]byte, error) {
	tx, _, err := s.DB.BeginAccess(ctx, a, false)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	asset, err := postgres.AssetByID(ctx, tx, a.ArchiveID, id)
	if err != nil {
		return nil, err
	}
	b, err := s.read(a.ArchiveID, asset)
	if err != nil {
		return nil, err
	}
	return b, tx.Commit(ctx)
}
func (s *Service) read(archive string, a postgres.Asset) ([]byte, error) {
	if a.Hit.SourceKind == "dataset" {
		return s.Files.ReadDataset(archive, a.Hit.AssetID, a.Hit.SHA256, a.ByteLength)
	}
	if a.Hit.FrameID == nil {
		return nil, protocol.E("integrity_error")
	}
	return s.Files.Read(archive, protocol.Metadata{FrameID: *a.Hit.FrameID, SHA256: a.Hit.SHA256, ByteLength: a.ByteLength})
}
func (s *Service) Run(ctx context.Context, a postgres.Access, r retrieval.Request, history bool) (any, error) {
	if err := r.Validate(history); err != nil {
		return nil, err
	}
	// Authenticate before any worker/index availability disclosure.
	tx, _, err := s.DB.BeginAccess(ctx, a, false)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	if s.Worker == nil {
		return nil, protocol.E("unavailable")
	}
	select {
	case s.slots <- struct{}{}:
		defer func() { <-s.slots }()
	default:
		return nil, protocol.E("unavailable")
	}
	g, err := postgres.GetGeneration(ctx, tx, a.ArchiveID, r.GenerationID)
	if err != nil {
		return nil, err
	}
	c, err := postgres.Coverage(ctx, tx, a.ArchiveID, g.ID)
	if err != nil {
		return nil, err
	}
	if c.AssetsIndexed == 0 {
		return nil, protocol.E("unavailable")
	}
	var b []byte
	sourceHash := ""
	if r.Query.AssetID != nil {
		asset, e := postgres.AssetByID(ctx, tx, a.ArchiveID, *r.Query.AssetID)
		if e != nil {
			return nil, e
		}
		b, err = s.read(a.ArchiveID, asset)
		if err != nil {
			return nil, protocol.E("unavailable")
		}
		sourceHash = asset.Hit.SHA256
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	d, err := s.Worker.Describe(ctx)
	if err != nil {
		return nil, protocol.E("unavailable")
	}
	if !d.Valid() || !d.Equal(g.Description) || d.Generation(g.Mode) != g.ID {
		return nil, protocol.E("unavailable")
	}
	q, err := s.Worker.Query(ctx, r.Query, b, d)
	if err != nil {
		return nil, err
	}
	// Reauthenticate after inference; revoked devices cannot acquire a new content
	// snapshot. Coverage and all vectors share one repeatable-read transaction.
	tx, _, err = s.DB.BeginAccess(ctx, a, true)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	g, err = postgres.GetGeneration(ctx, tx, a.ArchiveID, r.GenerationID)
	if err != nil {
		return nil, err
	}
	if !d.Equal(g.Description) || d.Generation(g.Mode) != g.ID {
		return nil, protocol.E("unavailable")
	}
	c, err = postgres.Coverage(ctx, tx, a.ArchiveID, g.ID)
	if err != nil {
		return nil, err
	}
	if c.AssetsIndexed == 0 {
		return nil, protocol.E("unavailable")
	}
	hits, err := postgres.Matches(ctx, tx, a.ArchiveID, g, r, q, sourceHash)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	if history {
		return retrieval.History(a.ArchiveID, r, c, hits), nil
	}
	return retrieval.Search(a.ArchiveID, r, c, hits), nil
}

type IndexReport struct {
	GenerationID   string             `json:"generation_id"`
	Mode           string             `json:"mode"`
	Completed      int                `json:"completed"`
	FailedAttempts int                `json:"failed_attempts"`
	Coverage       retrieval.Coverage `json:"coverage"`
}

func (s *Service) Index(ctx context.Context, a postgres.Access, mode string, maxJobs int) (IndexReport, error) {
	out := IndexReport{Mode: mode}
	if s.Worker == nil {
		return out, protocol.E("unavailable")
	}
	if maxJobs < 1 || maxJobs > retrieval.MaxAssets*3 {
		return out, protocol.E("invalid_request")
	}
	d, err := s.Worker.Describe(ctx)
	if err != nil {
		return out, err
	}
	g, err := s.DB.PrepareIndex(ctx, a, d, mode)
	if err != nil {
		return out, err
	}
	out.GenerationID = g.ID
	for i := 0; i < maxJobs; i++ {
		if err = ctx.Err(); err != nil {
			return out, err
		}
		claim, e := s.DB.ClaimIndex(ctx, a, g)
		if errors.Is(e, postgres.ErrNoJob) {
			break
		}
		if e != nil {
			return out, e
		}
		b, e := s.read(a.ArchiveID, claim.Asset)
		var result retrieval.ImageResult
		if e == nil {
			result, e = s.Worker.Image(ctx, b, mode, d)
		}
		if e == nil {
			e = s.DB.CompleteIndex(ctx, a, claim, result)
		}
		if e != nil {
			// Persist failed/malformed attempts even when the caller canceled. The
			// lease token still fences this cleanup against a replacement claimant.
			cleanup, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			failed := s.DB.FailIndex(cleanup, a, claim)
			cancel()
			if failed != nil {
				return out, failed
			}
			out.FailedAttempts++
		} else {
			out.Completed++
		}
	}
	tx, _, err := s.DB.BeginAccess(ctx, a, true)
	if err != nil {
		return out, err
	}
	defer tx.Rollback(ctx)
	out.Coverage, err = postgres.Coverage(ctx, tx, a.ArchiveID, g.ID)
	if err != nil {
		return out, err
	}
	return out, tx.Commit(ctx)
}
