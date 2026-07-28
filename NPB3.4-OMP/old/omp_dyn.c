#include <omp.h>
#include <stdio.h>
#include <pthread.h>
#include <unistd.h>
#include <stdlib.h>

static int read_int_env(const char *name, int fallback) {
  const char *value = getenv(name);
  if (!value || !*value) {
    return fallback;
  }
  return atoi(value);
}

static double read_double_env(const char *name, double fallback) {
  const char *value = getenv(name);
  if (!value || !*value) {
    return fallback;
  }
  return atof(value);
}

static const char *read_str_env(const char *name, const char *fallback) {
  const char *value = getenv(name);
  if (!value || !*value) {
    return fallback;
  }
  return value;
}

static void log_run_summary(int iterations,
                            double seconds,
                            int total_threads,
                            int avail_threads,
                            double mops_total,
                            const char *op_type) {
  printf(" Iterations      =             %12d\n", iterations);
  printf(" Time in seconds =             %12.2f\n", seconds);
  if (total_threads > 0) {
    printf(" Total threads   =             %12d\n", total_threads);
  }
  if (avail_threads > 0) {
    printf(" Avail threads   =             %12d\n", avail_threads);
  }
  printf(" Mop/s total     =             %12.2f\n", mops_total);
  if (total_threads > 0) {
    printf(" Mop/s/thread    =             %12.2f\n",
           mops_total / (double)total_threads);
  }
  printf(" Operation type  = %24s\n", op_type);
}

void parallelRegion(int id){
    printf("[REGION %d] pthread id: %lu, omp tid: %d/%d\n",
           id,
           pthread_self(),
           omp_get_thread_num(),
           omp_get_num_threads());
    const int num_threads = omp_get_num_threads();
    int cores = read_int_env("OMP_DYN_CORES", omp_get_num_procs());
    if (cores <= 0) {
        cores = 1;
    }
    const int oversub = (num_threads + cores - 1) / cores;
    const double base_seconds = read_double_env("OMP_DYN_BUSY_SECONDS", 2.0);
    const double busy_seconds = base_seconds * (double)oversub;
    const double start = omp_get_wtime();
    volatile double sink = 0.0;
    while (omp_get_wtime() - start < busy_seconds) {
        sink += 1.0;
    }
}

int main() {
  int total_threads = 0;
  int avail_threads = omp_get_max_threads();
  double start = 0.0;
  double end = 0.0;

  printf("PID: %d\n", getpid());
  start = omp_get_wtime();

  #pragma omp parallel
  {
    #pragma omp single
    total_threads = omp_get_num_threads();
    parallelRegion(1);
  }

  #pragma omp parallel
  {
    parallelRegion(2);
  }

  end = omp_get_wtime();

  {
    int iterations = read_int_env("OMP_DYN_ITERATIONS", 2);
    double seconds = read_double_env("OMP_DYN_TIME_SECONDS", end - start);
    double mops_total = read_double_env("OMP_DYN_MOPS_TOTAL", 0.0);
    const char *op_type = read_str_env("OMP_DYN_OPTYPE", "floating point");
    log_run_summary(iterations,
                    seconds,
                    total_threads,
                    avail_threads,
                    mops_total,
                    op_type);
  }

  printf("done\n");
}
