// SPDX-License-Identifier: AGPL-3.0-only
package archive

import (
	"bytes"
	"errors"
	"os"
	"syscall"

	"memotrace/server/internal/protocol"
)

// Dataset artifacts use a distinct server-generated namespace. No manifest path
// reaches this API and no synthetic legacy timestamp/capture record is required.
func datasetName(archive, id string) (string, error) {
	n, e := Name(archive, id)
	return "asset-" + n, e
}
func (f *Files) PublishDataset(archive, id, hash string, b []byte) error {
	name, err := datasetName(archive, id)
	if err != nil {
		return err
	}
	m := protocol.Metadata{SHA256: hash, ByteLength: int64(len(b))}
	s, err := f.Stage(bytes.NewReader(b), m)
	if err != nil {
		return err
	}
	defer s.Close()
	if err = call(f.Faults.Publish); err != nil {
		return err
	}
	err = f.root.Link(s.name, name)
	if errors.Is(err, os.ErrExist) {
		_, err = f.ReadDataset(archive, id, hash, int64(len(b)))
	}
	if err != nil {
		return err
	}
	return f.syncDir()
}
func (f *Files) ReadDataset(archive, id, hash string, length int64) ([]byte, error) {
	name, err := datasetName(archive, id)
	if err != nil {
		return nil, err
	}
	file, err := f.root.OpenFile(name, os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, protocol.E("integrity_error")
	}
	defer file.Close()
	st, err := file.Stat()
	if err != nil || !st.Mode().IsRegular() {
		return nil, protocol.E("integrity_error")
	}
	return checkedBytes(file, protocol.Metadata{SHA256: hash, ByteLength: length})
}
