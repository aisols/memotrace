// SPDX-License-Identifier: AGPL-3.0-only
package httpapi

import (
	"net"
	"sync"
)

// LimitConnections bounds accepted connections including idle clients and TLS
// handshakes, before HTTP admission. Close unblocks a saturated Accept on shutdown.
func LimitConnections(l net.Listener, n int) net.Listener {
	return &limitedListener{Listener: l, slots: make(chan struct{}, n), done: make(chan struct{})}
}

type limitedListener struct {
	net.Listener
	slots chan struct{}
	done  chan struct{}
	once  sync.Once
}

func (l *limitedListener) Accept() (net.Conn, error) {
	select {
	case l.slots <- struct{}{}:
	case <-l.done:
		return nil, net.ErrClosed
	}
	c, err := l.Listener.Accept()
	if err != nil {
		<-l.slots
		return nil, err
	}
	return &limitedConn{Conn: c, release: func() { <-l.slots }}, nil
}
func (l *limitedListener) Close() error {
	l.once.Do(func() { close(l.done) })
	return l.Listener.Close()
}

type limitedConn struct {
	net.Conn
	once    sync.Once
	release func()
}

func (c *limitedConn) Close() error { err := c.Conn.Close(); c.once.Do(c.release); return err }
