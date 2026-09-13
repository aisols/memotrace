// SPDX-License-Identifier: AGPL-3.0-only
package main

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestMigrationContextDeadline(t *testing.T) {
	before := time.Now()
	ctx, cancel, err := migrationContext(context.Background(), defaultMigrationTimeout)
	if err != nil {
		t.Fatal(err)
	}
	deadline, ok := ctx.Deadline()
	cancel()
	if !ok || deadline.Before(before.Add(defaultMigrationTimeout)) || deadline.After(time.Now().Add(defaultMigrationTimeout)) {
		t.Fatal("default migration deadline changed", deadline)
	}

	ctx, cancel, err = migrationContext(context.Background(), 0)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok = ctx.Deadline(); ok {
		t.Fatal("zero migration timeout installed a deadline")
	}
	cancel()
	if !errors.Is(ctx.Err(), context.Canceled) {
		t.Fatal("no-deadline migration context is not cancelable", ctx.Err())
	}

	if _, _, err = migrationContext(context.Background(), -time.Second); err == nil {
		t.Fatal("negative migration timeout accepted")
	}
}
