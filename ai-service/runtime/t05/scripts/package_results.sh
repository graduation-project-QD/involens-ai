#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p outputs

archive="t05-results-$(hostname)-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
mapfile -t files < <(find outputs -maxdepth 1 -type f -printf '%f\n' | sort)
if [[ ${#files[@]} -eq 0 ]]; then
  echo "No result files found." >&2
  exit 1
fi
tar -C outputs -czf "$archive" "${files[@]}"
sha256sum "$archive" > "$archive.sha256"
echo "Created $ROOT_DIR/$archive"
echo "Created $ROOT_DIR/$archive.sha256"
