# pipeline.py — THE ONE TRUE PIPELINE
# All your features. All correct. All yours.

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, List, Optional, Callable, Tuple, Generic, TypeVar, Union
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from pending_database_context import PendingDatabaseContext
from database_operations import DatabaseOperations
from queue_status_display import QueueStatusDisplay
from constants import BATCH_SIZE, CONSUMER_BATCH_SIZE
import logging_utils
from logging_utils import log_error, log_info

# Generics first
W = TypeVar("W", bound="WorkUnit")

# ==============================
# Constants
# ==============================
BACKPRESSURE_ENABLED_DEFAULT = False
ADAPTIVE_BACKPRESSURE = False
BACKPRESSURE_THRESHOLD = 2000
IDLE_THRESHOLD = 500
ADAPTIVE_INTERVAL = 30
MIN_WORKERS = {'grok': 4, 'census': 1}
MAX_WORKERS = {'grok': 32, 'census': 8}
ADAPTIVE_STAGES = ['grok', 'census']
MONITOR_UPDATE = 30
BATCHER_TIMEOUT = 1.0  # default; geocoding pipelines override via GEOCODING_BATCHER_TIMEOUT
CONSUMER_THRESHOLD = CONSUMER_BATCH_SIZE  # when to flush merged PDCs

# ==============================
# WorkUnit
# ==============================
@dataclass
class WorkUnit:
    type: str  # 'work', 'result', 'sentinel', 'batch'
    data: Any = None
    stage: Optional[str] = None
    producer_id: Optional[int] = None
    items: List["WorkUnit"] = field(default_factory=list)

    @classmethod
    def work_item(cls, stage: str, data: Any) -> "WorkUnit":
        return cls(type='work', data=data, stage=stage)

    @classmethod
    def result(cls, stage: str, context: PendingDatabaseContext) -> "WorkUnit":
        return cls(type='result', data=context, stage=stage)

    @classmethod
    def sentinel(cls, producer_id: int = 999) -> "WorkUnit":
        return cls(type='sentinel', producer_id=producer_id)

    @classmethod
    def batch(cls, stage: str, work_units: List["WorkUnit"]) -> "WorkUnit":
        return cls(type='batch', stage=stage, items=work_units)

    def is_work_item(self) -> bool:
        return self.type == 'work'

    def is_result(self) -> bool:
        return self.type == 'result'

    def is_sentinel(self) -> bool:
        return self.type == 'sentinel'

    def is_batch(self) -> bool:
        return self.type == 'batch'

    def copy(self) -> "WorkUnit":
        return WorkUnit(
            type=self.type,
            data=self.data,
            stage=self.stage,
            producer_id=self.producer_id,
            items=[item.copy() for item in self.items]
        )

    def __str__(self) -> str:
        if self.is_batch():
            return f"<Batch {self.stage} size={len(self.items)}>"
        return f"<WorkUnit {self.type} stage={self.stage}/>"

@dataclass
class ResultWorkUnit(WorkUnit):
    """Specialized WorkUnit for pipeline results (PendingDatabaseContext)."""
    type: str = field(default='result', init=False)
    data: PendingDatabaseContext = field(default_factory=PendingDatabaseContext)

    @classmethod
    def result(cls, stage: str, context: PendingDatabaseContext) -> "ResultWorkUnit":
        return cls(stage=stage, data=context)

    def is_result(self) -> bool:
        return self.type == 'result'
    
DEBUG_PIPELINE = False

class AtomicCounter:
    def __init__(self, initial=0):
        self._value = initial
        self._lock = threading.Lock()

    def inc(self, amount=1):
        with self._lock:
            self._value += amount
        return self._value

    def dec(self, amount=1):
        with self._lock:
            self._value -= amount
        return self._value

    def get(self):
        with self._lock:
            return self._value

    def set(self, value):
        with self._lock:
            self._value = value
        
# ==============================
# Base PipelineStage
# ==============================

