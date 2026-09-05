#include <omp.h>
#include <stdio.h>
#include <pthread.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <sys/syscall.h>

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

/* Native threads the process currently owns, counted from the OS rather than
   from OpenMP. A team size says nothing about how many workers still exist. */
static int native_thread_count(void) {
  DIR *dir = opendir("/proc/self/task");
  if (!dir) {
    return -1;
  }
  int count = 0;
  struct dirent *entry;
  while ((entry = readdir(dir)) != NULL) {
    if (entry->d_name[0] != '.') {
      count++;
    }
  }
  closedir(dir);
  return count;
}

/* Worker-lifecycle sequence: regions of differing size, every thread's identity
   recorded in every region, and the native population sampled around each one.
   Records both the POSIX handle and the Linux thread id, because only the
   latter is comparable with libomp's own diagnostic lines.
   Returns the first region's actual team size. */
static int run_region_sequence(const char *spec) {
  const double dwell = read_double_env("OMP_DYN_REGION_DWELL_SECONDS", 1.0);
  char *copy = strdup(spec);
  if (!copy) {
    return 0;
  }

  int index = 0;
  int first_team_size = 0;
  for (char *tok = strtok(copy, ","); tok != NULL; tok = strtok(NULL, ",")) {
    const int requested = atoi(tok);
    if (requested < 1) {
      continue;
    }
    index++;
    printf("[SEQ region %d] requested=%d native_threads_before=%d\n",
           index, requested, native_thread_count());
    fflush(stdout);

    int team_size = 0;
    #pragma omp parallel num_threads(requested)
    {
      #pragma omp single
      team_size = omp_get_num_threads();

      #pragma omp critical
      {
        printf("[SEQ region %d] omp_tid=%d/%d pthread=%lu os_tid=%ld\n",
               index, omp_get_thread_num(), omp_get_num_threads(),
               (unsigned long)pthread_self(), (long)syscall(SYS_gettid));
        fflush(stdout);
      }

      const double start = omp_get_wtime();
      volatile double sink = 0.0;
      while (omp_get_wtime() - start < dwell) {
        sink += 1.0;
      }
    }

    if (index == 1) {
      first_team_size = team_size;
    }
    printf("[SEQ region %d] team_size=%d native_threads_after=%d\n",
           index, team_size, native_thread_count());
    fflush(stdout);
  }

  free(copy);
  return first_team_size;
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
  printf("native_threads_start = %d\n", native_thread_count());
  start = omp_get_wtime();

  /* OMP_DYN_REGION_SIZES (e.g. "16,4,4") selects the worker-lifecycle sequence.
     Unset, the two busy regions of the grant sweep run unchanged. */
  const char *sequence = getenv("OMP_DYN_REGION_SIZES");
  if (sequence && *sequence) {
    total_threads = run_region_sequence(sequence);
  } else {
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
  }

  end = omp_get_wtime();
  printf("native_threads_end = %d\n", native_thread_count());

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
