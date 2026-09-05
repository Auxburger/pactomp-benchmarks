#!/bin/bash
#SBATCH --clusters=cm4
#SBATCH --partition=cm4_tiny
#SBATCH --export=NONE
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=89
#SBATCH --hint=nomultithread
#SBATCH --time=00:45:00
#SBATCH --output=data/slurm_logs/slurm-%j.out
#SBATCH --error=data/slurm_logs/slurm-%j.err

# Mixed workload experiment: a seeded schedule of concurrent NPB kernels, each
# joining after a random offset and running for a random time window. The same
# schedule is replayed twice — once with the DRM coordinating the runtime
# (OMP_DYNAMIC=true), once without it (OMP_DYNAMIC=false).
#
# 89 cores, matching run_npb_tiny/run_staggered/run_npb_exclusive, so all four
# experiments are measured under the same allocation.
#
# The size is what buys the NUMA guarantee, not the partition: a cm4 node is
# 2 sockets x 56 cores and cm4_tiny shares nodes between jobs
# (OverSubscribe=NO, ExclusiveUser=NO), so a request returns whichever cores
# were free — the dual runs saw masks like 0-8,23-102 across both sockets.
# With 89 of 112 cores, at most 23 are foreign, so by pigeonhole the better
# NUMA node always keeps at least 45 free cores. This experiment needs one
# domain of 33 (32 workload + coordinator), which 65 cores would already
# guarantee; the sibling experiments need two domains (33 + 32) and that is
# what makes 89 the tight bound they were sized to. Well inside either.
#
# What 89 does NOT buy is an empty node: up to 23 cores may run a foreign job
# (LRZ documents cm4_tiny as "shared", 17-112 cores per job). The dual and
# staggered experiments run their two sides simultaneously, so a co-tenant
# perturbs both at once; these two arms run one after the other, so a
# co-tenant arriving between them would land entirely on the second arm. Hence
# --repeats below: the arm order alternates every repeat (drm,nodrm |
# nodrm,drm | ...), so the linear part of any drift cancels instead of being
# charged to one arm. Raising the request to 112 reserves the node outright,
# at the price of comparability with the other three experiments.
#
# Submit from the repository root:
#   sbatch --clusters=cm4 experiments/run_mix.sbatch
#   sbatch --clusters=cm4 experiments/run_mix.sbatch --seed 7 --jobs 8
#   sbatch --clusters=cm4 experiments/run_mix.sbatch --arms nodrm,drm
# Extra arguments are forwarded to src/run_mix.py.

set -euo pipefail

cd "${SLURM_SUBMIT_DIR:?submit this job from the repository root}"
source experiments/paths.sh
module load slurm_setup
source experiments/load_modules_lrz.sh || true

echo "Cpus_allowed_list: $(grep Cpus_allowed_list /proc/$$/status | awk '{print $2}')"
echo "Running on $(hostname)"

OUT="$DATA_DIR/mix/${SLURM_JOB_ID}"
mkdir -p "$OUT" "$SLURM_LOG_DIR"

mpstat -P ALL 1 >> "$OUT/cpu_util.log" &
MPSTAT_PID=$!
pidstat -u -t 1 >> "$OUT/pidstat.log" &
PIDSTAT_PID=$!

# Three repeats: ~2 min per arm, so roughly 15 min of the 45 requested, and
# each arm goes first at least once. Override by passing --repeats N.
srun --cpu-bind=cores python3 "$REPO_ROOT/src/run_mix.py" --out "$OUT" --repeats 3 "$@"

kill "$MPSTAT_PID" "$PIDSTAT_PID" 2>/dev/null || true
echo "Results in $OUT/"
