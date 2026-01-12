// SPDX-License-Identifier: GPL-2.0
/*
 * smp_pingpong - Cross-vCPU round-trip latency
 *
 * Two threads pinned to two guest CPUs bounce a token and measure the
 * round-trip time in guest time.
 *
 * Modes:
 *  - spin (default): both sides busy-poll a shared atomic. Measures the
 *    raw cross-vCPU communication latency while both vCPUs stay
 *    runnable — under sync scheduling this shows how tightly the two
 *    vCPUs actually co-run.
 *  - futex (-f): the waiting side sleeps in FUTEX_WAIT and is woken
 *    with FUTEX_WAKE. Adds the guest kernel wake-up and the host
 *    scheduler's cross-vCPU kick/wake path to every hop.
 *
 * Output: one JSON object on stdout with the round-trip distribution.
 */
#include "../common/bench.h"

#include <getopt.h>
#include <linux/futex.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sys/syscall.h>
#include <unistd.h>

static atomic_int token;
static int use_futex;
static long iters = 100000;
static int cpu_a, cpu_b = 1;

static long futex_wait(atomic_int *addr, int val)
{
	return syscall(SYS_futex, addr, FUTEX_WAIT, val, NULL, NULL, 0);
}

static long futex_wake(atomic_int *addr)
{
	return syscall(SYS_futex, addr, FUTEX_WAKE, 1, NULL, NULL, 0);
}

/* Flip the token to @to and wait until the peer flips it back to @self. */
static void hop(int self, int to)
{
	atomic_store_explicit(&token, to, memory_order_release);
	if (use_futex) {
		futex_wake(&token);
		while (atomic_load_explicit(&token, memory_order_acquire) !=
		       self)
			futex_wait(&token, to);
	} else {
		while (atomic_load_explicit(&token, memory_order_acquire) !=
		       self)
			;
	}
}

static void *responder(void *arg)
{
	long i;

	(void)arg;

	if (bench_pin_to_cpu(cpu_b)) {
		perror("sched_setaffinity");
		exit(1);
	}

	for (i = 0; i < iters; i++) {
		while (atomic_load_explicit(&token, memory_order_acquire) != 1)
			if (use_futex)
				futex_wait(&token, 0);
		atomic_store_explicit(&token, 0, memory_order_release);
		if (use_futex)
			futex_wake(&token);
	}

	return NULL;
}

static void usage(const char *prog)
{
	fprintf(stderr,
		"Usage: %s [-a cpu] [-b cpu] [-n iters] [-f] [-r raw_file]\n"
		"  -a  initiator CPU (default 0)\n"
		"  -b  responder CPU (default 1)\n"
		"  -n  round trips (default 100000)\n"
		"  -f  sleep in futex instead of spinning\n"
		"  -r  dump raw per-round-trip latencies (ns) to a file\n",
		prog);
}

int main(int argc, char **argv)
{
	const char *raw_path = NULL;
	struct bench_stats st;
	uint64_t *rt_ns;
	pthread_t peer;
	long i;
	int opt;

	while ((opt = getopt(argc, argv, "a:b:n:fr:h")) != -1) {
		switch (opt) {
		case 'a':
			cpu_a = atoi(optarg);
			break;
		case 'b':
			cpu_b = atoi(optarg);
			break;
		case 'n':
			iters = atol(optarg);
			break;
		case 'f':
			use_futex = 1;
			break;
		case 'r':
			raw_path = optarg;
			break;
		default:
			usage(argv[0]);
			return opt == 'h' ? 0 : 1;
		}
	}
	if (iters <= 0 || cpu_a == cpu_b) {
		usage(argv[0]);
		return 1;
	}

	rt_ns = calloc(iters, sizeof(*rt_ns));
	if (!rt_ns) {
		perror("calloc");
		return 1;
	}

	if (bench_pin_to_cpu(cpu_a)) {
		perror("sched_setaffinity");
		return 1;
	}

	atomic_init(&token, 0);
	pthread_create(&peer, NULL, responder, NULL);

	for (i = 0; i < iters; i++) {
		uint64_t t0 = bench_now_ns();

		hop(0, 1);
		rt_ns[i] = bench_now_ns() - t0;
	}
	pthread_join(peer, NULL);

	bench_stats_compute(rt_ns, iters, &st);

	printf("{\"bench\": \"smp_pingpong\", \"cpu_a\": %d, \"cpu_b\": %d, "
	       "\"iters\": %ld, \"mode\": \"%s\", ",
	       cpu_a, cpu_b, iters, use_futex ? "futex" : "spin");
	bench_stats_json(stdout, "round_trip_ns", &st);
	printf("}\n");

	bench_dump_raw(raw_path, rt_ns, iters);
	free(rt_ns);
	return 0;
}
