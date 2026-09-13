// SPDX-License-Identifier: AGPL-3.0-only
package retrieval

import (
	"encoding/json"
	"strconv"
	"strings"

	"memotrace/server/internal/protocol"
)

// QueryBox deliberately differs from a returned float64 region Box. json.Number
// marshals the original numeric lexeme, including subnormals and adjacent decimal
// endpoints that collapse to one float64. Python rasterizes these exact endpoints
// to touched pixels before any float conversion. No coordinate strings on the wire.
type QueryBox [4]json.Number

func (b QueryBox) Valid() bool {
	var d [4]decimal
	for i, n := range b {
		var ok bool
		d[i], ok = parseDecimal(n)
		if !ok || d[i].negative || compareMagnitude(d[i], decimalOne) > 0 {
			return false
		}
	}
	return compareMagnitude(d[0], d[2]) < 0 && compareMagnitude(d[1], d[3]) < 0
}

// Exponents themselves are stored as signed decimal integers. Memory/time are
// linear in input bytes (already <=1MiB), never in 10^exponent. This accepts exact
// comparisons even for million-digit exponents without a giant rational/power.
type decimalInteger struct {
	negative bool
	digits   string
}
type decimal struct {
	negative bool
	digits   string
	order    decimalInteger
}

var decimalOne = decimal{digits: "1", order: decimalInteger{digits: "1"}}

func parseDecimal(n json.Number) (decimal, bool) {
	s := n.String()
	if len(s) == 0 || len(s) > protocol.MaxJSON || (s[0] != '-' && (s[0] < '0' || s[0] > '9')) || strings.TrimSpace(s) != s || !json.Valid([]byte(s)) {
		return decimal{}, false
	}
	negative := strings.HasPrefix(s, "-")
	mantissa, exponent, _ := strings.Cut(strings.ToLower(strings.TrimPrefix(s, "-")), "e")
	whole, fraction, _ := strings.Cut(mantissa, ".")
	digits := strings.TrimLeft(whole+fraction, "0")
	if digits == "" {
		return decimal{}, true
	}
	order := shiftExponent(exponent, len(digits)-len(fraction))
	digits = strings.TrimRight(digits, "0")
	return decimal{negative: negative, digits: digits, order: order}, true
}

func unitDecimal(n json.Number, signed bool) bool {
	d, ok := parseDecimal(n)
	return ok && (signed || !d.negative) && compareMagnitude(d, decimalOne) <= 0
}

// CompareNumbers compares finite JSON decimal values without exponent expansion.
// The conformance oracle shares only this numeric primitive, not production
// ranking, clock selection or history assembly.
func CompareNumbers(a, b json.Number) (int, bool) {
	x, ok := parseDecimal(a)
	if !ok {
		return 0, false
	}
	y, ok := parseDecimal(b)
	if !ok {
		return 0, false
	}
	return compareDecimal(x, y), true
}
func compareDecimal(x, y decimal) int {
	if x.negative != y.negative {
		if x.negative {
			return -1
		}
		return 1
	}
	c := compareMagnitude(x, y)
	if x.negative {
		c = -c
	}
	return c
}

func compareMagnitude(a, b decimal) int {
	if a.digits == "" {
		if b.digits == "" {
			return 0
		}
		return -1
	}
	if b.digits == "" {
		return 1
	}
	if c := compareInteger(a.order, b.order); c != 0 {
		return c
	}
	// Significands have no trailing zeroes. Equal prefixes therefore order by
	// length without scanning/allocating implicit zero padding for the shorter.
	return strings.Compare(a.digits, b.digits)
}

func integer(s string) decimalInteger {
	negative := strings.HasPrefix(s, "-")
	digits := strings.TrimLeft(strings.TrimLeft(s, "+-"), "0")
	if digits == "" {
		return decimalInteger{digits: "0"}
	}
	return decimalInteger{negative: negative, digits: digits}
}
func compareDigits(a, b string) int {
	if len(a) < len(b) {
		return -1
	}
	if len(a) > len(b) {
		return 1
	}
	return strings.Compare(a, b)
}
func compareInteger(a, b decimalInteger) int {
	if a.negative != b.negative {
		if a.negative {
			return -1
		}
		return 1
	}
	c := compareDigits(a.digits, b.digits)
	if a.negative {
		return -c
	}
	return c
}
func shiftExponent(s string, shift int) decimalInteger {
	a, b := integer(s), integer(strconv.Itoa(shift))
	if a.negative == b.negative {
		a.digits = addDigits(a.digits, b.digits, 1)
		return a
	}
	if compareDigits(a.digits, b.digits) < 0 {
		a, b = b, a
	}
	a.digits = addDigits(a.digits, b.digits, -1)
	if a.digits == "0" {
		a.negative = false
	}
	return a
}

// sign=1 adds; sign=-1 subtracts magnitudes with a>=b. Carry/borrow propagates
// only over the exponent text, not an exponent-expanded coordinate value.
func addDigits(a, b string, sign int) string {
	out := make([]byte, max(len(a), len(b))+1)
	carry := 0
	for i, j, k := len(a)-1, len(b)-1, len(out)-1; k >= 0; i, j, k = i-1, j-1, k-1 {
		n := carry
		if i >= 0 {
			n += int(a[i] - '0')
		}
		if j >= 0 {
			n += sign * int(b[j]-'0')
		}
		carry = 0
		if n < 0 {
			n += 10
			carry = -1
		} else if n >= 10 {
			n -= 10
			carry = 1
		}
		out[k] = byte(n) + '0'
	}
	digits := strings.TrimLeft(string(out), "0")
	if digits == "" {
		return "0"
	}
	return digits
}
