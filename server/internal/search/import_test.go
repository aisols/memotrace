// SPDX-License-Identifier: AGPL-3.0-only
package search

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestManifestPathsTimesAndResourceLimits(t *testing.T) {
	path := filepath.Join(t.TempDir(), "manifest.json")
	valid := Manifest{Version: "1", Dataset: DatasetInfo{Name: "synthetic", Version: "1", Source: "generated", License: "AGPL-3.0-only"}, Items: []DatasetItem{{ID: "item", Path: "images/a.jpg", SHA256: strings.Repeat("a", 64), ByteLength: 10}}}
	b, _ := json.Marshal(valid)
	check := func(raw []byte, want bool) {
		t.Helper()
		if e := os.WriteFile(path, raw, 0600); e != nil {
			t.Fatal(e)
		}
		_, _, e := ReadManifest(path)
		if (e == nil) != want {
			t.Fatalf("accepted=%v want=%v: %s", e == nil, want, raw)
		}
	}
	check(b, true)
	boundary := valid
	boundary.Dataset.Name = strings.Repeat("\U0001f600", 255)
	boundary.Dataset.Version = "\u00e9"
	boundary.Items = append([]DatasetItem(nil), valid.Items...)
	boundary.Items[0].ID = "\u00e9"
	raw, _ := json.Marshal(boundary)
	check(raw, true)
	boundary.Items[0].ID = "\u754c"
	raw, _ = json.Marshal(boundary)
	check(raw, false)
	for _, bad := range []string{"../a.jpg", "/a.jpg", "images/../../a.jpg", "a\\b.jpg", "./a.jpg", "a//b.jpg", ".", "a/../b.jpg", "a\x00.jpg"} {
		m := valid
		m.Items = append([]DatasetItem(nil), valid.Items...)
		m.Items[0].Path = bad
		raw, _ := json.Marshal(m)
		check(raw, false)
	}
	for _, field := range []string{"observed_at_ms", "sequence_id", "sequence_position_ms"} {
		var m map[string]any
		_ = json.Unmarshal(b, &m)
		delete(m["items"].([]any)[0].(map[string]any), field)
		raw, _ := json.Marshal(m)
		check(raw, false)
	}
	for _, mutate := range []func(*Manifest){func(m *Manifest) { m.Items = append(m.Items, m.Items[0]) }, func(m *Manifest) { x := int64(-1); m.Items[0].ObservedAtMS = &x }, func(m *Manifest) { s := "clip"; m.Items[0].SequenceID = &s }, func(m *Manifest) { m.Items[0].SHA256 = "bad" }, func(m *Manifest) { m.Items[0].ByteLength = 16777217 }, func(m *Manifest) { m.Version = "2" }, func(m *Manifest) { m.Dataset.Name = "" }} {
		var m Manifest
		_ = json.Unmarshal(b, &m)
		mutate(&m)
		raw, _ := json.Marshal(m)
		check(raw, false)
	}
	check([]byte(strings.Replace(string(b), `"version":"1"`, `"version":"1","version":"1"`, 1)), false)
}
