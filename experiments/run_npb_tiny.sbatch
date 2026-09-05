#!/bin/bash
#SBATCH --clusters=cm4
#SBATCH --partition=cm4_tiny
#SBATCH --export=NONE
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=89
#SBATCH --hint=nomultithread
#SBATCH --time=03:00:00
#SBATCH --output=data/slurm_logs/slurm-%j.out
#SBATCH --error=data/slurm_logs/slurm-%j.err

# 89 physical cores: 56 fill NUMA node 0, 33 spill to NUMA node 1.
# domain_cpus=32: RM(1)+WorkerA(32) on node 0, WorkerB(32) on node 1.

set -euo pipefail

# Submit from the repository root: sbatch --clusters=cm4 experiments/run_npb_tiny.sbatch
cd "${SLURM_SUBMIT_DIR:?submit this job from the repository root}"
source experiments/paths.sh
module load slurm_setup
# src/pick_cpus.py needs a current Python; the system one is too old.
source experiments/load_modules_lrz.sh || true

echo "Cpus_allowed_list: $(grep Cpus_allowed_list /proc/$$/status | awk '{print $2}')"
echo "Running on $(hostname)"

# Keep each job in its own directory: the run_<n> layout would otherwise
# overwrite the retained outputs of an earlier job.
export BASE_OUT="$DATA_DIR/dual/${SLURM_JOB_ID}"

# Sample per-CPU utilisation and per-process CPU placement every 5 seconds.
mkdir -p "$BASE_OUT" "$SLURM_LOG_DIR"
CPU_LOG="$BASE_OUT/cpu_util.log"
PID_LOG="$BASE_OUT/pidstat.log"

mpstat -P ALL 5 >> "$CPU_LOG" &
MPSTAT_PID=$!

# -u: CPU usage  -t: include threads  -p ALL: all processes
# The CPU column shows which physical core each thread is currently on.
pidstat -u -t 5 >> "$PID_LOG" &
PIDSTAT_PID=$!

srun --cpu-bind=cores "$EXPERIMENTS_DIR/test_all.sh" 89 32

kill "$MPSTAT_PID" "$PIDSTAT_PID" 2>/dev/null || true
echo "CPU utilisation log : $CPU_LOG"
echo "Per-process CPU log : $PID_LOG"