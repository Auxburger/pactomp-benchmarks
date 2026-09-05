#!/bin/bash
set -euo pipefail

cpus="${1:?usage: $0 <total_cpus> [domain_cpus] [run_tag]}"
domain_cpus="${2:-$(( (cpus - 1) / 2 ))}"
run_tag="${3:-dual}"

if (( domain_cpus < 1 )); then
  echo "ERROR: domain_cpus=$domain_cpus too small (need at least 1)" >&2
  exit 1
fi

source "$(dirname "${BASH_SOURCE[0]}")/paths.sh"
export LD_LIBRARY_PATH="$LLVM_BUILD/lib:${LD_LIBRARY_PATH:-}"

export OMP_DISPLAY_AFFINITY=1
# Disable the runtime's own load-balance heuristic (dynamic_load_balance).
# Without this, __kmp_reserve_threads() checks the system load-average and can
# return 1 (fully serialising a parallel region) even though the DRM already
# granted the correct number of threads.  "thread_limit" still honours
# OMP_THREAD_LIMIT / max_threads but skips the load-average check.
export KMP_DYNAMIC_MODE=thread_limit

algorithms=(ft cg ep)
runs=10

threads=()
t=2
while (( t <= domain_cpus )); do
  threads+=("$t")
  t=$(( t * 2 ))
done
echo "Generated thread counts: ${threads[*]}"

ALLOWED_RAW=$(awk -F'\t' '/^Cpus_allowed_list:/ {print $2}' /proc/self/status)
echo "Cpus_allowed_list (raw): $ALLOWED_RAW"
echo "Requested total cpus=$cpus => domain_cpus=$domain_cpus (per worker)"

readarray -t PICK < <(python3 "$REPO_ROOT/src/pick_cpus.py" --mask "$ALLOWED_RAW" --domain-cpus "$domain_cpus")

