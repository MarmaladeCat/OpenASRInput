#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRAMEWORK="${OPENASRINPUT_FRAMEWORK:-fcitx5}"
if [ "${1:-}" = --framework ]; then FRAMEWORK="${2:?missing framework}"; shift 2; fi
case "$FRAMEWORK" in fcitx4|fcitx5) ;; *) exit 2 ;; esac
BUILD="${OPENASRINPUT_NATIVE_BUILD_DIR:-$ROOT/build/$FRAMEWORK}"
cmake -S "$ROOT/src/native/$FRAMEWORK" -B "$BUILD" "$@"
cmake --build "$BUILD" -j"${BUILD_JOBS:-4}"
cmake -E chdir "$BUILD" ctest --output-on-failure
