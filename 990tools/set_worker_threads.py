#!/usr/bin/env python3
"""
set_worker_threads.py - Binary search script to find optimal worker thread count

This script performs a thorough binary search to find the optimal number of worker threads
for IRS 990 processing. It tests different worker counts over fixed time durations and
measures throughput to determine the sweet spot for parallelism.

Usage:
    python set_worker_threads.py [--min-workers MIN] [--max-workers MAX] [--iterations N] [--duration MINUTES]

Example:
    python set_worker_threads.py --min-workers 2 --max-workers 32 --iterations 3 --duration 10
"""

import subprocess
import time
import argparse
import sys
import os

def run_test(workers, duration_minutes=10):
    """Run a processing test with given worker count for specified duration and return files processed"""
    duration_seconds = duration_minutes * 60
    cmd = f'python irs990processor.py --quiet --start-step xml --stop-step xml --profile {duration_seconds} --workers {workers}'
    print(f'Testing with {workers} workers for {duration_minutes} minutes...')

    start_time = time.time()
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=os.path.dirname(__file__))
    end_time = time.time()

    elapsed = end_time - start_time

    if result.returncode == 0:
        # Parse the output to extract files processed
        output_lines = result.stdout.split('\n')
        files_processed = 0
        for line in output_lines:
            if 'Files processed:' in line:
                try:
                    files_processed = int(line.split(':')[1].strip())
                    break
                except (ValueError, IndexError):
                    pass

        throughput = files_processed / elapsed if elapsed > 0 else 0
        print(f'  Processed: {files_processed} files in {elapsed:.2f} seconds ({throughput:.2f} files/sec)')
        return files_processed, throughput
    else:
        print(f'  Failed: {result.stderr[:200]}...')
        return None, None

def binary_search_workers(min_workers=2, max_workers=64, iterations=3, duration_minutes=10):
    """Perform binary search for optimal worker count"""
    best_workers = None
    best_files = 0
    best_throughput = 0

    print('Starting binary search for optimal worker count...')
    print(f'Testing range: {min_workers}-{max_workers} workers, {iterations} iterations, {duration_minutes} minutes each')

    for iteration in range(iterations):
        print(f'\nIteration {iteration + 1}:')

        # Test current bounds and additional points for thorough search
        results = {}

        # Test min bound
        files_min, throughput_min = run_test(min_workers, duration_minutes)
        if files_min is not None:
            results[min_workers] = (files_min, throughput_min)

        # Test max bound
        files_max, throughput_max = run_test(max_workers, duration_minutes)
        if files_max is not None:
            results[max_workers] = (files_max, throughput_max)

        # Test midpoint
        mid_workers = (min_workers + max_workers) // 2
        if mid_workers not in results:
            files_mid, throughput_mid = run_test(mid_workers, duration_minutes)
            if files_mid is not None:
                results[mid_workers] = (files_mid, throughput_mid)

        # Test additional points for more thorough search
        quarter1 = min_workers + (mid_workers - min_workers) // 2
        quarter3 = mid_workers + (max_workers - mid_workers) // 2

        for test_workers in [quarter1, quarter3]:
            if test_workers not in results and min_workers < test_workers < max_workers:
                files_test, throughput_test = run_test(test_workers, duration_minutes)
                if files_test is not None:
                    results[test_workers] = (files_test, throughput_test)

        # Find best in this iteration (by throughput)
        if results:
            iter_best_workers = max(results.keys(), key=lambda w: results[w][1])  # Max by throughput
            iter_best_files, iter_best_throughput = results[iter_best_workers]

            print(f'  Best in iteration: {iter_best_workers} workers ({iter_best_files} files, {iter_best_throughput:.2f} files/sec)')

            # Update overall best
            if iter_best_throughput > best_throughput:
                best_throughput = iter_best_throughput
                best_files = iter_best_files
                best_workers = iter_best_workers

            # Narrow search space around the best (wider range for more exploration)
            if iter_best_workers == min_workers:
                max_workers = mid_workers
            elif iter_best_workers == max_workers:
                min_workers = mid_workers
            else:
                # Best is in middle, search around it with wider bounds
                search_radius = max(4, (max_workers - min_workers) // 4)
                min_workers = max(min_workers, iter_best_workers - search_radius)
                max_workers = min(max_workers, iter_best_workers + search_radius)

    print(f'Overall best: {best_workers} workers ({best_files} files processed, {best_throughput:.2f} files/sec)')
    return best_workers, best_files, best_throughput

def main():
    parser = argparse.ArgumentParser(description='Find optimal worker thread count for IRS 990 processing')
    parser.add_argument('--min-workers', type=int, default=2, help='Minimum worker count to test')
    parser.add_argument('--max-workers', type=int, default=64, help='Maximum worker count to test')
    parser.add_argument('--iterations', type=int, default=3, help='Number of binary search iterations')
    parser.add_argument('--duration', type=int, default=10, help='Duration in minutes for each test run')

    args = parser.parse_args()

    if args.min_workers < 2:
        print("Error: Minimum workers must be at least 2")
        sys.exit(1)

    optimal_workers, best_files, best_throughput = binary_search_workers(
        args.min_workers, args.max_workers, args.iterations, args.duration
    )

    print("\nOptimal configuration:")
    print(f"  Workers: {optimal_workers}")
    print(f"  Files processed: {best_files}")
    print(f"  Throughput: {best_throughput:.2f} files/second")
    print(f"  Estimated hourly throughput: {best_throughput * 3600:.0f} files/hour")

if __name__ == '__main__':
    main()