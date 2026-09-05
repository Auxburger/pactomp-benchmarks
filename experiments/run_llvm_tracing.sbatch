#!/bin/bash
#SBATCH --clusters=cm4
#SBATCH --partition=cm4_tiny
#SBATCH --export=NONE
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --hint=nomultithread
#SBATCH --time=00:15:00
#SBATCH --output=data/slurm_logs/slurm-%j.out
#SBATCH --error=data/slurm_logs/slurm-%j.err

# LLVM OpenMP tracing microbenchmark: sweeps thread counts with two concurrent
# processes per cell, once with OMP_DYNAMIC=true (DRM) and once with false.
#
# Submit from the repository root:
#   sbatch --clusters=cm4 experiments/run_llvm_tracing.sbatch
#   sbatch --clusters=cm4 experiments/run_llvm_tracing.sbatch --runs 3 --no-drm
# Extra arguments are forwarded to src/run_llvm_tracing.py.

set -euo pipefail

cd "${SLURM_SUBMIT_DIR:?submit this job from the repository root}"
source experiments/paths.sh
module load slurm_setup
source experiments/load_modules_lrz.sh || true

echo "Cpus_allowed_list: $(grep Cpus_allowed_list /proc/$$/status | awk '{print $2}')"
echo "Running on $(hostname)"

OUT="$DATA_DIR/tracing/${SLURM_JOB_ID}"
mkdir -p "$OUT" "$SLURM_LOG_DIR"

mpstat -P ALL 1 >> "$OUT/cpu_util.log" &
MPSTAT_PID=$!
pidstat -u -t 1 >> "$OUT/pidstat.log" &
PIDSTAT_PID=$!

srun --cpu-bind=cores python3 "$REPO_ROOT/src/run_llvm_tracing.py" --build --out "$OUT" "$@"

kill "$MPSTAT_PID" "$PIDSTAT_PID" 2>/dev/null || true
echo "Results in $OUT/"
