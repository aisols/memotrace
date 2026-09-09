// SPDX-License-Identifier: AGPL-3.0-only
package protocol

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"image/jpeg"
	"io"
	"reflect"
	"regexp"
	"unicode/utf8"
)

const Version = "0.1.0"
const MaxBytes = 16777216
const MaxJSON = 1048576
const MaxTime int64 = 9007199254740991

var uuidPattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)
var hashPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)
var tokenPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{43}$`)

func UUID(s string) bool { return uuidPattern.MatchString(s) }
func Token(s string) bool {
	b, err := base64.RawURLEncoding.DecodeString(s)
	return tokenPattern.MatchString(s) && err == nil && len(b) == 32 && base64.RawURLEncoding.EncodeToString(b) == s
}
func NewID() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	b[6] = (b[6] & 15) | 64
	b[8] = (b[8] & 63) | 128
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[:4], b[4:6], b[6:8], b[8:10], b[10:])
}
func NewToken() string {
	b := make([]byte, 32)
	_, _ = rand.Read(b)
	return base64.RawURLEncoding.EncodeToString(b)
}
func Hash(b []byte) string { h := sha256.Sum256(b); return hex.EncodeToString(h[:]) }

type Profile struct {
	ID               string `json:"id"`
	RequestedWidth   int    `json:"requested_width"`
	RequestedHeight  int    `json:"requested_height"`
	JPEGQuality      int    `json:"jpeg_quality"`
	NegotiatedWidth  *int   `json:"negotiated_width,omitempty"`
	NegotiatedHeight *int   `json:"negotiated_height,omitempty"`
}
type Metadata struct {
	FrameID          string   `json:"frame_id"`
	RequestWallMS    *int64   `json:"request_wall_ms"`
	SHA256           string   `json:"sha256"`
	ByteLength       int64    `json:"byte_length"`
	SessionID        *string  `json:"session_id,omitempty"`
	RequestElapsedMS *int64   `json:"request_elapsed_ms,omitempty"`
	SavedWallMS      *int64   `json:"saved_wall_ms,omitempty"`
	CaptureSettings  *string  `json:"capture_settings,omitempty"`
	Profile          *Profile `json:"profile,omitempty"`
}
type ManifestRequest struct {
	Frames []Metadata `json:"frames"`
}
type Receipt struct {
	ContractVersion string `json:"contract_version"`
	ArchiveID       string `json:"archive_id"`
	FrameID         string `json:"frame_id"`
	SHA256          string `json:"sha256"`
	ByteLength      int64  `json:"byte_length"`
	CommittedAt     string `json:"committed_at"`
	Integrity       string `json:"integrity"`
	State           string `json:"state"`
}
type FrameState struct {
	FrameID string   `json:"frame_id"`
	State   string   `json:"state"`
	Receipt *Receipt `json:"receipt"`
}
type ManifestResponse struct {
	ContractVersion string       `json:"contract_version"`
	Frames          []FrameState `json:"frames"`
}
type PairRequest struct {
	InvitationToken string `json:"invitation_token"`
	DeviceName      string `json:"device_name"`
}
type PairResponse struct {
	ContractVersion string `json:"contract_version"`
	OwnerID         string `json:"owner_id"`
	ArchiveID       string `json:"archive_id"`
	DeviceID        string `json:"device_id"`
	DeviceToken     string `json:"device_token"`
}
type Invitation struct {
	ContractVersion      string `json:"contract_version"`
	ServerURL            string `json:"server_url"`
	TLSCertificateSHA256 string `json:"tls_certificate_sha256"`
	InvitationToken      string `json:"invitation_token"`
	ExpiresAt            string `json:"expires_at"`
	ArchiveID            string `json:"archive_id"`
}

type Error struct {
	Code      string `json:"code"`
	Message   string `json:"message"`
	Retryable bool   `json:"retryable"`
}

func (e *Error) Error() string { return e.Code }
func E(code string) *Error {
	return &Error{Code: code, Message: "Request could not be completed.", Retryable: code == "unavailable" || code == "checksum_mismatch" || code == "not_committed"}
}
func Status(code string) int {
	switch code {
	case "unauthorized":
		return 401
	case "not_found":
		return 404
	case "conflict", "not_committed", "integrity_error":
		return 409
	case "checksum_mismatch", "invalid_image":
		return 422
	case "payload_too_large":
		return 413
	case "unsupported_media_type":
		return 415
	case "unavailable":
		return 503
	default:
		return 400
	}
}

// StrictJSON rejects duplicate members, unknown fields, invalid Unicode scalars,
// trailing values, null requests, and case-insensitive field aliases.
func StrictJSON(b []byte, dst any) error {
	if !validJSONScalars(b) {
		return E("invalid_request")
	}
	d := json.NewDecoder(bytes.NewReader(b))
	d.UseNumber()
	var walk func() error
	depth := 0
	walk = func() error {
		depth++
		defer func() { depth-- }()
		if depth > 16 {
			return E("invalid_request")
		}
		t, err := d.Token()
		if err != nil {
			return err
		}
		if delim, ok := t.(json.Delim); ok {
			switch delim {
			case '{':
				seen := map[string]bool{}
				for d.More() {
					k, err := d.Token()
					if err != nil {
						return err
					}
					s, ok := k.(string)
					if !ok || seen[s] {
						return errors.New("duplicate member")
					}
					seen[s] = true
					if err := walk(); err != nil {
						return err
					}
				}
			case '[':
				for d.More() {
					if err := walk(); err != nil {
						return err
					}
				}
			default:
				return errors.New("invalid delimiter")
			}
			_, err = d.Token()
			return err
		}
		return nil
	}
	if err := walk(); err != nil {
		return E("invalid_request")
	}
	if _, err := d.Token(); err != io.EOF {
		return E("invalid_request")
	}
	var raw any
	d = json.NewDecoder(bytes.NewReader(b))
	d.UseNumber()
	if err := d.Decode(&raw); err != nil {
		return E("invalid_request")
	}
	if !requestShape(raw, reflect.TypeOf(dst).Elem()) {
		return E("invalid_request")
	}
	normalized, err := normalizeNumbers(raw)
	if err != nil {
		return E("invalid_request")
	}
	encoded, err := json.Marshal(normalized)
	if err != nil {
		return E("invalid_request")
	}
	d = json.NewDecoder(bytes.NewReader(encoded))
	d.DisallowUnknownFields()
	if err := d.Decode(dst); err != nil {
		return E("invalid_request")
	}
	return nil
}

func (m Metadata) Validate() error {
	validTime := func(p *int64) bool { return p == nil || (*p >= 0 && *p <= MaxTime) }
	if !UUID(m.FrameID) || m.RequestWallMS == nil || !validTime(m.RequestWallMS) || !hashPattern.MatchString(m.SHA256) || m.ByteLength < 1 || m.ByteLength > MaxBytes || !validTime(m.RequestElapsedMS) || !validTime(m.SavedWallMS) {
		return E("invalid_request")
	}
	if m.SessionID != nil && !UUID(*m.SessionID) {
		return E("invalid_request")
	}
	if m.CaptureSettings != nil && (!validText(*m.CaptureSettings) || utf8.RuneCountInString(*m.CaptureSettings) > 2048) {
		return E("invalid_request")
	}
	if p := m.Profile; p != nil {
		dim := func(n int) bool { return n >= 1 && n <= 16384 }
		if n := utf8.RuneCountInString(p.ID); !validText(p.ID) || n < 1 || n > 64 || !dim(p.RequestedWidth) || !dim(p.RequestedHeight) || p.JPEGQuality < 1 || p.JPEGQuality > 100 || (p.NegotiatedWidth != nil && !dim(*p.NegotiatedWidth)) || (p.NegotiatedHeight != nil && !dim(*p.NegotiatedHeight)) {
			return E("invalid_request")
		}
	}
	return nil
}
func (m ManifestRequest) Validate() error {
	if len(m.Frames) < 1 || len(m.Frames) > 100 {
		return E("invalid_request")
	}
	seen := map[string]bool{}
	for _, f := range m.Frames {
		if seen[f.FrameID] {
			return E("invalid_request")
		}
		seen[f.FrameID] = true
		if err := f.Validate(); err != nil {
			return err
		}
	}
	return nil
}
func (p PairRequest) Validate() error {
	n := utf8.RuneCountInString(p.DeviceName)
	if !validText(p.DeviceName) || n < 1 || n > 80 {
		return E("invalid_request")
	}
	if !Token(p.InvitationToken) {
		return E("unauthorized")
	}
	return nil
}

// CheckImage checks the original bytes, not a re-encoded image or full decode.
func CheckImage(r io.ReadSeeker, size int64, hash string, m Metadata) error {
	if size != m.ByteLength || hash != m.SHA256 {
		return E("checksum_mismatch")
	}
	if size < 4 {
		return E("invalid_image")
	}
	var marker [2]byte
	if _, err := r.Seek(0, io.SeekStart); err != nil {
		return err
	}
	if _, err := io.ReadFull(r, marker[:]); err != nil {
		return err
	}
	if marker != [2]byte{255, 216} {
		return E("invalid_image")
	}
	if _, err := r.Seek(-2, io.SeekEnd); err != nil {
		return err
	}
	if _, err := io.ReadFull(r, marker[:]); err != nil {
		return err
	}
	if marker != [2]byte{255, 217} {
		return E("invalid_image")
	}
	if _, err := r.Seek(0, io.SeekStart); err != nil {
		return err
	}
	c, err := jpeg.DecodeConfig(r)
	if err != nil || c.Width < 1 || c.Height < 1 || c.Width > 16384 || c.Height > 16384 || int64(c.Width)*int64(c.Height) > 40000000 {
		return E("invalid_image")
	}
	_, err = r.Seek(0, io.SeekStart)
	return err
}
