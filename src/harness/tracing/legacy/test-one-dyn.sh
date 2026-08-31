#!/bin/bash
run_name=$1

iterations=2

# Ordner anlegen, falls nicht vorhanden
outdir="benchmarks/over/$run_name"
if [ ! -d "$outdir" ]; then
	mkdir -p "$outdir"
fi

logfile="$outdir/log_t${OMP_NUM_THREADS}.txt"
echo "Batch run started: $(date)" >> "$logfile"


# Test mit OMP_DYNAMIC=true
start_true=$(date +%s%3N)
export OMP_DYNAMIC=true
echo "dyn=$OMP_DYNAMIC num_threads=$OMP_NUM_THREADS" | tee -a "$logfile"
for i in $(seq 1 $iterations); do
	outfile="$outdir/threads_${OMP_NUM_THREADS}_dyn_true_${i}.out"
	touch "$outfile"
	./omp > "$outfile" 2>&1 &
done
wait
end_true=$(date +%s%3N)
runtime_true=$((end_true - start_true))
echo "dyn true finished: $(date) (Duration: ${runtime_true}ms)" >> "$logfile"


# Test mit OMP_DYNAMIC=false
start_false=$(date +%s%3N)
export OMP_DYNAMIC=false
echo "dyn=$OMP_DYNAMIC num_threads=$OMP_NUM_THREADS" | tee -a "$logfile"
for i in $(seq 1 $iterations); do
	outfile="$outdir/threads_${OMP_NUM_THREADS}_dyn_false_${i}.out"
	touch "$outfile"
	./omp > "$outfile" 2>&1 &
done
wait
end_false=$(date +%s%3N)
runtime_false=$((end_false - start_false))
echo "dyn false finished: $(date) (Duration: ${runtime_false}ms)" >> "$logfile"