class PipelineStage(Generic[W]):
    def __init__(
        self,
        name: str,
        workers: int,
        batch_size: int,
        handler: Callable[[List[W]], List[Tuple[bool, W]]],
        pipeline: Optional["Pipeline[W]"] = None,
        *,
        next_on_success: Optional["PipelineStage[W]"] = None,
        next_on_failure: Optional["PipelineStage[W]"] = None,
        is_final_failure: bool = False,
        max_workers: int = 64,
        worker_queue_maxsize: Optional[int] = None,
        batcher_timeout: Optional[float] = None,
    ):
        self.name = name
        self.workers = workers
        if DEBUG_PIPELINE:
            self.workers = 1
        self.batch_size = batch_size
        self.handler: Callable[[List[W]], List[Tuple[bool, W]]] = handler
        self.pipeline = pipeline
        self.next_on_success = next_on_success
        self.next_on_failure = next_on_failure
        self.is_final_failure = is_final_failure
        self.max_workers = max_workers
        self.batcher_timeout = batcher_timeout if batcher_timeout is not None else BATCHER_TIMEOUT

        self.input_queue = queue.Queue()  # unbounded — batcher absorbs bursts
        self.worker_queue = (
            queue.Queue(maxsize=worker_queue_maxsize)
            if worker_queue_maxsize is not None
            else queue.Queue()
        )
        self.executor = None
        self.current_workers = AtomicCounter(0)
        self.batcher_thread = None        
        self.stop_event = threading.Event()
        self.workload = AtomicCounter(0)


        self.metrics = {
            'total': 0,
            'success': 0,
            'failure': 0,
            'current_queue': 0,
            'peak_queue': 0,
            'input_queue_size': 0,
            'worker_queue_size': 0,
            'nThreads': 0,
        }

    def _update_queue_metrics(self):
        inp = self.input_queue.qsize()
        wrk = self.worker_queue.qsize()
        combined = inp + wrk
        self.metrics['input_queue_size'] = inp
        self.metrics['worker_queue_size'] = wrk
        self.metrics['current_queue'] = combined
        self.metrics['peak_queue'] = max(self.metrics['peak_queue'], combined)

    def set_executor(self, executor: ThreadPoolExecutor):
        self.executor = executor
        self._start_batcher()
        self._start_workers()

    def _start_batcher(self):
        def batcher():
            pending = []
            while not self.stop_event.is_set():
                unit = None
                try:
                    unit = self.input_queue.get(timeout=self.batcher_timeout)
                    if unit: self.input_queue.task_done() # ack
                    if unit.is_sentinel():
                        if pending:
                            self._push_batch(pending)
                            pending = []
                        # Drain stragglers / extra shutdown sentinels (never requeue — causes deadlock)
                        while True:
                            try:
                                extra = self.input_queue.get_nowait()
                                self.input_queue.task_done()
                                if extra and not extra.is_sentinel():
                                    if extra.is_batch():
                                        pending.extend(extra.items)
                                    else:
                                        pending.append(extra)
                            except queue.Empty:
                                break
                        if pending:
                            self._push_batch(pending)
                            pending = []
                        for _ in range(max(1, self.workers)):
                            self.worker_queue.put(WorkUnit.sentinel())
                        break

                    if unit.is_batch():
                        pending.extend(unit.items)
                    else:
                        pending.append(unit)

                    while len(pending) >= self.batch_size:
                        batch_chunk = pending[:self.batch_size]
                        if DEBUG_PIPELINE:
                            print(f"[{self.name}] BATCHING {len(batch_chunk)} units")
                        self._push_batch(batch_chunk)
                        pending = pending[self.batch_size:]

                except queue.Empty:
                    if pending:
                        self._push_batch(pending)
                        pending = []
                        if self.stop_event.is_set(): break
                        continue
                except Exception as e:
                    print(f"ERROR in {self.name} batcher: {e.__class__.__name__}: {str(e)}")
                    continue
                
            if  DEBUG_PIPELINE: print(f"[{self.name}] batcher exited")

        self.batcher_thread = threading.Thread(target=batcher, daemon=True, name=f"{self.name}_batcher")
        self.batcher_thread.start()

    def _push_batch(self, batch_units: List[W]):
        if not batch_units:
            return
        if len(batch_units) == 1:
            self.workload.inc()
            self.worker_queue.put(batch_units[0])
        else:
            # Use the pipeline's workunit_class to create a batch of the correct type
            batch_obj = self.pipeline.workunit_class.batch(self.name, batch_units)
            self.workload.inc(len(batch_units))
            self.worker_queue.put(batch_obj)
        self._update_queue_metrics()

    def _start_workers(self):
        for _ in range(self.workers):
            self._spawn_worker()

    def _spawn_worker(self):
        self.current_workers.inc()
        self.metrics['nThreads'] = self.current_workers.get()
        if  DEBUG_PIPELINE: print(f"SPAWNING WORKER for {self.name} — total: {self.current_workers}")

        def worker():
            if DEBUG_PIPELINE:
                print(f"WORKER STARTED for {self.name} T:{threading.current_thread().name}")
            pending = []

            exited=False
            while not self.stop_event.is_set() and not exited:
                unit = None
                try:
                    unit = self.worker_queue.get(timeout=1.0)
                    if unit and DEBUG_PIPELINE:
                        print(f"[{self.name}] GOT → {unit!s} (pending={len(pending)})")
                    if unit.is_sentinel():
                        if pending:
                            self._process_batch(pending)
                            pending = []
                        self.worker_queue.task_done()
                        exited = True
                        self.current_workers.dec()
                        self.metrics['nThreads'] = self.current_workers.get()
                        break

                    if unit.is_batch():
                        pending.extend(unit.items)
                    else:
                        pending.append(unit)

                    while len(pending) >= self.batch_size:
                        batch_chunk = pending[:self.batch_size]
                        self._process_batch(batch_chunk)
                        pending = pending[self.batch_size:]

                except queue.Empty:
                    if pending:
                        self._process_batch(pending)
                        pending = []
                        if self.stop_event.is_set(): break
                        continue
                except Exception as e:
                    log_error(f"ERROR in {self.name} worker: {e}")
            if  DEBUG_PIPELINE: print(f"[{self.name}] worker exited")  # Debug print for exit confirmation
            self.current_workers.dec()
            self.metrics['nThreads'] = self.current_workers.get()
        self.executor.submit(worker)

    def _process_batch(self, batch: List[W]):
        if not batch:
            return
        self.metrics['total'] += len(batch)
        self._update_queue_metrics()
        if DEBUG_PIPELINE:
            print(f"[{self.name}] PROCESSING BATCH of {len(batch)} units")
        try:
            results = self.handler(batch)
            success_units = []
            failure_units = []

            for continue_flag, output in results:
                if isinstance(output, ResultWorkUnit):
                    # Success with result context — forward to consumer as ResultWorkUnit
                    self.pipeline.result_consumer.put(output)
                    if continue_flag:
                        self.metrics['success'] += 1
                    else:
                        self.metrics['failure'] += 1
                else:
                    # Forward the original unit (W subclass)
                    if continue_flag:
                        success_units.append(output)
                    else:
                        failure_units.append(output)

            if DEBUG_PIPELINE:
                sname = self.next_on_success.name if self.next_on_success else "None"
                fname = self.next_on_failure.name if self.next_on_failure else "None"
                print(f"[{self.name}] FORWARDING {len(success_units)} success [{sname}], {len(failure_units)} failure units [{fname}]") 
            self._forward(success_units, self.next_on_success)
            self._forward(failure_units, self.next_on_failure)

        except Exception as e:
            log_error(f"Handler failed in {self.name}: {e}")
            self._forward(batch, self.next_on_failure)
            self.metrics['failure'] += len(batch)
        finally:
            self.worker_queue.task_done()
            self.workload.dec(len(batch))

    def _forward(self, units: List[W], target: Optional["PipelineStage[W]"]):
        if not units:
            return
        for u in units:
            u.stage = target.name
        if target:
            if len(units) == 1:
                target.put(units[0])
            else:
                batch = self.pipeline.workunit_class.batch(self.name, units)
                target.put(batch)
        else:
            # Should only happen if no next stage — normally results go to consumer
            for unit in units:
                self.pipeline.result_consumer.put(unit)

    def put(self, unit: W):
        self.input_queue.put(unit)
        self.metrics['total'] += 1 if unit.is_work_item() else len(unit.items) if unit.is_batch() else 0
        self._update_queue_metrics()

    def adjust_workers(self, new_workers: int):
        delta = new_workers - self.current_workers.get()
        if delta > 0:
            for _ in range(delta):
                self._spawn_worker()
        self.workers = new_workers
