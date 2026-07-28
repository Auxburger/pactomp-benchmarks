#!/bin/bash
# Staggered-start experiment: A1/B1 start first with full resources.
# After OFFSET seconds, A2/B2 join (DRM rebalances A side).
# A2/B2 run ITERS2 iterations then exit, so A1/B1 see the full cycle:
#   solo (full resources) → shared → solo restored.
#
# Usage (inside a SLURM job):
#   ./test_staggered.sh <total_cpus> [domain_cpus] [threads] [algorithm] [iters1] [offset_sec] [iters2] [outdir]
#
# Example: ./test_staggered.sh 89 32 32 ft 15 10 5 benchmarks/staggered/187000
set -euo pipefail

cpus="${1:?usage: $0 <total_cpus> [domain_cpus] [threads] [algorithm] [iters1] [offset_sec] [iters2]}"
domain_cpus="${2:-32}"
t="${3:-32}"
alg="${4:-ft}"
iters1="${5:-15}"
offset="${6:-10}"
iters2="${7:-5}"
BASE_OUT="${8:-benchmarks/staggered/${SLURM_JOB_ID:-$$}}"

export LLVM_BUILD=/dss/dsshome1/09/ga27qam2/llvm-project/build
export LD_LIBRARY_PATH="$LLVM_BUILD/lib:${LD_LIBRARY_PATH:-}"
export KMP_DYNAMIC_MODE=thread_limit
export OMP_NUM_THREADS="$t"

# ── CPU layout ────────────────────────────────────────────────────────────────
ALLOWED_RAW=$(awk -F'\t' '/^Cpus_allowed_list:/ {print $2}' /proc/self/status)

readarray -t PICK < <(
  MASK="$ALLOWED_RAW" CPUS="$cpus" DOMAIN_CPUS="$domain_cpus" python3 - <<'PY'
import glob, os
from collections import defaultdict
import subprocess

mask  = os.environ.get("MASK","").strip()
cpus  = int(os.environ["CPUS"])
domain = int(os.environ["DOMAIN_CPUS"])

def expand(mask):
    out=[]
    for part in mask.split(','):
        if '-' in part:
            a,b=part.split('-',1)
            out.extend(range(int(a),int(b)+1))
        else:
            out.append(int(part))
    return out

def node_of(cpu):
    paths = glob.glob(f"/sys/devices/system/cpu/cpu{cpu}/node*")
    for p in paths:
        b=os.path.basename(p)
        if b.startswith("node"):
            return int(b[4:])
    return -1

allowed = expand(mask)
by = defaultdict(list)
for c in allowed:
    by[node_of(c)].append(c)

cands = sorted((n,sorted(v)) for n,v in by.items() if n >= 0)
needA = 1 + domain
needB = domain
goodA = [(n,v) for n,v in cands if len(v) >= needA]
goodB = [(n,v) for n,v in cands if len(v) >= needB]

cpu_to_socket = {}
txt = subprocess.check_output(["lscpu","-e=CPU,SOCKET,NODE"], universal_newlines=True)
for line in txt.strip().splitlines()[1:]:
    cpu,sock,node = line.split()
    cpu_to_socket[int(cpu)] = int(sock)

goodA.sort(key=lambda nv: len(nv[1]), reverse=True)
goodB.sort(key=lambda nv: len(nv[1]), reverse=True)
best=None
for ni,vi in goodA:
    si = cpu_to_socket.get(vi[0],-1)
    for nj,vj in goodB:
        if nj==ni: continue
        sj = cpu_to_socket.get(vj[0],-1)
        if si!=-1 and sj!=-1 and si!=sj:
            best=(ni,vi,nj,vj); break
    if best: break
if not best:
    ni,vi=goodA[0]
    nj,vj=next(((n,v) for n,v in goodB if n!=ni),goodB[0])
    best=(ni,vi,nj,vj)

ni,vi,nj,vj=best
rm_cpu=vi[0]
a_cpus=vi[1:1+domain]
b_cpus=vj[:domain]
def fmt(lst): return ",".join(map(str,lst))
print(rm_cpu)
print(ni, fmt(a_cpus))
print(nj, fmt(b_cpus))
PY
)

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
DRM_BIN=/dss/dsshome1/09/ga27qam2/dynamic-resource-manager/target/release/dynamic-resource-manager
RM_LOG="$BASE_OUT/${LABEL}_rm.log"

rm -f /tmp/omp-rm.sock
DRM_CAPACITY="$t" DRM_CPU_LIST="$CPU_A_T" \
  stdbuf -oL -eL numactl --cpunodebind="$NODE_A" --membind="$NODE_A" \
  taskset -c "$RM_CPU" nice -n 15 \
  "$DRM_BIN" >> "$RM_LOG" 2>&1 &
DRM_PID=$!
sleep 0.5

# ── Worker runner ─────────────────────────────────────────────────────────────
run_worker() {
  local label="$1" dyn="$2" cpus="$3" node="$4" outfile="$5" iters="$6"
  export OMP_DYNAMIC="$dyn"

  echo "# label=$label dyn=$dyn t=$OMP_NUM_THREADS alg=$alg" > "$outfile"
  echo "# iter  start_epoch_ms  duration_ms  time_in_seconds" >> "$outfile"

  for i in $(seq 1 "$iters"); do
    local t0 t1 dur raw
    t0=$(date +%s%3N)
    raw=$(numactl --cpunodebind="$node" --membind="$node" \
            taskset -c "$cpus" \
            /dss/dsshome1/09/ga27qam2/master-thesis/NPB3.4-OMP/bin/${alg}.C.x \
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
run_worker A1 true  "$CPU_A_T" "$NODE_A" "$OUT_A1" "$iters1" &
PID_A1=$!
run_worker B1 false "$CPU_B_T" "$NODE_B" "$OUT_B1" "$iters1" &
PID_B1=$!

# ── A2 and B2 join after offset, run fewer iterations then leave ──────────────
echo "=== sleeping ${offset}s before A2/B2 ==="
sleep "$offset"

echo "=== $(date) : starting A2 and B2 (${iters2} iters each) ==="
run_worker A2 true  "$CPU_A_T" "$NODE_A" "$OUT_A2" "$iters2" &
PID_A2=$!
run_worker B2 false "$CPU_B_T" "$NODE_B" "$OUT_B2" "$iters2" &
PID_B2=$!

wait "$PID_A1" "$PID_A2" "$PID_B1" "$PID_B2"

kill "$DRM_PID" 2>/dev/null || true
wait "$DRM_PID" 2>/dev/null || true

echo "=== done ==="
echo "Results in $BASE_OUT/${LABEL}_*.log"
echo "DRM log:  $RM_LOG"
