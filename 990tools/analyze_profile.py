import pstats
import sys

# Load the profiling data
stats = pstats.Stats('profile_output.prof')

print("=== PROFILING ANALYSIS REPORT ===\n")

print("Top 20 functions by cumulative time:")
stats.sort_stats('cumulative').print_stats(20)

print("\n" + "="*50 + "\n")

print("Top 20 functions by total time:")
stats.sort_stats('time').print_stats(20)

print("\n" + "="*50 + "\n")

# Get stats as dictionary for pattern analysis
stats_dict = stats.stats

# Patterns to look for related to locks, queues, threading
patterns = ['lock', 'queue', 'thread', 'sync', 'mutex', 'semaphore', 'condition', 'event']

print("Functions potentially related to synchronization primitives:")
sync_functions = []
for func, (cc, nc, tt, ct, callers) in stats_dict.items():
    func_str = str(func).lower()
    if any(pat in func_str for pat in patterns):
        sync_functions.append((func, ct, tt))

# Sort by cumulative time descending
sync_functions.sort(key=lambda x: x[1], reverse=True)

if sync_functions:
    for func, ct, tt in sync_functions[:20]:  # Top 20
        print(f"Function: {func}")
        print(f"  Cumulative time: {ct:.4f}s")
        print(f"  Total time: {tt:.4f}s")
        print()
else:
    print("No functions found with synchronization-related names.")

print("\n" + "="*50 + "\n")

# Additional analysis: look for high cumulative time functions that might indicate bottlenecks
print("Potential bottlenecks (functions with high cumulative time > 1.0s):")
bottlenecks = []
for func, (cc, nc, tt, ct, callers) in stats_dict.items():
    if ct > 1.0:  # Threshold for significant time
        bottlenecks.append((func, ct, tt))

bottlenecks.sort(key=lambda x: x[1], reverse=True)

for func, ct, tt in bottlenecks[:10]:  # Top 10
    print(f"Function: {func}")
    print(f"  Cumulative time: {ct:.4f}s")
    print(f"  Total time: {tt:.4f}s")
    print()