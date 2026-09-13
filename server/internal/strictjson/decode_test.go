// SPDX-License-Identifier: AGPL-3.0-only
package strictjson

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestValueRejectsDuplicateKeysTrailingValuesAndMalformedInput(t *testing.T) {
	for _, input := range []string{
		`{"key":1,"key":2}`,
		`{} []`,
		`{"key":`,
	} {
		if _, err := Value([]byte(input)); err == nil {
			t.Fatalf("accepted invalid JSON %q", input)
		}
	}
}

func TestValueEnforcesDepthLimit(t *testing.T) {
	withinLimit := strings.Repeat("[", 16) + "0" + strings.Repeat("]", 16)
	if _, err := Value([]byte(withinLimit)); err != nil {
		t.Fatalf("rejected value within depth limit: %v", err)
	}
	overLimit := strings.Repeat("[", 17) + "0" + strings.Repeat("]", 17)
	if _, err := Value([]byte(overLimit)); err == nil {
		t.Fatal("accepted value beyond depth limit")
	}
}

func TestDecodePreservesExactNumbers(t *testing.T) {
	const score = "0.123456789012345678901234567890"
	const count = int64(9007199254740993)
	var got struct {
		Score json.Number `json:"score"`
		Count int64       `json:"count"`
	}
	if err := Decode([]byte(`{"score":`+score+`,"count":9007199254740993}`), &got); err != nil {
		t.Fatal(err)
	}
	if got.Score.String() != score || got.Count != count {
		t.Fatalf("numbers changed: score=%q count=%d", got.Score, got.Count)
	}
}

func TestDecodeRejectsUnknownFields(t *testing.T) {
	var got struct {
		Known string `json:"known"`
	}
	if err := Decode([]byte(`{"known":"value","unknown":true}`), &got); err == nil {
		t.Fatal("accepted unknown field")
	}
}
