// SPDX-License-Identifier: GPL-2.0
/*
 * simple_compute - Per-vCPU compute throughput without shared state
 *
 * N threads are pinned to consecutive guest CPUs. After one start barrier,
 * every thread executes an independent xorshift64 dependency chain. The
 * measured region contains no inter-thread synchronization or shared-memory
 * communication, so it isolates per-vCPU execution and clock/accounting cost
 * from gang/co-run effects.
 */
#include "../common/bench.h"

#include <getopt.h>
#include <limits.h>
#include <pthread.h>
#include <stdbool.h>
#include <unistd.h>

struct worker_result {
	uint64_t start_ns;
	uint64_t end_ns;
	uint64_t elapsed_ns;
	uint64_t checksum;
	double iterations_per_sec;
	int cpu;
	bool clock_regression;
};

struct worker_arg {
	pthread_barrier_t *start_barrier;
	struct worker_result *result;
	long iterations;
	int cpu;
};

static uint64_t xorshift64(uint64_t state)
{
	state ^= state << 13;
	state ^= state >> 7;
	state ^= state << 17;
	return state;
}

static void *worker(void *opaque)
{
	struct worker_arg *arg = opaque;
	struct worker_result *result = arg->result;
	uint64_t state = 0x9e3779b97f4a7c15ull ^ (uint64_t)arg->cpu;
	long i;

	if (bench_pin_to_cpu(arg->cpu)) {
		perror("sched_setaffinity");
		exit(1);
	}

	pthread_barrier_wait(arg->start_barrier);
	result->start_ns = bench_now_ns();
	for (i = 0; i < arg->iterations; i++)
		state = xorshift64(state);
	result->end_ns = bench_now_ns();

	result->cpu = arg->cpu;
	result->checksum = state;
	result->clock_regression = result->end_ns < result->start_ns;
	result->elapsed_ns = result->clock_regression ? 0 :
		result->end_ns - result->start_ns;
	result->iterations_per_sec = result->elapsed_ns ?
		(double)arg->iterations / ((double)result->elapsed_ns / 1e9) : 0.0;
	return NULL;
}

static void usage(const char *prog)
{
	fprintf(stderr,
		"Usage: %s [-a first_cpu] [-t threads] [-n iterations]\n"
		"  -a  first CPU; threads use consecutive CPUs (default 0)\n"
		"  -t  number of worker threads (default 2)\n"
		"  -n  iterations per thread (default 10000000)\n",
		prog);
}

int main(int argc, char **argv)
{
	long iterations = 10000000;
	int first_cpu = 0, nthreads = 2;
	struct worker_result *results;
	struct worker_arg *args;
	pthread_barrier_t start_barrier;
	pthread_t *threads;
	uint64_t min_start = ULLONG_MAX, max_start = 0;
	uint64_t min_end = ULLONG_MAX, max_end = 0;
	uint64_t elapsed_window;
	long total_iterations;
	double aggregate_rate;
	int regressions = 0;
	int i, opt;

	while ((opt = getopt(argc, argv, "a:t:n:h")) != -1) {
		switch (opt) {
		case 'a':
			first_cpu = atoi(optarg);
			break;
		case 't':
			nthreads = atoi(optarg);
			break;
		case 'n':
			iterations = atol(optarg);
			break;
		default:
			usage(argv[0]);
			return opt == 'h' ? 0 : 1;
		}
	}
	if (first_cpu < 0 || nthreads <= 0 || iterations <= 0 ||
	    first_cpu + nthreads > CPU_SETSIZE) {
		usage(argv[0]);
		return 1;
	}

	threads = calloc(nthreads, sizeof(*threads));
	args = calloc(nthreads, sizeof(*args));
	results = calloc(nthreads, sizeof(*results));
	if (!threads || !args || !results) {
		perror("calloc");
		return 1;
	}
	if (pthread_barrier_init(&start_barrier, NULL, nthreads)) {
		perror("pthread_barrier_init");
		return 1;
	}

	for (i = 0; i < nthreads; i++) {
		args[i].start_barrier = &start_barrier;
		args[i].result = &results[i];
		args[i].iterations = iterations;
		args[i].cpu = first_cpu + i;
		if (pthread_create(&threads[i], NULL, worker, &args[i])) {
			perror("pthread_create");
			return 1;
		}
	}
	for (i = 0; i < nthreads; i++)
		pthread_join(threads[i], NULL);

	for (i = 0; i < nthreads; i++) {
		if (results[i].start_ns < min_start)
			min_start = results[i].start_ns;
		if (results[i].start_ns > max_start)
			max_start = results[i].start_ns;
		if (results[i].end_ns < min_end)
			min_end = results[i].end_ns;
		if (results[i].end_ns > max_end)
			max_end = results[i].end_ns;
		regressions += results[i].clock_regression;
	}

	elapsed_window = max_end < min_start ? 0 : max_end - min_start;
	total_iterations = iterations * (long)nthreads;
	aggregate_rate = elapsed_window ?
		(double)total_iterations / ((double)elapsed_window / 1e9) : 0.0;

	printf("{\"bench\": \"simple_compute\", "
	       "\"clock\": \"CLOCK_MONOTONIC\", "
	       "\"compute_kernel\": \"xorshift64\", "
	       "\"threads\": %d, \"cpu_first\": %d, \"cpu_last\": %d, "
	       "\"iterations_per_thread\": %ld, \"total_iterations\": %ld, "
	       "\"elapsed_window_ns\": %llu, "
	       "\"aggregate_iterations_per_sec\": %.1f, "
	       "\"start_skew_ns\": %llu, \"finish_skew_ns\": %llu, "
	       "\"clock_regressions\": %d, \"thread_results\": [",
	       nthreads, first_cpu, first_cpu + nthreads - 1, iterations,
	       total_iterations, (unsigned long long)elapsed_window, aggregate_rate,
	       (unsigned long long)(max_start - min_start),
	       (unsigned long long)(max_end - min_end), regressions);
	for (i = 0; i < nthreads; i++) {
		if (i)
			printf(", ");
		printf("{\"cpu\": %d, \"start_ns\": %llu, \"end_ns\": %llu, "
		       "\"elapsed_ns\": %llu, \"iterations_per_sec\": %.1f, "
		       "\"checksum\": %llu, \"clock_regression\": %s}",
		       results[i].cpu,
		       (unsigned long long)results[i].start_ns,
		       (unsigned long long)results[i].end_ns,
		       (unsigned long long)results[i].elapsed_ns,
		       results[i].iterations_per_sec,
		       (unsigned long long)results[i].checksum,
		       results[i].clock_regression ? "true" : "false");
	}
	printf("]}\n");

	pthread_barrier_destroy(&start_barrier);
	free(results);
	free(args);
	free(threads);
	return 0;
}
