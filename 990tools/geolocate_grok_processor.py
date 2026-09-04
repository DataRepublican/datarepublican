#!/usr/bin/env python3
"""
geolocate_grok_processor.py — Grok batch geocoding for grok_pending + pending_api rows.

Runs preprocess (normalized pattern predicates) then submits xAI Batch API jobs,
polls, and merges results back into Geocoding. Resumable via geolocate_grok_state.json.

Honors global_config.max_files as a per-run row budget (preprocess + Grok applied).

When intake queues are fully drained, exports grok:* failures to
{final_dir}/grok_failures_for_patterns.tsv.gz for pattern-rule mining.
"""

from __future__ import annotations

import csv
import gzip
import json
import os
import shutil
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from openai import OpenAI
from pydantic import ValidationError

from config import global_config
from constants import (
    GEOCODING_GROK_BATCH_SIZE,
    GEOCODING_GROK_EXPORT_ROWS,
    GEOCODING_GROK_INTAKE_STATUSES,
    GEOCODING_GROK_ITER1_TEST_SET,
    GEOCODING_GROK_MIN_ADDRESS_COUNT,
    GEOCODING_GROK_POLL_INTERVAL,
    GEOCODING_PREPROCESS_BATCH_SIZE,
    GROK_FAILURES_EXPORT_FILE,
)

XAI_API_BASE = "https://api.x.ai/v1"
XAI_BATCH_ADD_CHUNK = 100
from database_operations import DatabaseOperations, DatabaseOperation, DatabaseOperationType
from geocoding_api_processor import BatchGeocodeOutput, GeocodingAPIProcessor, GeocodingWorkUnit
from logging_utils import log_error, log_info, log_warning
from pending_database_context import PendingDatabaseContext


STATE_FILE = Path(__file__).parent / "geolocate_grok_state.json"


def _test_set_path() -> Optional[Path]:
    raw = os.getenv("GEOCODING_GROK_TEST_SET")
    if raw is None:
        return None
    if raw in ("", "0", "false", "off"):
        return None
    if raw in ("1", "true", "yes", "on"):
        raw = GEOCODING_GROK_ITER1_TEST_SET
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).parent / path
    return path


def _grok_min_address_count() -> int:
    raw = os.getenv("GEOCODING_GROK_MIN_ADDRESS_COUNT")
    if raw is None:
        return GEOCODING_GROK_MIN_ADDRESS_COUNT
    try:
        return max(0, int(raw))
    except ValueError:
        return GEOCODING_GROK_MIN_ADDRESS_COUNT


def _load_test_set_ids() -> Optional[List[str]]:
    path = _test_set_path()
    if path is None:
        return None
    if not path.exists():
        raise FileNotFoundError(f"GEOCODING_GROK_TEST_SET not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        ids = data.get("geocoding_ids") or []
    elif isinstance(data, list):
        ids = data
    else:
        raise ValueError(f"Invalid test set format in {path}")
    return [str(x) for x in ids]


def _xai_api_key() -> str:
    key = os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY") or os.getenv("X_API_KEY")
    if not key:
        raise RuntimeError("No XAI_API_KEY / GROK_API_KEY / X_API_KEY in environment")
    return key


def _xai_client() -> OpenAI:
    return OpenAI(api_key=_xai_api_key(), base_url=XAI_API_BASE)


def _xai_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {_xai_api_key()}",
        "Content-Type": "application/json",
    }


def _batch_snapshot(batch_id: str) -> Dict[str, Any]:
    r = requests.get(
        f"{XAI_API_BASE}/batches/{batch_id}",
        headers=_xai_headers(),
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


def _load_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"active_batch": None, "completed_batches": 0, "rows_applied": 0}


def _json_safe_value(val: Any) -> Any:
    if val is None or isinstance(val, (str, int, float, bool)):
        return val
    if hasattr(val, "hex"):  # uuid.UUID
        return str(val)
    return str(val)


def _json_safe_work_data(data: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _json_safe_value(v) for k, v in data.items()}


def _save_state(state: Dict[str, Any]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)


