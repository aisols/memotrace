// SPDX-License-Identifier: AGPL-3.0-only
package httpapi

import (
	"bytes"
	"image/jpeg"
	"testing"

	"memotrace/server/internal/protocol"
)

func TestHTTPJPEGHeaderDimensionAndPixelBoundaries(t *testing.T) {
	h := setup(t)
	p := h.pair(h.owner())
	source, _ := synthetic()
	for _, tc := range []struct {
		name                  string
		width, height, status int
	}{
		{"maximum_width", 16384, 1, 200}, {"maximum_height", 1, 16384, 200}, {"maximum_pixels", 8000, 5000, 200},
		{"excess_width", 16385, 1, 422}, {"excess_height", 1, 16385, 422}, {"excess_pixels", 8000, 5001, 422},
	} {
		t.Run(tc.name, func(t *testing.T) {
			child := *h
			child.t = t
			h := &child
			// Synthetic SOF dimensions exercise the declared header-only commitment
			// check without allocating/claiming a fully decoded 40-million-pixel image.
			data := append([]byte(nil), source...)
			sof := bytes.Index(data, []byte{0xff, 0xc0})
			if sof < 0 {
				t.Fatal("synthetic JPEG has no SOF")
			}
			data[sof+5], data[sof+6] = byte(tc.height>>8), byte(tc.height)
			data[sof+7], data[sof+8] = byte(tc.width>>8), byte(tc.width)
			config, err := jpeg.DecodeConfig(bytes.NewReader(data))
			if err != nil || config.Width != tc.width || config.Height != tc.height {
				t.Fatal("boundary fixture header differs", config, err)
			}
			_, m := synthetic()
			m.SHA256 = protocol.Hash(data)
			m.ByteLength = int64(len(data))
			h.register(p, m)
			def := "Receipt"
			if tc.status == 422 {
				def = "invalid_image"
			}
			h.request("PUT", original(p.ArchiveID, m.FrameID), p.DeviceToken, "image/jpeg", data, tc.status, def)
			if tc.status == 200 {
				got := h.request("GET", original(p.ArchiveID, m.FrameID), p.DeviceToken, "", nil, 200, "")
				if !bytes.Equal(got.Body.Bytes(), data) {
					t.Fatal("boundary original changed")
				}
			} else {
				h.request("GET", receipt(p.ArchiveID, m.FrameID), p.DeviceToken, "", nil, 409, "not_committed")
				if h.count("jobs", p.ArchiveID, m.FrameID) != 0 {
					t.Fatal("excess dimension committed a job")
				}
			}
		})
	}
}

func TestHTTPExactly16MiBJPEGIsAcceptedAndRetryStillChecksBytes(t *testing.T) {
	h := setup(t)
	p := h.pair(h.owner())
	source, m := synthetic()
	// Pad a genuine small JPEG with well-formed COM segments, not trailing junk.
	// JPEG lengths include their two length bytes; marker bytes are additional.
	data := make([]byte, 0, protocol.MaxBytes)
	data = append(data, source[:2]...)
	remaining := protocol.MaxBytes - len(source)
	for remaining > 0 {
		size := min(remaining, 65537)
		if rest := remaining - size; rest > 0 && rest < 4 {
			size -= 4
		}
		length := size - 2
		data = append(data, 0xff, 0xfe, byte(length>>8), byte(length))
		data = append(data, make([]byte, size-4)...)
		remaining -= size
	}
	data = append(data, source[2:]...)
	if len(data) != protocol.MaxBytes {
		t.Fatal("maximum-byte fixture differs")
	}
	if _, err := jpeg.Decode(bytes.NewReader(data)); err != nil {
		t.Fatal("maximum-byte fixture is not a complete valid JPEG", err)
	}
	m.SHA256 = protocol.Hash(data)
	m.ByteLength = int64(len(data))
	h.register(p, m)
	first := h.request("PUT", original(p.ArchiveID, m.FrameID), p.DeviceToken, "image/jpeg", data, 200, "Receipt").Body.Bytes()
	got := h.request("GET", original(p.ArchiveID, m.FrameID), p.DeviceToken, "", nil, 200, "")
	if !bytes.Equal(got.Body.Bytes(), data) {
		t.Fatal("16MiB original not exact")
	}
	repeat := h.request("PUT", original(p.ArchiveID, m.FrameID), p.DeviceToken, "image/jpeg", data, 200, "Receipt").Body.Bytes()
	if !bytes.Equal(first, repeat) {
		t.Fatal("16MiB receipt changed")
	}
	data[6] ^= 1 // Same length and valid COM syntax, conflicting exact payload hash.
	h.request("PUT", original(p.ArchiveID, m.FrameID), p.DeviceToken, "image/jpeg", data, 422, "checksum_mismatch")
	if h.count("jobs", p.ArchiveID, m.FrameID) != 1 {
		t.Fatal("maximum-byte retry changed job count")
	}
	got = h.request("GET", original(p.ArchiveID, m.FrameID), p.DeviceToken, "", nil, 200, "")
	data[6] ^= 1
	if !bytes.Equal(got.Body.Bytes(), data) {
		t.Fatal("conflicting full-size retry overwrote original")
	}
}
