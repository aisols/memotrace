// SPDX-License-Identifier: AGPL-3.0-only
package archive

import (
	"errors"
	"io"
	"strings"

	"memotrace/server/internal/protocol"
)

// Audit preserves and counts unknown originals and abandoned staging files;
// callers report aggregate diagnostics without logging private path identities.
func (f *Files) Audit(known func(string, string) (bool, error), datasetKnown ...func(string, string) (bool, error)) (unknown, stages int, err error) {
	dir, err := f.root.Open(".")
	if err != nil {
		return 0, 0, err
	}
	defer dir.Close()
	for {
		entries, e := dir.ReadDir(128)
		if e != nil && !errors.Is(e, io.EOF) {
			return unknown, stages, e
		}
		for _, entry := range entries {
			name := entry.Name()
			if name == ".lock" {
				continue
			}
			if strings.HasPrefix(name, ".stage-") && protocol.UUID(strings.TrimPrefix(name, ".stage-")) {
				stages++
				continue
			}
			check := known
			if strings.HasPrefix(name, "asset-") && len(datasetKnown) == 1 {
				name = strings.TrimPrefix(name, "asset-")
				check = datasetKnown[0]
			}
			if len(name) != 77 || name[36] != '_' || name[73:] != ".jpg" || !protocol.UUID(name[:36]) || !protocol.UUID(name[37:73]) || !entry.Type().IsRegular() {
				unknown++
				continue
			}
			ok, err := check(name[:36], name[37:73])
			if err != nil {
				return unknown, stages, err
			}
			if !ok {
				unknown++
			}
		}
		if errors.Is(e, io.EOF) {
			break
		}
	}
	return unknown, stages, nil
}
