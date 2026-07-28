#!/bin/bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/paths.sh"

algorithm=$1
run_name=$2
iterations=${3:-1}
dyn=${4:-"false"}
basedir=$5
iter_start=${6:-1}   # output file index for first iteration

outdir="$basedir/$run_name/${algorithm}"
mkdir -p "$outdir"

logfile="$outdir/${algorithm}_log_t${OMP_NUM_THREADS}.txt"
echo "Batch run started: $(date)" >> "$logfile"

export OMP_DYNAMIC="$dyn"
echo "dyn=$OMP_DYNAMIC num_threads=$OMP_NUM_THREADS" | tee -a "$logfile"

start=$(date +%s%3N)

pids=()
for i in $(seq "$iter_start" "$((iter_start + iterations - 1))"); do
  outfile="$outdir/${algorithm}_threads_${OMP_NUM_THREADS}_dyn_${dyn}_${i}.out"
  "$NPB_BIN/${algorithm}.C.x" > "$outfile" 2>&1 &
  pids+=($!)
done
wait "${pids[@]}"

end=$(date +%s%3N)
runtime=$((end - start))
echo "dyn ${dyn} finished: $(date) (Duration: ${runtime}ms)" >> "$logfile"
