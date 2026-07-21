// SPDX-License-Identifier: GPL-2.0
/*
 * timer_jitter - Periodic timer wake-up latency in guest time
 *
 * Arms an absolute CLOCK_MONOTONIC timer at a fixed period and records
 * how late each wake-up is relative to its deadline. Under ossim sync
 * scheduling the observed latency is in virtual time, so the
 * distribution should match an idle dedicated machine regardless of
 * host-side contention.
 *
 * Output: one JSON object on stdout with the wake-latency distribution
 * in nanoseconds.
 */
#include "../common/bench.h"

#include <getopt.h>
#include <unistd.h>

static void usage(const char *prog)
{
	fprintf(stderr,
		"Usage: %s [-p period_us] [-n iters] [-w warmup_iters]\n"
		"          [-c cpu] [-r raw_output_file]\n"
		"  -p  timer period in microseconds (default 1000)\n"
		"  -n  measured iterations (default 10000)\n"
		"  -w  warm-up iterations, not recorded (default 100)\n"
		"  -c  pin to this guest CPU (default: no pinning)\n"
		"  -r  dump raw per-wake latencies (ns) to a file\n",
		prog);
}

int main(int argc, char **argv)
{
	long period_us = 1000, iters = 10000, warmup = 100;
	const char *raw_path = NULL;
	struct bench_stats st;
	struct bench_tail_counts tails;
	struct timespec next;
	uint64_t *lat_ns;
	uint64_t next_ns;
	long i, cpu = -1;
	int opt;

	while ((opt = getopt(argc, argv, "p:n:w:c:r:h")) != -1) {
		switch (opt) {
		case 'p':
			period_us = atol(optarg);
			break;
		case 'n':
			iters = atol(optarg);
			break;
		case 'w':
			warmup = atol(optarg);
			break;
		case 'c':
			cpu = atol(optarg);
			break;
		case 'r':
			raw_path = optarg;
			break;
		default:
			usage(argv[0]);
			return opt == 'h' ? 0 : 1;
		}
	}
	if (period_us <= 0 || iters <= 0 || warmup < 0) {
		usage(argv[0]);
		return 1;
	}

	if (cpu >= 0 && bench_pin_to_cpu((int)cpu)) {
		perror("sched_setaffinity");
		return 1;
	}

	lat_ns = calloc(iters, sizeof(*lat_ns));
	if (!lat_ns) {
		perror("calloc");
		return 1;
	}

	next_ns = bench_now_ns() + (uint64_t)period_us * 1000;
	for (i = -warmup; i < iters; i++) {
		uint64_t now;

		next.tv_sec = next_ns / 1000000000ull;
		next.tv_nsec = next_ns % 1000000000ull;
		while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next,
				       NULL))
			;

		now = bench_now_ns();
		if (i >= 0)
			lat_ns[i] = now > next_ns ? now - next_ns : 0;

		/*
		 * Schedule relative to the deadline, not the wake-up time,
		 * so one late wake does not shift every later deadline.
		 */
		next_ns += (uint64_t)period_us * 1000;
		if (next_ns <= now)
			next_ns = now + (uint64_t)period_us * 1000;
	}

	bench_stats_compute(lat_ns, iters, &st);
	bench_tail_counts_compute(lat_ns, iters, &tails);

	printf("{\"bench\": \"timer_jitter\", "
	       "\"clock\": \"CLOCK_MONOTONIC\", \"cpu\": %ld, "
	       "\"period_us\": %ld, \"warmup_iters\": %ld, ",
	       cpu, period_us, warmup);
	bench_stats_json(stdout, "wake_latency_ns", &st);
	printf(", \"tail_counts\": ");
	bench_tail_counts_json(stdout, &tails);
	printf("}\n");

	bench_dump_raw(raw_path, lat_ns, iters);
	free(lat_ns);
	return 0;
}
