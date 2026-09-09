// SPDX-License-Identifier: AGPL-3.0-only
// Package archive implements the Linux local-filesystem durability boundary.
package archive

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"
	"syscall"

	"memotrace/server/internal/protocol"
)

// Faults are local dependency-injection hooks used by tests only. The executable
// never configures them; no environment variable or request can activate them.
type Faults struct{ BeforeWrite, FileSync, Publish, DirectorySync func() error }
type Files struct {
	root      *os.Root
	dir, lock *os.File
	Faults    Faults
}
type Staged struct {
	file *os.File
	name string
	fs   *Files
}

func Open(path string) (*Files, error) {
	if !filepath.IsAbs(path) {
		return nil, errors.New("data root must be absolute")
	}
	// Operator creates the root on the encrypted volume. Never recursively create
	// an arbitrary caller path. Root and its parent are synced even when preexisting.
	st, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if !st.IsDir() || st.Mode()&os.ModeSymlink != 0 || st.Mode().Perm()&0077 != 0 {
		return nil, errors.New("data root must be a private real directory")
	}
	r, err := os.OpenRoot(path)
	if err != nil {
		return nil, err
	}
	f := &Files{root: r}
	fail := func(e error) (*Files, error) { f.Close(); return nil, e }
	f.dir, err = r.OpenFile(".", os.O_RDONLY|syscall.O_DIRECTORY|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return fail(err)
	}
	f.lock, err = r.OpenFile(".lock", os.O_CREATE|os.O_RDWR|syscall.O_NOFOLLOW, 0600)
	if err != nil {
		return fail(err)
	}
	if err = syscall.Flock(int(f.lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		return fail(errors.New("data root already locked"))
	}
	if err = f.dir.Sync(); err != nil {
		return fail(err)
	}
	// Sync the existing ancestor chain: making the root itself durable is part of
	// the deployment boundary. No runtime archive subdirectories are created.
	for p := filepath.Dir(path); ; p = filepath.Dir(p) {
		d, e := os.Open(p)
		if e != nil {
			return fail(e)
		}
		e = d.Sync()
		d.Close()
		if e != nil {
			return fail(e)
		}
		if p == "/" {
			break
		}
	}
	return f, nil
}
func (f *Files) Close() error {
	if f.lock != nil {
		f.lock.Close()
	}
	if f.dir != nil {
		f.dir.Close()
	}
	if f.root != nil {
		return f.root.Close()
	}
	return nil
}
func Name(archive, frame string) (string, error) {
	if !protocol.UUID(archive) || !protocol.UUID(frame) {
		return "", protocol.E("invalid_request")
	}
	return archive + "_" + frame + ".jpg", nil
}
func call(h func() error) error {
	if h != nil {
		return h()
	}
	return nil
}
func (f *Files) Stage(r io.Reader, m protocol.Metadata) (*Staged, error) {
	name := ".stage-" + protocol.NewID()
	file, err := f.root.OpenFile(name, os.O_CREATE|os.O_EXCL|os.O_RDWR|syscall.O_NOFOLLOW, 0600)
	if err != nil {
		return nil, err
	}
	s := &Staged{file: file, name: name, fs: f}
	fail := func(e error) (*Staged, error) { s.Close(); return nil, e }
	if err = call(f.Faults.BeforeWrite); err != nil {
		return fail(err)
	}
	h := sha256.New()
	n, err := io.Copy(io.MultiWriter(file, h), io.LimitReader(r, protocol.MaxBytes+1))
	if err != nil {
		return fail(err)
	}
	if n > protocol.MaxBytes {
		return fail(protocol.E("payload_too_large"))
	}
	if err = protocol.CheckImage(file, n, hex.EncodeToString(h.Sum(nil)), m); err != nil {
		return fail(err)
	}
	if err = call(f.Faults.FileSync); err != nil {
		return fail(err)
	}
	if err = file.Sync(); err != nil {
		return fail(err)
	}
	return s, nil
}
func (s *Staged) Close() {
	if s.file != nil {
		s.file.Close()
		s.file = nil
	}
	_ = s.fs.root.Remove(s.name)
}
func (f *Files) syncDir() error {
	if err := call(f.Faults.DirectorySync); err != nil {
		return err
	}
	return f.dir.Sync()
}
func (f *Files) Publish(s *Staged, archive string, m protocol.Metadata) error {
	name, err := Name(archive, m.FrameID)
	if err != nil {
		return err
	}
	if err = call(f.Faults.Publish); err != nil {
		return err
	}
	// Hard-link insertion is atomic and never replaces an existing pathname. Stage
	// and original are on one filesystem and refer to the already-fsynced inode.
	err = f.root.Link(s.name, name)
	if errors.Is(err, os.ErrExist) {
		b, e := f.Read(archive, m)
		if e != nil {
			return e
		}
		_ = b
	} else if err != nil {
		return err
	}
	return f.syncDir()
}
func (f *Files) openOriginal(archive string, m protocol.Metadata) (*os.File, error) {
	name, err := Name(archive, m.FrameID)
	if err != nil {
		return nil, err
	}
	file, err := f.root.OpenFile(name, os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	st, err := file.Stat()
	if err != nil || !st.Mode().IsRegular() {
		file.Close()
		return nil, protocol.E("integrity_error")
	}
	return file, nil
}

// Read validates a bounded private copy before HTTP headers are emitted. In-flight
// downloads cannot serve a different second read if bytes are later corrupted.
func (f *Files) Read(archive string, m protocol.Metadata) ([]byte, error) {
	file, err := f.openOriginal(archive, m)
	if err != nil {
		return nil, protocol.E("integrity_error")
	}
	defer file.Close()
	return checkedBytes(file, m)
}
func checkedBytes(file *os.File, m protocol.Metadata) ([]byte, error) {
	b, err := io.ReadAll(io.LimitReader(file, protocol.MaxBytes+1))
	if err != nil {
		return nil, err
	}
	if len(b) > protocol.MaxBytes {
		return nil, protocol.E("integrity_error")
	}
	// Check from the same captured bytes that will be returned to the client.
	if err = protocol.CheckImage(bytes.NewReader(b), int64(len(b)), protocol.Hash(b), m); err != nil {
		return nil, protocol.E("integrity_error")
	}
	return b, nil
}
func (f *Files) Recover(archive string, m protocol.Metadata) (bool, error) {
	file, err := f.openOriginal(archive, m)
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, protocol.E("integrity_error")
	}
	defer file.Close()
	if _, err = checkedBytes(file, m); err != nil {
		return false, err
	}
	if err = file.Sync(); err != nil {
		return false, err
	}
	if err = f.syncDir(); err != nil {
		return false, err
	}
	return true, nil
}
