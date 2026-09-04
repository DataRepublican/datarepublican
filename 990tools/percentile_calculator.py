#!/usr/bin/env python3
"""
percentile_calculator.py - Step 10: Compute denominator, _pct, and _ptile

Two separate, self-contained, restartable steps:
  ratios      → Phase 1 (denominator + _pct columns) - fully self-contained
  percentiles → Phase 2 (_ptile columns, memory-safe, one group at a time) - fully self-contained

Uses full Charity objects via select_dataclass for robustness and debugging.
Automatically resumes from where it left off (no need to manually pass start_after_*).
"""

import logging
import queue
import threading
from typing import Optional, List, Tuple

from database_operations import DatabaseOperations, DatabaseOperation, DatabaseOperationType
from pending_database_context import PendingDatabaseContext
from base_processor import BaseProcessor, WorkUnit
from logging_utils import log_info, log_error
from models import Charity
from config import global_config

logger = logging.getLogger(__name__)


class PercentileCalculator(BaseProcessor):
    """Step 10: Full ratio + percentile calculation (self-contained + restartable)"""

    def __init__(self, db_ops: DatabaseOperations):
        super().__init__(db_ops)
        self.exit_processing = False

    # ============================================================
    # STEP: ratios (Phase 1) - Self-contained, auto-resumes
    # ============================================================
    def compute_ratios(self, max_files: Optional[int] = None) -> int:
        """
        Compute denominator + all _pct columns.
        Fully self-contained: automatically resumes from the last processed charity.
        max_files: limit for this run (testing + DuckDB performance batches). If None, uses global_config.max_files.
        """
        if max_files is None:
            max_files = global_config.max_files

        print("Step: ratios - Computing denominator and _pct columns...")

        # Self-contained: automatically find where we left off
        start_after = self.db_ops.get_last_processed_charity_id()
        if start_after:
            print(f"  Resuming from charity_id > {start_after}")

        work_queue: queue.Queue = queue.Queue(maxsize=200)
        processed = 0
        lock = threading.Lock()

        def _feed_thread():
            last_id = start_after
            enqueued = 0
            while not self.exit_processing:
                batch, new_last_id = self.db_ops.get_charities_for_ratio_computation(
                    last_charity_id=last_id, limit=5000
                )
                if not batch:
                    break

                for charity in batch:
                    if self.exit_processing:
                        break
                    work_queue.put(WorkUnit.work_item(charity))
                    enqueued += 1
                    if max_files and enqueued >= max_files:
                        break

                if not new_last_id or (max_files and enqueued >= max_files):
                    break
                last_id = new_last_id

            for _ in range(4):
                work_queue.put(WorkUnit.sentinel(0))

        def _process_work_item(charity: Charity) -> PendingDatabaseContext:
            # Denominator logic: prefer receipt_amt (income), fallback to total_exp
            denominator = None
            if charity.receipt_amt and charity.receipt_amt > 0:
                denominator = charity.receipt_amt
            elif charity.total_exp and charity.total_exp > 0:
                denominator = charity.total_exp

            # Compute _pct values (safe division)
            comp_pct = charity.officer_comp / denominator if denominator and charity.officer_comp else None
            travel_pct = charity.travel_amt / denominator if denominator and charity.travel_amt else None
            conferences_pct = charity.conferences_amt / denominator if denominator and charity.conferences_amt else None
            grants_pct = charity.grants_to_others / denominator if denominator and charity.grants_to_others else None
            foreign_pct = charity.foreign_expenses / denominator if denominator and charity.foreign_expenses else None

            context = PendingDatabaseContext()
            context.addOperationToDatabase(DatabaseOperation(
                operation_type=DatabaseOperationType.GENERIC_UPDATE,
                data={
                    'table': 'Charities',
                    'updates': [{
                        'charity_id': charity.charity_id,
                        'denominator': denominator,
                        'comp_pct': comp_pct,
                        'travel_pct': travel_pct,
                        'conferences_pct': conferences_pct,
                        'grants_pct': grants_pct,
                        'foreign_expenses_pct': foreign_pct,
                    }],
                    'id_column': 'charity_id'
                }
            ))
            return context

        # Producer/Consumer
        producer = threading.Thread(target=_feed_thread, daemon=True)
        producer.start()

        while True:
            work = work_queue.get()
            if work.is_sentinel():
                work_queue.task_done()
                break

            context = _process_work_item(work.data)
            context.save_to_database(self.db_ops)

            with lock:
                processed += 1
            work_queue.task_done()

        producer.join()
        print(f"Step 'ratios' complete: {processed} charities updated")
        return processed

    # ============================================================
    # STEP: percentiles (Phase 2) - Self-contained, memory-safe, auto-resumes
    # ============================================================
    def compute_percentiles(self, max_groups: Optional[int] = None) -> int:
        """
        Compute _ptile columns - processes one (org_type, tax_year) "group" at a time.
        
        A "group" = all charities with the same org_type AND tax_year 
        (e.g., all 501(c)(3) charities for tax year 2023).
        
        This is memory-safe because we only load one group into memory at a time.
        Fully self-contained: automatically resumes from the last processed group.
        max_groups: limit for this run (testing + DuckDB performance batches). If None, uses global_config.max_files.
        """
        if max_groups is None:
            max_groups = global_config.max_files

        print("Step: percentiles - Computing _ptile columns (one group at a time)...")

        # Self-contained: automatically find where we left off
        last_group = self.db_ops.get_last_processed_group()
        start_after_org_type = None
        start_after_tax_year = None
        if last_group:
            start_after_org_type, start_after_tax_year = last_group
            print(f"  Resuming after group: {start_after_org_type} / {start_after_tax_year}")

        last_org_type = start_after_org_type
        last_tax_year = start_after_tax_year
        processed = 0

        while True:
            groups = self.db_ops.get_charity_groups_for_percentiles(
                last_org_type=last_org_type,
                last_tax_year=last_tax_year,
                limit=50
            )

            if not groups:
                break

            for org_type, tax_year in groups:
                if self.exit_processing:
                    break

                # Fetch full Charity objects for this group (great for debugging)
                charities = self.db_ops.get_charities_for_percentile_group(org_type, tax_year)

                if len(charities) < 2:
                    processed += 1
                    last_org_type = org_type
                    last_tax_year = tax_year
                    continue

                # Extract and sort values for each metric
                metric_values = {}
                for metric in ['comp', 'travel', 'conferences', 'grants', 'foreign_expenses']:
                    pct_col = f"{metric}_pct"
                    values = [getattr(c, pct_col) for c in charities if getattr(c, pct_col) is not None]
                    metric_values[metric] = sorted([float(v) for v in values if v is not None])

                # Compute percentiles for each charity
                updates = []
                for charity in charities:
                    ptile_args = {}
                    for metric in ['comp', 'travel', 'conferences', 'grants', 'foreign_expenses']:
                        pct_col = f"{metric}_pct"
                        ptile_col = f"{metric}_ptile"
                        val = getattr(charity, pct_col)
                        values = metric_values[metric]

                        if val is not None and values:
                            try:
                                v = float(val)
                                ptile_args[ptile_col] = self._calculate_percentile(v, values)
                            except (ValueError, TypeError):
                                ptile_args[ptile_col] = None
                        else:
                            ptile_args[ptile_col] = None

                    updates.append({
                        'charity_id': charity.charity_id,
                        'comp_ptile': ptile_args.get('comp_ptile'),
                        'travel_ptile': ptile_args.get('travel_ptile'),
                        'conferences_ptile': ptile_args.get('conferences_ptile'),
                        'grants_ptile': ptile_args.get('grants_ptile'),
                        'foreign_expenses_ptile': ptile_args.get('foreign_expenses_ptile'),
                    })

                # Bulk update
                if updates:
                    self.db_ops.bulk_update('Charities', updates, id_column='charity_id', commit=False)

                processed += 1
                last_org_type = org_type
                last_tax_year = tax_year

                if max_groups and processed >= max_groups:
                    break

            if max_groups and processed >= max_groups:
                break

        self.db_ops.commit()
        print(f"Step 'percentiles' complete: {processed} groups processed")
        return processed

    def _calculate_percentile(self, value: float, sorted_values: List[float]) -> float:
        if not sorted_values:
            return 0.0
        for i, v in enumerate(sorted_values):
            if value <= v:
                return (i / len(sorted_values)) * 100.0
        return 100.0

    # ============================================================
    # Thin wrappers for irs990processor.py integration (matches lambda calls)
    # ============================================================
    def calculate_ratios(self) -> int:
        """Wrapper for irs990processor.py - pulls max_files from global_config automatically"""
        return self.compute_ratios()

    def calculate_percentiles(self) -> int:
        """Wrapper for irs990processor.py - pulls max_files from global_config automatically"""
        return self.compute_percentiles()

    def run(self, max_files: Optional[int] = None, max_groups: Optional[int] = None) -> dict:
        """Main entry point - runs both steps in correct order (self-contained)"""
        print("\n=== Step 10: Percentile Calculation ===")
        
        ratios = self.compute_ratios(max_files=max_files)
        percentiles = self.compute_percentiles(max_groups=max_groups)

        print(f"\nStep 10 Summary: {ratios} ratios + {percentiles} percentiles updated")
        return {
            'ratios_updated': ratios,
            'percentiles_updated': percentiles
        }


if __name__ == "__main__":
    from database_operations import DatabaseOperations
    db = DatabaseOperations()
    calc = PercentileCalculator(db)
    result = calc.run()
    print(result)
