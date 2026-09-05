#!/bin/bash
#SBATCH --clusters=cm4
#SBATCH --partition=cm4_tiny
#SBATCH --export=NONE
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=89
#SBATCH --hint=nomultithread
#SBATCH --time=04:00:00
#SBATCH --output=data/slurm_logs/slurm-%j.out
#SBATCH --error=data/slurm_logs/slurm-%j.err

# Uncontended reference for the main experiment: one process per NUMA domain,
# coordinator enabled on one and disabled on the other, roles alternating
# between domains across runs. Same 89-core allocation and 32-CPU domains as
# run_npb_tiny.sbatch so the two are comparable.
#
# Submit from the repository root:
#   sbatch --clusters=cm4 experiments/run_npb_exclusive.sbatch

set -euo pipefail

cd "${SLURM_SUBMIT_DIR:?submit this job from the repository root}"
source experiments/paths.sh
module load slurm_setup
# src/pick_cpus.py needs a current Python; the system one is too old.
source experiments/load_modules_lrz.sh || true

mkdir -p "$SLURM_LOG_DIR"
echo "Cpus_allowed_list: $(grep Cpus_allowed_list /proc/$$/status | awk '{print $2}')"
echo "Running on $(hostname)"

srun --cpu-bind=cores "$EXPERIMENTS_DIR/test_exclusive.sh" 89 32 10
