#!/bin/bash
#SBATCH --clusters=serial
#SBATCH --partition=serial_std
#SBATCH --export=NONE
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=9
#SBATCH --time=08:00:00
#SBATCH --output=slurm_logs/slurm-%j.out
#SBATCH --error=slurm_logs/slurm-%j.err

set -euo pipefail

cd /dss/dsshome1/09/ga27qam2/master-thesis/NPB3.4-OMP
module load slurm_setup

echo "Cpus_allowed_list: $(grep Cpus_allowed_list /proc/$$/status | awk '{print $2}')"
echo "Running on $(hostname)"
srun --cpu-bind=cores ./test_all.sh 9