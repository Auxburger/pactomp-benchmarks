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
