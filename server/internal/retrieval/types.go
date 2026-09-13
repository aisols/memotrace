// SPDX-License-Identifier: AGPL-3.0-only
// Package retrieval defines the bounded exact-cosine experiment's wire/domain.
package retrieval

import (
	"encoding/json"
	"math"
	"strconv"
	"strings"
	"unicode/utf8"

	"memotrace/server/internal/protocol"
)

const Version = "0.2.0"
const MaxAssets = 5000
const MaxVectors = 50000
const MaxDimension = 4096
const MaxRegions = 64
const MaxDatasetIdentityBytes = 1024

type Box [4]float64

func (b Box) Valid() bool {
	for _, x := range b {
		if !Finite(x) || x < 0 || x > 1 {
			return false
		}
	}
	return b[0] < b[2] && b[1] < b[3]
}
func Finite(x float64) bool { return !math.IsNaN(x) && !math.IsInf(x, 0) }
func Hash(s string) bool {
	return len(s) == 64 && strings.Trim(s, "0123456789abcdef") == ""
}
func Text(s string, max int) bool {
	n := utf8.RuneCountInString(s)
	return utf8.ValidString(s) && n > 0 && n <= max && !strings.ContainsRune(s, 0)
}
func DatasetIdentityValid(name, version, item string) bool {
	return Text(name, 256) && Text(version, 256) && Text(item, 256) && len(name)+len(version)+len(item) <= MaxDatasetIdentityBytes
}
func Time(p *int64) bool { return p == nil || *p >= 0 && *p <= protocol.MaxTime }

type Query struct {
	Text    *string   `json:"text,omitempty"`
	AssetID *string   `json:"asset_id,omitempty"`
	Box     *QueryBox `json:"box,omitempty"`
}
type Timeline struct {
	Kind       string  `json:"kind"`
	SequenceID *string `json:"sequence_id,omitempty"`
}
type Request struct {
	GenerationID string       `json:"generation_id"`
	Query        Query        `json:"query"`
	Limit        *int         `json:"limit,omitempty"`
	MinScore     *json.Number `json:"min_score,omitempty"`
	Timeline     *Timeline    `json:"timeline,omitempty"`
	BeforeMS     *int64       `json:"before_ms,omitempty"`
	GapMS        *int64       `json:"gap_ms,omitempty"`
}

func (r Request) Validate(history bool) error {
	bad := protocol.E("invalid_request")
	if !Hash(r.GenerationID) || (r.Query.Text == nil) == (r.Query.AssetID == nil) {
		return bad
	}
	if r.Query.Text != nil && (!Text(*r.Query.Text, 2048) || r.Query.Box != nil) {
		return bad
	}
	if r.Query.AssetID != nil && !protocol.UUID(*r.Query.AssetID) {
		return bad
	}
	if r.Query.Box != nil && !r.Query.Box.Valid() {
		return bad
	}
	if r.Limit != nil && (*r.Limit < 1 || *r.Limit > 100) {
		return bad
	}
	if history && r.MinScore == nil {
		return bad
	}
	if r.MinScore != nil && !unitDecimal(*r.MinScore, true) {
		return bad
	}
	if !Time(r.BeforeMS) || r.BeforeMS != nil && r.Timeline == nil {
		return bad
	}
	if t := r.Timeline; t != nil {
		if t.Kind == "wall" {
			if t.SequenceID != nil {
				return bad
			}
		} else if t.Kind != "sequence" || t.SequenceID == nil || !Text(*t.SequenceID, 256) {
			return bad
		}
	}
	if r.GapMS != nil && (!history || *r.GapMS < 0 || *r.GapMS > 3600000) {
		return bad
	}
	return nil
}
func (r Request) ResultLimit() int {
	if r.Limit != nil {
		return *r.Limit
	}
	return 20
}

// ScoreFilter prepares the exact decimal threshold once, not per stored region.
// Comparisons use the score's JSON decimal representation and a normalized
// significand, so even a near-endpoint million-byte threshold cannot multiply
// parsing or zero-padding work by the corpus size.
func (r Request) ScoreFilter() func(float64) bool {
	limit := decimalOne
	limit.negative = true
	valid := true
	if r.MinScore != nil {
		limit, valid = parseDecimal(*r.MinScore)
	}
	return func(score float64) bool {
		if !valid || !Finite(score) || score < -1 || score > 1 {
			return false
		}
		value, _ := parseDecimal(json.Number(strconv.FormatFloat(score, 'g', -1, 64)))
		return compareDecimal(value, limit) >= 0
	}
}

type Dataset struct {
	Name    string `json:"name"`
	Version string `json:"version"`
	ItemID  string `json:"item_id"`
}
type Region struct {
	Kind string `json:"kind"`
	Box  Box    `json:"box"`
}
type Hit struct {
	AssetID            string   `json:"asset_id"`
	SourceKind         string   `json:"source_kind"`
	FrameID            *string  `json:"frame_id"`
	Dataset            *Dataset `json:"dataset"`
	SHA256             string   `json:"sha256"`
	Score              float64  `json:"score"`
	Region             Region   `json:"region"`
	ObservedAtMS       *int64   `json:"observed_at_ms"`
	SequenceID         *string  `json:"sequence_id"`
	SequencePositionMS *int64   `json:"sequence_position_ms"`
	OriginalPath       string   `json:"original_path"`
}
type Coverage struct {
	AssetsTotal    int `json:"assets_total"`
	AssetsIndexed  int `json:"assets_indexed"`
	Pending        int `json:"pending"`
	Failed         int `json:"failed"`
	RegionsIndexed int `json:"regions_indexed"`
}

