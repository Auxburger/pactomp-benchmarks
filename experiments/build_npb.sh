#!/bin/bash
# Build the NPB benchmarks used by the DRM experiments.
#
# NPB3.4-OMP/ is kept byte-identical to the upstream NPB 3.4.3 release,
# so the build configuration it needs is not committed inside it. This script
# installs config/make.def from the canonical copy in this directory, then
# builds the benchmarks.
#
# Usage:
#   ./build_npb.sh                # ft, cg, ep at class C
#   ./build_npb.sh C ft cg ep mg  # explicit class and benchmark list
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/paths.sh"

CLASS="${1:-C}"
shift || true
BENCHMARKS=("${@:-ft cg ep}")
# shellcheck disable=SC2206
[[ $# -eq 0 ]] && BENCHMARKS=(ft cg ep)

if [[ ! -d "$NPB_DIR" ]]; then
  echo "ERROR: NPB tree not found at $NPB_DIR" >&2
  exit 1
fi

echo "Installing build config into $NPB_DIR/config …"
install -m 644 "$EXPERIMENTS_DIR/make.def" "$NPB_DIR/config/make.def"

for bench in "${BENCHMARKS[@]}"; do
  echo "Building $bench class $CLASS …"
  make -C "$NPB_DIR" "$bench" CLASS="$CLASS"
done

echo
echo "Binaries in $NPB_BIN:"
ls -1 "$NPB_BIN"
echo
echo "Confirm the binaries link against the patched runtime:"
echo "  ldd $NPB_BIN/ft.$CLASS.x | grep omp"
