/*
 * pchase - random pointer-chase memory latency probe.
 *
 * Builds a single random cycle of cache-line-sized stride pointers across a
 * working set, walks it for N hops, reports ns/load on stdout as JSON.
 *
 * Each "node" is one 64-byte cache line; the next-pointer is the first 8
 * bytes. A random permutation guarantees no spatial locality, so DRAM
 * latency dominates once the working set blows past LLC.
 *
 *   --working-set-mb N    working set in MiB (default 256)
 *   --hops N              number of dependent loads (default 30M)
 *   --seed N              PRNG seed (default 42)
 */
#define _GNU_SOURCE
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>

#define LINE_BYTES 64

/* xorshift64 — fast, fine for shuffling. */
static uint64_t xs_state;
static uint64_t xs64(void) {
  uint64_t x = xs_state;
  x ^= x << 13; x ^= x >> 7; x ^= x << 17;
  xs_state = x;
  return x;
}

static uint64_t now_ns(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return (uint64_t)t.tv_sec * 1000000000ULL + t.tv_nsec;
}

int main(int argc, char **argv) {
  uint64_t working_set_mb = 256;
  uint64_t hops = 30 * 1000 * 1000ULL;
  uint64_t seed = 42;

  for (int i = 1; i < argc; ++i) {
    if (i + 1 >= argc) break;
    if (!strcmp(argv[i], "--working-set-mb")) working_set_mb = strtoull(argv[++i], NULL, 10);
    else if (!strcmp(argv[i], "--hops"))      hops           = strtoull(argv[++i], NULL, 10);
    else if (!strcmp(argv[i], "--seed"))      seed           = strtoull(argv[++i], NULL, 10);
  }

  uint64_t bytes = working_set_mb * 1024ULL * 1024ULL;
  uint64_t nodes = bytes / LINE_BYTES;
  if (nodes < 2) {
    fprintf(stderr, "working set too small\n"); return 1;
  }

  /* Allocate aligned to 2 MiB to encourage 2M pages on systems where THP is
   * available; this isolates measured DRAM latency from TLB misses. */
  void *buf = NULL;
  if (posix_memalign(&buf, 2 * 1024 * 1024, bytes) != 0) {
    perror("posix_memalign"); return 1;
  }
  memset(buf, 0, bytes);
  /* Hint the kernel to back this region with huge pages if possible. */
  (void)madvise(buf, bytes, MADV_HUGEPAGE);

  /* Build a Sattolo-style single cycle of cache-line indices. */
  uint64_t *order = malloc(nodes * sizeof(uint64_t));
  if (!order) { perror("malloc"); return 1; }
  for (uint64_t i = 0; i < nodes; ++i) order[i] = i;
  xs_state = seed ? seed : 1;
  for (uint64_t i = nodes - 1; i > 0; --i) {
    uint64_t j = xs64() % i;        /* j in [0, i) — Sattolo */
    uint64_t t = order[i]; order[i] = order[j]; order[j] = t;
  }

  /* Wire the chain: lines[order[k]] points to lines[order[k+1]]. */
  uint8_t *base = (uint8_t *)buf;
  for (uint64_t k = 0; k < nodes - 1; ++k) {
    void **slot = (void **)(base + order[k] * LINE_BYTES);
    *slot = (void *)(base + order[k + 1] * LINE_BYTES);
  }
  /* Close the cycle. */
  void **last = (void **)(base + order[nodes - 1] * LINE_BYTES);
  *last = (void *)(base + order[0] * LINE_BYTES);

  free(order);

  /* Warm: walk through every line once to populate TLB and pull pages in. */
  void *p = base;
  for (uint64_t i = 0; i < nodes; ++i) p = *(void **)p;

  uint64_t t0 = now_ns();
  /* Hot loop. The dependency chain on p forbids prefetch / OoO overlap. */
  for (uint64_t i = 0; i < hops; ++i) p = *(void **)p;
  uint64_t t1 = now_ns();

  /* Sentinel touch so the compiler can't elide the chase. */
  volatile uintptr_t sentinel = (uintptr_t)p;
  (void)sentinel;

  uint64_t elapsed_ns = t1 - t0;
  double ns_per_load = (double)elapsed_ns / (double)hops;

  printf("{");
  printf("\"working_set_mb\":%" PRIu64 ",", working_set_mb);
  printf("\"hops\":%" PRIu64 ",", hops);
  printf("\"elapsed_ns\":%" PRIu64 ",", elapsed_ns);
  printf("\"ns_per_load\":%.3f,", ns_per_load);
  printf("\"line_bytes\":%d,", LINE_BYTES);
  printf("\"nodes\":%" PRIu64 ",", nodes);
  printf("\"seed\":%" PRIu64, seed);
  printf("}\n");
  return 0;
}
