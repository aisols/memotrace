// SPDX-License-Identifier: AGPL-3.0-only
package archive

import (
	"bytes"
	"errors"
	"image"
	"image/jpeg"
	"os"
	"path/filepath"
	"syscall"
	"testing"

	"memotrace/server/internal/protocol"
)

func fixture(t *testing.T) ([]byte, protocol.Metadata) {
	t.Helper()
	var b bytes.Buffer
	if err := jpeg.Encode(&b, image.NewRGBA(image.Rect(0, 0, 2, 3)), nil); err != nil {
		t.Fatal(err)
	}
	wall := int64(0)
	return b.Bytes(), protocol.Metadata{FrameID: protocol.NewID(), RequestWallMS: &wall, ByteLength: int64(b.Len()), SHA256: protocol.Hash(b.Bytes())}
}
func TestExclusiveRootNoClobberAndSymlinkDefense(t *testing.T) {
	root := t.TempDir()
	if err := os.Chmod(root, 0700); err != nil {
		t.Fatal(err)
	}
	fs, err := Open(root)
	if err != nil {
		t.Fatal(err)
	}
	defer fs.Close()
	if second, err := Open(root); err == nil {
		second.Close()
		t.Fatal("exclusive lock not enforced")
	}
	b, m := fixture(t)
	a := protocol.NewID()
	s, err := fs.Stage(bytes.NewReader(b), m)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if err = fs.Publish(s, a, m); err != nil {
		t.Fatal(err)
	}
	if err = fs.Publish(s, a, m); err != nil {
		t.Fatal(err)
	}
	got, err := fs.Read(a, m)
	if err != nil || !bytes.Equal(b, got) {
		t.Fatal("exact original lost", err)
	}
	name, _ := Name(a, m.FrameID)
	if err = os.WriteFile(filepath.Join(root, name), []byte("corrupt"), 0600); err != nil {
		t.Fatal(err)
	}
	if err = fs.Publish(s, a, m); err == nil {
		t.Fatal("corrupt original silently replaced")
	}
	if _, err = fs.Read(a, m); err == nil {
		t.Fatal("corrupt bytes served")
	}
	m.FrameID = protocol.NewID()
	name, _ = Name(a, m.FrameID)
	outside := filepath.Join(t.TempDir(), "secret")
	if err = os.WriteFile(outside, b, 0600); err != nil {
		t.Fatal(err)
	}
	if err = os.Symlink(outside, filepath.Join(root, name)); err != nil {
		t.Fatal(err)
	}
	if _, err = fs.Read(a, m); err == nil {
		t.Fatal("symlink followed")
	}
	if _, err = fs.Recover(a, m); err == nil {
		t.Fatal("symlink recovered")
	}
	if _, err = Name("../x", m.FrameID); err == nil {
		t.Fatal("caller path allowed")
	}
}
func TestDiskFullFileSyncPublishAndDirectorySyncFaults(t *testing.T) {
	for _, point := range []string{"diskfull", "fileSync", "publish", "directorySync"} {
		t.Run(point, func(t *testing.T) {
			root := t.TempDir()
			if err := os.Chmod(root, 0700); err != nil {
				t.Fatal(err)
			}
			fs, err := Open(root)
			if err != nil {
				t.Fatal(err)
			}
			defer fs.Close()
			failure := func() error { return syscall.ENOSPC }
			b, m := fixture(t)
			a := protocol.NewID()
			switch point {
			case "diskfull":
				fs.Faults.BeforeWrite = failure
			case "fileSync":
				fs.Faults.FileSync = failure
			case "publish":
				fs.Faults.Publish = failure
			case "directorySync":
				fs.Faults.DirectorySync = failure
			}
			s, err := fs.Stage(bytes.NewReader(b), m)
			if point == "diskfull" || point == "fileSync" {
				if !errors.Is(err, syscall.ENOSPC) {
					t.Fatal(err)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			defer s.Close()
			if err = fs.Publish(s, a, m); !errors.Is(err, syscall.ENOSPC) {
				t.Fatal(err)
			}
			fs.Faults = Faults{}
			ok, err := fs.Recover(a, m)
			if err != nil || ok != (point == "directorySync") {
				t.Fatal("publication boundary", ok, err)
			}
		})
	}
}
func TestStreamingLimitAndPrivateRoot(t *testing.T) {
	root := t.TempDir()
	if err := os.Chmod(root, 0755); err != nil {
		t.Fatal(err)
	}
	if f, err := Open(root); err == nil {
		f.Close()
		t.Fatal("public root allowed")
	}
	if _, err := Open("relative"); err == nil {
		t.Fatal("relative root allowed")
	}
	if err := os.Chmod(root, 0700); err != nil {
		t.Fatal(err)
	}
	fs, err := Open(root)
	if err != nil {
		t.Fatal(err)
	}
	defer fs.Close()
	_, m := fixture(t)
	if _, err = fs.Stage(bytes.NewReader(make([]byte, protocol.MaxBytes+1)), m); err == nil || err.Error() != "payload_too_large" {
		t.Fatal(err)
	}
}

func TestAuditPreservesUnknownAndAbandonedStage(t *testing.T) {
	root := t.TempDir()
	if err := os.Chmod(root, 0700); err != nil {
		t.Fatal(err)
	}
	fs, err := Open(root)
	if err != nil {
		t.Fatal(err)
	}
	defer fs.Close()
	b, m := fixture(t)
	a := protocol.NewID()
	name, _ := Name(a, m.FrameID)
	for _, n := range []string{name, "unknown-evidence", ".stage-" + protocol.NewID()} {
		if err = os.WriteFile(filepath.Join(root, n), b, 0600); err != nil {
			t.Fatal(err)
		}
	}
	unknown, stages, err := fs.Audit(func(a, f string) (bool, error) { return false, nil })
	if err != nil || unknown != 2 || stages != 1 {
		t.Fatal(unknown, stages, err)
	}
	if _, err = os.Stat(filepath.Join(root, name)); err != nil {
		t.Fatal("unknown evidence deleted", err)
	}
	if _, err = os.Stat(filepath.Join(root, "unknown-evidence")); err != nil {
		t.Fatal("unknown entry deleted", err)
	}
}