# ==============================
# ConsumerStage: Custom class because only the consumer can write to the DB
# ==============================
class ConsumerStage(PipelineStage):
    def __init__(
        self,
        name: str,
        db_ops: DatabaseOperations,
        threshold: int,
        pipeline: Optional["Pipeline"] = None,
        checkpoint_interval: int = 10_000,
    ):
        super().__init__(
            name=name,
            workers=1,
            batch_size=threshold,
            handler=self._consume_handler,
            pipeline=pipeline,
            max_workers=1,
        )
        self.db_ops = db_ops
        self.last_checkpoint = 0
        self.checkpoint_interval = checkpoint_interval

    def _admission_release_count(self, ctx: PendingDatabaseContext) -> int:
        return ctx.count_completed_work_items()

    def _consume_handler(self, batch: List[ResultWorkUnit]) -> List[Tuple[bool, Any]]:
        print(f"###ERROR### CONSUMER HANDLER: Processing batch of {len(batch)} units, should never be called")
        merged = PendingDatabaseContext()
        for unit in batch:
            if unit.is_result():
                merged.merge([unit.data])
        self.db_ops.process_pdc(merged)
        return [(True, None) for _ in batch]  # No forward
    
    def _flush_check(self, pending_contexts: List[PendingDatabaseContext], accumulated_updates: int, total_updates: int)  -> bool:
        if accumulated_updates >= self.batch_size:
            if  DEBUG_PIPELINE: print(f"[{self.name}] Threshhold Reached — pending={len(pending_contexts)}, accumulated={accumulated_updates}")
            self._flush_pending_contexts(pending_contexts, accumulated_updates, total_updates)
            return True
        return False
    
    def _spawn_worker(self):
       self.current_workers.inc()
       self.metrics['nThreads'] = 1
       if  DEBUG_PIPELINE: print(f"SPAWNING WORKER for {self.name} — total: {self.current_workers.get()}")

       def worker():
           if DEBUG_PIPELINE: print(f"WORKER STARTED for Consumer")
           pending_contexts: List[PendingDatabaseContext] = []
           accumulated_updates = 0
           total_updates = 0
           exited=False
           while not self.stop_event.is_set() and not exited:
               unit = None
               try:
                    unit = self.worker_queue.get(timeout=1.0)
                    if unit:
                        self.worker_queue.task_done()
                    if DEBUG_PIPELINE: print(f"[{self.name}] GOT → {unit!s} (pending={len(pending_contexts)})")
                    if unit and unit.is_result(): 
                        if  DEBUG_PIPELINE: print(f"[{self.name}] Result Unit recieved Pending Context, {len(pending_contexts)}")
                    
                    
                        
                    if unit.is_sentinel():
                        self._flush_pending_contexts(pending_contexts, accumulated_updates, total_updates)
                        exited = True
                        pending_contexts = []
                        total_updates += accumulated_updates
                        accumulated_updates = 0
                        if DEBUG_PIPELINE:
                            print(f"[{self.name}] EXITING on sentinel")
                        break
                    elif unit.is_result() and isinstance(unit.data, PendingDatabaseContext):
                        ctx = unit.data
                        pending_contexts.append(ctx)
                        added = ctx.estimated_updates or ctx.getTotalObjectCount() or 1
                        accumulated_updates += added
                        self.workload.inc(added)
                        print(f"[{self.name}] Added {added} updates to pending contexts, {len(pending_contexts)} {accumulated_updates} {self.batch_size}")
                        if self._flush_check(pending_contexts, accumulated_updates, total_updates):
                            pending_contexts = []
                            total_updates += accumulated_updates
                            accumulated_updates = 0

                        release_count = self._admission_release_count(ctx)
                        self.metrics['success'] += 1
                        self.pipeline._record_global_success(release_count)
                    elif unit.is_batch():
                        contexts = [item.data for item in unit.items if item.is_result() and isinstance(item.data, PendingDatabaseContext)]
                        added = sum([ctx.estimated_updates or ctx.getTotalObjectCount() or 1 for ctx in contexts])
                        release_count = sum(self._admission_release_count(ctx) for ctx in contexts)
                        self.metrics['success'] += len(contexts)
                        self.pipeline._record_global_success(release_count)
                        accumulated_updates += added
                        pending_contexts.extend(contexts)
                        if self._flush_check(pending_contexts, accumulated_updates, total_updates):
                            pending_contexts = []
                            total_updates += accumulated_updates
                            accumulated_updates = 0
   
                    else:
                        print(f"Error wrong Unit type in 'result' {unit.type}")
                        
               except queue.Empty:
                   if pending_contexts:
                       self._flush_pending_contexts(pending_contexts, accumulated_updates,total_updates)
                       pending_contexts = []
                       total_updates += accumulated_updates
                       accumulated_updates = 0
                   continue
               except Exception as e:
                    print(f"[{self.name}] UNEXPECTED ERROR in get(): {e.__class__.__name__}: {str(e)}")
                    # Optional: add traceback
                    import traceback
                    traceback.print_exc()
                    # Continue loop — don't let thread die
                    continue
    

           if pending_contexts:
               self._flush_pending_contexts(pending_contexts, accumulated_updates, -1)
               pending_contexts=[]
           self.current_workers.dec()
           self.metrics['nThreads'] = self.current_workers.get()
           print(f"[{self.name}] worker exited")

       self.executor.submit(worker)

    def _flush_pending_contexts(self, contexts: List[PendingDatabaseContext], count: int, totalups: int):
        if not contexts:
            return
        print(f"Consumer flushing {len(contexts)} PDCs (~{count:,} updates)")
        merged = PendingDatabaseContext.merge(contexts)
        try:
            should_checkpoint = (
                totalups == -1
                or (totalups - self.last_checkpoint) >= self.checkpoint_interval
            )
            merged.save_to_database(self.db_ops, checkpoint=should_checkpoint)
            rows_saved = merged.count_geocoding_status_updates()
            if rows_saved:
                self.pipeline._record_rows_committed(rows_saved)
            if should_checkpoint:
                if totalups != -1:
                    self.last_checkpoint = totalups
                log_info(
                    f"[{self.name}] FORCE CHECKPOINT at ~{totalups:,} cumulative updates "
                    f"(interval={self.checkpoint_interval:,})"
                )
        except Exception as e:
            log_error(f"[{self.name}] ERROR saving to database: {e}")
            print(f"[{self.name}] ERROR saving to database: {e}", flush=True)
            proc = getattr(self.pipeline, '_geocode_processor', None)
            if proc and hasattr(proc, 'run_stats'):
                proc.run_stats.save_errors += 1
        
        self.workload.dec(len(contexts))