func (c Coverage) Partial() bool { return c.AssetsIndexed < c.AssetsTotal }

type SearchResponse struct {
	ContractVersion string   `json:"contract_version"`
	ArchiveID       string   `json:"archive_id"`
	GenerationID    string   `json:"generation_id"`
	Coverage        Coverage `json:"coverage"`
	Hits            []Hit    `json:"hits"`
	Truncated       bool     `json:"truncated"`
}
type Observation struct {
	StartMS  int64   `json:"start_ms"`
	EndMS    int64   `json:"end_ms"`
	MaxScore float64 `json:"max_score"`
	Evidence []Hit   `json:"evidence"`
}
type HistoryResponse struct {
	ContractVersion  string        `json:"contract_version"`
	ArchiveID        string        `json:"archive_id"`
	GenerationID     string        `json:"generation_id"`
	Coverage         Coverage      `json:"coverage"`
	Timeline         *Timeline     `json:"timeline"`
	HistoryAvailable bool          `json:"history_available"`
	Observations     []Observation `json:"observations"`
	UnsequencedHits  []Hit         `json:"unsequenced_hits"`
	FirstObservedMS  *int64        `json:"first_observed_ms"`
	LastObservedMS   *int64        `json:"last_observed_ms"`
	Truncated        bool          `json:"truncated"`
	Interpretation   string        `json:"interpretation"`
}

type Description struct {
	ModelFingerprint     string            `json:"model_fingerprint"`
	Dimension            int               `json:"dimension"`
	ModelID              string            `json:"model_id"`
	ModelRevision        string            `json:"model_revision"`
	InputResolution      int               `json:"input_resolution"`
	PreprocessingVersion string            `json:"preprocessing_version"`
	Policies             map[string]string `json:"policies"`
}

func (d Description) Valid() bool {
	return Hash(d.ModelFingerprint) && d.Dimension > 0 && d.Dimension <= MaxDimension && Text(d.ModelID, 256) && Text(d.ModelRevision, 256) && (d.InputResolution == 224 || d.InputResolution == 384) && Text(d.PreprocessingVersion, 256) && len(d.Policies) == 2 && Hash(d.Policies["full"]) && Hash(d.Policies["overlap"])
}
func (d Description) Generation(mode string) string {
	return protocol.Hash([]byte(d.ModelFingerprint + ":" + d.Policies[mode]))
}
func (d Description) Equal(other Description) bool {
	if d.ModelFingerprint != other.ModelFingerprint || d.Dimension != other.Dimension || d.ModelID != other.ModelID || d.ModelRevision != other.ModelRevision || d.InputResolution != other.InputResolution || d.PreprocessingVersion != other.PreprocessingVersion || len(d.Policies) != len(other.Policies) {
		return false
	}
	for mode, fingerprint := range d.Policies {
		if other.Policies[mode] != fingerprint {
			return false
		}
	}
	return true
}

type Vector struct {
	Kind      string    `json:"kind"`
	Box       Box       `json:"box"`
	Embedding []float32 `json:"embedding"`
}

func Unit(v []float32, dimension int) bool {
	if len(v) != dimension {
		return false
	}
	var n float64
	for _, x := range v {
		if !Finite(float64(x)) {
			return false
		}
		n += float64(x) * float64(x)
	}
	return math.Abs(n-1) <= 0.002
}

type ImageResult struct {
	ModelFingerprint  string   `json:"model_fingerprint"`
	PolicyFingerprint string   `json:"policy_fingerprint"`
	Width             int      `json:"width"`
	Height            int      `json:"height"`
	Vectors           []Vector `json:"vectors"`
}

func (r ImageResult) Valid(d Description, mode string) bool {
	if mode != "full" && mode != "overlap" {
		return false
	}
	if r.ModelFingerprint != d.ModelFingerprint || r.PolicyFingerprint != d.Policies[mode] || r.Width < 1 || r.Height < 1 || r.Width > 16384 || r.Height > 16384 || int64(r.Width)*int64(r.Height) > 40000000 || len(r.Vectors) < 1 || len(r.Vectors) > MaxRegions || mode == "full" && len(r.Vectors) != 1 {
		return false
	}
	full := 0
	seen := map[Box]bool{}
	for _, v := range r.Vectors {
		if !v.Box.Valid() || !Unit(v.Embedding, d.Dimension) || seen[v.Box] {
			return false
		}
		seen[v.Box] = true
		if v.Kind == "full" {
			full++
			if v.Box != (Box{0, 0, 1, 1}) {
				return false
			}
		} else if v.Kind != "crop" {
			return false
		}
	}
	return full == 1
}
