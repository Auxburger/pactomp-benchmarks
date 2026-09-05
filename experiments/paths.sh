#!/bin/bash
# Shared path resolution for the PactOMP experiment scripts.
#
# Source this from any script in this directory:
#
#     source "$(dirname "${BASH_SOURCE[0]}")/paths.sh"
#
# Every path is either derived from this file's own location — so a checkout
# works wherever it lives — or overridable from the environment, for the
# external dependencies that live outside this repository.

EXPERIMENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$EXPERIMENTS_DIR/.." && pwd)"

# ── This repository ──────────────────────────────────────────────────────────
# Unmodified NPB 3.4.3 and the binaries its build writes into bin/.
NPB_DIR="${NPB_DIR:-$REPO_ROOT/NPB3.4-OMP}"
NPB_BIN="${NPB_BIN:-$NPB_DIR/bin}"

# Measurement record. Retained run outputs are committed under here.
DATA_DIR="${DATA_DIR:-$REPO_ROOT/data}"
SLURM_LOG_DIR="${SLURM_LOG_DIR:-$DATA_DIR/slurm_logs}"

# ── External dependencies ────────────────────────────────────────────────────
# The patched LLVM OpenMP runtime and the DRM coordinator are separate
# checkouts. The defaults match the layout used on LRZ CoolMUC-4, where both
# sit in the cluster $HOME. Override either if yours live elsewhere:
#
#     LLVM_BUILD=/path/to/llvm-project/build ./test_all.sh 89
#
# The coordinator was named dynamic-resource-manager when the dual and staggered
# runs were made. It is now pactomp-coordinator, and the rename went with a
# rename of its environment variables (DRM_CAPACITY/DRM_CPU_LIST became
# POMP_CAPACITY/POMP_CPU_LIST). An old checkout therefore silently ignores the
# settings the harness passes, so the default points at the current name.
LLVM_BUILD="${LLVM_BUILD:-$HOME/llvm-project/build}"
POMP_DIR="${POMP_DIR:-$HOME/pactomp-coordinator}"
POMP_BIN="${POMP_BIN:-$POMP_DIR/target/release/pactomp-coordinator}"

export EXPERIMENTS_DIR REPO_ROOT NPB_DIR NPB_BIN DATA_DIR SLURM_LOG_DIR
export LLVM_BUILD POMP_DIR POMP_BIN
