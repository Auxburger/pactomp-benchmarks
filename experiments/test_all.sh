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

echo "start $(date) host $(hostname) mask $ALLOWED_RAW" | tee "$META_A/meta.txt" "$META_B/meta.txt" >/dev/null

source ~/.cargo/env
export RUST_LOG="${RUST_LOG:-info}"
RM_LOG="$BASE_OUT/$RUN_TAG/rm.log"

# Pre-build DRM once so restarts between thread counts are instant.
echo "Building DRM at $(date)" >> "$RM_LOG"
cd "$POMP_DIR"
cargo build --release >> "$RM_LOG" 2>&1
cd "$NPB_DIR"

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

  # Start DRM with:
  #   POMP_CAPACITY=t   → fair-share grants t/2 threads per client (2 clients)
  #   POMP_CPU_LIST=... → ordered pool of t A-domain CPUs; DRM assigns disjoint
  #                      contiguous slices of size t/2 to each process
  rm -f /tmp/omp-rm.sock
  echo "Starting DRM at $(date), capacity=$t, cpu_pool=$CPU_A_T, RM_CPU=$RM_CPU" >> "$RM_LOG"
  POMP_CAPACITY="$t" POMP_CPU_LIST="$CPU_A_T" \
    stdbuf -oL -eL numactl --cpunodebind="$NODE_A" --membind="$NODE_A" \
    taskset -c "$RM_CPU" nice -n 15 \
    "$POMP_BIN" >> "$RM_LOG" 2>&1 &
  POMP_PID=$!
  sleep 0.2
  ps -p "$POMP_PID" -o pid,cmd >> "$RM_LOG" 2>&1 || true

  for ((r=1; r<=runs; r++)); do
    echo "==== t=$t r=$r ====" | tee -a "$META_A/meta.txt" "$META_B/meta.txt" >/dev/null

    for alg in "${algorithms[@]}"; do
      echo "alg=$alg start $(date)" | tee -a "$META_A/meta.txt" "$META_B/meta.txt" >/dev/null

      # WorkerA iter 1 — t A-domain CPUs, DRM pins to first t/2
      ( export OMP_NUM_THREADS="$t"
        numactl --cpunodebind="$NODE_A" --membind="$NODE_A" \
          taskset -c "$CPU_A_T" \
          ./test-one.sh "$alg" "run_${r}" "1" "true" $BASE_OUT "1" \
          >> "$META_A/${alg}_t${t}.log" 2>&1 ) &
      PID_A1=$!
      # WorkerA iter 2 — t A-domain CPUs, DRM pins to second t/2
      ( export OMP_NUM_THREADS="$t"
        numactl --cpunodebind="$NODE_A" --membind="$NODE_A" \
          taskset -c "$CPU_A_T" \
          ./test-one.sh "$alg" "run_${r}" "1" "true" $BASE_OUT "2" \
          >> "$META_A/${alg}_t${t}.log" 2>&1 ) &
      PID_A2=$!

      # WorkerB iter 1 — t B-domain CPUs, no DRM → 2× oversubscribed
      ( export OMP_NUM_THREADS="$t"
        numactl --cpunodebind="$NODE_B" --membind="$NODE_B" \
          taskset -c "$CPU_B_T" \
          ./test-one.sh "$alg" "run_${r}" "1" "false" $BASE_OUT "1" \
          >> "$META_B/${alg}_t${t}.log" 2>&1 ) &
      PID_B1=$!
      # WorkerB iter 2 — t B-domain CPUs, no DRM → 2× oversubscribed
      ( export OMP_NUM_THREADS="$t"
        numactl --cpunodebind="$NODE_B" --membind="$NODE_B" \
          taskset -c "$CPU_B_T" \
          ./test-one.sh "$alg" "run_${r}" "1" "false" $BASE_OUT "2" \
          >> "$META_B/${alg}_t${t}.log" 2>&1 ) &
      PID_B2=$!

      wait "$PID_A1" "$PID_A2" "$PID_B1" "$PID_B2"
      sleep 5
    done
  done

  # Stop DRM before next thread count
  kill "$POMP_PID" 2>/dev/null || true
  wait "$POMP_PID" 2>/dev/null || true
  echo "DRM stopped at $(date), was capacity=$t" >> "$RM_LOG"
  sleep 1
done

echo "All done."