def _chunk(items: List, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _extract_completion_content(item: Dict[str, Any]) -> Optional[str]:
    if "batch_result" in item:
        try:
            br = item["batch_result"]
            resp = br.get("response") or {}
            cgc = resp.get("chat_get_completion") or {}
            choices = cgc.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                content = msg.get("content")
                if isinstance(content, str):
                    return content
        except Exception:
            pass
    if "response" in item:
        resp = item["response"]
        if isinstance(resp, dict):
            body = resp.get("body")
            if isinstance(body, dict):
                choices = body.get("choices") or []
                if choices:
                    msg = choices[0].get("message") or {}
                    content = msg.get("content")
                    if isinstance(content, str):
                        return content
            if isinstance(body, str):
                return body
    if "error" in item and item["error"]:
        return None
    return None


XAI_BATCH_RESULTS_PAGE_SIZE = 1000


def _load_batch_results(client: OpenAI, batch_id: str, out_path: Path) -> List[Dict[str, Any]]:
    batch = client.batches.retrieve(batch_id)
    if getattr(batch, "output_file_id", None):
        content = client.files.content(batch.output_file_id)
        out_path.write_bytes(content.content)
        results = []
        for line in out_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                results.append(json.loads(line))
        return results

    key = os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY") or os.getenv("X_API_KEY")
    if not key:
        raise RuntimeError("XAI_API_KEY (or GROK_API_KEY / X_API_KEY) required to fetch batch results")

    results: List[Dict[str, Any]] = []
    pagination_token: Optional[str] = None
    while True:
        params: Dict[str, Any] = {"limit": XAI_BATCH_RESULTS_PAGE_SIZE}
        if pagination_token:
            params["pagination_token"] = pagination_token
        r = requests.get(
            f"{XAI_API_BASE}/batches/{batch_id}/results",
            headers={"Authorization": f"Bearer {key}"},
            params=params,
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        page = (
            data.get("results")
            if isinstance(data, dict) and "results" in data
            else data.get("data")
            if isinstance(data, dict) and "data" in data
            else data if isinstance(data, list) else [data]
        )
        if not isinstance(page, list):
            page = [page]
        results.extend(page)
        pagination_token = data.get("pagination_token") if isinstance(data, dict) else None
        if not pagination_token:
            break

    out_path.write_text(json.dumps({"results": results}, ensure_ascii=False), encoding="utf-8")
    return results


class GeolocateGrokProcessor:
    """xAI Batch API processor for grok_pending + pending_api Geocoding rows."""

    _INTAKE_SQL = ", ".join(f"'{s}'" for s in GEOCODING_GROK_INTAKE_STATUSES)

    def __init__(self, db_ops: DatabaseOperations):
        self.db_ops = db_ops
        self.export_rows = GEOCODING_GROK_EXPORT_ROWS
        self.prompt_batch_size = GEOCODING_GROK_BATCH_SIZE
        self._preprocess_proc: Optional[GeocodingAPIProcessor] = None
        self._test_set_ids: Optional[List[str]] = _load_test_set_ids()
        self._min_address_count = _grok_min_address_count()
        if self._min_address_count:
            print(
                f"[geolocate_grok] intake min_address_count={self._min_address_count:,} "
                f"(set GEOCODING_GROK_MIN_ADDRESS_COUNT=0 to disable)",
                flush=True,
            )
        if self._test_set_ids:
            path = _test_set_path()
            print(
                f"[geolocate_grok] test set active n={len(self._test_set_ids):,} "
                f"file={path.name if path else '?'}",
                flush=True,
            )

    @property
    def preprocess_proc(self) -> GeocodingAPIProcessor:
        if self._preprocess_proc is None:
            self._preprocess_proc = GeocodingAPIProcessor(self.db_ops)
        return self._preprocess_proc

    def _intake_count_filter_sql(self) -> str:
        if self._min_address_count <= 0:
            return ""
        return f" AND COALESCE(address_count, 0) >= {int(self._min_address_count)}"

    def _count_intake_pending(self) -> int:
        count_filter = self._intake_count_filter_sql()
        if self._test_set_ids:
            placeholders = ",".join("?" for _ in self._test_set_ids)
            row = self.db_ops.execute_query(
                f"""
                SELECT COUNT(*) FROM Geocoding
                WHERE geocoding_id IN ({placeholders})
                  AND geocoding_status IN ({self._INTAKE_SQL})
                  {count_filter}
                """,
                tuple(self._test_set_ids),
            ).fetchone()
            return int(row[0]) if row else 0
        row = self.db_ops.execute_query(
            f"SELECT COUNT(*) FROM Geocoding WHERE geocoding_status IN ({self._INTAKE_SQL})"
            f"{count_filter}"
        ).fetchone()
        return int(row[0]) if row else 0

    def _fetch_intake_rows(self, limit: int) -> List[Tuple]:
        count_filter = self._intake_count_filter_sql()
        if self._test_set_ids:
            placeholders = ",".join("?" for _ in self._test_set_ids)
            query = f"""
                SELECT geocoding_id, normalized_address, attempt_count, canonical_address, address_count, geocoding_status
                FROM Geocoding
                WHERE geocoding_id IN ({placeholders})
                  AND geocoding_status IN ({self._INTAKE_SQL})
                  {count_filter}
                ORDER BY geocoding_id
                LIMIT ?
            """
            return self.db_ops.execute_query(query, (*self._test_set_ids, limit)).fetchall()

        # pending_api (FEC/API tail garbage) before grok_pending (hard street misses);
        # within each bucket, city-only / no-street rows before full street addresses.
        query = f"""
            SELECT geocoding_id, normalized_address, attempt_count, canonical_address, address_count, geocoding_status
            FROM Geocoding
            WHERE geocoding_status IN ({self._INTAKE_SQL})
            {count_filter}
            ORDER BY
                CASE geocoding_status WHEN 'pending_api' THEN 0 ELSE 1 END,
                CASE
                    WHEN COALESCE(TRIM(json_extract_string(normalized_address, '$.street')), '') = ''
                    THEN 0 ELSE 1
                END,
                address_count DESC NULLS LAST,
                geocoding_id
            LIMIT ?
        """
        return self.db_ops.execute_query(query, (limit,)).fetchall()

    def _preprocess_before_grok(self, units: List[GeocodingWorkUnit]) -> tuple[List[GeocodingWorkUnit], int]:
        survivors: List[GeocodingWorkUnit] = []
        preprocess_matched = 0
        for chunk in _chunk(units, GEOCODING_PREPROCESS_BATCH_SIZE):
            chunk_survivors, n = self.preprocess_proc.apply_preprocess_batch(chunk)
            survivors.extend(chunk_survivors)
            preprocess_matched += n
        if preprocess_matched:
            print(
                f"[geolocate_grok] preprocess matched={preprocess_matched} "
                f"survivors={len(survivors)}/{len(units)}",
                flush=True,
            )
        return survivors, preprocess_matched

    def _rows_to_units(self, rows: List[Tuple]) -> List[GeocodingWorkUnit]:
        units = []
        for row in rows:
            data = _json_safe_work_data({
                "geocoding_id": row[0],
                "normalized_address": row[1],
                "attempt_count": row[2],
                "canonical_address": row[3],
                "address_count": row[4] or 0,
                "geocoding_status": row[5],
            })
            units.append(GeocodingWorkUnit.work_item("feed", data))
        return units

    def _build_batch_requests(
        self, units: List[GeocodingWorkUnit],
    ) -> tuple[List[Dict[str, Any]], Dict[str, List[GeocodingWorkUnit]]]:
        """Build native xAI batch_requests payloads; return (requests, id_map)."""
        id_map: Dict[str, List[GeocodingWorkUnit]] = {}
        batch_requests: List[Dict[str, Any]] = []
        batch_model = GeocodingAPIProcessor.grok_geocode_batch_model()
        for idx, chunk in enumerate(_chunk(units, self.prompt_batch_size)):
            custom_id = f"geocode_{idx:06d}"
            id_map[custom_id] = chunk
            body = GeocodingAPIProcessor.build_grok_geocode_request_body(chunk)
            body["model"] = batch_model
            batch_requests.append({
                "batch_request_id": custom_id,
                "batch_request": {"chat_get_completion": body},
            })
        return batch_requests, id_map

    def _write_jsonl_audit(
        self,
        batch_requests: List[Dict[str, Any]],
        jsonl_path: Path,
    ) -> None:
        """Write OpenAI-style JSONL for human audit (not used for xAI upload)."""
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for rec in batch_requests:
                body = rec["batch_request"]["chat_get_completion"]
                line = {
                    "custom_id": rec["batch_request_id"],
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": body,
                }
                f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def _queue_grok_update(
        self,
        ctx: PendingDatabaseContext,
        unit: GeocodingWorkUnit,
        fields: Dict[str, Any],
    ) -> None:
        ctx.addOperationToDatabase(DatabaseOperation(
            operation_type=DatabaseOperationType.GENERIC_UPDATE,
            data={
                "table": "Geocoding",
                "updates": [fields],
                "id_column": "geocoding_id",
            },
        ))
        ctx.addOperationToDatabase(DatabaseOperation(
            operation_type=DatabaseOperationType.PROGRESS_UPDATE,
            data={"count": unit.address_count},
        ))

    def _apply_batch_results(
        self,
        results: List[Dict[str, Any]],
        id_map: Dict[str, List[GeocodingWorkUnit]],
    ) -> Tuple[int, int]:
        matched = 0
        classified = 0
        now = datetime.now().isoformat()
        ctx = PendingDatabaseContext()
        unit_by_id = {
            u.geocoding_id: u
            for units in id_map.values()
            for u in units
        }
        seen_ids: set[str] = set()

        def apply_unit(unit: GeocodingWorkUnit, res_item=None) -> None:
            nonlocal matched, classified
            if unit.geocoding_id in seen_ids:
                return
            seen_ids.add(unit.geocoding_id)
            fields = GeocodingAPIProcessor.grok_result_update_fields(unit, res_item, now=now)
            if fields["geocoding_status"] == "Match:Grok-4":
                matched += 1
            else:
                classified += 1
            self._queue_grok_update(ctx, unit, fields)

        for item in results:
            custom_id = item.get("custom_id") or item.get("batch_request_id") or ""
            chunk = id_map.get(custom_id, [])
            content = _extract_completion_content(item)
            if not content:
                for unit in chunk:
                    apply_unit(unit, None)
                continue
            try:
                parsed = BatchGeocodeOutput.model_validate_json(content)
            except ValidationError as e:
                log_warning(f"Grok batch parse fail custom_id={custom_id}: {e}")
                for unit in chunk:
                    apply_unit(unit, None)
                continue

            parsed_dict = {res.id: res for res in parsed.results}
            for unit in chunk:
                apply_unit(unit, parsed_dict.get(unit.geocoding_id))

        for gid, unit in unit_by_id.items():
            if gid not in seen_ids:
                apply_unit(unit, None)

        if ctx.getOperationsCount() > 0:
            ctx.save_to_database(self.db_ops, checkpoint=True)
        return matched, classified

    def _submit_batch(
        self,
        batch_requests: List[Dict[str, Any]],
        name: str,
        *,
        audit_path: Optional[Path] = None,
    ) -> str:
        """Create xAI batch and POST /batches/{id}/requests (native API, not JSONL upload)."""
        if not batch_requests:
            raise RuntimeError("cannot submit empty batch")
        r = requests.post(
            f"{XAI_API_BASE}/batches",
            headers=_xai_headers(),
            json={"name": name},
            timeout=120,
        )
        r.raise_for_status()
        batch_id = str(r.json().get("batch_id") or "")
        if not batch_id:
            raise RuntimeError(f"xAI batch create returned no batch_id for {name}")

        for chunk in _chunk(batch_requests, XAI_BATCH_ADD_CHUNK):
            r_add = requests.post(
                f"{XAI_API_BASE}/batches/{batch_id}/requests",
                headers=_xai_headers(),
                json={"batch_requests": chunk},
                timeout=300,
            )
            if not r_add.ok:
                raise RuntimeError(
                    f"xAI add requests failed for {batch_id}: "
                    f"{r_add.status_code} {r_add.text[:500]}"
                )

        snap = _batch_snapshot(batch_id)
        state = snap.get("state") or {}
        num_requests = int(state.get("num_requests") or 0)
        if num_requests != len(batch_requests):
            raise RuntimeError(
                f"xAI batch {batch_id} expected {len(batch_requests)} requests, "
                f"got {num_requests} (model={GeocodingAPIProcessor.grok_geocode_batch_model()})"
            )

        audit_note = f" audit={audit_path.name}" if audit_path else ""
        log_info(f"Submitted xAI batch {batch_id} ({name}) requests={num_requests}{audit_note}")
        print(
            f"[geolocate_grok] submitted batch_id={batch_id} name={name} "
            f"requests={num_requests} model={GeocodingAPIProcessor.grok_geocode_batch_model()}"
            f"{audit_note}",
            flush=True,
        )
        return batch_id

    def _poll_batch(self, batch_id: str) -> str:
        empty_polls = 0
        while True:
            data = _batch_snapshot(batch_id)
            state = data.get("state") or {}
            num_requests = int(state.get("num_requests") or 0)
            num_pending = int(state.get("num_pending") or 0)
            num_success = int(state.get("num_success") or 0)
            num_error = int(state.get("num_error") or 0)
            if data.get("cancel_time"):
                print(
                    f"[geolocate_grok] batch {batch_id} cancelled "
                    f"msg={data.get('cancel_by_xai_message')}",
                    flush=True,
                )
                return "cancelled"
            print(
                f"[geolocate_grok] polling {batch_id} "
                f"requests={num_requests} pending={num_pending} "
                f"success={num_success} error={num_error}",
                flush=True,
            )
            if num_requests > 0 and num_pending == 0:
                return "completed"
            if num_requests == 0:
                empty_polls += 1
                if empty_polls >= 3:
                    return "failed"
            else:
                empty_polls = 0
            time.sleep(GEOCODING_GROK_POLL_INTERVAL)

    def _process_active_batch(self, client: OpenAI, state: Dict[str, Any]) -> int:
        active = state.get("active_batch")
        if not active:
            return 0
        batch_id = active["batch_id"]
        status = self._poll_batch(batch_id)
        if status != "completed":
            log_error(f"Batch {batch_id} ended with status={status}")
            state["active_batch"] = None
            _save_state(state)
            return 0
        results_path = Path(active["results_path"])
        id_map = {
            custom_id: [GeocodingWorkUnit.work_item("feed", d) for d in serialized]
            for custom_id, serialized in active["id_map"].items()
        }
        results = _load_batch_results(client, batch_id, results_path)
        matched, classified = self._apply_batch_results(results, id_map)
        applied = matched + classified
        state["active_batch"] = None
        state["completed_batches"] = state.get("completed_batches", 0) + 1
        state["rows_applied"] = state.get("rows_applied", 0) + applied
        _save_state(state)
        print(
            f"[geolocate_grok] batch {batch_id} applied matched={matched} classified={classified}",
            flush=True,
        )
        return applied

    def export_grok_failures(self, output_file: str = GROK_FAILURES_EXPORT_FILE) -> int:
        """Export grok:* classified failures grouped by failure_code for pattern-rule mining."""
        output_path = os.path.join(global_config.final_dir, output_file)
        rows = self.db_ops.execute_query("""
            SELECT
                split_part(geocoding_status, ':', 2) AS failure_code,
                canonical_address,
                matched_address,
                normalized_address,
                address_count,
                geocoding_id
            FROM Geocoding
            WHERE geocoding_status LIKE 'grok:%'
            ORDER BY
                failure_code,
                address_count DESC NULLS LAST,
                canonical_address
        """).fetchall()

        os.makedirs(global_config.final_dir or ".", exist_ok=True)
        tmp_path = output_path + ".tmp"
        try:
            with gzip.open(tmp_path, "wt", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, delimiter="\t", lineterminator="\n")
                writer.writerow([
                    "failure_code",
                    "canonical_address",
                    "reason",
                    "address_count",
                    "normalized_address",
                    "geocoding_id",
                ])
                for code, canon, reason, norm, count, gid in rows:
                    writer.writerow([
                        code or "UNKN",
                        canon or "",
                        reason or "",
                        count or 0,
                        norm or "",
                        gid or "",
                    ])
            shutil.move(tmp_path, output_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        by_code = Counter((r[0] or "UNKN") for r in rows)
        summary = ", ".join(f"{k}={v:,}" for k, v in sorted(by_code.items()))
        log_info(f"Exported {len(rows):,} grok failures → {output_path} ({summary})")
        print(
            f"[geolocate_grok] exported {len(rows):,} failures → {output_path}"
            + (f" ({summary})" if summary else ""),
            flush=True,
        )
        return len(rows)

    def run(
        self,
        max_batches: Optional[int] = None,
        max_rows: Optional[int] = None,
    ) -> int:
        """Submit/poll/apply batches until intake queues drain or limits hit."""
        if max_rows is None:
            max_rows = global_config.max_files
        state = _load_state()
        client = _xai_client()
        batches_done = 0
        total_applied = 0
        rows_handled = 0

        if state.get("active_batch"):
            print("[geolocate_grok] resuming active batch from state", flush=True)
            applied = self._process_active_batch(client, state)
            if applied:
                batches_done += 1
                total_applied += applied

        while True:
            if max_batches is not None and batches_done >= max_batches:
                break
            if max_rows is not None and rows_handled >= max_rows:
                print(
                    f"[geolocate_grok] max_rows={max_rows:,} reached — stopping",
                    flush=True,
                )
                break
            pending = self._count_intake_pending()
            if pending == 0:
                print(
                    f"[geolocate_grok] no intake rows remaining "
                    f"(statuses: {', '.join(GEOCODING_GROK_INTAKE_STATUSES)})",
                    flush=True,
                )
                break

            fetch_limit = self.export_rows
            if max_rows is not None:
                fetch_limit = min(fetch_limit, max_rows - rows_handled)
                if fetch_limit <= 0:
                    break

            rows = self._fetch_intake_rows(fetch_limit)
            if not rows:
                break
            units = self._rows_to_units(rows)
            units, preprocess_matched = self._preprocess_before_grok(units)
            rows_handled += len(rows)
            total_applied += preprocess_matched
            if not units:
                continue
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            jsonl_path = Path(__file__).parent / f"geolocate_grok_batch_{ts}.jsonl"
            batch_requests, id_map = self._build_batch_requests(units)
            self._write_jsonl_audit(batch_requests, jsonl_path)
            serialized_map = {
                cid: [_json_safe_work_data(u.data) for u in chunk]
                for cid, chunk in id_map.items()
            }
            name = f"geolocate_grok_{ts}"
            batch_id = self._submit_batch(batch_requests, name, audit_path=jsonl_path)
            state["active_batch"] = {
                "batch_id": batch_id,
                "name": name,
                "jsonl_path": str(jsonl_path),
                "results_path": str(jsonl_path.with_suffix(".results.jsonl")),
                "id_map": serialized_map,
                "row_count": len(units),
            }
            _save_state(state)

            status = self._poll_batch(batch_id)
            if status != "completed":
                log_error(f"Batch {batch_id} ended with status={status}")
                state["active_batch"] = None
                _save_state(state)
                break

            results_path = Path(state["active_batch"]["results_path"])
            id_map_units = {
                cid: [GeocodingWorkUnit.work_item("feed", d) for d in chunk]
                for cid, chunk in serialized_map.items()
            }
            results = _load_batch_results(client, batch_id, results_path)
            matched, classified = self._apply_batch_results(results, id_map_units)
            total_applied += matched + classified
            state["active_batch"] = None
            state["completed_batches"] = state.get("completed_batches", 0) + 1
            state["rows_applied"] = state.get("rows_applied", 0) + matched + classified
            _save_state(state)
            batches_done += 1
            print(
                f"[geolocate_grok] batch {batches_done} done matched={matched} classified={classified} "
                f"total_applied={total_applied}",
                flush=True,
            )

        print(
            f"[geolocate_grok] SUMMARY batches={batches_done} rows_applied={total_applied}",
            flush=True,
        )

        pending = self._count_intake_pending()
        if pending == 0 and not state.get("active_batch"):
            self.export_grok_failures()
        elif pending > 0:
            print(
                f"[geolocate_grok] skipping failure export — {pending:,} intake rows still remain",
                flush=True,
            )

        return total_applied