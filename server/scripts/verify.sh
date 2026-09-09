#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Run from the server component root. Never reuse an operator database/container.
set -euo pipefail
test -f go.mod
test "$(go env GOVERSION)" = go1.26.4
if test -n "$(gofmt -l cmd internal)"; then
  gofmt -l cmd internal
  exit 1
fi
go mod verify
go vet ./...
mkdir -p .build
go build -trimpath -o .build/memotrace ./cmd/memotrace
go test -count=1 ./internal/contract

image='postgres@sha256:74e110c41804365e3915fcc09d5e7a1eff50161aaa94d5da0e58e0cd75ae509c'
nonce="$(python3 -c 'import secrets; print(secrets.token_hex(12))')"
name="memotrace-verify-${nonce}"
password="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
container=''
cleanup() {
  if test -n "$container"; then
    local owned
    owned="$(docker inspect --format '{{index .Config.Labels "memotrace.verify"}}' "$container" 2>/dev/null || true)"
    if test "$owned" = "$nonce"; then docker rm -f -v "$container" >/dev/null; fi
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
container="$(docker run --rm -d --name "$name" --label "memotrace.verify=$nonce" -e "POSTGRES_PASSWORD=$password" -p 127.0.0.1::5432 "$image")"
ready=false
for attempt in {1..60}; do
  if docker exec "$container" pg_isready -U postgres >/dev/null 2>&1; then ready=true; break; fi
  sleep 1
done
test "$ready" = true
port="$(docker inspect --format '{{(index (index .NetworkSettings.Ports "5432/tcp") 0).HostPort}}' "$container")"
docker exec "$container" psql -U postgres -v ON_ERROR_STOP=1 \
  -c "CREATE ROLE memotrace_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD '$password'; CREATE ROLE memotrace_admin LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD '$password';" \
  -c 'CREATE DATABASE memotrace_test OWNER memotrace_admin;' >/dev/null
export MEMOTRACE_TEST_ADMIN_DSN="postgres://memotrace_admin:$password@127.0.0.1:$port/memotrace_test?sslmode=disable"
export MEMOTRACE_TEST_DSN="postgres://memotrace_runtime:$password@127.0.0.1:$port/memotrace_test?sslmode=disable"
export MEMOTRACE_REQUIRE_POSTGRES=1
# Packages share this one disposable schema; serialize packages so deliberately
# deferred SQL-failure triggers cannot affect another package's lifecycle test.
go test -race -p 1 -count=1 -timeout=5m -coverprofile=.build/coverage.out ./...
python3 scripts/coverage.py .build/coverage.out
