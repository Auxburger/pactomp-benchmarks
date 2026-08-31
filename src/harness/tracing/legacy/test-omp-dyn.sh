#!/bin/bash


# Ensure 'module' works in non-interactive shells
source /etc/profile 2>/dev/null || true
source /etc/profile.d/modules.sh 2>/dev/null || true

# Spack module trees (needed for ninja/cmake/gcc/python in your setup)
module use /lrz/sys/spack/release/24.4.0/modules/x86_64
module use /lrz/sys/spack/release/24.4.0/modules/compilers

module load ninja/1.12.1
module load cmake/3.30.0
module load gcc/13.2.0
module load python/3.10.12-base

# sanity
command -v ninja
command -v cmake
command -v gcc
command -v python3


# export OMP_NUM_THREADS=4
export OMP_PLACES=cores
export OMP_PROC_BIND=spread
export OMP_DISPLAY_AFFINITY=1
export OMP_DYNAMIC=true

#export KMP_A_DEBUG=20
#export KMP_F_DEBUG=20
#export KMP_DEBUG=1
#export KMP_SETTINGS=1
#export KMP_AFFINITY=verbose

base_dir=/dss/dsshome1/09/ga27qam2
source_dir=$base_dir/llvm-project/llvm
build_dir=$base_dir/llvm-project/build

#cmake -S "$source_dir" -B "$build_dir" -G Ninja \
#  -DLLVM_ENABLE_PROJECTS="clang;openmp" \
#  -DCMAKE_BUILD_TYPE=Release \
#  -DCMAKE_C_COMPILER="$(which gcc)" \
#  -DCMAKE_CXX_COMPILER="$(which g++)"

# cmake -S $source_dir -B $build_dir -G Ninja  -DLLVM_ENABLE_PROJECTS="clang;openmp" -DCMAKE_BUILD_TYPE=Debug

ninja -C $build_dir -j 10

echo "Using LLVM OpenMP runtime"
$build_dir/bin/clang -fopenmp   -I$build_dir/projects/openmp/runtime/src   omp_dyn.c -o omp   -Wl,-rpath,$build_dir/lib
exit 0
#./omp &
#./omp 2>&1 | tee omp_debug_dyn.log

threads=(2 4 8 16 32 64)
runs=1
for ((r=0; r<=runs; r++)); do
  for t in "${threads[@]}"; do
    export OMP_NUM_THREADS="$t"
    echo "==== Running with OMP_NUM_THREADS=$t ===="
    ./test-one-dyn.sh "run_$r"
    sleep 5
  done
done
