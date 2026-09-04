# IRS 990 Processor Performance Monitoring Guide

This guide explains how to monitor and analyze the performance of the IRS 990 processing pipeline.

## Overview

The processor includes comprehensive performance monitoring capabilities to track:
- Processing rates and throughput
- Error rates and success metrics
- XPath caching effectiveness
- Memory usage patterns
- Bottleneck identification

## Built-in Performance Metrics

### Automatic Logging

The processor automatically logs performance metrics when verbose mode is enabled:

```bash
python 990processor.py 2017 2025 --verbose
```

**Logged Metrics:**
- Files processed per second
- Error rates and types
- XPath cache hit/miss ratios
- Memory usage statistics
- Database operation timings

### Benchmark Reports

Generate detailed benchmark reports:

```bash
# Run 120-second benchmark
python profile_pipeline.py

# Output files:
# - pipeline_profile_120s.txt (human-readable report)
# - pipeline_profile_120s.stats (binary stats for analysis)
```

**Benchmark Metrics:**
```
Execution Time: 120.29 seconds
Files Processed: 324
Processing Rate: 2.69 files/second
Error Rate: 0.00%
Throughput: 161.61 files/minute
```

## Performance Monitoring Tools

### Profiling with cProfile

```python
import cProfile
import pstats

# Profile specific functions
profiler = cProfile.Profile()
profiler.enable()

# Your code here
processor.process_xml_files()

profiler.disable()

# Generate report
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative').print_stats(20)
```

### Memory Profiling

```python
from memory_profiler import profile

@profile
def process_files():
    processor = IRS990Processor()
    processor.process_xml_files()

process_files()
```

### XPath Cache Monitoring

The processor tracks XPath cache effectiveness:

```python
# Access cache statistics
xpath_match_stats = {}

# After processing, analyze:
total_hits = sum(xpath_match_stats.values())
cache_efficiency = total_hits / total_xpath_evaluations

print(f"Cache efficiency: {cache_efficiency:.2%}")
```

## Key Performance Indicators (KPIs)

### Processing Metrics
- **Files/Second**: Target >2.5 files/second
- **Error Rate**: Target <0.1%
- **Success Rate**: Target >99.9%
- **Memory Usage**: Monitor for leaks

### Cache Performance
- **XPath Cache Hit Rate**: Target >80%
- **Cache Size**: Monitor memory impact
- **Cache Invalidation Rate**: Should be minimal

### Database Performance
- **Query Response Time**: Target <100ms average
- **Transaction Rate**: Monitor batch operations
- **Lock Contention**: Minimize with proper batching

## Monitoring Scripts

### Real-time Performance Dashboard

```bash
#!/bin/bash
# monitor_performance.sh

while true; do
    clear
    echo "=== IRS 990 Processor Performance Monitor ==="
    echo "Timestamp: $(date)"

    # Check processing status
    if [ -f "irs990.db" ]; then
        PROCESSED=$(sqlite3 irs990.db "SELECT COUNT(*) FROM XmlFiles WHERE processed = 1;")
        TOTAL=$(sqlite3 irs990.db "SELECT COUNT(*) FROM XmlFiles;")
        echo "Progress: $PROCESSED / $TOTAL files processed"
    fi

    # Check error rates
    ERRORS=$(tail -n 100 processing.log | grep -c "ERROR")
    echo "Recent errors: $ERRORS (last 100 lines)"

    # Check system resources
    echo "CPU Usage: $(top -bn1 | grep "Cpu(s)" | sed "s/.*, *\([0-9.]*\)%* id.*/\1/" | awk '{print 100 - $1"%"}')"
    echo "Memory Usage: $(free | grep Mem | awk '{printf "%.2f%", $3/$2 * 100.0}')"

    sleep 5
done
```

### Performance Trend Analysis

```python
# analyze_performance_trends.py
import sqlite3
import matplotlib.pyplot as plt
from datetime import datetime

def analyze_trends():
    conn = sqlite3.connect('irs990.db')

    # Query processing history
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            strftime('%Y-%m-%d', processed_date) as date,
            COUNT(*) as files_processed,
            AVG(processing_time) as avg_time
        FROM processing_history
        GROUP BY date
        ORDER BY date
    """)

    data = cursor.fetchall()

    # Plot trends
    dates = [row[0] for row in data]
    counts = [row[1] for row in data]
    times = [row[2] for row in data]

    plt.figure(figsize=(12, 6))

    plt.subplot(2, 1, 1)
    plt.plot(dates, counts, 'b-o')
    plt.title('Daily Processing Volume')
    plt.ylabel('Files Processed')

    plt.subplot(2, 1, 2)
    plt.plot(dates, times, 'r-o')
    plt.title('Average Processing Time')
    plt.ylabel('Time (seconds)')

    plt.tight_layout()
    plt.savefig('performance_trends.png')
    plt.show()

if __name__ == "__main__":
    analyze_trends()
```

## Bottleneck Analysis

### Identifying Performance Issues

1. **High CPU Usage**
   - Check XPath evaluation frequency
   - Monitor regex compilation
   - Profile parsing functions

2. **Memory Growth**
   - Monitor cache sizes
   - Check for object leaks
   - Profile memory allocation

3. **Slow I/O Operations**
   - ZIP file access patterns
   - Database transaction frequency
   - File system performance

4. **Thread Contention**
   - Database lock conflicts
   - Shared resource access
   - Thread synchronization overhead

### Profiling Commands

```bash
# Profile specific function
python -m cProfile -s cumulative 990processor.py 2017 2025 --step xml

# Memory profiling
python -c "
from memory_profiler import profile
import 990processor

@profile
def test():
    p = 990processor.IRS990Processor()
    p.process_xml_files()

test()
"

# Line-by-line profiling
kernprof -l 990processor.py 2017 2025
python -m line_profiler 990processor.py.lprof
```

