# queue_status_display.py
from __future__ import annotations
from queue import Queue
import time
import threading
from typing import Callable, Dict, Any, Optional, Set, List
from tqdm import tqdm
import psutil

from logging_utils import get_logger
from config import global_config

logger = get_logger(__name__)


# ----------------------------------------------------------------------
# One source of truth: which gauges belong to which pipeline step(s)
# Add a new metric → one line here → it auto-shows only when relevant
# ----------------------------------------------------------------------
GAUGE_REGISTRY = [
    # Example of "all steps" gauge
("processed_total", "Total Processed", {"all"}, lambda m: m.get("overall_total", 0), lambda m: m.get("overall_total", 0), lambda v: f"{v:,}"),

]


class QueueStatusDisplay:
    """
    Fully dynamic, step-aware queue + system monitor.
    Gauges are created lazily and only shown when the current pipeline step needs them.
    """

    def __init__(
        self,
        tracking_queue: Queue,
        update_interval: float = 1.0,
        estimated_size_per_item_mb: float = 0.002,
        custom_metrics_func: Optional[Callable[[], Dict[str, Any]]] = None,
    ):
        self.queue = tracking_queue
        self.update_interval = update_interval
        self.est_item_bytes = estimated_size_per_item_mb * 1024 * 1024
        self.custom_metrics_func = custom_metrics_func

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._process = psutil.Process()

        # Fixed bars (always shown)
        self.queue_bar = tqdm(total=100, desc="Queue Status", position=1, leave=True,
                              bar_format='{desc}: {percentage:3.0f}%|{bar}| {postfix}')
        self.mem_bar = tqdm(total=100, desc="Memory Usage", position=2, leave=True,
                            bar_format='{desc}: {percentage:3.0f}%|{bar}| {postfix}')

        # Lazily created gauges
        self._gauges: Dict[str, tqdm] = {}
        self._peaks: Dict[str, float] = {}
        self._active_keys: Set[str] = set()

    def start(self):
        if not self._thread:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        for bar in [self.queue_bar, self.mem_bar] + list(self._gauges.values()):
            bar.close()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._update_all()
                time.sleep(self.update_interval)
            except Exception as e:
                logger.exception(f"QueueStatusDisplay loop crashed: {e}")
                break

    def _update_all(self):
        custom = self.custom_metrics_func() if self.custom_metrics_func else {}
        current_step = custom.get("current_step", "unknown")  # e.g. "parse", "geolocate", "address"

        self._update_queue_bar(custom)
        self._update_memory_bar()
        self._prune_and_create_gauges(custom, current_step)
        self._update_active_gauges(custom)

    def _prune_and_create_gauges(self, metrics: dict, current_step: str):
 # Always show universal gauges
        wanted_keys = {"total_processed"}

        # Auto-discover stage gauges
        for key in metrics:
            if key.endswith('_processed') or key.endswith('_failed'):
                # Extract stage name: "census_processed" → "census"
                stage = key.rsplit('_', 1)[0]
                if current_step == 'geolocate' or stage in metrics.get('active_stages', []):
                    wanted_keys.add(key)
                    
        # Close gauges that are no longer relevant
        for key in self._active_keys - wanted_keys:
            self._gauges[key].close()
            del self._gauges[key]
            self._peaks.pop(key, None)

        # Create new gauges that just became relevant
        next_position = 3  # start after memory bar
        for key, desc, _, _, _, _ in GAUGE_REGISTRY:
            if key in wanted_keys and key not in self._gauges:
                bar = tqdm(total=100, desc=desc, position=next_position, leave=True,
                           bar_format='{desc}: {percentage:3.0f}%|{bar}| {postfix}')
                self._gauges[key] = bar
                self._peaks[key] = 0
                next_position += 1

        self._active_keys = wanted_keys

    def _update_active_gauges(self, metrics: dict):
        for key, desc, _, total_fn, value_fn, format_fn in GAUGE_REGISTRY:
            if key not in self._active_keys:
                continue
            value = value_fn(metrics)
            total = total_fn(metrics)
            self._peaks[key] = max(self._peaks[key], value)

            bar = self._gauges[key]
            pct = min((value / max(total, 1)) * 100, 100) if total > 0 else 0

            bar.n = int(pct)
            bar.set_postfix_str(f"{format_fn(value)} · Peak {self._peaks[key]:,.0f}")
            bar.refresh()

    def _update_queue_bar(self, custom: dict):
        try:
            # Use direct qsize() — the only reliable way with standard Queue
            queue_depth = self.queue.qsize()

            # Optional: estimate utilization if you know max expected
            max_expected = custom.get('overall_expected', 10000)
            utilization = min(100, (queue_depth / max(1, max_expected // 10)) * 100)

            parts = [
                f"Queue: {queue_depth:,}",
                f"Util: {utilization:.0f}%"
            ]

            self.queue_bar.n = queue_depth
            self.queue_bar.total = max_expected  # optional — shows "progress" of queue fill
            self.queue_bar.set_postfix_str(" · ".join(parts))
            self.queue_bar.refresh()
        except Exception as e:
            logger.debug(f"Failed to update queue bar: {e}")
            
    def _update_memory_bar(self):
        mem_gb = self._process.memory_info().rss / (1024**3)
        peak = max(getattr(self, "_mem_peak", mem_gb), mem_gb)
        self.__dict__["_mem_peak"] = peak

        sys_mem = psutil.virtual_memory()
        pct = mem_gb / (sys_mem.total / (1024**3)) * 100
        status = ["LOW", "MEDIUM", "HIGH", "CRITICAL"][min(int(pct // 25), 3)]

        postfix = f"{mem_gb:.1f}GB · Peak {peak:.1f}GB · Free {sys_mem.available/(1024**3):.1f}GB · {status}"
        self.mem_bar.n = int(pct)
        self.mem_bar.set_postfix_str(postfix)
        self.mem_bar.refresh()