# SPDX-License-Identifier: AGPL-3.0-only
FROM golang:1.26.4-alpine@sha256:3ad57304ad93bbec8548a0437ad9e06a455660655d9af011d58b993f6f615648 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download && go mod verify
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /memotrace ./cmd/memotrace

FROM alpine:3.23@sha256:fd791d74b68913cbb027c6546007b3f0d3bc45125f797758156952bc2d6daf40
RUN addgroup -g 10001 memotrace && adduser -D -H -u 10001 -G memotrace memotrace
COPY --from=build /memotrace /usr/local/bin/memotrace
COPY LICENSE THIRD_PARTY_NOTICES.md /usr/share/licenses/memotrace/
USER 10001:10001
EXPOSE 8443
ENTRYPOINT ["/usr/local/bin/memotrace"]
CMD ["serve", "--data-root", "/data", "--cert", "/tls/cert.pem", "--key", "/tls/key.pem"]