## Optimization Validation

### Pre-optimization Baseline
```
Files/Second: ~2.2
Error Rate: >5%
Memory Usage: High (cache not optimized)
XPath Evaluations: Redundant
```

### Post-optimization Metrics
```
Files/Second: 2.69
Error Rate: 0.00%
Memory Usage: Optimized (scoped caching)
XPath Evaluations: Cached (20-30% reduction)
```

### Validation Tests

```bash
# Run optimization validation suite
python test_xpath_caching.py      # Cache effectiveness
python test_float_parsing.py      # Parsing robustness
python test_integration.py        # End-to-end performance

# Performance regression testing
python benchmark_optimizations.py
```

## Alerting and Notifications

### Performance Thresholds

Set up monitoring alerts for:

```python
# performance_alerts.py
PERFORMANCE_THRESHOLDS = {
    'processing_rate': 2.0,  # files/second
    'error_rate': 0.01,      # 1%
    'memory_usage': 80,      # percent
    'cache_hit_rate': 0.75   # 75%
}

def check_performance():
    # Current metrics
    current_rate = get_processing_rate()
    current_errors = get_error_rate()
    current_memory = get_memory_usage()
    current_cache = get_cache_hit_rate()

    alerts = []

    if current_rate < PERFORMANCE_THRESHOLDS['processing_rate']:
        alerts.append(f"Processing rate below threshold: {current_rate}")

    if current_errors > PERFORMANCE_THRESHOLDS['error_rate']:
        alerts.append(f"Error rate above threshold: {current_errors}")

    if current_memory > PERFORMANCE_THRESHOLDS['memory_usage']:
        alerts.append(f"Memory usage above threshold: {current_memory}%")

    if current_cache < PERFORMANCE_THRESHOLDS['cache_hit_rate']:
        alerts.append(f"Cache hit rate below threshold: {current_cache}")

    return alerts
```

## Reporting

### Daily Performance Report

```bash
#!/bin/bash
# daily_performance_report.sh

REPORT_DATE=$(date +%Y-%m-%d)
REPORT_FILE="performance_report_$REPORT_DATE.md"

cat > "$REPORT_FILE" << EOF
# Daily Performance Report - $REPORT_DATE

## Processing Metrics
- Files Processed: $(sqlite3 irs990.db "SELECT COUNT(*) FROM XmlFiles WHERE processed = 1;")
- Processing Rate: $(calculate_rate)
- Error Rate: $(calculate_error_rate)

## System Resources
- CPU Usage: $(get_cpu_usage)
- Memory Usage: $(get_memory_usage)
- Disk I/O: $(get_disk_io)

## Cache Performance
- XPath Cache Hits: $(get_cache_hits)
- Cache Efficiency: $(get_cache_efficiency)

## Issues Detected
$(check_for_issues)

## Recommendations
$(generate_recommendations)
EOF

echo "Daily report generated: $REPORT_FILE"
```

### Weekly Trend Analysis

```python
# weekly_trends.py
import pandas as pd
import matplotlib.pyplot as plt

def generate_weekly_report():
    # Collect 7 days of data
    df = pd.read_sql_query("""
        SELECT date, files_processed, avg_processing_time, error_rate
        FROM daily_metrics
        WHERE date >= date('now', '-7 days')
        ORDER BY date
    """, conn)

    # Generate charts
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))

    # Processing volume
    ax1.plot(df['date'], df['files_processed'])
    ax1.set_title('Daily Processing Volume')
    ax1.tick_params(axis='x', rotation=45)

    # Processing time
    ax2.plot(df['date'], df['avg_processing_time'])
    ax2.set_title('Average Processing Time')
    ax2.tick_params(axis='x', rotation=45)

    # Error rate
    ax3.plot(df['date'], df['error_rate'])
    ax3.set_title('Daily Error Rate')
    ax3.tick_params(axis='x', rotation=45)

    # Performance trend
    ax4.plot(df['date'], df['files_processed'] / df['avg_processing_time'])
    ax4.set_title('Processing Efficiency Trend')
    ax4.tick_params(axis='x', rotation=45)

    plt.tight_layout()
    plt.savefig(f'weekly_performance_{pd.Timestamp.now().strftime("%Y%m%d")}.png')

    # Generate summary
    summary = f"""
    Weekly Performance Summary ({df['date'].min()} to {df['date'].max()})

    Total Files Processed: {df['files_processed'].sum()}
    Average Daily Volume: {df['files_processed'].mean():.0f}
    Average Processing Time: {df['avg_processing_time'].mean():.2f}s
    Average Error Rate: {df['error_rate'].mean():.3f}%

    Performance Trend: {'Improving' if df['files_processed'].iloc[-1] > df['files_processed'].iloc[0] else 'Declining'}
    """

    with open(f'weekly_summary_{pd.Timestamp.now().strftime("%Y%m%d")}.txt', 'w') as f:
        f.write(summary)
```

## Maintenance Recommendations

### Regular Monitoring Tasks
1. **Daily**: Check error rates and processing volumes
2. **Weekly**: Review performance trends and cache efficiency
3. **Monthly**: Analyze bottleneck patterns and optimization opportunities

### Performance Baselines
- Establish normal operating ranges
- Set up alerts for deviations
- Track improvement over time

### Capacity Planning
- Monitor resource usage trends
- Plan for data volume growth
- Identify scaling requirements

---

*This performance monitoring guide should be reviewed and updated as the system evolves. Regular benchmarking helps maintain optimal performance.*