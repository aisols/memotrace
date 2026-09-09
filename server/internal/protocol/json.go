// SPDX-License-Identifier: AGPL-3.0-only
package protocol

import (
	"encoding/json"
	"reflect"
	"strconv"
	"strings"
)

// Request types use omitempty only for optional nullable fields. Check exact
// property names and required/non-null structure before Go's permissive decoder.
func requestShape(v any, t reflect.Type) bool {
	if v == nil {
		return false
	}
	for t.Kind() == reflect.Pointer {
		t = t.Elem()
	}
	switch t.Kind() {
	case reflect.Struct:
		m, ok := v.(map[string]any)
		if !ok {
			return false
		}
		known := map[string]bool{}
		for i := 0; i < t.NumField(); i++ {
			field := t.Field(i)
			name, options, _ := strings.Cut(field.Tag.Get("json"), ",")
			known[name] = true
			x, exists := m[name]
			optional := options == "omitempty"
			if !exists || x == nil {
				if !optional {
					return false
				}
				continue
			}
			if !requestShape(x, field.Type) {
				return false
			}
		}
		for name := range m {
			if !known[name] {
				return false
			}
		}
		return true
	case reflect.Slice:
		a, ok := v.([]any)
		if !ok {
			return false
		}
		for _, x := range a {
			if !requestShape(x, t.Elem()) {
				return false
			}
		}
		return true
	default:
		return true // Typed decoding below verifies primitive kinds.
	}
}
func normalizeNumbers(v any) (any, error) {
	switch x := v.(type) {
	case json.Number:
		return integral(x)
	case map[string]any:
		for k, y := range x {
			n, err := normalizeNumbers(y)
			if err != nil {
				return nil, err
			}
			x[k] = n
		}
	case []any:
		for i, y := range x {
			n, err := normalizeNumbers(y)
			if err != nil {
				return nil, err
			}
			x[i] = n
		}
	}
	return v, nil
}

// Normalize JSON Schema's mathematical integers without float rounding or huge
// exponent allocations. All protocol numeric fields fit in at most 16 digits.
func integral(n json.Number) (json.Number, error) {
	s := n.String()
	negative := strings.HasPrefix(s, "-")
	s = strings.TrimPrefix(s, "-")
	mantissa, exponent, hasExponent := strings.Cut(strings.ToLower(s), "e")
	whole, fraction, _ := strings.Cut(mantissa, ".")
	digits := strings.TrimLeft(whole+fraction, "0")
	if digits == "" {
		return json.Number("0"), nil
	}
	var exp int64
	var err error
	if hasExponent {
		exp, err = strconv.ParseInt(exponent, 10, 32)
		if err != nil {
			return "", E("invalid_request")
		}
	}
	scale := exp - int64(len(fraction))
	if scale < 0 {
		remove := -scale
		if remove >= int64(len(digits)) {
			return "", E("invalid_request")
		}
		cut := int64(len(digits)) - remove
		if strings.Trim(digits[cut:], "0") != "" {
			return "", E("invalid_request")
		}
		digits = digits[:cut]
	} else {
		if int64(len(digits))+scale > 16 {
			return "", E("invalid_request")
		}
		digits += strings.Repeat("0", int(scale))
	}
	if len(digits) > 16 {
		return "", E("invalid_request")
	}
	if negative {
		digits = "-" + digits
	}
	return json.Number(digits), nil
}
