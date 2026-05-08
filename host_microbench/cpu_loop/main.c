/*
 * cpu_loop - deterministic CPU-bound bench with periodic vtime sampling.
 *
 * Runs a fixed-cost inner kernel ("ticks" of work) until the guest's
 * CLOCK_MONOTONIC reaches a target duration. Emits samples of
 * (mono_ns, ticks_done) every --sample-ms guest-time milliseconds, plus a
 * final summary, as a single JSON object on stdout.
 *
 * The point of the periodic samples: post-processing can compute max-min
 * vtime skew and work-vs-vtime curves across N concurrent VMs, which is
 * exactly the scheduling claim S1 wants to prove.
 *
 * Args:
 *   --duration-s N    target guest-monotonic duration (default 30)
 *   --sample-ms N     sample interval in guest-monotonic ms (default 100)
 *   --inner N         inner-loop trip count per tick (default 100000)
 */
#define _GNU_SOURCE
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static uint64_t now_ns(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return (uint64_t)t.tv_sec * 1000000000ULL + t.tv_nsec;
}

/* Deterministic inner kernel. Independent of memory/IO so it's pure CPU.
 * Compiler can't elide because the result feeds back through `acc`. */
static inline uint64_t inner_kernel(uint64_t iters, uint64_t seed) {
  uint64_t a = seed | 1;
  for (uint64_t i = 0; i < iters; ++i) {
    /* Mix: integer multiply + xor + rotate. About a dozen ops per iter. */
    a = a * 6364136223846793005ULL + 1442695040888963407ULL;
    a ^= (a >> 33);
    a = (a << 17) | (a >> 47);
  }
  return a;
}

#define MAX_SAMPLES 100000

int main(int argc, char **argv) {
  uint64_t duration_s = 30;
  uint64_t sample_ms = 100;
  uint64_t inner = 100000;

  for (int i = 1; i < argc; ++i) {
    if (i + 1 >= argc) break;
    if (!strcmp(argv[i], "--duration-s")) duration_s = strtoull(argv[++i], NULL, 10);
    else if (!strcmp(argv[i], "--sample-ms")) sample_ms = strtoull(argv[++i], NULL, 10);
    else if (!strcmp(argv[i], "--inner"))     inner     = strtoull(argv[++i], NULL, 10);
  }

  uint64_t target_ns = duration_s * 1000000000ULL;
  uint64_t sample_ns = sample_ms * 1000000ULL;

  static uint64_t s_mono[MAX_SAMPLES];
  static uint64_t s_ticks[MAX_SAMPLES];
  uint64_t n_samples = 0;

  uint64_t t0 = now_ns();
  uint64_t next_sample = t0;
  uint64_t ticks = 0;
  uint64_t sink = 0;

  while (1) {
    uint64_t now = now_ns();
    if (now - t0 >= target_ns) break;
    if (now >= next_sample && n_samples < MAX_SAMPLES) {
      s_mono[n_samples] = now;
      s_ticks[n_samples] = ticks;
      n_samples++;
      next_sample = now + sample_ns;
    }
    sink ^= inner_kernel(inner, ticks);
    ticks++;
  }
  uint64_t t1 = now_ns();

  /* Sentinel touch. */
  volatile uint64_t out = sink;
  (void)out;

  printf("{");
  printf("\"mono_start\":%" PRIu64 ",", t0);
  printf("\"mono_end\":%" PRIu64 ",", t1);
  printf("\"duration_s\":%" PRIu64 ",", duration_s);
  printf("\"sample_ms\":%" PRIu64 ",", sample_ms);
  printf("\"inner\":%" PRIu64 ",", inner);
  printf("\"total_ticks\":%" PRIu64 ",", ticks);
  printf("\"work_per_guest_s\":%.3f,",
         (double)ticks / ((double)(t1 - t0) / 1e9));
  printf("\"samples\":[");
  for (uint64_t i = 0; i < n_samples; ++i) {
    if (i) printf(",");
    printf("[%" PRIu64 ",%" PRIu64 "]", s_mono[i], s_ticks[i]);
  }
  printf("]}\n");
  return 0;
}
