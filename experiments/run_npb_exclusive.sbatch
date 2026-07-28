#!/bin/bash
#SBATCH --clusters=serial
#SBATCH --partition=serial_std
#SBATCH --export=NONE
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=9
#SBATCH --time=08:00:00
#SBATCH --output=data/slurm_logs/slurm-%j.out
#SBATCH --error=data/slurm_logs/slurm-%j.err

set -euo pipefail

# Submit from the repository root: sbatch --clusters=serial experiments/run_npb_exclusive.sbatch
cd "${SLURM_SUBMIT_DIR:?submit this job from the repository root}"
source experiments/paths.sh
module load slurm_setup

mkdir -p "$SLURM_LOG_DIR"
echo "Cpus_allowed_list: $(grep Cpus_allowed_list /proc/$$/status | awk '{print $2}')"
echo "Running on $(hostname)"
srun --cpu-bind=cores "$EXPERIMENTS_DIR/test_all.sh" 9