# ==============================
# Pipeline
# ==============================
class Pipeline(Generic[W]):
    
    master= None
    def __init__(
        self,
        stages: List[PipelineStage[W]],
        db_ops: DatabaseOperations,
        backpressure_enabled: bool = BACKPRESSURE_ENABLED_DEFAULT,
        in_flight_cap: int = BACKPRESSURE_THRESHOLD,
        chain_on: str = 'success',
        workunit_class: type[W] = WorkUnit,
        consumer_threshold: int = CONSUMER_BATCH_SIZE,
        checkpoint_interval: int = 10_000,
        buffered_feed: bool = False,
        feed_buffer_batches: Optional[int] = None,
        batcher_timeout: Optional[float] = None,
    ):
        if chain_on not in ('success', 'failure'):
            raise ValueError(f"Invalid chain_on: {chain_on}")
        self.chain_on = chain_on
        self.stages = {s.name: s for s in stages}
        self.order = ['feed'] +[s.name for s in stages] + ['result']
        self.db_ops = db_ops
        self.workunit_class = workunit_class
        self.buffered_feed = buffered_feed
        self.feed_buffer_batches = feed_buffer_batches
        self.batcher_timeout = batcher_timeout

        for stage in self.stages.values():
            stage.pipeline = self
            if batcher_timeout is not None and stage.batcher_timeout == BATCHER_TIMEOUT:
                stage.batcher_timeout = batcher_timeout
        self.backpressure_enabled = backpressure_enabled and not buffered_feed
        self.in_flight_cap = in_flight_cap
        self._admission_queue: Optional[queue.Queue] = None
        if self.backpressure_enabled:
            self._admission_queue = queue.Queue(maxsize=in_flight_cap)
            for _ in range(in_flight_cap):
                self._admission_queue.put_nowait(None)

        # Feed handler: pass full W, not .data
        continue_flag = False if chain_on == 'failure' else True
        feed_wq_max = feed_buffer_batches if buffered_feed and feed_buffer_batches else None
        self.feed_stage = PipelineStage[W](
            name="feed",
            workers=1,
            batch_size=10000,
            handler=lambda batch: [(continue_flag, wu) for wu in batch],
            pipeline=self,
            worker_queue_maxsize=feed_wq_max,
            batcher_timeout=batcher_timeout,
        )
        self.stages["feed"] = self.feed_stage

        self.result_consumer = ConsumerStage(
            name="result",
            db_ops=db_ops,
            threshold=consumer_threshold,
            pipeline=self,
            checkpoint_interval=checkpoint_interval,
        )
        self.stages["result"] = self.result_consumer

        chain_attr = 'next_on_success' if chain_on == 'success' else 'next_on_failure'
        for i, stage in enumerate(stages):
            if i + 1 < len(stages):
                setattr(stage, chain_attr, stages[i + 1])
        if stages:
            setattr(self.feed_stage, chain_attr, stages[0])

        self.metrics = {
            'overall': {'total': 0, 'success': 0, 'failure': 0, 'expected': 0, 'rows_committed': 0},
            'stages': {}
        }
        for stage in stages:
            self.metrics['stages'][stage.name] = {
                'total': 0,
                'success': 0,
                'failure': 0,
                'current_queue': 0,
                'peak_queue': 0,
                'nThreads': stage.workers,
            }

        for stage in [self.feed_stage] + stages+ [self.result_consumer]:
            stage.set_executor(ThreadPoolExecutor(max_workers=stage.max_workers, thread_name_prefix=stage.name))
            print(f"Executor created with prefix: {stage.name}")
            

        if ADAPTIVE_BACKPRESSURE:
            self._start_adaptive_monitor()
        Pipeline.master = self

    def _record_global_total(self, count: int = 1):
        self.metrics['overall']['total'] += count

    def _record_global_success(self, count: int = 1):
        self.metrics['overall']['success'] += count
        if self._admission_queue is not None:
            for _ in range(count):
                self._admission_queue.put(None, block=True)

    def _record_rows_committed(self, count: int):
        if count > 0:
            self.metrics['overall']['rows_committed'] += count

    def feed(self, items: List[Any]):
        if not items:
            return
        if DEBUG_PIPELINE:
            print(f"FEEDING BATCH of {len(items)} items (buffered={self.buffered_feed})")
        if self.buffered_feed:
            work_units: List[W] = []
            for item in items:
                if isinstance(item, self.workunit_class) and item.is_work_item():
                    wu = item
                    wu.stage = "feed"
                    work_units.append(wu)
                else:
                    data = item.data if hasattr(item, "data") else item
                    work_units.append(self.workunit_class.work_item("feed", data))
            if len(work_units) == 1:
                self.feed_stage.put(work_units[0])
            else:
                self.feed_stage.put(self.workunit_class.batch("feed", work_units))
        else:
            for item in items:
                if self._admission_queue is not None:
                    self._admission_queue.get(block=True)
                data = item.data if hasattr(item, "data") else item
                wu = self.workunit_class.work_item("feed", data)
                self.feed_stage.put(wu)

    def _format_queue_sizes(self) -> str:
        parts = []
        for name in self.order:
            stage = self.stages.get(name)
            if not stage:
                continue
            stage._update_queue_metrics()
            parts.append(
                f"{name}:in={stage.metrics['input_queue_size']}"
                f"/wrk={stage.metrics['worker_queue_size']}"
            )
        return " ".join(parts)

    def run_with_provider(self, provider, max_items: Optional[int] = None):
        total = provider.get_total_work()
        if max_items is not None:
            total = min(total, max_items)
        self.metrics['overall']['expected'] = total
        print(f"Pipeline starting — {total:,} items")

        first_stage_queue = self.stages[self.order[0]].worker_queue if self.stages else self.feed_stage.worker_queue
        self.queue_status_display = QueueStatusDisplay(
            tracking_queue=first_stage_queue,
            update_interval=MONITOR_UPDATE,
            custom_metrics_func=self.get_status
        )
        self.queue_status_display.start()

        processed = 0
        last_id = None

        while True:
            batch, new_last_id = provider.get_work_batch(last_id)
            if not batch:
                break

            if max_items is not None:
                remaining = max_items - processed
                if remaining <= 0:
                    break
                if len(batch) > remaining:
                    batch = batch[:remaining]

            self.feed(batch)
            self._record_global_total(len(batch))
            processed += len(batch)
            last_id = new_last_id

            if processed % 10000 == 0 or processed == total:
                pdcs_saved = self.metrics['overall']['success']
                rows_saved = self.metrics['overall'].get('rows_committed', 0)
                in_flight = max(0, processed - rows_saved)
                q_sizes = self._format_queue_sizes()
                print(
                    f"→ {processed:,}/{total:,} fed | rows_saved={rows_saved:,} "
                    f"in_flight≈{in_flight:,} pdcs={pdcs_saved:,} | queues: {q_sizes}",
                    flush=True,
                )
                proc = getattr(self, '_geocode_processor', None)
                if proc and hasattr(proc, 'run_stats'):
                    s = proc.run_stats
                    step = getattr(proc, 'pipeline_step', 'geolocate_new')
                    if step == "geolocate_grok":
                        print(
                            f"[{step}] running grok_match={s.grok_match:,} "
                            f"grok_fail={s.grok_fail:,} rows_saved={rows_saved:,} "
                            f"in_flight≈{in_flight:,} pdcs={pdcs_saved:,} save_err={s.save_errors:,}",
                            flush=True,
                        )
                    elif step == "geolocate_census":
                        snap = s.census_call_snapshot()
                        print(
                            f"[{step}] running census={s.census_match:,} "
                            f"census_strip={s.census_strip_match:,} "
                            f"preprocess={s.preprocess_match:,} "
                            f"pending_api={s.pending_api_queued:,} rows_saved={rows_saved:,} "
                            f"in_flight≈{in_flight:,} pdcs={pdcs_saved:,} save_err={s.save_errors:,} "
                            f"census_calls={snap['census_calls']}+{snap['census_strip_calls']}strip "
                            f"failures={snap['failures']} avg_s={snap['avg_s']:.1f} "
                            f"rate={snap['rate_hr']:.1f}/hr",
                            flush=True,
                        )
                    elif step == "geolocate_api":
                        print(
                            f"[{step}] running preprocess={s.preprocess_match:,} "
                            f"other={s.other_match:,} grok_queued={s.grok_queued:,} "
                            f"rows_saved={rows_saved:,} in_flight≈{in_flight:,} "
                            f"pdcs={pdcs_saved:,} save_err={s.save_errors:,}",
                            flush=True,
                        )
                    else:
                        print(
                            f"[{step}] running census={s.census_match:,} "
                            f"census_strip={s.census_strip_match:,} "
                            f"preprocess={s.preprocess_match:,} other={s.other_match:,} "
                            f"grok_queued={s.grok_queued:,} rows_saved={rows_saved:,} "
                            f"in_flight≈{in_flight:,} pdcs={pdcs_saved:,} save_err={s.save_errors:,}",
                            flush=True,
                        )
                else:
                    print(
                        f"[pipeline] rows_saved={rows_saved:,} in_flight≈{in_flight:,} pdcs={pdcs_saved:,}",
                        flush=True,
                    )

        print("Last batch sent — starting graceful shutdown...")
        self.shutdown()
        print(f"Pipeline complete — {processed:,} processed")
        self._log_stage_summary()
        return processed
        
    @classmethod
    def result(cls, stage: str, context: PendingDatabaseContext) -> ResultWorkUnit:
        """Create a result unit (non-generic, always ResultWorkUnit)."""
        return ResultWorkUnit(stage=stage, data=context)
    
    def _log_stage_summary(self):
        print("[pipeline] Stage metrics:", flush=True)
        for name in self.order:
            stage = self.stages.get(name)
            if not stage:
                continue
            m = stage.metrics
            print(
                f"  {name}: total={m.get('total', 0):,} success={m.get('success', 0):,} "
                f"failure={m.get('failure', 0):,} peak_q={m.get('peak_queue', 0):,}",
                flush=True,
            )
        o = self.metrics['overall']
        print(
            f"  overall: fed={o.get('total', 0):,} rows_saved={o.get('rows_committed', 0):,} "
            f"pdcs={o.get('success', 0):,} expected={o.get('expected', 0):,}",
            flush=True,
        )

    def _join_with_timeout(self, q, name: str, timeout_s: int = 24*3600):
        """Poll join w/ timeout."""
        start = time.time()
        while time.time() - start < timeout_s:
            if q.unfinished_tasks == 0:  # qsize() unreliable
                print(f"{name} joined OK")
                return True
            time.sleep(0.5)
        print(f"*** TIMEOUT *** {name} unfinished_tasks={q.unfinished_tasks}")
        return False

    def shutdown(self):
        """
        Deterministic sequential shutdown:
        - Poison each stage one-by-one, waiting for upstream to drain first
        - This lets work/sentinels flow naturally downstream
        """
        print("Initiating graceful shutdown — poisoning sequentially")
        print(f"shutdown order{self.order}")

        for i, stage_name in enumerate(self.order):
            stage = self.stages[stage_name]
            nThreads = stage.current_workers.get()
            # One sentinel for the batcher; it fans out per-worker sentinels on worker_queue.
            stage.input_queue.put(WorkUnit.sentinel())

            print(f"Poisoned {stage.name} with 1 input sentinel ({nThreads} workers)")
            if stage.name == 'result':
                 print(f"result sentinels {nThreads}") # this is here for a breakpoint

            # Join input_queue: wait for batcher to flush to worker_queue
            print(f"joining input_queue for {stage.name}")
            self._join_with_timeout(stage.input_queue, f"batcher for {stage.name}")

            print(f"joining worker_queue for {stage.name} {stage.workload.get()}")

            # Join worker_queue: wait for workers to process and exit
            print(f"  -> Joining worker_queue for {stage.name} (unfinished_tasks={stage.worker_queue.unfinished_tasks if hasattr(stage.worker_queue, 'unfinished_tasks') else 'N/A'})")
            self._join_with_timeout(stage.worker_queue, f"work_queue for {stage.name}")
            print(f"  -> worker_queue drained - stage {stage.name} done")            
            stage.executor.shutdown(wait=False, cancel_futures=True)  # Non-blocking shutdown
            stage.executor._threads.clear()      # Force-clear internal thread refs (undocumented but works)
            stage.executor=None # Force GC
            # Safety: force any lingering loops to break
            stage.stop_event.set()

            print(f"{stage.name} fully drained — {nThreads} workers exited")

        print("Pipeline shutdown complete — all stages drained deterministically")

    def get_status(self) -> dict:
        prefixed = {}
        for stage_name, stage in ({"feed": self.feed_stage, **self.stages, "result": self.result_consumer}).items():
            stage._update_queue_metrics()
            prefix = f"{stage_name}_"
            for k, v in stage.metrics.items():
                prefixed[f"{prefix}{k}"] = v

        prefixed.update({
            'overall_total': self.metrics['overall']['total'],
            'overall_success': self.metrics['overall']['success'],
            'overall_expected': self.metrics['overall']['expected'],
            'overall_failure': self.metrics['overall']['failure'],
            'in_flight': sum(s.metrics['current_queue'] for s in self.stages.values()),
            'queue_sizes': self._format_queue_sizes(),
        })

        return {
            'stages': ['feed'] + self.order + ['result'],
            'metrics': prefixed,
        }

    def _start_adaptive_monitor(self):
        def monitor():
            while True:
                time.sleep(MONITOR_UPDATE)
                for stage_name, stage in self.stages.items():
                    if stage_name not in ADAPTIVE_STAGES:
                        continue
                    current_queue = stage.metrics['current_queue']
                    current_workers = stage.current_workers
                    target = stage.workers
                    if current_queue > 3000:
                        target = min(target + 4, MAX_WORKERS.get(stage_name, 32))
                    elif current_queue < IDLE_THRESHOLD:
                        target = max(target - 2, max(1, MIN_WORKERS.get(stage_name, 1)))
                    if target != stage.workers:
                        print(f"ADAPTING {stage_name}: {stage.workers} → {target}")
                        stage.adjust_workers(target)

        threading.Thread(target=monitor, daemon=True).start()