# harden against empty output
if ((${#PICK[@]} < 3)); then
  echo "ERROR: CPU picker returned too few lines (${#PICK[@]})." >&2
  printf '%s\n' "${PICK[@]:-<empty>}" >&2
  exit 1
fi
if [[ "${PICK[0]}" == ERROR* ]]; then
  printf '%s\n' "${PICK[@]}" >&2
  exit 1
fi

RM_CPU="${PICK[0]}"
NODE_A="${PICK[1]%% *}"; CPU_A_LIST="${PICK[1]#* }"
NODE_B="${PICK[2]%% *}"; CPU_B_LIST="${PICK[2]#* }"

echo "RM_CPU=$RM_CPU"
echo "WorkerA: NUMA node $NODE_A CPUs=$CPU_A_LIST"
echo "WorkerB: NUMA node $NODE_B CPUs=$CPU_B_LIST"

# -------------------------
# Output dirs
# -------------------------
BASE_OUT="${BASE_OUT:-$DATA_DIR/dual}"
RUN_TAG="${1:-dual}"
META_A="$BASE_OUT/$RUN_TAG/node${NODE_A}"
META_B="$BASE_OUT/$RUN_TAG/node${NODE_B}"
mkdir -p "$META_A" "$META_B"

ASSIGN="$BASE_OUT/$RUN_TAG/assignment.csv"
[[ -f "$ASSIGN" ]] || echo "run,threads,alg,enabled_node,unmanaged_node" > "$ASSIGN"

echo "start $(date) host $(hostname) mask $ALLOWED_RAW" | tee "$META_A/meta.txt" "$META_B/meta.txt" >/dev/null

source ~/.cargo/env
export RUST_LOG="${RUST_LOG:-info}"
RM_LOG="$BASE_OUT/$RUN_TAG/rm.log"

# Pre-build DRM once so restarts between thread counts are instant.
echo "Building DRM at $(date)" >> "$RM_LOG"
cd "$POMP_DIR"
cargo build --release >> "$RM_LOG" 2>&1
cd "$REPO_ROOT"

# -------------------------
# Run loop — t is outermost so DRM capacity and CPU assignments match each thread count.
#
# NEW CPU management strategy:
#   dyn=true  (WorkerA): both processes get the FULL domain CPU set via taskset.
#             The DRM assigns disjoint subsets of size t/2 to each process and
#             the runtime applies sched_setaffinity before forking the OMP team.
#   dyn=false (WorkerB): both processes also get the FULL domain CPU set.
#             They ignore the DRM → 2× oversubscription of the B domain.
# -------------------------
for t in "${threads[@]}"; do
  # Use exactly t CPUs per domain so dyn=false always oversubscribes (2×t threads
  # on t CPUs) while dyn=true is coordinated (2×(t/2) = t threads on t CPUs).
  CPU_A_T=$(echo "$CPU_A_LIST" | tr ',' '\n' | head -n "$t" | tr '\n' ',' | sed 's/,$//')
  CPU_B_T=$(echo "$CPU_B_LIST" | tr ',' '\n' | head -n "$t" | tr '\n' ',' | sed 's/,$//')
  echo "t=$t | A_pool: [$CPU_A_T] | B_pool: [$CPU_B_T]"

  for ((r=1; r<=runs; r++)); do
    # Alternate which domain hosts the coordinator-enabled pair. The domains are
    # not symmetric, so a fixed assignment confounds condition with node.
    if (( r % 2 == 1 )); then
      ON_NODE="$NODE_A"; ON_CPUS="$CPU_A_T"; ON_META="$META_A"
      OFF_NODE="$NODE_B"; OFF_CPUS="$CPU_B_T"; OFF_META="$META_B"
    else
      ON_NODE="$NODE_B"; ON_CPUS="$CPU_B_T"; ON_META="$META_B"
      OFF_NODE="$NODE_A"; OFF_CPUS="$CPU_A_T"; OFF_META="$META_A"
    fi

    # POMP_CPU_LIST follows the enabled domain, so the coordinator restarts per
    # run rather than per thread count.
    #   POMP_CAPACITY=t → fair-share grants t/2 threads per client (2 clients)
    rm -f /tmp/omp-rm.sock
    echo "Starting DRM at $(date), capacity=$t, cpu_pool=$ON_CPUS, RM_CPU=$RM_CPU" >> "$RM_LOG"
    POMP_CAPACITY="$t" POMP_CPU_LIST="$ON_CPUS" \
      stdbuf -oL -eL taskset -c "$RM_CPU" nice -n 15 \
      "$POMP_BIN" >> "$RM_LOG" 2>&1 &
    POMP_PID=$!
    sleep 0.2

    echo "==== t=$t r=$r enabled_node=$ON_NODE ====" | tee -a "$META_A/meta.txt" "$META_B/meta.txt" >/dev/null

    for alg in "${algorithms[@]}"; do
      echo "alg=$alg start $(date)" | tee -a "$META_A/meta.txt" "$META_B/meta.txt" >/dev/null
      echo "$r,$t,$alg,$ON_NODE,$OFF_NODE" >> "$ASSIGN"

      # Enabled pair — t CPUs of the enabled domain, DRM pins each to t/2
      ( export OMP_NUM_THREADS="$t"
        taskset -c "$ON_CPUS" \
          "$EXPERIMENTS_DIR/test-one.sh" "$alg" "run_${r}" "1" "true" $BASE_OUT "1" \
          >> "$ON_META/${alg}_t${t}.log" 2>&1 ) &
      PID_A1=$!
      ( export OMP_NUM_THREADS="$t"
        taskset -c "$ON_CPUS" \
          "$EXPERIMENTS_DIR/test-one.sh" "$alg" "run_${r}" "1" "true" $BASE_OUT "2" \
          >> "$ON_META/${alg}_t${t}.log" 2>&1 ) &
      PID_A2=$!

      # Unmanaged pair — t CPUs of the other domain, no DRM → 2× oversubscribed
      ( export OMP_NUM_THREADS="$t"
        taskset -c "$OFF_CPUS" \
          "$EXPERIMENTS_DIR/test-one.sh" "$alg" "run_${r}" "1" "false" $BASE_OUT "1" \
          >> "$OFF_META/${alg}_t${t}.log" 2>&1 ) &
      PID_B1=$!
      ( export OMP_NUM_THREADS="$t"
        taskset -c "$OFF_CPUS" \
          "$EXPERIMENTS_DIR/test-one.sh" "$alg" "run_${r}" "1" "false" $BASE_OUT "2" \
          >> "$OFF_META/${alg}_t${t}.log" 2>&1 ) &
      PID_B2=$!

      wait "$PID_A1" "$PID_A2" "$PID_B1" "$PID_B2"
      sleep 5
    done

    kill "$POMP_PID" 2>/dev/null || true
    wait "$POMP_PID" 2>/dev/null || true
    echo "DRM stopped at $(date), was capacity=$t" >> "$RM_LOG"
    sleep 1
  done
done

echo "All done."
