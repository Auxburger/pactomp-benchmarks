#!/bin/bash
#export OMP_NUM_THREADS=4
export OMP_PLACES=threads
export OMP_PROC_BIND=spread
export OMP_DISPLAY_AFFINITY=true

export KMP_A_DEBUG=20
export KMP_DEBUG=1
export KMP_SETTINGS=1
export OMP_DISPLAY_AFFINITY=true
export KMP_AFFINITY=verbose

source_dir=/home/darius/programming/uni/llvm-project/llvm
build_dir=/home/darius/programming/uni/llvm-project/build

cmake -S $source_dir -B $build_dir -G Ninja  -DLLVM_ENABLE_PROJECTS="clang;openmp"
ninja -C $build_dir -j 4

echo "Using LLVM OpenMP runtime"
$build_dir/bin/clang -fopenmp   -I$build_dir/projects/openmp/runtime/src   omp.c -o omp   -Wl,-rpath,$build_dir/lib
./omp 2>&1 | tee omp_debug.log
