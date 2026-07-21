// SPDX-License-Identifier: GPL-2.0
/*
 * smp_barrier - Cross-vCPU barrier synchronization throughput
 *
 * One thread per guest CPU repeatedly meets at a barrier, optionally
 * doing a fixed amount of dummy work between rounds. Barrier rounds per
 * guest-time second degrade directly with vCPU time skew, so this is an
 * end-to-end probe of how tightly the scheduler co-runs the vCPUs of a
 * VM. Thread 0 additionally samples its per-round barrier wait time.
 *
 * Modes: the default spin barrier busy-waits (stresses co-scheduling
 * hardest); -s uses a pthread barrier instead, which sleeps in futex
 * and therefore also exercises the cross-vCPU wake-up path.
 *
 * Output: one JSON object on stdout.
 */
#include "../common/bench.h"

#include <getopt.h>
#include <pthread.h>
#include <stdatomic.h>
#include <unistd.h>

struct spin_barrier {
	atomic_int count;
	atomic_int sense;
	int nthreads;
};

static struct spin_barrier sbar;
static pthread_barrier_t pbar;
static int use_sleep_barrier;
static int nthreads;
static int first_cpu;
static long iters = 100000;
static long work_cycles;
static uint64_t *wait_ns; /* thread 0's per-round barrier wait */

static void spin_barrier_wait(struct spin_barrier *b, int *local_sense)
{
	*local_sense = !*local_sense;
	if (atomic_fetch_add_explicit(&b->count, 1, memory_order_acq_rel) ==
	    b->nthreads - 1) {
		atomic_store_explicit(&b->count, 0, memory_order_relaxed);
		atomic_store_explicit(&b->sense, *local_sense,
				      memory_order_release);
	} else {
		while (atomic_load_explicit(&b->sense, memory_order_acquire) !=
		       *local_sense)
			;
	}
}

static void *worker(void *arg)
{
	int id = (int)(intptr_t)arg;
	int local_sense = 0;
	volatile uint64_t sink = 0;
	long i, w;

	if (bench_pin_to_cpu(first_cpu + id)) {
		perror("sched_setaffinity");
		exit(1);
	}

	for (i = 0; i < iters; i++) {
		uint64_t t0 = 0;

		for (w = 0; w < work_cycles; w++)
			sink += w;

		if (id == 0)
			t0 = bench_now_ns();

		if (use_sleep_barrier) {
			pthread_barrier_wait(&pbar);
		} else {
			spin_barrier_wait(&sbar, &local_sense);
		}

		if (id == 0)
			wait_ns[i] = bench_now_ns() - t0;
	}

	(void)sink;
	return NULL;
}

static void usage(const char *prog)
{
	fprintf(stderr,
		"Usage: %s [-a first_cpu] [-t threads] [-n iters] "
		"[-w work_cycles] [-s] [-r raw_file]\n"
		"  -a  first CPU; threads use consecutive CPUs (default 0)\n"
		"  -t  threads, one per CPU starting at first_cpu "
		"(default: online CPUs)\n"
		"  -n  barrier rounds (default 100000)\n"
		"  -w  dummy work iterations between rounds (default 0)\n"
		"  -s  use a sleeping pthread barrier instead of a spin barrier\n"
		"  -r  dump raw thread-0 barrier waits in temporal order\n",
		prog);
}

int main(int argc, char **argv)
{
	pthread_t *threads;
	struct bench_stats st;
	struct bench_tail_counts tails;
	const char *raw_path = NULL;
	uint64_t start, elapsed;
	int opt, i;

	nthreads = (int)sysconf(_SC_NPROCESSORS_ONLN);

	while ((opt = getopt(argc, argv, "a:t:n:w:sr:h")) != -1) {
		switch (opt) {
		case 'a':
			first_cpu = atoi(optarg);
			break;
		case 't':
			nthreads = atoi(optarg);
			break;
		case 'n':
			iters = atol(optarg);
			break;
		case 'w':
			work_cycles = atol(optarg);
			break;
		case 's':
			use_sleep_barrier = 1;
			break;
		case 'r':
			raw_path = optarg;
			break;
		default:
			usage(argv[0]);
			return opt == 'h' ? 0 : 1;
		}
	}
	if (nthreads < 2 || iters <= 0 || first_cpu < 0) {
		usage(argv[0]);
		return 1;
	}

	sbar.nthreads = nthreads;
	atomic_init(&sbar.count, 0);
	atomic_init(&sbar.sense, 0);
	pthread_barrier_init(&pbar, NULL, nthreads);

	wait_ns = calloc(iters, sizeof(*wait_ns));
	threads = calloc(nthreads, sizeof(*threads));
	if (!wait_ns || !threads) {
		perror("calloc");
		return 1;
	}

	if (bench_pin_to_cpu(first_cpu)) {
		perror("sched_setaffinity");
		return 1;
	}

	start = bench_now_ns();
	for (i = 1; i < nthreads; i++)
		pthread_create(&threads[i], NULL, worker,
			       (void *)(intptr_t)i);
	worker((void *)(intptr_t)0);
	for (i = 1; i < nthreads; i++)
		pthread_join(threads[i], NULL);
	elapsed = bench_now_ns() - start;

	bench_stats_compute(wait_ns, iters, &st);
	bench_tail_counts_compute(wait_ns, iters, &tails);

	printf("{\"bench\": \"smp_barrier\", \"threads\": %d, \"iters\": %ld, "
	       "\"work_cycles\": %ld, \"mode\": \"%s\", "
	       "\"clock\": \"CLOCK_MONOTONIC\", "
	       "\"cpu_first\": %d, \"cpu_last\": %d, "
	       "\"elapsed_ns\": %llu, \"rounds_per_sec\": %.1f, ",
	       nthreads, iters, work_cycles,
	       use_sleep_barrier ? "sleep" : "spin",
	       first_cpu, first_cpu + nthreads - 1,
	       (unsigned long long)elapsed,
	       (double)iters / ((double)elapsed / 1e9));
	bench_stats_json(stdout, "t0_wait_ns", &st);
	printf(", \"tail_counts\": ");
	bench_tail_counts_json(stdout, &tails);
	printf("}\n");
	bench_dump_raw(raw_path, wait_ns, iters);

	free(threads);
	free(wait_ns);
	return 0;
}
