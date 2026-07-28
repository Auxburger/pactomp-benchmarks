#!/bin/bash
#SBATCH --clusters=cm4
#SBATCH --partition=cm4_tiny
#SBATCH --export=NONE
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=89
#SBATCH --hint=nomultithread
#SBATCH --time=00:30:00
#SBATCH --output=data/slurm_logs/slurm-%j.out
#SBATCH --error=data/slurm_logs/slurm-%j.err

set -euo pipefail

# Submit from the repository root: sbatch --clusters=cm4 experiments/run_staggered.sbatch
cd "${SLURM_SUBMIT_DIR:?submit this job from the repository root}"
source experiments/paths.sh
module load slurm_setup

echo "Cpus_allowed_list: $(grep Cpus_allowed_list /proc/$$/status | awk '{print $2}')"
echo "Running on $(hostname)"

OUT="$DATA_DIR/staggered/${SLURM_JOB_ID}"
mkdir -p "$OUT" "$SLURM_LOG_DIR"

mpstat -P ALL 1 >> "$OUT/cpu_util.log" &
MPSTAT_PID=$!
pidstat -u -t 1 >> "$OUT/pidstat.log" &
PIDSTAT_PID=$!

# Solo runtimes at t=32: FT ~4s, CG ~3.5s, EP ~1.8s
# Offset chosen so A2/B2 join roughly halfway through A1/B1's single run
srun --cpu-bind=cores "$EXPERIMENTS_DIR/test_staggered.sh" 89 32 32 ft 15 10 15 "$OUT"
srun --cpu-bind=cores "$EXPERIMENTS_DIR/test_staggered.sh" 89 32 32 cg 15 10 15 "$OUT"
srun --cpu-bind=cores "$EXPERIMENTS_DIR/test_staggered.sh" 89 32 32 ep 15 5 15 "$OUT"

kill "$MPSTAT_PID" "$PIDSTAT_PID" 2>/dev/null || true
echo "Results in $OUT/"
