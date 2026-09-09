// SPDX-License-Identifier: AGPL-3.0-only
package postgres

import (
	"context"
)

// Known is startup-only catalog reconciliation, while holding the root lock.
// The security-definer helper reveals scope identity, never arbitrary content.
func (s *Store) Known(ctx context.Context, archive, frame string) (bool, error) {
	tx, err := s.Pool.Begin(ctx)
	if err != nil {
		return false, err
	}
	defer tx.Rollback(ctx)
	var owner *string
	if err = tx.QueryRow(ctx, "SELECT mt.recovery_archive_owner($1)::text", archive).Scan(&owner); err != nil {
		return false, err
	}
	if owner == nil {
		return false, nil
	}
	if _, err = tx.Exec(ctx, "SELECT set_config('mt.owner_id',$1,true)", *owner); err != nil {
		return false, err
	}
	var exists bool
	err = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM mt.frames WHERE archive_id=$1 AND id=$2)", archive, frame).Scan(&exists)
	return exists, err
}
