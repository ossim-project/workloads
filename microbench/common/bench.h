/* SPDX-License-Identifier: GPL-2.0 */
/*
 * bench.h - Shared helpers for the ossim guest microbenchmarks
 *
 * All benchmarks measure in CLOCK_MONOTONIC, which under ossim sync
 * scheduling advances in virtual time via pvclock. Results are printed
 * as a single JSON object on stdout so the host-side harness can parse
 * them from the serial log or the shared /out directory.
 */
#ifndef MICROBENCH_BENCH_H
#define MICROBENCH_BENCH_H

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static inline uint64_t bench_now_ns(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (uint64_t)ts.tv_sec * 1000000000ull + ts.tv_nsec;
}

static inline int bench_pin_to_cpu(int cpu)
{
	cpu_set_t set;

	CPU_ZERO(&set);
	CPU_SET(cpu, &set);
	return sched_setaffinity(0, sizeof(set), &set);
}

struct bench_stats {
	uint64_t min;
	uint64_t max;
	double mean;
	uint64_t p50;
	uint64_t p90;
	uint64_t p99;
	size_t n;
};

struct bench_tail_counts {
	size_t zero;
	size_t gt_10us;
	size_t gt_1ms;
	size_t gt_10ms;
	size_t gt_100ms;
	size_t gt_1s;
};

static inline void bench_tail_counts_compute(const uint64_t *samples, size_t n,
					     struct bench_tail_counts *tails)
{
	size_t i;

	memset(tails, 0, sizeof(*tails));
	for (i = 0; i < n; i++) {
		tails->zero += samples[i] == 0;
		tails->gt_10us += samples[i] > 10000;
		tails->gt_1ms += samples[i] > 1000000;
		tails->gt_10ms += samples[i] > 10000000;
		tails->gt_100ms += samples[i] > 100000000;
		tails->gt_1s += samples[i] > 1000000000;
	}
}

static inline void bench_tail_counts_json(FILE *f,
					  const struct bench_tail_counts *tails)
{
	fprintf(f,
		"{\"zero\": %zu, \"gt_10us\": %zu, \"gt_1ms\": %zu, "
		"\"gt_10ms\": %zu, \"gt_100ms\": %zu, \"gt_1s\": %zu}",
		tails->zero, tails->gt_10us, tails->gt_1ms, tails->gt_10ms,
		tails->gt_100ms, tails->gt_1s);
}

static int bench_cmp_u64(const void *a, const void *b)
{
	uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;

	return x < y ? -1 : x > y ? 1 : 0;
}

static inline void bench_stats_compute(const uint64_t *samples, size_t n,
				       struct bench_stats *st)
{
	uint64_t *sorted;
	double sum = 0.0;
	size_t i;

	sorted = malloc(n * sizeof(*sorted));
	if (!sorted) {
		perror("malloc statistics scratch space");
		exit(1);
	}
	memcpy(sorted, samples, n * sizeof(*sorted));
	qsort(sorted, n, sizeof(*sorted), bench_cmp_u64);
	for (i = 0; i < n; i++)
		sum += (double)samples[i];

	st->n = n;
	st->min = sorted[0];
	st->max = sorted[n - 1];
	st->mean = sum / (double)n;
	st->p50 = sorted[n / 2];
	st->p90 = sorted[(size_t)((double)(n - 1) * 0.90)];
	st->p99 = sorted[(size_t)((double)(n - 1) * 0.99)];
	free(sorted);
}

static inline void bench_stats_json(FILE *f, const char *key,
				    const struct bench_stats *st)
{
	fprintf(f,
		"\"%s\": {\"n\": %zu, \"min\": %llu, \"mean\": %.1f, "
		"\"p50\": %llu, \"p90\": %llu, \"p99\": %llu, \"max\": %llu}",
		key, st->n, (unsigned long long)st->min, st->mean,
		(unsigned long long)st->p50, (unsigned long long)st->p90,
		(unsigned long long)st->p99, (unsigned long long)st->max);
}

/* Optional raw-sample dump, one value per line; @path may be NULL. */
static inline int bench_dump_raw(const char *path, const uint64_t *samples,
				 size_t n)
{
	FILE *f;
	size_t i;

	if (!path)
		return 0;

	f = fopen(path, "w");
	if (!f) {
		perror("fopen raw output");
		return -1;
	}
	for (i = 0; i < n; i++)
		fprintf(f, "%llu\n", (unsigned long long)samples[i]);
	fclose(f);
	return 0;
}

#endif /* MICROBENCH_BENCH_H */
