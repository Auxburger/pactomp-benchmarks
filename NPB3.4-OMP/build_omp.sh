#!/bin/bash
# Build (or rebuild) the custom LLVM OpenMP runtime (libomp.so).
#
# First time (full configure + build):  ./build_omp.sh
# Rebuild runtime only (after editing kmp_resource_manager.cpp):
#   ./build_omp.sh --runtime-only

# ── module setup ─────────────────────────────────────────────────────────────
echo "Loading modules …"
source /etc/profile 2>/dev/null || true
source /etc/profile.d/modules.sh 2>/dev/null || true

module use /lrz/sys/spack/release/24.4.0/modules/x86_64   || true
module use /lrz/sys/spack/release/24.4.0/modules/compilers || true

module load ninja/1.12.1        || true
module load cmake/3.30.0        || true
module load gcc/13.2.0          || true
module load python/3.10.12-base || true

for tool in ninja cmake gcc python3; do
  path=$(command -v "$tool" 2>/dev/null) || { echo "ERROR: '$tool' not found after module load"; exit 1; }
  echo "  $tool → $path"
done

# ── paths ────────────────────────────────────────────────────────────────────
base_dir=/dss/dsshome1/09/ga27qam2
source_dir=$base_dir/llvm-project/llvm
build_dir=$base_dir/llvm-project/build

# ── configure (skip when build dir already exists or --runtime-only) ─────────
if [[ "${1:-}" == "--runtime-only" ]]; then
  echo "Skipping configure (--runtime-only)"
elif [[ -f "$build_dir/build.ninja" ]]; then
  echo "Build dir already configured, skipping cmake configure"
  echo "  (delete $build_dir to force reconfigure)"
else
  echo "Configuring LLVM …"
  cmake -S "$source_dir" -B "$build_dir" -G Ninja \
    -DLLVM_ENABLE_PROJECTS="clang;openmp" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_COMPILER="$(which gcc)" \
    -DCMAKE_CXX_COMPILER="$(which g++)"
  echo "Configure done."
fi

# ── build: only the OpenMP runtime target ────────────────────────────────────
echo "Building libomp.so (target: omp, jobs: $(nproc)) …"
cmake --build "$build_dir" --target omp -- -j"$(nproc)"
echo "Done: $build_dir/lib/libomp.so"
