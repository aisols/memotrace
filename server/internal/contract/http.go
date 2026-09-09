// SPDX-License-Identifier: AGPL-3.0-only
package contract

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
)

// CheckResponse checks a real handler exchange against the snapshot's OpenAPI
// routing/status/media/schema and error-code definitions, rather than Go types.
func CheckResponse(method, path string, status int, headers http.Header, body []byte) error {
	b, err := files.ReadFile("snapshot/openapi/ingestion.json")
	if err != nil {
		return err
	}
	var api map[string]any
	if err = json.Unmarshal(b, &api); err != nil {
		return err
	}
	object := func(v any) map[string]any { m, _ := v.(map[string]any); return m }
	var operation map[string]any
	for template, item := range object(api["paths"]) {
		want, got := strings.Split(template, "/"), strings.Split(path, "/")
		if len(want) != len(got) {
			continue
		}
		match := true
		for i := range want {
			if want[i] != got[i] && !strings.HasPrefix(want[i], "{") {
				match = false
			}
		}
		if match {
			operation = object(object(item)[strings.ToLower(method)])
			break
		}
	}
	if headers.Get("Cache-Control") != "no-store" || headers.Get("X-Content-Type-Options") != "nosniff" {
		return fmt.Errorf("missing privacy headers")
	}
	if operation == nil {
		if status != 404 && status != 405 {
			return fmt.Errorf("undefined OpenAPI operation returned %d", status)
		}
		return Validate("Error", body)
	}
	response := object(object(operation["responses"])[strconv.Itoa(status)])
	if response == nil {
		return fmt.Errorf("undocumented HTTP status %d", status)
	}
	if ref, ok := response["$ref"].(string); ok {
		response = object(object(object(api["components"])["responses"])[strings.TrimPrefix(ref, "#/components/responses/")])
	}
	for name, definition := range object(response["headers"]) {
		header := object(definition)
		if ref, ok := header["$ref"].(string); ok {
			header = object(object(object(api["components"])["headers"])[strings.TrimPrefix(ref, "#/components/headers/")])
		}
		values := headers.Values(name)
		if len(values) == 0 {
			if header["required"] == true {
				return fmt.Errorf("missing required OpenAPI header: %s", name)
			}
			continue
		}
		if len(values) != 1 {
			return fmt.Errorf("unexpected repeated response header: %s", name)
		}
		var value any = values[0]
		if strings.EqualFold(name, "Content-Length") {
			n, err := strconv.ParseInt(values[0], 10, 64)
			if err != nil {
				return fmt.Errorf("invalid content length")
			}
			value = n
		}
		schema, err := CompileHeader(header["schema"])
		if err != nil {
			return err
		}
		if err = schema.Validate(value); err != nil {
			return fmt.Errorf("response header %s violates canonical schema: %w", name, err)
		}
	}
	media, _, _ := strings.Cut(headers.Get("Content-Type"), ";")
	content := object(object(response["content"])[media])
	if content == nil {
		return fmt.Errorf("undocumented media type %q", media)
	}
	if status >= 400 {
		var envelope struct {
			Error struct {
				Code string `json:"code"`
			} `json:"error"`
		}
		if err = json.Unmarshal(body, &envelope); err != nil {
			return err
		}
		allowed := false
		for _, code := range response["x-error-codes"].([]any) {
			if code == envelope.Error.Code {
				allowed = true
			}
		}
		if !allowed {
			return fmt.Errorf("undocumented error code for operation/status")
		}
	}
	if ref, ok := object(content["schema"])["$ref"].(string); ok {
		_, def, _ := strings.Cut(ref, "#/$defs/")
		return Validate(def, body)
	}
	if media == "image/jpeg" {
		n, err := strconv.Atoi(headers.Get("Content-Length"))
		if err != nil || n != len(body) {
			return fmt.Errorf("original content length differs")
		}
		return nil
	}
	return fmt.Errorf("unsupported response contract shape")
}
