// SPDX-License-Identifier: AGPL-3.0-only
package protocol

import (
	"strings"
	"unicode/utf8"
)

// Text fields are Unicode scalar values excluding NUL, matching the canonical
// contract and PostgreSQL text/jsonb. Never strip or replace rejected input.
func validText(s string) bool {
	return utf8.ValidString(s) && !strings.ContainsRune(s, 0)
}

// Go's JSON decoder replaces unpaired UTF-16 surrogate escapes with U+FFFD.
// Check every raw JSON string (keys and values) before that lossy decoding step.
// Non-Unicode escapes are skipped as units; the JSON decoder checks their syntax.
func validJSONScalars(b []byte) bool {
	if !utf8.Valid(b) {
		return false
	}
	inString := false
	for i := 0; i < len(b); i++ {
		if b[i] == '"' {
			inString = !inString
			continue
		}
		if !inString || b[i] != '\\' {
			continue
		}
		if i+1 >= len(b) {
			return false
		}
		if b[i+1] != 'u' {
			i++
			continue
		}
		u, ok := escapedUnit(b[i:])
		if !ok {
			return false
		}
		if u >= 0xdc00 && u <= 0xdfff {
			return false
		}
		if u >= 0xd800 && u <= 0xdbff {
			low, ok := escapedUnit(b[i+6:])
			if !ok || low < 0xdc00 || low > 0xdfff {
				return false
			}
			i += 6
		}
		i += 5
	}
	return true
}

func escapedUnit(b []byte) (uint16, bool) {
	if len(b) < 6 || b[0] != '\\' || b[1] != 'u' {
		return 0, false
	}
	var unit uint16
	for _, c := range b[2:6] {
		unit <<= 4
		switch {
		case c >= '0' && c <= '9':
			unit |= uint16(c - '0')
		case c >= 'a' && c <= 'f':
			unit |= uint16(c - 'a' + 10)
		case c >= 'A' && c <= 'F':
			unit |= uint16(c - 'A' + 10)
		default:
			return 0, false
		}
	}
	return unit, true
}
