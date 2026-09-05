#!/bin/bash
# Staggered-start experiment: A1/B1 start first with full resources.
# After OFFSET seconds, A2/B2 join (DRM rebalances A side).
# A2/B2 run ITERS2 iterations then exit, so A1/B1 see the full cycle:
#   solo (full resources) → shared → solo restored.
#
# Usage (inside a SLURM job):
#   ./test_staggered.sh <total_cpus> [domain_cpus] [threads] [algorithm] [iters1] [offset_sec] [iters2] [outdir]
#
# Example: ./test_staggered.sh 89 32 32 ft 15 10 5 ../data/staggered/187000
set -euo pipefail

cpus="${1:?usage: $0 <total_cpus> [domain_cpus] [threads] [algorithm] [iters1] [offset_sec] [iters2]}"
domain_cpus="${2:-32}"
t="${3:-32}"
alg="${4:-ft}"
iters1="${5:-15}"
offset="${6:-10}"
iters2="${7:-5}"
source "$(dirname "${BASH_SOURCE[0]}")/paths.sh"
BASE_OUT="${8:-$DATA_DIR/staggered/${SLURM_JOB_ID:-$$}}"

command -v taskset >/dev/null 2>&1 || {
  echo "ERROR: 'taskset' not found on $(hostname); CPU pinning is not optional." >&2
  exit 2
}

export LD_LIBRARY_PATH="$LLVM_BUILD/lib:${LD_LIBRARY_PATH:-}"
export KMP_DYNAMIC_MODE=thread_limit
export OMP_NUM_THREADS="$t"

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

CPU_A_T=$(echo "$CPU_A_LIST" | tr ',' '\n' | head -n "$t" | tr '\n' ',' | sed 's/,$//')
CPU_B_T=$(echo "$CPU_B_LIST" | tr ',' '\n' | head -n "$t" | tr '\n' ',' | sed 's/,$//')

echo "RM_CPU=$RM_CPU"
echo "WorkerA: NUMA node $NODE_A CPUs=$CPU_A_T"
echo "WorkerB: NUMA node $NODE_B CPUs=$CPU_B_T"
echo "t=$t alg=$alg iters1=$iters1 iters2=$iters2 offset=${offset}s"

# ── Output dir ────────────────────────────────────────────────────────────────
mkdir -p "$BASE_OUT"
LABEL="${alg}_t${t}_off${offset}"
OUT_A1="$BASE_OUT/${LABEL}_A1.log"
OUT_A2="$BASE_OUT/${LABEL}_A2.log"
OUT_B1="$BASE_OUT/${LABEL}_B1.log"
OUT_B2="$BASE_OUT/${LABEL}_B2.log"

# ── DRM ───────────────────────────────────────────────────────────────────────
source ~/.cargo/env
RM_LOG="$BASE_OUT/${LABEL}_rm.log"

rm -f /tmp/omp-rm.sock
POMP_CAPACITY="$t" POMP_CPU_LIST="$CPU_A_T" \
  taskset -c "$RM_CPU" stdbuf -oL -eL nice -n 15 \
  "$POMP_BIN" >> "$RM_LOG" 2>&1 &
POMP_PID=$!
sleep 0.5

# ── Worker runner ─────────────────────────────────────────────────────────────
run_worker() {
  local label="$1" dyn="$2" cpus="$3" outfile="$4" iters="$5"
  export OMP_DYNAMIC="$dyn"

  echo "# label=$label dyn=$dyn t=$OMP_NUM_THREADS alg=$alg" > "$outfile"
  echo "# iter  start_epoch_ms  duration_ms  time_in_seconds" >> "$outfile"

  for i in $(seq 1 "$iters"); do
    local t0 t1 dur raw
    t0=$(date +%s%3N)
    raw=$(taskset -c "$cpus" \
            "$NPB_BIN/${alg}.C.x" \
            2>>"$BASE_OUT/${LABEL}_${label}_drm.log")
    t1=$(date +%s%3N)
    dur=$(( t1 - t0 ))
    tis=$(echo "$raw" | grep "Time in seconds" | awk '{print $NF}')
    echo "$i  $t0  $dur  ${tis:-NA}" >> "$outfile"
    echo "[$label] iter=$i  ${dur}ms  tis=${tis:-NA}s"
    sleep 0.5
  done
}

# ── A1 and B1 start first ─────────────────────────────────────────────────────
echo "=== $(date) : starting A1 and B1 (${iters1} iters each) ==="
run_worker A1 true  "$CPU_A_T" "$OUT_A1" "$iters1" &
PID_A1=$!
run_worker B1 false "$CPU_B_T" "$OUT_B1" "$iters1" &
PID_B1=$!

# ── A2 and B2 join after offset, run fewer iterations then leave ──────────────
echo "=== sleeping ${offset}s before A2/B2 ==="
sleep "$offset"

echo "=== $(date) : starting A2 and B2 (${iters2} iters each) ==="
run_worker A2 true  "$CPU_A_T" "$OUT_A2" "$iters2" &
PID_A2=$!
run_worker B2 false "$CPU_B_T" "$OUT_B2" "$iters2" &
PID_B2=$!

wait "$PID_A1" "$PID_A2" "$PID_B1" "$PID_B2"

kill "$POMP_PID" 2>/dev/null || true
wait "$POMP_PID" 2>/dev/null || true

echo "=== done ==="
echo "Results in $BASE_OUT/${LABEL}_*.log"
echo "DRM log:  $RM_LOG"
