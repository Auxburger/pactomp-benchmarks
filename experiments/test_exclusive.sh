#!/bin/bash
# Uncontended reference: one process per NUMA domain, one with the coordinator
# enabled and one without. Neither competes with the other, so the difference
# is the cost of participating rather than of being coordinated.
#
# The two roles alternate between the domains across runs. A 89-core allocation
# fills one node before spilling into the other, so the domains are not
# symmetric and a fixed assignment would confound the comparison with the node.
# With an even number of runs each condition sees each domain equally often,
# and assignment.csv records which was which.
#
# Usage (inside a SLURM job):
#   ./test_exclusive.sh <total_cpus> [domain_cpus] [runs] [outdir]
set -euo pipefail

cpus="${1:?usage: $0 <total_cpus> [domain_cpus] [runs] [outdir]}"
domain_cpus="${2:-32}"
runs="${3:-10}"
source "$(dirname "${BASH_SOURCE[0]}")/paths.sh"
BASE_OUT="${4:-$DATA_DIR/dual-exclusive/${SLURM_JOB_ID:-$$}}"

command -v taskset >/dev/null 2>&1 || {
  echo "ERROR: 'taskset' not found on $(hostname); CPU pinning is not optional." >&2
  exit 2
}

algorithms=(ft cg ep)
export LD_LIBRARY_PATH="$LLVM_BUILD/lib:${LD_LIBRARY_PATH:-}"
export KMP_DYNAMIC_MODE=thread_limit

# ── CPU layout ────────────────────────────────────────────────────────────────
ALLOWED_RAW=$(awk -F'\t' '/^Cpus_allowed_list:/ {print $2}' /proc/self/status)
readarray -t PICK < <(python3 "$REPO_ROOT/src/pick_cpus.py" --mask "$ALLOWED_RAW" --domain-cpus "$domain_cpus")

if ((${#PICK[@]} < 3)) || [[ "${PICK[0]}" == ERROR* ]]; then
  printf '%s\n' "${PICK[@]:-<empty>}" >&2
  exit 1
fi

RM_CPU="${PICK[0]}"
NODE_A="${PICK[1]%% *}"; CPU_A_LIST="${PICK[1]#* }"
NODE_B="${PICK[2]%% *}"; CPU_B_LIST="${PICK[2]#* }"

echo "RM_CPU=$RM_CPU"
echo "Domain A: NUMA node $NODE_A CPUs=$CPU_A_LIST"
echo "Domain B: NUMA node $NODE_B CPUs=$CPU_B_LIST"
echo "runs=$runs algorithms=${algorithms[*]}"

mkdir -p "$BASE_OUT"
ASSIGN="$BASE_OUT/assignment.csv"
[[ -f "$ASSIGN" ]] || echo "run,threads,alg,enabled_node,unmanaged_node" > "$ASSIGN"
RM_LOG="$BASE_OUT/rm.log"
echo "start $(date) host $(hostname) mask $ALLOWED_RAW" > "$BASE_OUT/meta.txt"

# ── Run loop ──────────────────────────────────────────────────────────────────
# t outermost so the coordinator's capacity matches each thread count, as in
# test_all.sh. The coordinator restarts per run too, because its CPU pool
# follows whichever domain currently hosts the enabled process.
for ((t = 2; t <= domain_cpus; t *= 2)); do
  CPU_A_T=$(echo "$CPU_A_LIST" | tr ',' '\n' | head -n "$t" | tr '\n' ',' | sed 's/,$//')
  CPU_B_T=$(echo "$CPU_B_LIST" | tr ',' '\n' | head -n "$t" | tr '\n' ',' | sed 's/,$//')

  for ((r = 1; r <= runs; r++)); do
    if (( r % 2 == 1 )); then
      ON_NODE="$NODE_A"; ON_CPUS="$CPU_A_T"; OFF_NODE="$NODE_B"; OFF_CPUS="$CPU_B_T"
    else
      ON_NODE="$NODE_B"; ON_CPUS="$CPU_B_T"; OFF_NODE="$NODE_A"; OFF_CPUS="$CPU_A_T"
    fi

    rm -f /tmp/omp-rm.sock
    echo "Starting DRM at $(date), capacity=$t, cpu_pool=$ON_CPUS" >> "$RM_LOG"
    POMP_CAPACITY="$t" POMP_CPU_LIST="$ON_CPUS" \
      stdbuf -oL -eL taskset -c "$RM_CPU" nice -n 15 \
      "$POMP_BIN" >> "$RM_LOG" 2>&1 &
    POMP_PID=$!
    sleep 0.5

    for alg in "${algorithms[@]}"; do
      echo "$r,$t,$alg,$ON_NODE,$OFF_NODE" >> "$ASSIGN"

      ( export OMP_NUM_THREADS="$t"
        taskset -c "$ON_CPUS" \
          "$EXPERIMENTS_DIR/test-one.sh" "$alg" "run_${r}" "1" "true" "$BASE_OUT" "1" ) &
      PID_ON=$!

      ( export OMP_NUM_THREADS="$t"
        taskset -c "$OFF_CPUS" \
          "$EXPERIMENTS_DIR/test-one.sh" "$alg" "run_${r}" "1" "false" "$BASE_OUT" "1" ) &
      PID_OFF=$!

      wait "$PID_ON" "$PID_OFF"
      sleep 2
    done

    kill "$POMP_PID" 2>/dev/null || true
    wait "$POMP_PID" 2>/dev/null || true
  done
done

echo "=== done ==="
echo "Results in $BASE_OUT/"
echo "Node assignment: $ASSIGN"
