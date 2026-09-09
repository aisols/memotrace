// SPDX-License-Identifier: AGPL-3.0-only
package httpapi

import (
	"errors"
	"net"
	"testing"
	"time"
)

func TestConnectionLimitIncludesIdleAndUnblocksShutdown(t *testing.T) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	limited := LimitConnections(l, 1)
	defer limited.Close()
	client, err := net.Dial("tcp", l.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	accepted, err := limited.Accept()
	if err != nil {
		t.Fatal(err)
	}
	defer accepted.Close()
	result := make(chan error, 1)
	go func() { _, err := limited.Accept(); result <- err }()
	select {
	case err := <-result:
		t.Fatal("saturated listener accepted", err)
	case <-time.After(20 * time.Millisecond):
	}
	limited.Close()
	select {
	case err := <-result:
		if !errors.Is(err, net.ErrClosed) {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("shutdown did not unblock saturated accept")
	}
	if err := accepted.Close(); err != nil {
		t.Fatal(err)
	} // deferred second close must not release twice
}
