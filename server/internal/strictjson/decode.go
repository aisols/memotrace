// SPDX-License-Identifier: AGPL-3.0-only
// Package strictjson is the retrieval/private-IPC decoder. Unlike legacy ingestion
// it preserves decimal numbers, normalizing only fields whose Go type is integer.
package strictjson

import (
	"bytes"
	"encoding/json"
	"io"
	"reflect"
	"strings"

	"memotrace/server/internal/protocol"
)

func Value(b []byte) (any, error) {
	bad := protocol.E("invalid_request")
	if !protocol.ValidJSONScalars(b) {
		return nil, bad
	}
	d := json.NewDecoder(bytes.NewReader(b))
	d.UseNumber()
	var walk func(int) (any, error)
	walk = func(depth int) (any, error) {
		if depth > 16 {
			return nil, bad
		}
		t, err := d.Token()
		if err != nil {
			return nil, bad
		}
		switch t {
		case json.Delim('{'):
			m := map[string]any{}
			for d.More() {
				k, e := d.Token()
				if e != nil {
					return nil, bad
				}
				s, ok := k.(string)
				if !ok {
					return nil, bad
				}
				if _, ok = m[s]; ok {
					return nil, bad
				}
				v, e := walk(depth + 1)
				if e != nil {
					return nil, e
				}
				m[s] = v
			}
			end, e := d.Token()
			if e != nil || end != json.Delim('}') {
				return nil, bad
			}
			return m, nil
		case json.Delim('['):
			a := []any{}
			for d.More() {
				v, e := walk(depth + 1)
				if e != nil {
					return nil, e
				}
				a = append(a, v)
			}
			end, e := d.Token()
			if e != nil || end != json.Delim(']') {
				return nil, bad
			}
			return a, nil
		}
		if _, ok := t.(json.Delim); ok {
			return nil, bad
		}
		return t, nil
	}
	v, err := walk(0)
	if err != nil {
		return nil, err
	}
	if _, err = d.Token(); err != io.EOF {
		return nil, bad
	}
	return v, nil
}
func Decode(b []byte, dst any) error {
	v, err := Value(b)
	if err != nil {
		return err
	}
	return Assign(v, dst)
}
func Assign(v any, dst any) error {
	t := reflect.TypeOf(dst)
	if t == nil || t.Kind() != reflect.Pointer {
		return protocol.E("invalid_request")
	}
	n, err := typed(v, t.Elem())
	if err != nil {
		return err
	}
	b, err := json.Marshal(n)
	if err != nil {
		return protocol.E("invalid_request")
	}
	d := json.NewDecoder(bytes.NewReader(b))
	d.DisallowUnknownFields()
	d.UseNumber()
	if err = d.Decode(dst); err != nil {
		return protocol.E("invalid_request")
	}
	return nil
}
func typed(v any, t reflect.Type) (any, error) {
	bad := protocol.E("invalid_request")
	if v == nil {
		if t.Kind() == reflect.Pointer || t.Kind() == reflect.Slice || t.Kind() == reflect.Map {
			return nil, nil
		}
		return nil, bad
	}
	for t.Kind() == reflect.Pointer {
		t = t.Elem()
	}
	// encoding/json also accepts quoted numeric strings into json.Number; the
	// strict wire requires actual number tokens for decimal fields.
	if t == reflect.TypeFor[json.Number]() {
		if _, ok := v.(json.Number); !ok {
			return nil, bad
		}
		return v, nil
	}
	switch t.Kind() {
	case reflect.Struct:
		m, ok := v.(map[string]any)
		if !ok {
			return nil, bad
		}
		fields := map[string]reflect.Type{}
		for i := 0; i < t.NumField(); i++ {
			f := t.Field(i)
			name, _, _ := strings.Cut(f.Tag.Get("json"), ",")
			if name != "-" {
				fields[name] = f.Type
			}
		}
		for k, x := range m {
			ft, ok := fields[k]
			if !ok {
				return nil, bad
			}
			n, e := typed(x, ft)
			if e != nil {
				return nil, e
			}
			m[k] = n
		}
		return m, nil
	case reflect.Map:
		m, ok := v.(map[string]any)
		if !ok {
			return nil, bad
		}
		for k, x := range m {
			n, e := typed(x, t.Elem())
			if e != nil {
				return nil, e
			}
			m[k] = n
		}
		return m, nil
	case reflect.Slice, reflect.Array:
		a, ok := v.([]any)
		if !ok || t.Kind() == reflect.Array && len(a) != t.Len() {
			return nil, bad
		}
		for i, x := range a {
			n, e := typed(x, t.Elem())
			if e != nil {
				return nil, e
			}
			a[i] = n
		}
		return a, nil
	case reflect.Int, reflect.Int64, reflect.Int32:
		n, ok := v.(json.Number)
		if !ok {
			return nil, bad
		}
		return protocol.IntegralNumber(n)
	}
	return v, nil
}
