// SPDX-License-Identifier: AGPL-3.0-only
package retrieval

import (
	"encoding/json"
	"math"
	"math/big"
	"strings"
	"testing"

	"memotrace/server/internal/protocol"
)

func TestQueryDecimalBoxExactOrderAndWireRoundTrip(t *testing.T) {
	for _, box := range []string{`[0,0,1e-400,1]`, `[0.5,0,0.50000000000000001,1]`, `[0e99999,-0,1,1]`, `[1e-401,0,1e-400,1]`, `[0.10,0,0.1000000000000000001,1]`} {
		b := []byte(`{"generation_id":"` + strings.Repeat("a", 64) + `","query":{"asset_id":"` + protocol.NewID() + `","box":` + box + `}}`)
		r, err := DecodeRequest(b, false)
		if err != nil {
			t.Fatal("exact positive-area box rejected", box, err)
		}
		out, err := json.Marshal(r.Query.Box)
		if err != nil || string(out) != box {
			t.Fatal("query endpoints rounded on IPC marshal", box, string(out), err)
		}
	}
	for _, box := range []string{`[0.100,0,1e-1,1]`, `[1e-400,0,1e-401,1]`, `[0.50000000000000001,0,0.5,1]`, `[-1e-400,0,1,1]`, `[0,0,1.00000000000000001,1]`, `[0,0,"1e-400",1]`, `[0,0,0,1]`, `[0,1e-999,1,0]`} {
		b := []byte(`{"generation_id":"` + strings.Repeat("a", 64) + `","query":{"asset_id":"` + protocol.NewID() + `","box":` + box + `}}`)
		if _, err := DecodeRequest(b, false); err == nil {
			t.Fatal("invalid exact geometry accepted", box)
		}
	}
}

func TestDecimalComparisonMatchesIndependentSmallRationalOracle(t *testing.T) {
	// Rational construction is intentionally limited to small test exponents.
	// Production never constructs powers/rationals from unbounded exponent input.
	values := []string{"0", "-0", "0e-999", "1", "1.0", "1.00000000000000001", "0.99999999999999999", "0.5", "0.50000000000000001", "0.10", "1e-1", "123.45e-3", "12.345e-2", "1e-400", "2e-400", "1e-401", "100e-402", "1e+10", "1e-10", "0.000123e5", "0.000123e-5", "10e-1", "9.9e-1", "10e+1", "99e-1"}
	for _, a := range values {
		for _, b := range values {
			x, ok := parseDecimal(json.Number(a))
			if !ok {
				t.Fatal(a)
			}
			y, ok := parseDecimal(json.Number(b))
			if !ok {
				t.Fatal(b)
			}
			ra, _ := new(big.Rat).SetString(a)
			rb, _ := new(big.Rat).SetString(b)
			if got, want := compareMagnitude(x, y), ra.Cmp(rb); got != want {
				t.Fatalf("compare %s %s got%d want%d", a, b, got, want)
			}
		}
	}
	for _, n := range []json.Number{"", "NaN", "Infinity", "null", "true", `"1"`, "01", "1 ", "1e", json.Number(strings.Repeat("0", protocol.MaxJSON+1))} {
		if _, ok := parseDecimal(n); ok {
			t.Fatal("invalid numeric lexeme accepted")
		}
	}
	if unitDecimal("-1e-400", false) || !unitDecimal("-1e-400", true) || unitDecimal("-1.00000000000001", true) {
		t.Fatal("signed range check")
	}
	for _, a := range []json.Number{"-1", "-0.5", "-1e-400", "0", "1e-400", ".5"} {
		for _, b := range []json.Number{"-1", "-0.5", "0", "1", "null"} {
			x, xok := new(big.Rat).SetString(a.String())
			y, yok := new(big.Rat).SetString(b.String())
			got, ok := CompareNumbers(a, b)
			valid := xok && yok && json.Valid([]byte(a)) && json.Valid([]byte(b))
			if ok != valid || ok && got != x.Cmp(y) {
				t.Fatal("signed comparison differs from oracle", a, b, got, ok)
			}
		}
	}
}

func TestDecimalExtremeExponentComparisonBoundedByInput(t *testing.T) {
	// Huge negative powers remain distinguishable; exponent carrying/borrowing
	// works across arbitrarily long runs of 9/0 without exponent-sized allocation.
	nines := strings.Repeat("9", 100000)
	power := "1" + strings.Repeat("0", 100000)
	for _, tc := range []struct {
		a, b string
		want int
	}{
		{"1e-" + power, "1e-" + nines, -1},
		{"10e-" + power, "1e-" + nines, 0},
		{"100e-" + power, "1e-" + nines, 1},
		{"1e-" + power, "10e-" + power, -1},
		{"1e" + power, "1e" + nines, 1},
		{"1e-000000400", "1e-400", 0},
	} {
		a, ok := parseDecimal(json.Number(tc.a))
		if !ok {
			t.Fatal("parse exponent")
		}
		b, ok := parseDecimal(json.Number(tc.b))
		if !ok {
			t.Fatal("parse exponent")
		}
		if got := compareMagnitude(a, b); got != tc.want {
			t.Fatal("extreme exponent compare", got, tc.want)
		}
	}
	box := QueryBox{"0", "0", json.Number("1e-" + power), "1"}
	if !box.Valid() {
		t.Fatal("tiny positive exact box rejected")
	}
	if (QueryBox{"0", "0", json.Number("1e" + power), "1"}).Valid() {
		t.Fatal("huge positive box accepted")
	}
}

func TestExactScoreThresholdPreparedWithoutPerRegionExpansion(t *testing.T) {
	for _, tc := range []struct {
		threshold json.Number
		score     float64
		want      bool
	}{
		{"1e-400", 0, false}, {"-1e-400", 0, true}, {"0.50000000000000001", .5, false},
		{"0.5", .5, true}, {"-1", -1, true}, {"1", 1, true}, {"invalid", 0, false},
		{json.Number("0.5" + strings.Repeat("0", 100000) + "1"), .5, false},
		{json.Number("0.5" + strings.Repeat("0", 100000) + "1"), .6, true},
	} {
		r := Request{MinScore: &tc.threshold}
		accept := r.ScoreFilter()
		if got := accept(tc.score); got != tc.want {
			t.Fatal("exact threshold result", got, tc.want)
		}
	}
	accept := (Request{}).ScoreFilter()
	for _, value := range []float64{-1, 0, 1} {
		if !accept(value) {
			t.Fatal("default threshold", value)
		}
	}
	for _, value := range []float64{math.NaN(), math.Inf(1), 2, -2} {
		if accept(value) {
			t.Fatal("invalid score accepted")
		}
	}
}
