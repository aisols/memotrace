// SPDX-License-Identifier: AGPL-3.0-only
package main

import (
	"context"
	"errors"
	"time"
)

const defaultMigrationTimeout = time.Hour

func migrationContext(parent context.Context, timeout time.Duration) (context.Context, context.CancelFunc, error) {
	if timeout < 0 {
		return nil, nil, errors.New("migration timeout must be nonnegative")
	}
	if timeout == 0 {
		ctx, cancel := context.WithCancel(parent)
		return ctx, cancel, nil
	}
	ctx, cancel := context.WithTimeout(parent, timeout)
	return ctx, cancel, nil
}
