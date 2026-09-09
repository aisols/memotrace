// SPDX-License-Identifier: AGPL-3.0-only
// Package contract contains the controlled canonical consumer snapshot. Validation
// is exercised against real HTTP requests/responses by the component test suite.
package contract

import (
	"bytes"
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"time"

	"github.com/dlclark/regexp2"
	"github.com/santhosh-tekuri/jsonschema/v6"
	"memotrace/server/internal/protocol"
)

//go:embed snapshot
var files embed.FS

type schemaRegexp struct{ *regexp2.Regexp }

func (r schemaRegexp) MatchString(s string) bool {
	matched, err := r.Regexp.MatchString(s)
	if err != nil {
		panic(fmt.Errorf("canonical schema regex validation failed: %w", err))
	}
	return matched
}
func newCompiler() *jsonschema.Compiler {
	c := jsonschema.NewCompiler()
	c.AssertFormat()
	c.UseRegexpEngine(func(pattern string) (jsonschema.Regexp, error) {
		r, err := regexp2.Compile(pattern, regexp2.ECMAScript|regexp2.Unicode)
		if err != nil {
			return nil, err
		}
		r.MatchTimeout = time.Second
		return schemaRegexp{r}, nil
	})
	return c
}

func CheckHashes() error {
	b, err := files.ReadFile("snapshot/manifest.json")
	if err != nil {
		return err
	}
	var m struct {
		ContractVersion string            `json:"contract_version"`
		SourceBase      string            `json:"source_base_revision"`
		Provenance      string            `json:"provenance"`
		Files           map[string]string `json:"files"`
	}
	if err = json.Unmarshal(b, &m); err != nil {
		return err
	}
	if m.ContractVersion != protocol.Version || m.SourceBase == "" || m.Provenance == "" || len(m.Files) != 3 {
		return fmt.Errorf("invalid snapshot provenance")
	}
	for _, name := range []string{"schemas/ingestion.schema.json", "openapi/ingestion.json", "VERSION"} {
		want, ok := m.Files[name]
		if !ok {
			return fmt.Errorf("missing snapshot file hash: %s", name)
		}
		b, err = files.ReadFile("snapshot/" + name)
		if err != nil {
			return err
		}
		h := sha256.Sum256(b)
		if hex.EncodeToString(h[:]) != want {
			return fmt.Errorf("snapshot checksum mismatch: %s", name)
		}
		if name == "VERSION" && !bytes.Equal(b, []byte(m.ContractVersion+"\n")) {
			return fmt.Errorf("snapshot VERSION differs from manifest/protocol")
		}
	}
	return nil
}

// CompileHeader uses the canonical OpenAPI document's base URI for relative refs.
// Header schemas still use the genuine JSON Schema validator, including constants.
func CompileHeader(schema any) (*jsonschema.Schema, error) {
	if err := CheckHashes(); err != nil {
		return nil, err
	}
	b, err := files.ReadFile("snapshot/schemas/ingestion.schema.json")
	if err != nil {
		return nil, err
	}
	doc, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		return nil, err
	}
	c := newCompiler()
	if err = c.AddResource("https://memotrace.example/contracts/0.1.0/schemas/ingestion.schema.json", doc); err != nil {
		return nil, err
	}
	const id = "https://memotrace.example/contracts/0.1.0/openapi/header.json"
	if err = c.AddResource(id, schema); err != nil {
		return nil, err
	}
	return c.Compile(id)
}
func Compile(def string) (*jsonschema.Schema, error) {
	if err := CheckHashes(); err != nil {
		return nil, err
	}
	b, err := files.ReadFile("snapshot/schemas/ingestion.schema.json")
	if err != nil {
		return nil, err
	}
	doc, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		return nil, err
	}
	c := newCompiler()
	const id = "https://memotrace.example/contracts/0.1.0/ingestion.schema.json"
	if err = c.AddResource(id, doc); err != nil {
		return nil, err
	}
	return c.Compile(id + "#/$defs/" + def)
}
func Validate(def string, b []byte) error {
	s, err := Compile(def)
	if err != nil {
		return err
	}
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		return err
	}
	return s.Validate(v)
}
