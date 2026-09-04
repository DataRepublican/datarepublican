#!/usr/bin/env python3
"""
geocoding_api_processor.py - Cleaned, consolidated, geopy-integrated version
Preserves all original logic + adds thread-safe geopy for supported services.
"""

import json
import logging
import re
import os
import sys
import time
import threading
import gc
import gzip
import csv
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

import requests
from urllib.parse import quote
from censusbatchgeocoder import geocode
from geopy.exc import (
    GeocoderTimedOut, GeocoderServiceError, GeocoderQuotaExceeded,
    GeocoderAuthenticationFailure,
)
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim, Photon, OpenCage
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

try:
    import tqdm
except ImportError:
    tqdm = None

from base_processor import BaseProcessor
from config import global_config
from constants import (
    GEOCODING_BATCH_SIZE, GEOCODING_FEED_BATCH_SIZE, GEOCODING_API_WORKERS,
    CENSUS_API_BATCH_SIZE, CENSUS_API_MIN_DELAY, CENSUS_API_RETRY_ATTEMPTS,
    CENSUS_API_RETRY_BACKOFF_BASE, GEOCODE_CONSUMER_BATCH_SIZE, GEOCODE_CHECKPOINT_INTERVAL,
    GEOCODING_IN_FLIGHT_CAP, GEOCODING_API_IN_FLIGHT_CAP, GEOCODING_GROK_WORKERS,
    GEOCODING_GROK_BATCH_SIZE, GEOCODING_PREPROCESS_BATCH_SIZE,
    GEOCODING_WORKER_QUEUE_DEPTH, GEOCODING_FEED_BUFFER_BATCHES,
    GEOCODING_PENDING_API_BATCH_SIZE, GEOCODING_BATCHER_TIMEOUT,
    GEOCODING_STATUS_PENDING_API, CENSUS_FAILURES_EXPORT_FILE,
    GROK_GEOCODE_MODEL_DEFAULT, GROK_FAILURE_CODES, grok_failure_status,
    GEOCODING_GROK_MIN_CONFIDENCE_PCT, VALID_STATES,
    GEOCODE_MAPS_CO_WORKERS, GEOCODE_MAPS_CO_MIN_DELAY,
    GEOCODING_PHOTON_WORKERS, GEOCODING_PHOTON_MIN_DELAY,
    GEOCODING_PHOTON_SELF_HOSTED_WORKERS, GEOCODING_PHOTON_SELF_HOSTED_MIN_DELAY,
    DEFAULT_FINAL_DIR,
)
from database_operations import DatabaseOperations, DatabaseOperation, DatabaseOperationType
from logging_utils import log_info, log_error, log_debug, log_warning
from models.geocoding import Geocoding
from pending_database_context import PendingDatabaseContext
from pipeline import PipelineStage, Pipeline, WorkUnit, ResultWorkUnit
import os

archive_path = os.path.join(os.path.dirname(DEFAULT_FINAL_DIR), 'geocode_archive_distinct.tsv.gz')

# geopy RateLimiter logs full tracebacks on retries — keep at ERROR
for _geopy_logger in ('geopy', 'geopy.geocoders', 'geopy.extra.rate_limiter'):
    logging.getLogger(_geopy_logger).setLevel(logging.ERROR)

# === API Configuration ===
API_CONFIG = {
    'ENABLE_CENSUS_RAW': True,
    'ENABLE_GROK': False,  # inline Grok removed — use geolocate_grok step (batch API)
    'ENABLE_PHOTON': True,
    'ENABLE_NOMINATIM': True,
    'ENABLE_GEOCODE_MAPS_CO': True,  # parallel Nominatim-class stage when key present; probe disables on 401

    'ENABLE_LIBRESTREET': False,  # librestreet.org NXDOMAIN — was 4.4k wasted connection attempts/run
    'ENABLE_OPENCAGE': True,
    'ENABLE_GOOGLE_MAPS': False,
    'ENABLE_NAME_SEARCH': False,
}

owner_mapping = {
                'charity': ('Charities', 'charity_id'),
                'filer': ('Charities', 'charity_id'),
                'grant': ('Grants', 'grant_id'),
                'contractor': ('Contractors', 'contractor_id'),
                'officer': ('Officers', 'officer_id'),
                'politicalcontribution': ('PoliticalContributions', 'political_id'),
                'political': ('PoliticalContributions', 'political_id')
            }

# === Structured Output for Grok-4 ===
class GeocodeResult(BaseModel):
    id: str = Field(..., description="geocoding_id UUID from the prompt")
    lat: Optional[float] = None
    long: Optional[float] = None
    matched_address: Optional[str] = None
    failure_code: Optional[str] = Field(
        None,
        description=(
            "Required when lat/long are null. One of: NOTA, VAGUE, AMBIG, REDACT, UNKN. "
            "UNKN is only for foreign/non-US or unparseable junk — never for a complete "
            "US street+city+state+ZIP and never because an external geocoder is unavailable."
        ),
    )
    reason: Optional[str] = Field(
        None,
        description=(
            "Brief explanation of match or failure. Do not cite missing tools/APIs or "
            "prior geocoder failure as the reason."
        ),
    )

class BatchGeocodeOutput(BaseModel):
    results: List[GeocodeResult]

@dataclass
class GeocodingWorkUnit(WorkUnit):
    _parsed_normalized: Optional[Dict[str, str]] = field(default=None, init=False)

    @property
    def geocoding_id(self) -> str: return self.data['geocoding_id']
    @property
    def normalized_address(self) -> any: return self.data['normalized_address']
    @property
    def attempt_count(self) -> int: return self.data['attempt_count']
    @property
    def canonical_address(self) -> str: return self.data['canonical_address']
    @property
    def address_count(self) -> int: return self.data.get('address_count', 0)
    @property
    def geocoding_status(self) -> str: return self.data['geocoding_status']

    @property
    def parsed_normalized(self) -> Dict[str, str]:
        if self._parsed_normalized is None:
            norm = self.normalized_address
            if isinstance(norm, str):
                try: self._parsed_normalized = json.loads(norm)
                except json.JSONDecodeError:
                    self._parsed_normalized = {}
                    log_warning(f"JSON parse fail for {self.geocoding_id}")
            elif isinstance(norm, dict): self._parsed_normalized = norm
            else: self._parsed_normalized = {}
        return self._parsed_normalized

    @classmethod
    def work_item(cls, stage: str, data: Dict) -> "GeocodingWorkUnit":
        if not isinstance(data,Dict):
            raise ValueError(f"Expected dict for work item, got {type(data)}")
        return cls(type='work', data=data, stage=stage)
    
    @classmethod
    def batch(cls, stage: str, work_units: List["WorkUnit"]) -> "GeocodingWorkUnit":
        return cls(type='batch', stage=stage, items=work_units)
    
    def __str__(self) -> str:
        if self.is_batch():
            return f"<GeoBatch {self.stage} size={len(self.items)}>"
        return f"<GeoWorkUnit {self.type} stage={self.stage}/>"


@dataclass
class GeocodeRunStats:
    """Per-run counters for geolocate step diagnostics."""
    fed: int = 0
    preprocess_match: int = 0
    census_match: int = 0
    census_strip_match: int = 0
    pending_api_queued: int = 0
    other_match: int = 0
    grok_queued: int = 0
    grok_match: int = 0
    grok_fail: int = 0
    save_errors: int = 0
    census_pending_total: int = 0
    census_calls: int = 0
    census_strip_calls: int = 0
    census_call_failures: int = 0
    census_strip_call_failures: int = 0
    census_addrs_sent: int = 0
    census_call_secs_total: float = 0.0
    census_call_secs_last: float = 0.0
    census_call_secs_max: float = 0.0
    census_run_start: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_census_call(
        self,
        *,
        stage: str,
        batch_size: int,
        elapsed_s: float,
        matched: int,
        failed: bool,
    ) -> None:
        with self._lock:
            self.census_addrs_sent += batch_size
            self.census_call_secs_total += elapsed_s
            self.census_call_secs_last = elapsed_s
            if elapsed_s > self.census_call_secs_max:
                self.census_call_secs_max = elapsed_s
            if stage == "census_strip":
                self.census_strip_calls += 1
                if failed:
                    self.census_strip_call_failures += 1
            else:
                self.census_calls += 1
                if failed:
                    self.census_call_failures += 1

    def census_call_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            calls = self.census_calls + self.census_strip_calls
            failures = self.census_call_failures + self.census_strip_call_failures
            elapsed_s = max(time.time() - self.census_run_start, 1.0)
            elapsed_hr = elapsed_s / 3600.0
            avg_s = (self.census_call_secs_total / calls) if calls else 0.0
            rate_hr = calls / elapsed_hr if elapsed_hr > 0 else 0.0
            return {
                "calls": calls,
                "census_calls": self.census_calls,
                "census_strip_calls": self.census_strip_calls,
                "failures": failures,
                "addrs_sent": self.census_addrs_sent,
                "elapsed_s": elapsed_s,
                "elapsed_hr": elapsed_hr,
                "last_s": self.census_call_secs_last,
                "avg_s": avg_s,
                "max_s": self.census_call_secs_max,
                "rate_hr": rate_hr,
            }

    def log_summary(self, step: str = "geolocate_new"):
        snap = self.census_call_snapshot()
        log_info(
            f"Geocode run summary ({step}): fed={self.fed:,} preprocess={self.preprocess_match:,} "
            f"census={self.census_match:,} census_strip={self.census_strip_match:,} "
            f"pending_api={self.pending_api_queued:,} other={self.other_match:,} "
            f"grok_queued={self.grok_queued:,} grok_match={self.grok_match:,} "
            f"grok_fail={self.grok_fail:,} save_errors={self.save_errors:,} "
            f"census_calls={snap['census_calls']:,} census_strip_calls={snap['census_strip_calls']:,} "
            f"census_failures={snap['failures']:,} census_avg_s={snap['avg_s']:.1f}"
        )
        print(
            f"[{step}] SUMMARY fed={self.fed:,} preprocess={self.preprocess_match:,} "
            f"census={self.census_match:,} census_strip={self.census_strip_match:,} "
            f"pending_api={self.pending_api_queued:,} other={self.other_match:,} "
            f"grok_queued={self.grok_queued:,} grok_match={self.grok_match:,} "
            f"grok_fail={self.grok_fail:,} save_errors={self.save_errors:,} "
            f"census_calls={snap['census_calls']:,}+{snap['census_strip_calls']:,}strip "
            f"census_failures={snap['failures']:,} census_avg_s={snap['avg_s']:.1f}",
            flush=True,
        )


class GeocodingAPIProcessor(BaseProcessor):
    _maps_co_disabled = False
    _librestreet_disabled = False
    _census_api_lock = threading.Lock()
    _census_api_last_request: float = 0.0
    _us_zip_codes: Optional[frozenset[str]] = None
    _us_zip_states: Optional[Dict[str, str]] = None
    _us_zip_coords: Optional[Dict[str, Tuple[float, float]]] = None
    _major_foreign_cities: Optional[frozenset[str]] = None
    _major_foreign_countries: Optional[frozenset[str]] = None
    _foreign_shell_phrases: Optional[tuple[re.Pattern, ...]] = None

    def __init__(self, db_ops: DatabaseOperations, batch_size: int = GEOCODING_FEED_BATCH_SIZE):
        super().__init__(db_ops)
        self.batch_size = batch_size
        self._thread_local = threading.local()
        self._ensure_us_zip_lookup(db_ops)
        self._ensure_major_foreign_places()
        self.geocoding_patterns = self._load_geocoding_patterns()
        self._census_strip_suite_regexes = self._load_census_strip_suite_regexes()
        self.run_stats = GeocodeRunStats()
        self.pipeline_step = "geolocate_new"
        self._db_ops = db_ops
        self._census_pipeline: Optional[Pipeline[GeocodingWorkUnit]] = None
        self._api_pipeline: Optional[Pipeline[GeocodingWorkUnit]] = None
        self._free_pipeline: Optional[Pipeline[GeocodingWorkUnit]] = None
        self._grok_pipeline: Optional[Pipeline[GeocodingWorkUnit]] = None
        self.pipeline: Optional[Pipeline[GeocodingWorkUnit]] = None
        self._validate_geocoder_api_keys()

    def _bind_pipeline(self, pl: Pipeline[GeocodingWorkUnit]) -> Pipeline[GeocodingWorkUnit]:
        pl._geocode_processor = self
        return pl

    @property
    def census_pipeline(self) -> Pipeline[GeocodingWorkUnit]:
        if self._census_pipeline is None:
            self._census_pipeline = self._bind_pipeline(self._build_census_pipeline(self._db_ops))
        return self._census_pipeline

    @property
    def api_pipeline(self) -> Pipeline[GeocodingWorkUnit]:
        if self._api_pipeline is None:
            self._api_pipeline = self._bind_pipeline(self._build_api_pipeline(self._db_ops))
        return self._api_pipeline

    @property
    def free_pipeline(self) -> Pipeline[GeocodingWorkUnit]:
        if self._free_pipeline is None:
            self._free_pipeline = self._bind_pipeline(self._build_free_pipeline(self._db_ops))
        return self._free_pipeline

    @property
    def grok_pipeline(self) -> Pipeline[GeocodingWorkUnit]:
        if self._grok_pipeline is None:
            self._grok_pipeline = self._bind_pipeline(self._build_grok_pipeline(self._db_ops))
        return self._grok_pipeline

    @staticmethod
    def _worker_queue_slots(workers: int) -> int:
        return workers * GEOCODING_WORKER_QUEUE_DEPTH

    @classmethod
    def _us_zips_file_path(cls) -> str:
        here = os.path.dirname(os.path.abspath(__file__))
        for candidate in (
            os.path.join(os.getcwd(), 'US_zips.txt.gz'),
            os.path.join(here, 'US_zips.txt.gz'),
        ):
            if os.path.isfile(candidate):
                return candidate
        return os.path.join(here, 'US_zips.txt.gz')

    @classmethod
    def _load_us_zips_from_file(cls, path: str) -> None:
        codes: set[str] = set()
        states: Dict[str, str] = {}
        coords: Dict[str, Tuple[float, float]] = {}
        with gzip.open(path, 'rt', encoding='utf-8') as handle:
            for line in handle:
                parts = line.rstrip('\n').split('\t')
                if len(parts) < 11:
                    continue
                zip_code = parts[1].strip()
                if not zip_code or zip_code in codes:
                    continue
                codes.add(zip_code)
                states[zip_code] = parts[4].strip()
                try:
                    coords[zip_code] = (float(parts[9]), float(parts[10]))
                except ValueError:
                    pass
        cls._us_zip_codes = frozenset(codes)
        cls._us_zip_states = states
        cls._us_zip_coords = coords

    @classmethod
    def _ensure_us_zip_lookup(cls, db_ops: Optional[DatabaseOperations] = None) -> None:
        if cls._us_zip_codes is not None:
            return
        if db_ops is not None:
            try:
                describe = db_ops.execute_query("DESCRIBE Zips").fetchall()
                col_names = {row[0] for row in describe} if describe else set()
                state_col = (
                    "state_code" if "state_code" in col_names
                    else "state" if "state" in col_names
                    else None
                )
                if state_col:
                    query = f"SELECT zip, {state_col}, lat, lon FROM Zips"
                else:
                    query = "SELECT zip, NULL, lat, lon FROM Zips"
                rows = db_ops.execute_query(query).fetchall()
                if (
                    isinstance(rows, (list, tuple))
                    and len(rows) > 1000
                    and isinstance(rows[0], (list, tuple))
                    and isinstance(rows[0][0], str)
                ):
                    codes = frozenset(row[0] for row in rows if row[0])
                    states = {row[0]: row[1] for row in rows if row[0] and row[1]}
                    coords: Dict[str, Tuple[float, float]] = {}
                    for row in rows:
                        if row[0] and row[2] is not None and row[3] is not None:
                            coords[row[0]] = (row[2], row[3])
                    cls._us_zip_codes = codes
                    cls._us_zip_states = states
                    cls._us_zip_coords = coords
                    log_info(f"Loaded {len(codes):,} US zip codes from Zips table")
                    return
            except Exception as exc:
                log_debug(f"Zips table unavailable for in-memory lookup: {exc}")
        zip_path = cls._us_zips_file_path()
        if os.path.isfile(zip_path):
            cls._load_us_zips_from_file(zip_path)
            log_info(
                f"Loaded {len(cls._us_zip_codes or ()):,} US zip codes from {zip_path}",
            )
            return
        log_warning("US zip lookup unavailable — preprocess zip rules degraded")
        cls._us_zip_codes = frozenset()
        cls._us_zip_states = {}
        cls._us_zip_coords = {}

    def _is_valid_us_zip(self, zip5: str) -> bool:
        return bool(zip5 and self._us_zip_codes and zip5 in self._us_zip_codes)

    def _us_zip_state_code(self, zip5: str) -> str:
        return (self._us_zip_states or {}).get(zip5, '')

    def _vendor_colocator(self, city: str, state: str, zip5: str) -> str:
        state = (state or self._us_zip_state_code(zip5) or '').strip()
        return f'VENDOR:{city}:{state}:{zip5}'

    def _build_preprocess_stage(self, *, worker_queue_maxsize: Optional[int] = None) -> PipelineStage:
        wq = worker_queue_maxsize if worker_queue_maxsize is not None else self._worker_queue_slots(4)
        return PipelineStage(
            "preprocess", 4, GEOCODING_PREPROCESS_BATCH_SIZE, self._preprocess_handler,
            worker_queue_maxsize=wq,
            batcher_timeout=GEOCODING_BATCHER_TIMEOUT,
        )

    def _append_api_tail_stages(self, stages: List[PipelineStage]) -> None:
        if API_CONFIG['ENABLE_PHOTON']:
            photon_workers, _ = self._photon_runtime_settings()
            stages.append(PipelineStage("photon", photon_workers, 1, self._photon_handler))
        if API_CONFIG['ENABLE_GEOCODE_MAPS_CO'] and not GeocodingAPIProcessor._maps_co_disabled:
            stages.append(PipelineStage(
                "geocode_maps_co", GEOCODE_MAPS_CO_WORKERS, 1, self._geocode_maps_co_handler,
            ))
        elif API_CONFIG['ENABLE_NOMINATIM']:
            stages.append(PipelineStage("nominatim", 4, 1, self._nominatim_handler))
        if API_CONFIG['ENABLE_OPENCAGE']:
            stages.append(PipelineStage("opencage", 8, 1, self._opencage_handler))
        if API_CONFIG['ENABLE_LIBRESTREET'] and not GeocodingAPIProcessor._librestreet_disabled:
            stages.append(PipelineStage("librestreet", 6, 1, self._librestreet_handler))
        stages.append(PipelineStage(
            "fail", 1, 5000, self._grok_pending_fail_handler, is_final_failure=True,
        ))

    def _build_census_pipeline(self, db_ops: DatabaseOperations) -> Pipeline[GeocodingWorkUnit]:
        census_wq = self._worker_queue_slots(GEOCODING_API_WORKERS)
        stages = [
            self._build_preprocess_stage(worker_queue_maxsize=census_wq),
            PipelineStage(
                "census", GEOCODING_API_WORKERS, CENSUS_API_BATCH_SIZE, self._census_handler_raw,
                worker_queue_maxsize=census_wq,
                batcher_timeout=GEOCODING_BATCHER_TIMEOUT,
            ),
            PipelineStage(
                "census_strip", GEOCODING_API_WORKERS, CENSUS_API_BATCH_SIZE, self._census_handler_strip,
                worker_queue_maxsize=census_wq,
                batcher_timeout=GEOCODING_BATCHER_TIMEOUT,
            ),
            PipelineStage(
                "fail", 1, GEOCODING_PENDING_API_BATCH_SIZE, self._pending_api_fail_handler,
                is_final_failure=True,
                worker_queue_maxsize=self._worker_queue_slots(1),
                batcher_timeout=GEOCODING_BATCHER_TIMEOUT,
            ),
        ]
        # Smaller consumer flushes on 16GB hosts: 500 PDCs × Addresses WHERE
        # used to OOM at 7.4GB before UPDATE…FROM rewrite; 100 keeps margin.
        census_consumer = int(os.getenv("GEOCODE_CENSUS_CONSUMER_BATCH", "100"))
        return Pipeline(
            stages=stages,
            db_ops=db_ops,
            chain_on='failure',
            workunit_class=GeocodingWorkUnit,
            consumer_threshold=census_consumer,
            checkpoint_interval=GEOCODE_CHECKPOINT_INTERVAL,
            buffered_feed=True,
            feed_buffer_batches=GEOCODING_FEED_BUFFER_BATCHES,
            batcher_timeout=GEOCODING_BATCHER_TIMEOUT,
        )

    def _build_api_pipeline(self, db_ops: DatabaseOperations) -> Pipeline[GeocodingWorkUnit]:
        stages = [self._build_preprocess_stage()]
        self._append_api_tail_stages(stages)
        return Pipeline(
            stages=stages,
            db_ops=db_ops,
            chain_on='failure',
            workunit_class=GeocodingWorkUnit,
            consumer_threshold=GEOCODE_CONSUMER_BATCH_SIZE,
            checkpoint_interval=GEOCODE_CHECKPOINT_INTERVAL,
            backpressure_enabled=True,
            in_flight_cap=GEOCODING_API_IN_FLIGHT_CAP,
        )

    def _build_free_pipeline(self, db_ops: DatabaseOperations) -> Pipeline[GeocodingWorkUnit]:
        preprocess_stage = self._build_preprocess_stage()
        census_stage_raw = PipelineStage(
            "census", GEOCODING_API_WORKERS, CENSUS_API_BATCH_SIZE, self._census_handler_raw,
        )
        census_stage_strip = PipelineStage(
            "census_strip", GEOCODING_API_WORKERS, CENSUS_API_BATCH_SIZE, self._census_handler_strip,
        )
        stages = [preprocess_stage, census_stage_raw, census_stage_strip]
        self._append_api_tail_stages(stages)
        return Pipeline(
            stages=stages,
            db_ops=db_ops,
            chain_on='failure',
            workunit_class=GeocodingWorkUnit,
            consumer_threshold=GEOCODE_CONSUMER_BATCH_SIZE,
            checkpoint_interval=GEOCODE_CHECKPOINT_INTERVAL,
            backpressure_enabled=True,
            in_flight_cap=GEOCODING_IN_FLIGHT_CAP,
        )

    def _build_grok_pipeline(self, db_ops: DatabaseOperations) -> Pipeline[GeocodingWorkUnit]:
        stages = [
            PipelineStage(
                "grok", GEOCODING_GROK_WORKERS, GEOCODING_GROK_BATCH_SIZE, self._grok_handler,
            ),
            PipelineStage("fail", 1, 5000, self._grok_final_fail_handler, is_final_failure=True),
        ]
        return Pipeline(
            stages=stages,
            db_ops=db_ops,
            chain_on='failure',
            workunit_class=GeocodingWorkUnit,
            consumer_threshold=GEOCODE_CONSUMER_BATCH_SIZE,
            checkpoint_interval=GEOCODE_CHECKPOINT_INTERVAL,
            backpressure_enabled=True,
            in_flight_cap=GEOCODING_IN_FLIGHT_CAP,
        )

    @property
    def _geocoders(self):
        if not hasattr(self._thread_local, 'geocoders'):
            self._thread_local.geocoders = {}
        return self._thread_local.geocoders

    def _photon_runtime_settings(self) -> tuple[int, float]:
        domain = (os.getenv("PHOTON_DOMAIN") or "photon.komoot.io").strip().rstrip("/")
        self_hosted = domain not in ("photon.komoot.io", "photon.komoot.de")
        if self_hosted:
            return GEOCODING_PHOTON_SELF_HOSTED_WORKERS, GEOCODING_PHOTON_SELF_HOSTED_MIN_DELAY
        return GEOCODING_PHOTON_WORKERS, GEOCODING_PHOTON_MIN_DELAY

    def _probe_photon(self) -> None:
        domain = (os.getenv("PHOTON_DOMAIN") or "").strip().rstrip("/")
        if not domain or domain in ("photon.komoot.io", "photon.komoot.de"):
            return
        scheme = os.getenv("PHOTON_SCHEME", "http").strip() or "http"
        workers, delay = self._photon_runtime_settings()
        try:
            r = requests.get(
                f"{scheme}://{domain}/api",
                params={"q": "1600 Pennsylvania Ave NW Washington DC"},
                timeout=10,
            )
            if r.status_code != 200:
                log_warning(f"Photon probe {domain} returned HTTP {r.status_code}")
                print(f"[geolocate_new] Photon self-hosted probe HTTP {r.status_code} — stage enabled anyway", flush=True)
            else:
                print(
                    f"[geolocate_new] Photon self-hosted {scheme}://{domain} "
                    f"({workers} workers, {delay}s delay)",
                    flush=True,
                )
        except Exception as e:
            log_warning(f"Photon probe failed for {domain}: {e}")
            print(f"[geolocate_new] Photon self-hosted probe failed ({e}) — stage enabled anyway", flush=True)

    def _validate_geocoder_api_keys(self):
        self._probe_photon()
        self._probe_geocode_maps_co()
        self._probe_librestreet()

    def _geocode_maps_co_api_key(self) -> Optional[str]:
        return os.getenv('GEOCODE_MAPS_API_KEY') or os.getenv('GEOCODE_MAPS_CO_KEY')

    def _maps_co_search(self, params: Dict[str, str]) -> Optional[dict]:
        maps_key = self._geocode_maps_co_api_key()
        if not maps_key:
            return None
        query = dict(params)
        query['api_key'] = maps_key
        query.setdefault('format', 'jsonv2')
        r = requests.get("https://geocode.maps.co/search", params=query, timeout=15)
        if r.status_code == 401:
            raise GeocoderAuthenticationFailure("geocode.maps.co API key unauthorized")
        if r.status_code == 429:
            raise GeocoderQuotaExceeded("geocode.maps.co rate limit")
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data:
            return data[0]
        return None

    def _probe_geocode_maps_co(self) -> None:
        maps_key = self._geocode_maps_co_api_key()
        if not maps_key:
            GeocodingAPIProcessor._maps_co_disabled = True
            API_CONFIG['ENABLE_GEOCODE_MAPS_CO'] = False
            log_info("geocode.maps.co disabled: GEOCODE_MAPS_API_KEY not set")
            print("[geolocate_new] geocode.maps.co disabled (no API key) — skipping stage", flush=True)
            return
        try:
            hit = self._maps_co_search({
                'street': '1600 Pennsylvania Ave NW',
                'city': 'Washington',
                'state': 'DC',
                'postalcode': '20500',
                'country': 'US',
            })
            if not hit:
                log_warning("geocode.maps.co probe returned no results — stage enabled anyway")
            API_CONFIG['ENABLE_NOMINATIM'] = False
            print(
                f"[geolocate_new] geocode.maps.co enabled "
                f"({GEOCODE_MAPS_CO_WORKERS} workers, ~{GEOCODE_MAPS_CO_WORKERS} req/sec) — free Nominatim skipped",
                flush=True,
            )
        except GeocoderAuthenticationFailure:
            GeocodingAPIProcessor._maps_co_disabled = True
            API_CONFIG['ENABLE_GEOCODE_MAPS_CO'] = False
            log_warning("geocode.maps.co disabled: API key returned 401 Unauthorized")
            print("[geolocate_new] geocode.maps.co disabled (401) — skipping stage", flush=True)
        except Exception as e:
            log_debug(f"geocode.maps.co probe inconclusive: {e}")

    def _probe_librestreet(self) -> None:
        """librestreet.org is NXDOMAIN as of 2026-06 — skip stage to avoid per-address connection retries."""
        try:
            r = requests.head("https://librestreet.org/search.php", timeout=5)
            if r.status_code >= 500:
                raise GeocoderServiceError(f"HTTP {r.status_code}")
        except Exception as e:
            GeocodingAPIProcessor._librestreet_disabled = True
            API_CONFIG['ENABLE_LIBRESTREET'] = False
            log_warning(f"LibreStreet disabled: service unreachable ({e})")
            print(f"[geolocate_new] LibreStreet disabled (unreachable) — skipping stage", flush=True)

    def _geocode_with_geopy(self, unit: GeocodingWorkUnit, geocoder_key: str, source_name: str,
                            prefer_structured: bool = True, rate_limit_min_delay: float = 0.0,
                            max_retries: int = 2) -> tuple[bool, Any]:
        if geocoder_key not in self._geocoders:
            if geocoder_key == "nominatim":
                geo = Nominatim(user_agent="irs990-geocoder/1.0")
                limiter = RateLimiter(geo.geocode, min_delay_seconds=1.1, max_retries=3)
            elif geocoder_key == "photon":
                domain = (os.getenv("PHOTON_DOMAIN") or "photon.komoot.io").strip().rstrip("/")
                scheme = os.getenv("PHOTON_SCHEME")
                if not scheme:
                    scheme = "http" if domain not in ("photon.komoot.io", "photon.komoot.de") else "https"
                _, photon_delay = self._photon_runtime_settings()
                geo = Photon(domain=domain, scheme=scheme)
                limiter = RateLimiter(geo.geocode, min_delay_seconds=photon_delay, max_retries=max_retries)
            elif geocoder_key == "geocode_maps_co":
                if GeocodingAPIProcessor._maps_co_disabled:
                    return (False, unit)
                if not self._geocode_maps_co_api_key():
                    return (False, unit)
                limiter = RateLimiter(
                    self._maps_co_search,
                    min_delay_seconds=GEOCODE_MAPS_CO_MIN_DELAY,
                    max_retries=0,
                )
            elif geocoder_key == "opencage":
                opencage_key = os.getenv('OPENCAGE_API_KEY')
                if not opencage_key:
                    return (False, unit)
                geo = OpenCage(api_key=opencage_key)
                limiter = RateLimiter(geo.geocode, min_delay_seconds=0.6, max_retries=max_retries)
            else: raise ValueError(geocoder_key)
            self._geocoders[geocoder_key] = limiter
            
        

        limiter = self._geocoders[geocoder_key]

        parsed = unit.parsed_normalized
        query = None
        if geocoder_key == "geocode_maps_co":
            if prefer_structured and parsed:
                query = {k: v for k, v in {
                    'street': parsed.get('street', '') or parsed.get('address_line1', ''),
                    'city': parsed.get('city', ''),
                    'state': parsed.get('state', ''),
                    'postalcode': parsed.get('zip', ''),
                    'country': 'US',
                }.items() if v}
            if not query:
                parts = [parsed.get('street', '') or parsed.get('address_line1', ''),
                         parsed.get('city', ''), parsed.get('state', ''), parsed.get('zip', '')]
                freeform = ', '.join(filter(None, parts)).strip(', ') or unit.canonical_address.strip()
                query = {'q': freeform} if freeform else None
        elif prefer_structured and geocoder_key == "nominatim" and parsed:
            query = {k: v for k, v in {
                'street': parsed.get('street', '') or parsed.get('address_line1', ''),
                'city': parsed.get('city', ''),
                'state': parsed.get('state', ''),
                'postalcode': parsed.get('zip', '')
            }.items() if v}

        if not query:
            parts = [parsed.get('street', '') or parsed.get('address_line1', ''),
                     parsed.get('city', ''), parsed.get('state', ''), parsed.get('zip', '')]
            query = ', '.join(filter(None, parts)).strip(', ') or unit.canonical_address.strip()

        if not query:
            return False, unit

        try:
            if geocoder_key == "geocode_maps_co":
                hit = limiter(query if isinstance(query, dict) else {'q': query})
                if hit:
                    matched = hit.get('display_name') or unit.canonical_address
                    return True, self._apply_successful_geocode(
                        unit, float(hit['lat']), float(hit['lon']),
                        f"Match:{source_name}", matched,
                    )
            else:
                loc = limiter(query)
                if loc:
                    return True, self._apply_successful_geocode(
                        unit, loc.latitude, loc.longitude, f"Match:{source_name}", loc.address or unit.canonical_address
                    )
        except GeocoderAuthenticationFailure:
            if geocoder_key == "geocode_maps_co":
                GeocodingAPIProcessor._maps_co_disabled = True
                log_warning("geocode.maps.co disabled after 401 — skipping remaining lookups")
            else:
                log_warning(f"{source_name} auth failed {unit.geocoding_id}")
        except Exception as e:
            log_warning(f"{source_name} failed {unit.geocoding_id}: {e}")
        return False, unit

    def _load_geocoding_patterns(self) -> List[Dict[str, Any]]:
        path = os.path.join(os.path.dirname(__file__), 'geocoding_patterns.json')
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            patterns = data.get('patterns', [])
            patterns.sort(key=lambda x: x.get('priority', 999))
            print(f"Loaded {len(patterns)} geocoding patterns")
            return patterns
        except Exception as e:
            log_warning(f"Failed to load geocoding_patterns.json: {e}")
            return []

    @classmethod
    def _major_foreign_cities_path(cls) -> str:
        here = os.path.dirname(os.path.abspath(__file__))
        for candidate in (
            os.path.join(os.getcwd(), 'major_foreign_cities.json'),
            os.path.join(here, 'major_foreign_cities.json'),
        ):
            if os.path.isfile(candidate):
                return candidate
        return os.path.join(here, 'major_foreign_cities.json')

    @classmethod
    def _ensure_major_foreign_places(cls) -> None:
        """Load major_foreign_cities.json once (cities/countries/shell phrases)."""
        if cls._major_foreign_cities is not None:
            return
        path = cls._major_foreign_cities_path()
        cities: set[str] = set()
        countries: set[str] = set()
        shell_rx: List[re.Pattern] = []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for item in data.get('cities') or []:
                t = str(item).strip().lower()
                if t:
                    cities.add(t)
            for item in data.get('countries') or []:
                t = str(item).strip().lower()
                if t:
                    countries.add(t)
            for phrase in data.get('shell_phrases') or []:
                p = str(phrase).strip()
                if p:
                    shell_rx.append(re.compile(r'(?i)\b' + re.escape(p) + r'\b'))
            print(
                f"Loaded major foreign places: {len(cities)} cities, "
                f"{len(countries)} countries from {os.path.basename(path)}",
                flush=True,
            )
        except FileNotFoundError:
            log_warning(f"major_foreign_cities.json not found at {path}")
        except Exception as e:
            log_warning(f"Failed to load major_foreign_cities.json: {e}")
        cls._major_foreign_cities = frozenset(cities)
        cls._major_foreign_countries = frozenset(countries)
        cls._foreign_shell_phrases = tuple(shell_rx)

    @classmethod
    def _normalize_place_token(cls, text: str) -> str:
        t = (text or '').strip().lower()
        t = re.sub(r'\s+', ' ', t)
        t = t.strip('.,;:')
        return t

    def _is_major_foreign_place_name(self, text: str) -> bool:
        """Exact match against bootstrap foreign city/country list."""
        self._ensure_major_foreign_places()
        token = self._normalize_place_token(text)
        if not token or re.search(r'\d', token):
            return False
        if token in (self._major_foreign_cities or ()):
            return True
        if token in (self._major_foreign_countries or ()):
            return True
        return False

    def _has_foreign_shell_phrase(self, text: str) -> bool:
        self._ensure_major_foreign_places()
        if not text:
            return False
        for rx in self._foreign_shell_phrases or ():
            if rx.search(text):
                return True
        return False

    def _is_state_zip_mismatch(self, state: str, zip5: str) -> bool:
        """Delegate to shared lookup (same rule as Address.canonicalize colocator)."""
        from us_zip_lookup import is_state_zip_mismatch
        return is_state_zip_mismatch(state, zip5)

    def _load_census_strip_suite_regexes(self) -> List[re.Pattern]:
        """Suite/unit strip patterns for census_strip (colocator is round(lat,4) — suite irrelevant)."""
        regexes: List[str] = []
        for pattern in self.geocoding_patterns:
            if pattern.get("name") != "census_strip_suites":
                continue
            for sub in pattern.get("patterns", []):
                if sub.get("action") == "strip" and sub.get("regex"):
                    regexes.append(sub["regex"])
            if pattern.get("action") == "strip" and pattern.get("regex"):
                regexes.append(pattern["regex"])
        if not regexes:
            regexes = [
                r"(?i)[,\s]+(?:suite|ste\.?|apt\.?|apartment|unit|rm\.?|room|fl\.?|floor|bldg\.?|building)\s*#?\s*(?:\d+[a-z0-9-]*|[a-z](?:\d+|(?=\s*,|\s*$)))",
                r"(?i)[,\s]+#\s*\d+[a-z0-9-]*",
                r"(?i)[,\s]+\d{1,4}(?=,\s*[A-Za-z])",
            ]
        return [re.compile(rx) for rx in regexes]

    def _strip_suite_from_address(self, address: str) -> str:
        """Remove suite/unit/# clauses so census_strip can match the building."""
        if not address:
            return address
        result = address
        changed = True
        while changed:
            changed = False
            for rx in self._census_strip_suite_regexes:
                new = rx.sub("", result).strip()
                new = re.sub(r"\s{2,}", " ", new)
                new = re.sub(r",\s*,", ", ", new)
                if new != result:
                    result = new
                    changed = True
        return result

    def _strip_for_census_strip(self, address: str) -> str:
        """C/O then suite/unit strip for census_strip retry."""
        return self._strip_suite_from_address(self._strip_co_from_address(address))

    # Leading care-of: C/O (slash) is unambiguous; bare CO needs a word boundary so
    # COLUMBIA/COLORADO/CONNECTION do not enter the stripper. Bare CO is common on
    # 990 street lines ("CO JOHN DOE 123 MAIN") and is handled the same as C/O once gated.
    _CO_PREFIX_RE = re.compile(r'(?i)^(c/o|co)\b,?\s*')
    _CO_COMMA_RE = re.compile(r'(?i)^(c/o|co)\b,?\s*[^,\d]*,\s*')
    _CO_DIGIT_RE = re.compile(r'(?i)^(c/o|co)\b,?\s*.*?(?=\d)')
    # Street cues after the care-of party (no house number): ordinal place names and
    # "Name Road/Street/…" — used when digit/comma patterns cannot fire.
    _CO_NUMWORD_CUE_RE = re.compile(
        r'(?i)\b(?:one|two|three|four|five|six|seven|eight|nine|ten|'
        r'first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\b'
    )
    _CO_DIRECTION_CUE_RE = re.compile(
        r'(?i)\b(?:[nsew]|north|south|east|west)\s+\S+'
    )
    _CO_STREET_TYPE_CUE_RE = re.compile(
        r'(?i)\b\S+\s+(?:st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|ln|lane|'
        r'way|ct|court|pl|place|pkwy|parkway|hwy|highway|cir|circle|ter|terrace|'
        r'sq|square|trl|trail|row|alley|loop|path|pike|run)\b'
    )

    def _strip_co_via_street_cue(self, address: str) -> Optional[str]:
        """If address is CO/C/O + party + street-ish tail (no house #), return the tail."""
        m = self._CO_PREFIX_RE.match(address)
        if not m:
            return None
        rest = address[m.end():].strip()
        if not rest:
            return None
        starts = []
        for rx in (
            self._CO_NUMWORD_CUE_RE,
            self._CO_DIRECTION_CUE_RE,
            self._CO_STREET_TYPE_CUE_RE,
        ):
            hit = rx.search(rest)
            if hit:
                starts.append(hit.start())
        if not starts:
            return None
        street = rest[min(starts):].strip()
        if not street:
            return None
        # Always an improvement when we dropped a care-of prefix (and maybe a party name).
        if street.lower() == address.lower():
            return None
        return street

    def _strip_co_from_address(self, address: str) -> str:
        """Strip leading C/O or CO (care-of) patterns from address strings."""
        if not address:
            return address
        if not self._CO_PREFIX_RE.match(address):
            return address
        log_debug(f"C/O strip: {address[:80]}")
        if "Tull Charitable Foundation" in address:
            print(f"DEBUG_TULL: C/O stripping initiated for '{address}'")

        m = self._CO_COMMA_RE.match(address)
        if m:
            result = address[m.end():].strip()
            log_debug(f"C/O strip: Used comma pattern, result: '{result}'")
            if "Tull Charitable Foundation" in address:
                print(f"DEBUG_TULL: C/O stripping - comma pattern matched, result: '{result}'")
            return result

        m = self._CO_DIGIT_RE.match(address)
        if m:
            result = address[m.end():].strip()
            # Guard: require a real house-number run at the cut point
            if re.match(r'^\d', result):
                log_debug(f"C/O strip: Used digit pattern, result: '{result}'")
                if "Tull Charitable Foundation" in address:
                    print(f"DEBUG_TULL: C/O stripping - digit pattern matched, result: '{result}'")
                return result

        cued = self._strip_co_via_street_cue(address)
        if cued:
            log_debug(f"C/O strip: Used street-cue pattern, result: '{cued}'")
            return cued

        log_debug(f"C/O strip: No pattern matched for '{address}', returning original")
        if "Tull Charitable Foundation" in address:
            print(f"DEBUG_TULL: C/O stripping - no pattern matched, returning original: '{address}'")
        return address

    def _extract_entity_from_co_address(self, address: str) -> str:
        """Extract entity name from C/O / CO addresses for search-oriented queries."""
        if not address or not self._CO_PREFIX_RE.match(address):
            return ""
        comma_match = re.match(
            r'(?i)^(c/o|co)\b,?\s*([^,\d]*),\s*(.*)', address
        )
        if comma_match:
            entity = comma_match.group(2).strip()
            if entity:
                return entity
        digit_match = re.match(
            r'(?i)^(c/o|co)\b,?\s*(.*?)(?=\d)', address
        )
        if digit_match:
            entity = digit_match.group(2).strip()
            if entity:
                return entity
        no_delimiter_match = re.match(
            r'(?i)^(c/o|co)\b,?\s*(.+)', address
        )
        if no_delimiter_match:
            entity = no_delimiter_match.group(2).strip()
            entity = re.sub(r'[,.]$', '', entity).strip()
            if entity:
                return entity
        return ""

    def _parse_co_address(self, address: str, api_type: str, zip_code: str = "") -> str:
        """Parse C/O addresses differently based on API type."""
        if not address:
            return address
        if api_type.lower() == 'census':
            return self._strip_co_from_address(address)
        elif api_type.lower() == 'grok':
            if not self._CO_PREFIX_RE.match(address):
                return address
            comma_match = re.match(
                r'(?i)^(c/o|co)\b,?\s*([^,\d]*),\s*(.*)', address
            )
            if comma_match:
                entity = comma_match.group(2).strip()
                rest = comma_match.group(3).strip()
                zip_match = re.search(r'\b(\d{5})\b', rest)
                zip_part = zip_match.group(1) if zip_match else zip_code
                if zip_part:
                    return f"{entity}, {zip_part}"
            digit_match = re.match(
                r'(?i)^(c/o|co)\b,?\s*(.*?)(?=\d)(.*)', address
            )
            if digit_match:
                entity = digit_match.group(2).strip()
                rest = digit_match.group(3).strip()
                zip_match = re.search(r'\b(\d{5})\b', rest)
                zip_part = zip_match.group(1) if zip_match else zip_code
                if zip_part:
                    return f"{entity}, {zip_part}"
            no_delimiter_match = re.match(r'^(?:c/?o,?)\s*(.+)', address, flags=re.IGNORECASE)
            if no_delimiter_match:
                entity = no_delimiter_match.group(1).strip()
                entity = re.sub(r'[,.]$', '', entity).strip()
                if entity and zip_code:
                    return f"{entity}, {zip_code}"
            return address
        else:
            return address

    _PLACEHOLDER_STREET = re.compile(
        r'(?i)^(unknown|none|n/a|na|tbd|not available|general delivery|gen delivery|address unknown|'
        r'no street address|no address|unable to locate|same as(?:\s+(?:above|below|c\s+above))?|'
        r'see statement|see schedule|not present|no actual location|local|fellowship|oth|'
        r'telehealth|general telehealth|remote telehealth)\b'
    )
    _US_TERRITORIES = frozenset({'PR', 'VI', 'GU', 'AS', 'MP', 'FM', 'MH', 'PW'})
    _MILITARY_STATES = frozenset({'AP', 'AE', 'AA'})
    _MILITARY_CITIES = frozenset({'APO', 'FPO', 'DPO'})
    _CA_PROVINCE = re.compile(r'(?i)^(Ab|Bc|Mb|Nb|Nl|Ns|Nt|Nu|On|Pe|Qc|Sk|Yt)$')
    _MX_BORDER_CITY = re.compile(r'(?i)^(Tijuana|Mexicali|Nogales|Ciudad Juarez|Baja California)$')
    _FOREIGN_COUNTRY_MARKERS = re.compile(
        r'(?i)\b(?:'
        r'germany|canada|france|england|scotland|wales|ireland|israel|china|india|mexico|'
        r'brazil|australia|netherlands|norway|sweden|denmark|finland|poland|spain|italy|'
        r'russia|ukraine|pakistan|japan|korea|taiwan|philippines|indonesia|thailand|'
        r'vietnam|colombia|argentina|chile|peru|ecuador|venezuela|belgium|switzerland|'
        r'austria|portugal|greece|turkey|egypt|morocco|nigeria|kenya|south africa|'
        r'saudi arabia|uae|qatar|kuwait|lebanon|syria|iraq|iran|afghanistan|bangladesh|'
        r'sri lanka|nepal|cambodia|malaysia|singapore|hong kong|new zealand|british columbia|'
        r'ontario|quebec|saskatchewan|catalonia|cataloni|ingushetia|chechnya|kashmir'
        r')\b'
    )
    _FOREIGN_CITY_HINTS = re.compile(
        r'(?i)\b(?:'
        r'calgary|toronto|vancouver|montreal|ottawa|london|paris|berlin|munich|muenchen|'
        r'milan|milano|rome|roma|barcelona|madrid|amsterdam|brussels|vienna|prague|'
        r'warsaw|budapest|bucharest|athens|lisbon|stockholm|oslo|copenhagen|helsinki|'
        r'dublin|edinburgh|glasgow|goteborg|gothenburg|vilnius|riga|tallinn|kyiv|kiev|'
        r'moscow|istanbul|dubai|riyadh|tel aviv|jerusalem|beirut|cairo|nairobi|lagos|'
        r'sydney|melbourne|auckland|singapore|bangkok|manila|jakarta|hanoi|seoul|tokyo|'
        r'beijing|shanghai|taipei|mumbai|delhi|islamabad|karachi|dhaka|colombo|'
        r'buenos aires|sao paulo|mexico city|guadalajara|monterrey|havana|bogota|lima|'
        r'santiago|hauzenberg|malappuram|aulnay|guelph|courtenay|'
        r'wiesbaden|yokosuka|okinawa|ramstein|stuttgart|kaiserslautern|chinhae'
        r')\b'
    )
    _HWY_INTERSECTION = re.compile(
        r'(?i)(?:\b(hwy|highway|interstate|i-\d+)\b.*(?:\s&\s|\band\b)|(?:\s&\s|\band\b).*\b(hwy|highway|interstate|i-\d+)\b)'
    )
    _STREET_NUMBER_WORDS = re.compile(
        r'(?i)\b(?:'
        r'zero|one|two|three|four|five|six|seven|eight|nine|ten|'
        r'eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|'
        r'twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand'
        r')\b'
    )

    def _street_has_number(self, street: str) -> bool:
        """True when street appears to include a civic number (digit or spelled-out)."""
        if not street:
            return False
        if re.search(r'\d', street):
            return True
        return bool(self._STREET_NUMBER_WORDS.search(street))

    def _parsed_address_fields(self, parsed: Dict[str, Any]) -> tuple[str, str, str, str]:
        street = (parsed.get('street') or parsed.get('address_line1') or '').strip()
        city = (parsed.get('city') or '').strip()
        state = (parsed.get('state') or '').strip()
        zip5 = (parsed.get('zip') or '')[:5]
        return street, city, state, zip5

    def _expand_colocator(
        self,
        colocator: str,
        canonical_address: str,
        zip_code: str = "",
        parsed: Optional[Dict[str, Any]] = None,
    ) -> str:
        if not colocator:
            return colocator
        parsed = parsed or {}
        zip5 = zip_code or (parsed.get('zip') or '')[:5] or '00000'
        colocator = colocator.replace('{zip}', zip5)
        city = (parsed.get('city') or '').strip()
        state = (parsed.get('state') or '').strip()
        if '{city}' in colocator:
            if not city:
                m = re.search(r', ([^,]+), ([A-Za-z]{2}),', canonical_address)
                if m:
                    city = m.group(1).strip()
            colocator = colocator.replace('{city}', city or '?')
        if '{state}' in colocator:
            if not state:
                state = self._us_zip_state_code(zip5)
            if not state:
                m = re.search(r', ([A-Za-z]{2}),', canonical_address)
                if m:
                    state = m.group(1).strip()
            colocator = colocator.replace('{state}', state or '?')
        if '{entity}' in colocator:
            m = re.match(r'c/o\s+(.+?)[,]', canonical_address, re.IGNORECASE)
            if m:
                colocator = colocator.replace('{entity}', m.group(1).strip())
        if '{box}' in colocator:
            box_m = re.search(r'(?i)p\.?\s*o\.?\s*(?:box|drawer)\s*#?\s*(\d+)', canonical_address)
            if box_m:
                colocator = colocator.replace('{box}', box_m.group(1))
        return colocator

    def _apply_preprocess_shortcircuit(
        self, unit: GeocodingWorkUnit, colocator: str, matched: Optional[str] = None,
    ) -> tuple[bool, ResultWorkUnit]:
        self.run_stats.preprocess_match += 1
        return True, self._apply_geocoding_only_update(
            unit, 'Match:PatternOwners',
            colocator=colocator,
            matched=matched or unit.canonical_address,
        )

    def _is_city_only_parsed(
        self,
        street: str,
        city: str,
        state: str,
        zip5: str,
        canonical: str,
    ) -> bool:
        """Vendor/city-only address: city+state+zip present but no geocodable street."""
        if not (city and state and zip5):
            return False
        if not street:
            return True
        if self._street_has_number(street):
            return False
        if self._HWY_INTERSECTION.search(street):
            return False
        if street.lower().strip(' ,') == city.lower().strip(' ,'):
            return True
        parts = [p.strip() for p in canonical.split(',')]
        if len(parts) == 3:
            head, mid, tail = parts
            if re.match(r'^[A-Za-z]{2}$', mid) and re.match(r'^\d{5}', tail) and not self._street_has_number(head):
                return True
        return False

    def _is_city_state_only_parsed(
        self,
        street: str,
        city: str,
        state: str,
        zip5: str,
    ) -> bool:
        """Vendor/city-only: city+US state, no street, no zip (iter-3 grok tail)."""
        if street or not city or not state or zip5:
            return False
        return state.upper() in VALID_STATES

    def _is_city_zip_no_state_parsed(
        self,
        street: str,
        city: str,
        state: str,
        zip5: str,
    ) -> bool:
        """Vendor city+zip without state when zip is in the US Zips lookup."""
        if street or not city or state or not zip5:
            return False
        if zip5 in ('00000', '99999') or not self._is_valid_us_zip(zip5):
            return False
        if self._FOREIGN_COUNTRY_MARKERS.search(city) or self._FOREIGN_CITY_HINTS.search(city):
            return False
        return True

    def _is_foreign_city_zip_no_state(
        self,
        street: str,
        city: str,
        state: str,
        zip_raw: str,
        zip5: str,
    ) -> bool:
        if street or not city or state:
            return False
        if not zip_raw:
            return False
        if zip5 in ('00000', '99999'):
            return True
        if zip5.isdigit() and len(zip5) == 5 and not self._is_valid_us_zip(zip5):
            return True
        if not re.match(r'^\d{5}', zip_raw):
            return True
        return bool(
            self._FOREIGN_COUNTRY_MARKERS.search(city)
            or self._FOREIGN_CITY_HINTS.search(city)
        )

    def _is_zip_only_parsed(
        self,
        street: str,
        city: str,
        state: str,
        zip5: str,
        canonical: str = "",
    ) -> bool:
        """Malformed row: only a zip (or bare number) with no street/city/state."""
        if street or city or state:
            return False
        if zip5:
            return True
        return bool(canonical and re.fullmatch(r'\d{3,5}', canonical.strip()))

    def _is_us_territory_parsed(self, state: str) -> bool:
        return state.upper() in self._US_TERRITORIES

    def _zip_only_colocator(self, zip5: str, canonical: str = "") -> str:
        zip5 = zip5 or (canonical.strip() if canonical else '')
        if self._is_valid_us_zip(zip5):
            return f'VENDOR::{self._us_zip_state_code(zip5)}:{zip5}'
        if zip5.isdigit() and len(zip5) == 5:
            return f'PARTIAL:{zip5}'
        return f'PARTIAL:{zip5 or "00000"}'

    def _is_city_only_intl_parsed(
        self,
        street: str,
        city: str,
        state: str,
        zip5: str,
    ) -> bool:
        """Foreign city name with no US street/state/zip anchor (iter-3 grok UNKN tail)."""
        if street or state or zip5 or not city:
            return False
        if city.upper() in VALID_STATES:
            return False
        if self._is_major_foreign_place_name(city):
            return True
        if self._FOREIGN_COUNTRY_MARKERS.search(city):
            return True
        if self._CA_PROVINCE.match(city):
            return True
        if self._MX_BORDER_CITY.search(city):
            return True
        return True

    def _is_foreign_name_only_address(
        self,
        street: str,
        city: str,
        state: str,
        zip5: str,
        canonical: str = "",
    ) -> bool:
        """
        Foreign city/country as the only place token (e.g. street='Moscow' with empty city,
        or country name 'Nicaragua' alone). Avoids treating 'Paris TX' as foreign when
        state+ZIP are a valid agreeing US pair.
        """
        # Shell / offshore registration phrases (Marshall Islands etc.)
        if self._has_foreign_shell_phrase(canonical) or self._has_foreign_shell_phrase(street):
            return True

        state_u = (state or '').strip().upper()
        has_us_anchor = (
            len(state_u) == 2
            and state_u in VALID_STATES
            and bool(zip5)
            and self._is_valid_us_zip(zip5)
            and not self._is_state_zip_mismatch(state_u, zip5)
        )
        if has_us_anchor:
            return False

        if self._street_has_number(street or ''):
            return False

        # Street is exactly a foreign city/country
        if street and self._is_major_foreign_place_name(street):
            return True
        # City alone is foreign (no street)
        if city and not street and self._is_major_foreign_place_name(city):
            return True
        # Country marker as the sole place token
        blob = (street or city or '').strip()
        if blob and self._FOREIGN_COUNTRY_MARKERS.fullmatch(blob):
            return True
        return False

    def _preprocess_bogus_shortcircuit(
        self,
        unit: GeocodingWorkUnit,
        parsed: Dict[str, Any],
        zip_code: str,
    ) -> Optional[tuple[bool, ResultWorkUnit]]:
        """Structured-data bogus detection before Census (DOT/FEC/NPPES fraud-source families)."""
        addr = unit.canonical_address
        street = (parsed.get('street') or parsed.get('address_line1') or '').strip()
        city = (parsed.get('city') or '').strip()
        state = (parsed.get('state') or '').strip()
        zip5 = zip_code or (parsed.get('zip') or '')[:5]
        country = (parsed.get('country') or '').strip().upper()

        if country and country not in ('US', 'USA', 'UNITED STATES'):
            tag = country[:2] if len(country) >= 2 else 'XX'
            return self._apply_preprocess_shortcircuit(unit, f'FA:{tag}')

        # State vs ZIP region disagreement (e.g. Atlanta, NJ 30339).
        # Primary assignment is Address.canonicalize → AMBIG:{state}:{zip}; this
        # residual path covers Geocoding rows that never re-pass Address.
        if state and zip5 and self._is_state_zip_mismatch(state, zip5):
            from us_zip_lookup import ambig_colocator
            return self._apply_preprocess_shortcircuit(
                unit, ambig_colocator(state, zip5),
            )

        if state and self._CA_PROVINCE.match(state):
            return self._apply_preprocess_shortcircuit(unit, 'FA:CA')

        if city and self._MX_BORDER_CITY.search(city):
            return self._apply_preprocess_shortcircuit(unit, 'FA:MX')

        if self._is_foreign_name_only_address(street, city, state, zip5, addr):
            return self._apply_preprocess_shortcircuit(unit, 'FA:INTL')

        if self._is_us_territory_parsed(state):
            return self._apply_preprocess_shortcircuit(
                unit, self._vendor_colocator(city or '?', state.upper(), zip5),
            )

        psc_src = ' '.join(filter(None, (street, city, addr)))
        if re.search(r'(?i)\bpsc\s+\d+', psc_src):
            psc_m = re.search(r'(?i)\bpsc\s+(\d+)', psc_src)
            psc_code = psc_m.group(1) if psc_m else '?'
            return self._apply_preprocess_shortcircuit(
                unit, f'MILITARY:PSC{psc_code}:{zip5 or "00000"}',
            )

        if (
            self._FOREIGN_COUNTRY_MARKERS.search(street)
            or self._FOREIGN_COUNTRY_MARKERS.search(addr)
            or (
                re.search(r'(?i)\b(usnh|us\s+army)\b', street or addr)
                and self._FOREIGN_CITY_HINTS.search(f'{city} {addr}')
            )
        ):
            return self._apply_preprocess_shortcircuit(unit, 'FA:INTL')

        city_upper = city.upper()
        mil_city_token = city_upper.split()[0] if city_upper else ''
        if (
            state.upper() in self._MILITARY_STATES
            or city_upper in self._MILITARY_CITIES
            or mil_city_token in self._MILITARY_CITIES
        ):
            mil_city = mil_city_token if mil_city_token in self._MILITARY_CITIES else 'APO'
            return self._apply_preprocess_shortcircuit(
                unit, f'MILITARY:{mil_city}:{zip5 or "00000"}',
            )

        if street and re.match(r'(?i)^(?:dept\.?|department)\s+(?:la\s+)?', street):
            dept_m = re.match(r'(?i)^(?:dept\.?|department)\s+(?:la\s+)?(\S+)', street)
            dept_code = dept_m.group(1) if dept_m else '?'
            return self._apply_preprocess_shortcircuit(
                unit, f'DEPT:{dept_code}:{zip5 or "00000"}',
            )

        if street and re.match(r'(?i)^bin\s+\d+', street):
            bin_m = re.match(r'(?i)^bin\s+(\d+)', street)
            bin_code = bin_m.group(1) if bin_m else '?'
            return self._apply_preprocess_shortcircuit(
                unit, f'DEPT:BIN{bin_code}:{zip5 or "00000"}',
            )

        if zip5 in ('00000', '99999') or (parsed.get('zip') or '').strip() in ('00000', '99999'):
            return self._apply_preprocess_shortcircuit(unit, 'FA:INTL')

        raw_zip = (parsed.get('zip') or '').strip()
        zip_digits = re.sub(r'\D', '', raw_zip) if raw_zip else ''
        if zip_digits and len(zip_digits) != 5 and not self._is_valid_us_zip(zip_digits[:5]):
            return self._apply_preprocess_shortcircuit(unit, 'FA:INTL')
        if raw_zip and not state and self._is_foreign_city_zip_no_state(
            street, city, state, raw_zip, zip5,
        ):
            return self._apply_preprocess_shortcircuit(unit, 'FA:INTL')

        if self._is_city_only_intl_parsed(street, city, state, zip5):
            return self._apply_preprocess_shortcircuit(unit, 'FA:INTL')

        if not street and not city and state.upper() in VALID_STATES and not zip5:
            return self._apply_preprocess_shortcircuit(
                unit, f'VENDOR::{state.upper()}:',
            )

        if self._is_city_state_only_parsed(street, city, state, zip5):
            return self._apply_preprocess_shortcircuit(
                unit, f'VENDOR:{city}:{state}:{zip5 or ""}',
            )

        if self._is_city_zip_no_state_parsed(street, city, state, zip5):
            return self._apply_preprocess_shortcircuit(
                unit, self._vendor_colocator(city, state, zip5),
            )

        if self._is_zip_only_parsed(street, city, state, zip5, addr):
            return self._apply_preprocess_shortcircuit(
                unit, self._zip_only_colocator(zip5, addr),
            )

        if street and self._PLACEHOLDER_STREET.match(street):
            return self._apply_preprocess_shortcircuit(unit, f'BOGUS:{zip5 or "00000"}')

        if re.match(r'(?i)^(unknown|none|n/a|na|tbd|not available|general delivery)\s*,', addr):
            return self._apply_preprocess_shortcircuit(unit, f'BOGUS:{zip5 or "00000"}')

        if street and not re.search(r'\d{3,}', street) and self._HWY_INTERSECTION.search(street):
            return self._apply_preprocess_shortcircuit(unit, f'PARTIAL:{zip5 or "00000"}')

        if street and re.search(r'\bAND\b', street, re.IGNORECASE) and not self._street_has_number(street):
            return self._apply_preprocess_shortcircuit(unit, f'PARTIAL:{zip5 or "00000"}')

        _STREET_TYPE = r'(?:st|street|streets|ave|avenue|rd|road|blvd|boulevard|rt|route|pkwy|parkway|ter|terrace|way|ln|lane|dr|drive)'

        if street and street.lstrip().startswith('&'):
            return self._apply_preprocess_shortcircuit(unit, f'PARTIAL:{zip5 or "00000"}')

        if street and '&' in street and re.search(rf'(?i)\b{_STREET_TYPE}\b', street):
            return self._apply_preprocess_shortcircuit(unit, f'PARTIAL:{zip5 or "00000"}')

        if street and re.search(
            rf'(?i)\b{_STREET_TYPE}\b.*\band\b.*\b{_STREET_TYPE}\b',
            street,
        ):
            return self._apply_preprocess_shortcircuit(unit, f'PARTIAL:{zip5 or "00000"}')

        if street and re.fullmatch(r'\d+', street.strip()):
            return self._apply_preprocess_shortcircuit(unit, f'PARTIAL:{zip5 or "00000"}')

        if street and re.match(r'(?i)^(attn|dba)\s+', street):
            return self._apply_preprocess_shortcircuit(unit, f'PERSON:{zip5 or "00000"}')

        if street and re.search(r'(?i)\battn\b', street) and not re.search(r'\d{3,}', street):
            return self._apply_preprocess_shortcircuit(unit, f'PERSON:{zip5 or "00000"}')

        if street and re.match(r'(?i)^e[de]?amc\b', street) and not self._street_has_number(street):
            return self._apply_preprocess_shortcircuit(unit, f'DEPT:{zip5 or "00000"}')

        if street and re.match(r'(?i)^university at\s+', street):
            return self._apply_preprocess_shortcircuit(unit, f'UNIV:{zip5 or "00000"}')

        if street and re.match(r'(?i)^dumc\s+\d+', street):
            return self._apply_preprocess_shortcircuit(unit, f'UNIV:{zip5 or "00000"}')

        if street and re.search(r'(?i)\bmchj-', street):
            return self._apply_preprocess_shortcircuit(unit, f'DEPT:{zip5 or "00000"}')

        if street and re.match(r'(?i)^mail\s+location\s+\d+', street):
            m = re.match(r'(?i)^mail\s+location\s+(\d+)', street)
            loc = m.group(1) if m else '?'
            return self._apply_preprocess_shortcircuit(unit, f'DEPT:LOC{loc}:{zip5 or "00000"}')

        if street and re.match(r'(?i)^athletic\s+department\b', street):
            return self._apply_preprocess_shortcircuit(unit, f'DEPT:{zip5 or "00000"}')

        if re.search(r'(?i)housecalls\s+only', addr):
            return self._apply_preprocess_shortcircuit(unit, f'BOGUS:{zip5 or "00000"}')

        if re.search(r'(?i)\bsp-fr-', addr):
            return self._apply_preprocess_shortcircuit(unit, f'DEPT:{zip5 or "00000"}')

        if re.search(r'(?i)\bcrdamc\b', addr):
            return self._apply_preprocess_shortcircuit(unit, f'DEPT:{zip5 or "00000"}')

        # Highway / county-road without a house number → not Census-grade.
        # With a street number (e.g. "2418 E HWY 66") these are real addresses —
        # do NOT short-circuit (was incorrectly vacuuming ~5k grok_pending weight).
        if (
            street
            and re.search(
                r'(?i)\b(highway|hwy|county rd|county road|state hwy|state road|us highway)\b',
                street,
            )
            and not self._street_has_number(street)
        ):
            return self._apply_preprocess_shortcircuit(unit, f'PARTIAL:{zip5 or "00000"}')

        if street and re.match(r'(?i)^(rr|rt|route)\s*\d', street) and not self._street_has_number(street):
            return self._apply_preprocess_shortcircuit(unit, f'RR:{zip5 or "00000"}')

        return None

    def _pattern_match_result(
        self,
        spec: Dict[str, Any],
        canonical_address: str,
        zip_code: str,
        parsed: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        colocator = self._expand_colocator(
            spec.get('colocator', ''), canonical_address, zip_code, parsed,
        )
        if '{location}' in colocator:
            m = re.search(r'(.+?)\s+(mall|center|plaza)', canonical_address, re.IGNORECASE)
            if m:
                colocator = colocator.replace('{location}', m.group(1).strip())
        status = 'owners' if spec.get('colocator') else spec.get('status', 'pending')
        return {
            **spec,
            'colocator': colocator,
            'action': spec.get('action', 'match'),
            'status': status,
        }

    def _eval_normalized_subpattern(
        self,
        sub: Dict[str, Any],
        parsed: Dict[str, Any],
        canonical_address: str,
        zip_code: str,
    ) -> bool:
        predicate = sub.get('predicate')
        if predicate == 'city_zip_only':
            street, city, state, zip5 = self._parsed_address_fields(parsed)
            zip5 = zip5 or zip_code
            return self._is_city_only_parsed(street, city, state, zip5, canonical_address)

        if predicate == 'city_state_only':
            street, city, state, zip5 = self._parsed_address_fields(parsed)
            return self._is_city_state_only_parsed(street, city, state, zip5)

        if predicate == 'city_zip_no_state':
            street, city, state, zip5 = self._parsed_address_fields(parsed)
            zip5 = zip5 or zip_code
            return self._is_city_zip_no_state_parsed(street, city, state, zip5)

        if predicate == 'city_only_intl':
            street, city, state, zip5 = self._parsed_address_fields(parsed)
            return self._is_city_only_intl_parsed(street, city, state, zip5)

        if predicate == 'zip_only':
            street, city, state, zip5 = self._parsed_address_fields(parsed)
            zip5 = zip5 or zip_code
            return self._is_zip_only_parsed(street, city, state, zip5, canonical_address)

        if predicate == 'us_territory':
            street, city, state, zip5 = self._parsed_address_fields(parsed)
            return self._is_us_territory_parsed(state)

        if predicate == 'state_zip_mismatch':
            street, city, state, zip5 = self._parsed_address_fields(parsed)
            zip5 = zip5 or zip_code
            return self._is_state_zip_mismatch(state, zip5)

        if predicate == 'foreign_name_only':
            street, city, state, zip5 = self._parsed_address_fields(parsed)
            zip5 = zip5 or zip_code
            return self._is_foreign_name_only_address(
                street, city, state, zip5, canonical_address,
            )

        for field in sub.get('require') or []:
            if not (parsed.get(field) or '').strip():
                return False
        for field in sub.get('absent') or []:
            if (parsed.get(field) or '').strip():
                return False

        fields = sub.get('fields') or {}
        if not predicate and not fields:
            return False
        for field, regex in fields.items():
            if field == 'street':
                val = (parsed.get('street') or parsed.get('address_line1') or '').strip()
            else:
                val = (parsed.get(field) or '').strip()
            if not regex:
                continue
            if not re.search(regex, val, re.IGNORECASE):
                return False
        return True

    def _check_geocoding_patterns(
        self,
        canonical_address: str,
        zip_code: str = "",
        pattern_type: str = 'all',
        parsed: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        safe_names = [
            'privacy_addresses', 'various_addresses', 'incomplete_addresses', 'no_street_number',
            'mail_drop_addresses', 'rural_route', 'exempt_addresses', 'fraud_source_addresses',
            'address_unknown_placeholders', 'mail_collections_centers', 'suite_pmb_box_junk',
            'normalized_preprocess',
        ]
        dangerous_names = ['po_box_addresses', 'co_addresses', 'mall_complexes', 'major_institutions', 'registered_agents_2025']
        patterns = [p for p in self.geocoding_patterns if pattern_type == 'all' or p.get('name') in (safe_names if pattern_type == 'safe' else dangerous_names)]
        for pattern in patterns:
            group_match_on = pattern.get('match_on', 'canonical')
            if 'patterns' in pattern:
                for sub in pattern['patterns']:
                    match_on = sub.get('match_on', group_match_on)
                    if match_on == 'normalized':
                        if not parsed or not self._eval_normalized_subpattern(
                            sub, parsed, canonical_address, zip_code,
                        ):
                            continue
                    elif not re.search(sub.get('regex', ''), canonical_address, re.IGNORECASE):
                        continue
                    return self._pattern_match_result(sub, canonical_address, zip_code, parsed)
            else:
                match_on = pattern.get('match_on', 'canonical')
                if match_on == 'normalized':
                    if not parsed or not self._eval_normalized_subpattern(
                        pattern, parsed, canonical_address, zip_code,
                    ):
                        continue
                    return self._pattern_match_result(pattern, canonical_address, zip_code, parsed)
                regex = pattern.get('regex', '')
                if not re.search(regex, canonical_address, re.IGNORECASE):
                    continue
                return self._pattern_match_result(pattern, canonical_address, zip_code, parsed)
        return None

    def apply_preprocess_batch(
        self, units: List[GeocodingWorkUnit],
    ) -> tuple[List[GeocodingWorkUnit], int]:
        """Run preprocess on work units; persist matches; return rows still needing geocoding."""
        if not units:
            return [], 0
        survivors: List[GeocodingWorkUnit] = []
        match_ctxs: List[PendingDatabaseContext] = []
        matched = 0
        for _flag, output in self._preprocess_handler(units):
            if isinstance(output, ResultWorkUnit):
                matched += 1
                match_ctxs.append(output.data)
            else:
                survivors.append(output)
        if match_ctxs:
            merged = PendingDatabaseContext.merge(match_ctxs)
            if merged.getOperationsCount() > 0:
                merged.save_to_database(self._db_ops, checkpoint=True)
        return survivors, matched
    
    def _update_geocoding_status(self,ctx: PendingDatabaseContext, unit: GeocodingWorkUnit, geocoding_id: str, status: str):
        now = datetime.now().isoformat()
        item = unit.data
        update = {
            'geocoding_id': geocoding_id,
            'last_attempt': now,
            'attempt_count': item.get('attempt_count', 0) + 1,
            'geocoding_status': status,
        }
        ctx.addOperationToDatabase(DatabaseOperation(
            operation_type=DatabaseOperationType.GENERIC_UPDATE,
            data={'table': 'Geocoding', 'updates': [update], 'id_column': 'geocoding_id'}
        ))
        ctx.addOperationToDatabase(DatabaseOperation(
            operation_type=DatabaseOperationType.PROGRESS_UPDATE,
            data={'count': item.get('address_count', 1)}
        ))

    def _update_owner_colocators(self, context: PendingDatabaseContext, geocoding_id: str, colocator: str):
        # Owner fan-out (Charities/Officers/…) is memory-heavy on 16GB hosts during
        # census bulk saves. Geocoding + Addresses.colocator land first; owner
        # backfill can run later from Addresses. Set GEOCODE_SKIP_OWNER_COLOCATORS=0
        # to restore inline owner writes.
        if os.getenv("GEOCODE_SKIP_OWNER_COLOCATORS", "1") == "1":
            return
        result = self.db_ops.execute_query(
            "SELECT address_type, owner_id FROM Addresses WHERE geocoding_id = ?", (geocoding_id,)
        )
        updates = {}
        for row in result.fetchall():
            if not row[1]: continue
            addr_type, owner_id = row[0], row[1]
            
            if addr_type in owner_mapping:
                table, col = owner_mapping[addr_type]
                updates.setdefault(table, []).append({col: str(owner_id), 'colocator': colocator})
        for table, items in updates.items():
            context.addOperationToDatabase(DatabaseOperation(
                operation_type=DatabaseOperationType.GENERIC_UPDATE,
                data={'table': table, 'updates': items, 'id_column': list(items[0].keys())[0]}
            ))

    def _apply_geocoding_only_update(
        self,
        unit: GeocodingWorkUnit,
        status: str,
        *,
        colocator: Optional[str] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        matched: Optional[str] = None,
    ) -> ResultWorkUnit:
        """
        Persist match on Geocoding and always propagate colocator to Addresses + owners.

        (Historically deferred Addresses/owner writes for OOM/ART index pain; that left
        Geocoding.LL full while Addresses.colocator stayed empty. Proper path is always on.)
        """
        item = unit.data
        ctx = PendingDatabaseContext()
        now = datetime.now().isoformat()
        gid = item['geocoding_id']
        rlat = round(lat, 4) if lat is not None else None
        rlon = round(lon, 4) if lon is not None else None
        update: Dict[str, Any] = {
            'geocoding_id': gid,
            'last_attempt': now,
            'attempt_count': item.get('attempt_count', 0) + 1,
            'geocoding_status': status,
            'matched_address': matched or item['canonical_address'],
        }
        if colocator is not None:
            update['colocator'] = colocator
        if rlat is not None:
            update['latitude'] = rlat
        if rlon is not None:
            update['longitude'] = rlon
        ctx.addOperationToDatabase(DatabaseOperation(
            operation_type=DatabaseOperationType.GENERIC_UPDATE,
            data={'table': 'Geocoding', 'updates': [update], 'id_column': 'geocoding_id'}
        ))

        # Always push colocator (and lat/lon) onto every Address sharing this geocoding_id.
        if colocator is not None:
            set_parts = ["colocator = ?"]
            params: list = [colocator]
            if rlat is not None:
                set_parts.append("latitude = COALESCE(latitude, ?)")
                params.append(rlat)
            if rlon is not None:
                set_parts.append("longitude = COALESCE(longitude, ?)")
                params.append(rlon)
            params.append(gid)
            ctx.addOperationToDatabase(DatabaseOperation(
                operation_type=DatabaseOperationType.GENERIC_UPDATE,
                data={
                    'table': 'Addresses',
                    'set_clause': ', '.join(set_parts),
                    'where_clause': (
                        "geocoding_id = ? AND (colocator IS NULL OR TRIM(colocator) = '')"
                    ),
                    'params': params,
                },
            ))
            self._update_owner_colocators(ctx, str(gid), colocator)

        ctx.addOperationToDatabase(DatabaseOperation(
            operation_type=DatabaseOperationType.PROGRESS_UPDATE,
            data={'count': item.get('address_count', 1)}
        ))
        return ResultWorkUnit.result("result", ctx)

    def _apply_successful_geocode(self, unit: GeocodingWorkUnit, lat: float, lon: float, status: str, matched: str) -> ResultWorkUnit:
        if status.startswith('Match:Grok'):
            self.run_stats.grok_match += 1
        elif status not in ('Match:Census', 'Match:Census_Strip'):
            self.run_stats.other_match += 1
        rlat = round(lat, 4)
        rlon = round(lon, 4)
        return self._apply_geocoding_only_update(
            unit, status,
            colocator=f"LL:{rlat}:{rlon}",
            lat=rlat, lon=rlon,
            matched=matched or unit.canonical_address,
        )

    def _apply_po_box_match(self, unit: GeocodingWorkUnit, po_box: str, zip5: str) -> ResultWorkUnit:
        colocator = f"PO:{po_box}:{zip5}"
        lat = lon = None
        coords = (self._us_zip_coords or {}).get(zip5)
        if coords:
            lat, lon = coords
        else:
            try:
                row = self.db_ops.execute_query(
                    "SELECT lat, lon FROM Zips WHERE zip = ? LIMIT 1", (zip5,)
                ).fetchone()
                if row:
                    lat, lon = row[0], row[1]
            except Exception:
                pass
        return self._apply_geocoding_only_update(
            unit, 'Match:PO',
            colocator=colocator,
            lat=lat, lon=lon,
            matched=unit.canonical_address,
        )

    def _preprocess_handler(self, batch: List[GeocodingWorkUnit]) -> List[tuple[bool, GeocodingWorkUnit]]:
        results = []
        now = datetime.now().isoformat()

        for unit in batch:
            addr = unit.canonical_address
            gid = unit.geocoding_id
            parsed = unit.parsed_normalized
            zip_code = (parsed.get('zip') or '')[:5]

            po_box = parsed.get('po_box')
            if not po_box:
                m = re.search(r'(?i)p[0o]\.?\s*o\.?\s*(?:box|drawer)\s*#?\s*(\d+)', addr)
                if not m:
                    m = re.search(r'(?i)\bdrawer\s+([a-z0-9#]+)\b', addr)
                if m:
                    po_box = m.group(1)
            if po_box and zip_code:
                results.append((True, self._apply_po_box_match(unit, str(po_box), zip_code)))
                self.run_stats.preprocess_match += 1
                continue

            if parsed:
                bogus = self._preprocess_bogus_shortcircuit(unit, parsed, zip_code)
                if bogus:
                    results.append(bogus)
                    continue

            pattern = self._check_geocoding_patterns(addr, zip_code, 'safe', parsed=parsed)
            if pattern:
                if pattern['status'] == 'owners':
                    colocator = self._expand_colocator(
                        pattern.get('colocator', ''), addr, zip_code, parsed,
                    )
                    if '{box}' in colocator and po_box:
                        colocator = colocator.replace('{box}', str(po_box))
                    results.append((True, self._apply_geocoding_only_update(
                        unit, 'Match:PatternOwners', colocator=colocator or None,
                        matched=addr,
                    )))
                    self.run_stats.preprocess_match += 1
                    continue
                ctx = PendingDatabaseContext()
                update = {
                    'geocoding_id': gid,
                    'last_attempt': now,
                    'attempt_count': unit.attempt_count + 1,
                    'geocoding_status': pattern.get('status', 'Pattern_Match'),
                }
                if pattern.get('lat') is not None:
                    update['lat'] = pattern['lat']
                    update['lon'] = pattern['lon']
                if pattern.get('formatted_address'):
                    update['matched_address'] = pattern['formatted_address']

                ctx.addOperationToDatabase(DatabaseOperation(
                    operation_type=DatabaseOperationType.GENERIC_UPDATE,
                    data={'table': 'Geocoding', 'updates': [update], 'id_column': 'geocoding_id'}
                ))
                ctx.addOperationToDatabase(DatabaseOperation(
                    operation_type=DatabaseOperationType.PROGRESS_UPDATE,
                    data={'count': unit.address_count}
                ))
                results.append((True, ResultWorkUnit.result("result", ctx)))
                self.run_stats.preprocess_match += 1
                continue

            stripped = self._strip_co_from_address(addr)
            if stripped != addr:
                ctx = PendingDatabaseContext()
                ctx.addOperationToDatabase(DatabaseOperation(
                    operation_type=DatabaseOperationType.GENERIC_UPDATE,
                    data={
                        'table': 'Geocoding',
                        'updates': [{'geocoding_id': gid, 'canonical_address': stripped}],
                        'id_column': 'geocoding_id'
                    }
                ))
                parsed = unit.parsed_normalized
                if parsed and 'street' in parsed and re.match(r'(?i)^c/?o', parsed['street']):
                    stripped_street = self._strip_co_from_address(parsed['street'])
                    if stripped_street != parsed['street']:
                        updated_norm = json.dumps({**parsed, 'street': stripped_street})
                        ctx.addOperationToDatabase(DatabaseOperation(
                            operation_type=DatabaseOperationType.GENERIC_UPDATE,
                            data={
                                'table': 'Geocoding',
                                'updates': [{'geocoding_id': gid, 'normalized_address': updated_norm}],
                                'id_column': 'geocoding_id'
                            }
                        ))
                unit.data['canonical_address'] = stripped
                results.append((False, unit))
            else:
                results.append((False, unit))

        return results
    
    def _format_census_progress(
        self,
        *,
        stage: str,
        batch_size: int,
        matched: int,
        elapsed_s: float,
        context: str = "call",
    ) -> str:
        snap = self.run_stats.census_call_snapshot()
        pl = self.pipeline
        fed = rows_saved = pdcs_saved = in_flight = 0
        queues = ""
        if pl is not None:
            fed = pl.metrics['overall'].get('total', 0)
            rows_saved = pl.metrics['overall'].get('rows_committed', 0)
            pdcs_saved = pl.metrics['overall'].get('success', 0)
            in_flight = max(0, fed - rows_saved)
            queues = pl._format_queue_sizes()

        pct = (100.0 * matched / batch_size) if batch_size else 0.0
        eta_hr = 0.0
        if snap['rate_hr'] > 0 and fed > 0:
            batches_remaining = max(0, (fed + CENSUS_API_BATCH_SIZE - 1) // CENSUS_API_BATCH_SIZE - snap['census_calls'])
            eta_hr = batches_remaining / snap['rate_hr']

        return (
            f"[{self.pipeline_step}] census {context} stage={stage} "
            f"batch={batch_size} matched={matched}/{batch_size} ({pct:.0f}%) "
            f"elapsed={elapsed_s:.1f}s last={snap['last_s']:.1f}s avg={snap['avg_s']:.1f}s max={snap['max_s']:.1f}s "
            f"calls={snap['census_calls']}+{snap['census_strip_calls']}strip "
            f"failures={snap['failures']} addrs_sent={snap['addrs_sent']:,} "
            f"rate={snap['rate_hr']:.1f}/hr "
            f"eta_census≈{eta_hr:.0f}h "
            f"fed={fed:,} rows_saved={rows_saved:,} in_flight≈{in_flight:,} "
            f"pdcs={pdcs_saved:,} queues: {queues}"
        )

    def _log_census_progress(
        self,
        *,
        stage: str = "",
        batch_size: int = 0,
        matched: int = 0,
        elapsed_s: float = 0.0,
        context: str = "heartbeat",
    ) -> None:
        msg = self._format_census_progress(
            stage=stage or "—",
            batch_size=batch_size,
            matched=matched,
            elapsed_s=elapsed_s,
            context=context,
        )
        log_info(msg)
        print(msg, flush=True)

    @classmethod
    def _census_rate_limit_wait(cls) -> None:
        """Serialize Census HTTP calls with a minimum gap (TUI-safe global throttle)."""
        with cls._census_api_lock:
            now = time.monotonic()
            wait_s = CENSUS_API_MIN_DELAY - (now - cls._census_api_last_request)
            if wait_s > 0:
                time.sleep(wait_s)
            cls._census_api_last_request = time.monotonic()

    @staticmethod
    def _is_transient_census_error(exc: BaseException) -> bool:
        if isinstance(exc, (ConnectionResetError, ConnectionError, OSError)):
            return True
        if isinstance(exc, requests.exceptions.RequestException):
            return True
        msg = str(exc).lower()
        return 'connection reset' in msg or 'connection broken' in msg

    def _geocode_census_data_chunk(
        self,
        census_data: List[Dict[str, Any]],
        stage: str,
        depth: int = 0,
    ) -> List[Dict[str, Any]]:
        """Call Census batch API with rate limit, retry+backoff, and binary split on partial responses."""
        n = len(census_data)
        if n == 0:
            return []

        last_exc: Optional[BaseException] = None
        for attempt in range(CENSUS_API_RETRY_ATTEMPTS):
            try:
                self._census_rate_limit_wait()
                return geocode(
                    census_data,
                    return_type='locations',
                    batch_size=CENSUS_API_BATCH_SIZE,
                )
            except KeyError as e:
                # censusbatchgeocoder: response CSV missing a geocoding_id (partial/truncated batch)
                last_exc = e
                break
            except Exception as e:
                if not self._is_transient_census_error(e):
                    raise
                last_exc = e
                if attempt + 1 < CENSUS_API_RETRY_ATTEMPTS:
                    delay = CENSUS_API_RETRY_BACKOFF_BASE * (2 ** attempt)
                    log_warning(
                        f"Census {stage} transient error ({n} addrs), "
                        f"retry {attempt + 2}/{CENSUS_API_RETRY_ATTEMPTS} in {delay:.0f}s: {e}"
                    )
                    time.sleep(delay)
                    continue
                break

        if n <= 1:
            row = census_data[0]
            log_warning(
                f"Census {stage} exhausted retries on 1 address ({last_exc}) — No_Match"
            )
            return [self._census_no_match_row(row)]

        mid = n // 2
        log_warning(
            f"Census {stage} partial/transient failure on {n} addrs ({last_exc}); "
            f"splitting → {mid}+{n - mid} (depth={depth})"
        )
        left = self._geocode_census_data_chunk(census_data[:mid], stage, depth + 1)
        right = self._geocode_census_data_chunk(census_data[mid:], stage, depth + 1)
        return left + right

    @staticmethod
    def _census_no_match_row(row: Dict[str, Any]) -> Dict[str, Any]:
        """Synthetic Census API row when the service omits an id or the chunk is unrecoverable."""
        return {
            **row,
            'geocoded_address': '',
            'is_match': 'No_Match',
            'is_exact': '',
            'returned_address': '',
            'coordinates': '',
            'tiger_line': '',
            'side': '',
            'state_fips': '',
            'county_fips': '',
            'tract': '',
            'block': '',
            'longitude': None,
            'latitude': None,
        }

    def _geocode_census_data(self, census_data: List[Dict[str, Any]], stage: str) -> List[Dict[str, Any]]:
        return self._geocode_census_data_chunk(census_data, stage)

    def _census_handler_raw(self, batch: List[GeocodingWorkUnit]) -> List[tuple[bool, GeocodingWorkUnit]]:
        return self._census_handler(batch, do_strip=False)
        
    def _census_handler_strip(self, batch: List[GeocodingWorkUnit]) -> List[tuple[bool, GeocodingWorkUnit]]:
        return self._census_handler(batch, do_strip=True)

    def _census_handler(self, batch: List[GeocodingWorkUnit], do_strip=False) -> List[tuple[bool, GeocodingWorkUnit]]:
        results = []
        census_data = []

        for unit in batch:
            parsed = unit.parsed_normalized.copy()
            source_addr = unit.canonical_address
            if do_strip:
                source_addr = self._strip_for_census_strip(unit.canonical_address)
                if parsed.get('street'):
                    parsed['street'] = self._strip_for_census_strip(parsed['street'])
            if not parsed:
                log_warning(f"Census fallback to canonical {unit.geocoding_id}")
                parts = source_addr.split(', ')
                street = ', '.join(parts[:-3]) if len(parts) > 3 else source_addr
                city = parts[-3] if len(parts) > 2 else ''
                state = parts[-2] if len(parts) > 1 else ''
                zip_code = parts[-1] if parts else ''
                parsed = {'street': street, 'city': city, 'state': state, 'zip': zip_code}
            elif do_strip and (not parsed.get('street') or re.match(r'(?i)^c/?o', parsed.get('street', ''))):
                parts = source_addr.split(', ')
                street = ', '.join(parts[:-3]) if len(parts) > 3 else source_addr
                parsed['street'] = street
                if not parsed.get('city') and len(parts) > 2:
                    parsed['city'] = parts[-3]
                if not parsed.get('state') and len(parts) > 1:
                    parsed['state'] = parts[-2]
                if not parsed.get('zip') and parts:
                    parsed['zip'] = parts[-1]

            census_entry = {
                'id': unit.geocoding_id,
                'address': parsed.get('street', ''),
                'city': parsed.get('city', ''),
                'state': parsed.get('state', ''),
                'zipcode': parsed.get('zip', '')
            }
            census_data.append(census_entry)

        stage = "census_strip" if do_strip else "census"
        t0 = time.perf_counter()
        try:
            geocoded_results = self._geocode_census_data(census_data, stage)
            elapsed_s = time.perf_counter() - t0
            if len(geocoded_results) != len(batch):
                raise RuntimeError(
                    f"Census {stage} result count mismatch: {len(geocoded_results)} != {len(batch)}"
                )
            n_match = 0
            for res, unit in zip(geocoded_results, batch):
                is_match = (res.get('is_match') or '').strip()
                lat = res.get('latitude')
                if is_match and is_match != 'No_Match' and lat is not None:
                    lon = res.get('longitude')
                    matched = res.get('returned_address') or res.get('matched_address') or ''
                    status = "Match:Census_Strip" if do_strip else "Match:Census"
                    result_unit = self._apply_successful_geocode(unit, lat, lon, status, matched)
                    results.append((True, result_unit))
                    n_match += 1
                    if do_strip:
                        self.run_stats.census_strip_match += 1
                    else:
                        self.run_stats.census_match += 1
                else:
                    unit.data['attempt_count'] = unit.attempt_count + 1
                    results.append((False, unit))
            self.run_stats.record_census_call(
                stage=stage,
                batch_size=len(batch),
                elapsed_s=elapsed_s,
                matched=n_match,
                failed=False,
            )
            self._log_census_progress(
                stage=stage,
                batch_size=len(batch),
                matched=n_match,
                elapsed_s=elapsed_s,
                context="call",
            )
        except Exception as e:
            elapsed_s = time.perf_counter() - t0
            self.run_stats.record_census_call(
                stage=stage,
                batch_size=len(batch),
                elapsed_s=elapsed_s,
                matched=0,
                failed=True,
            )
            log_error(f"Census {stage} failed after {elapsed_s:.1f}s: {e}")
            self._log_census_progress(
                stage=stage,
                batch_size=len(batch),
                matched=0,
                elapsed_s=elapsed_s,
                context="call_failed",
            )
            for unit in batch:
                unit.data['attempt_count'] = unit.attempt_count + 1
                results.append((False, unit))
        return results
    
    def safe_parse(self, raw: str):
        try:
            return BatchGeocodeOutput.model_validate_json(raw)
        except ValidationError as e:
            print(f"Bad Json from grok,{raw}")
            raise  # or handle gracefully depending on your needs

    @staticmethod
    def grok_geocode_model() -> str:
        return os.getenv("GROK_GEOCODE_MODEL", GROK_GEOCODE_MODEL_DEFAULT)

    @staticmethod
    def grok_geocode_batch_model() -> str:
        from constants import GEOCODING_GROK_BATCH_MODEL
        return os.getenv("GROK_GEOCODE_BATCH_MODEL", GEOCODING_GROK_BATCH_MODEL)

    @classmethod
    def grok_result_update_fields(
        cls,
        unit: GeocodingWorkUnit,
        res_item: Optional[GeocodeResult],
        *,
        now: str,
    ) -> Dict[str, Any]:
        """Build Geocoding row fields from a Grok GeocodeResult (None → grok:UNKN)."""
        base: Dict[str, Any] = {
            "geocoding_id": unit.geocoding_id,
            "last_attempt": now,
            "attempt_count": unit.attempt_count + 1,
        }
        if res_item and res_item.lat is not None and res_item.long is not None:
            rlat = round(res_item.lat, 4)
            rlon = round(res_item.long, 4)
            return {
                **base,
                "geocoding_status": "Match:Grok-4",
                "matched_address": res_item.matched_address or unit.canonical_address,
                "latitude": rlat,
                "longitude": rlon,
                "colocator": f"LL:{rlat}:{rlon}",
            }
        code = res_item.failure_code if res_item else None
        status = grok_failure_status(code)
        note = (res_item.reason if res_item and res_item.reason else status)
        return {
            **base,
            "geocoding_status": status,
            "matched_address": note[:500],
            "latitude": None,
            "longitude": None,
            "colocator": status,
        }

    @classmethod
    def build_grok_geocode_messages(cls, units: List[GeocodingWorkUnit]) -> tuple[str, str]:
        codes = ", ".join(sorted(GROK_FAILURE_CODES))
        prompt_lines = []
        for unit in units:
            canon = unit.canonical_address.strip()
            norm_str = json.dumps(unit.parsed_normalized, separators=(',', ':')) if unit.parsed_normalized else ""
            prompt_lines.append(f"ID: {unit.geocoding_id} | Raw: \"{canon}\" | Parsed JSON: {norm_str}")
        min_conf = GEOCODING_GROK_MIN_CONFIDENCE_PCT
        system_prompt = f"""You are an expert geocoder for messy IRS 990 nonprofit addresses.
These rows already failed Census, Photon, and paid geocoders — your job is to geocode them when
you can, and classify only when you truly cannot pick a location.
Ignore C/O, Attn:, See Statement, personal names unless tied to a known org HQ.
Use known entity HQs when obvious (e.g. First Citizens → Raleigh area).

You have NO external geocoder API in this task. That is intentional. Use your geographic
knowledge of US streets, cities, ZIP regions, campuses, and well-known buildings. Never
refuse because you "lack a tool," "need an external geocoder," "prior APIs failed," or are
"genuinely unsure without lookup." Those are invalid reasons.

Geocoding bar: return lat/long when ≥{min_conf}% confident in ONE best US location.
Prior pipeline failure is not a reason to refuse — messy casing (9Th), rural routes, highways,
campus buildings, and suite/room/building suffixes are common; geocode the building or street
entrance when that is the clear best match (e.g. "520 S 9th … Ellis Library, Columbia, MO" →
University of Missouri Ellis Library area). Campus/university building names with
street+city+state+ZIP should be geocoded, not classified as UNKN.

COMPLETE US STREET RULE (mandatory):
If the address has a street (with number or clear street name), US city, 2-letter state, and
5-digit ZIP that together form one plausible US location, you MUST either:
  (a) return lat/long for the best single location, OR
  (b) failure_code=AMBIG if two+ equally good street matches exist, OR
  (c) failure_code=VAGUE only if the street is incomplete (no number/name usable).
You MUST NOT use failure_code=UNKN for a complete US street address. Approximate the
block/building from knowledge when exact suite/floor is unknown — suite/floor rarely needs
its own coordinate.

When you cannot geocode, you MUST set failure_code (not just null coords):
- NOTA: not a postal address (org name only, "see statement", narrative, department label)
- VAGUE: incomplete US address (city/state only, missing street number or name)
- AMBIG: multiple equally plausible US street matches — cannot pick one (not "prior APIs failed")
- REDACT: intentionally redacted or privacy placeholder
- UNKN: ONLY foreign/non-US, unparseable garbage with no US place, or no plausible US location.
  NEVER for normal complete US streets. NEVER because tools/APIs are unavailable.

Classify precisely — failure labels feed pattern-rule mining to auto-handle similar addresses later."""
        user_prompt = f"""Analyze these addresses — geocode when possible, otherwise classify the failure:

{'\n'.join(prompt_lines)}

CRITICAL: For each result, set 'id' to the EXACT geocoding_id UUID shown at the start of the line.

For each address provide:
- id: geocoding_id UUID (required, exact match)
- lat / long: floats when ≥{min_conf}% confident in one best US location; otherwise null
- matched_address: best full geocoded address when matched; otherwise null
- failure_code: REQUIRED when lat/long are null — one of: {codes}
- reason: one short sentence explaining the match or why this failure_code applies
  (Do not cite missing tools, missing APIs, or "prior geocoders failed" as the reason.)

Output ONLY the complete valid JSON object matching the schema. Include ALL addresses."""
        return system_prompt, user_prompt

    @classmethod
    def build_grok_geocode_request_body(cls, units: List[GeocodingWorkUnit]) -> dict:
        system_prompt, user_prompt = cls.build_grok_geocode_messages(units)
        schema = BatchGeocodeOutput.model_json_schema()
        return {
            "model": cls.grok_geocode_model(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "batch_geocode", "strict": False, "schema": schema},
            },
            "temperature": 0.0,
            "max_tokens": 16384,
        }

    def _grok_handler(self, batch: List[GeocodingWorkUnit]) -> List[tuple[bool, GeocodingWorkUnit]]:
        if not batch:
            return []

        client = OpenAI(api_key=os.getenv("X_API_KEY"), base_url="https://api.x.ai/v1")
        items = batch
        body = self.build_grok_geocode_request_body(items)
        grok_model = body["model"]
        raw = None
        try:
            response = client.chat.completions.create(**body, timeout=120)
            raw = (response.choices[0].message.content or "").strip()
            parsed = self.safe_parse(raw)

            results = []
            parsed_dict = {res.id: res for res in parsed.results}  # map by UUID
            n_match = 0
            now = datetime.now().isoformat()
            for unit in items:
                res_item = parsed_dict.get(unit.geocoding_id)
                if res_item and res_item.lat is not None and res_item.long is not None:
                    result_unit = self._apply_successful_geocode(
                        unit, res_item.lat, res_item.long, "Match:Grok-4", res_item.matched_address or unit.canonical_address
                    )
                    results.append((True, result_unit))
                    n_match += 1
                else:
                    fields = self.grok_result_update_fields(unit, res_item, now=now)
                    self.run_stats.grok_fail += 1
                    result_unit = self._apply_geocoding_only_update(
                        unit, fields["geocoding_status"],
                        colocator=fields.get("colocator"),
                        lat=fields.get("latitude"),
                        lon=fields.get("longitude"),
                        matched=fields.get("matched_address"),
                    )
                    results.append((True, result_unit))
            print(
                f"[{self.pipeline_step}] grok batch={len(batch)} matched={n_match}/{len(batch)} model={grok_model}",
                flush=True,
            )
            return results
        except Exception as e:
            if raw:
                log_error(f"Grok failed: {e} | response={raw[:500]}")
            else:
                log_error(f"Grok failed: {e}")
            return [(False, unit) for unit in batch]

    def _geopy_stage_handler(
        self, batch: List[GeocodingWorkUnit], stage: str, geocoder_key: str, source_name: str,
        *, prefer_structured: bool,
    ) -> List[tuple[bool, GeocodingWorkUnit]]:
        results = [
            self._geocode_with_geopy(u, geocoder_key, source_name, prefer_structured=prefer_structured)
            for u in batch
        ]
        n_match = sum(1 for ok, _ in results if ok)
        print(
            f"[{self.pipeline_step}] {stage} batch={len(batch)} matched={n_match}/{len(batch)}",
            flush=True,
        )
        return results

    def _photon_handler(self, batch: List[GeocodingWorkUnit]) -> List[tuple[bool, GeocodingWorkUnit]]:
        return self._geopy_stage_handler(batch, "photon", "photon", "Photon", prefer_structured=False)

    def _nominatim_handler(self, batch: List[GeocodingWorkUnit]) -> List[tuple[bool, GeocodingWorkUnit]]:
        return self._geopy_stage_handler(batch, "nominatim", "nominatim", "Nominatim", prefer_structured=True)

    def _geocode_maps_co_handler(self, batch: List[GeocodingWorkUnit]) -> List[tuple[bool, GeocodingWorkUnit]]:
        return self._geopy_stage_handler(
            batch, "geocode_maps_co", "geocode_maps_co", "GeocodeMapsCo", prefer_structured=True,
        )

    def _opencage_handler(self, batch: List[GeocodingWorkUnit]) -> List[tuple[bool, GeocodingWorkUnit]]:
        return self._geopy_stage_handler(batch, "opencage", "opencage", "OpenCage", prefer_structured=False)

    def _librestreet_handler(self, batch: List[GeocodingWorkUnit]) -> List[tuple[bool, GeocodingWorkUnit]]:
        if GeocodingAPIProcessor._librestreet_disabled:
            return [(False, unit) for unit in batch]
        results = []
        for unit in batch:
            parsed = unit.parsed_normalized
            address_str = unit.canonical_address
            if parsed:
                street = parsed.get('street', '')
                city = parsed.get('city', '')
                state = parsed.get('state', '')
                zip_code = parsed.get('zip', '')
                constructed = f"{street}, {city}, {state} {zip_code}".strip(', ')
                if constructed: address_str = constructed

            try:
                url = f"https://librestreet.org/search.php?q={quote(address_str)}&format=json"
                r = requests.get(url, timeout=10)
                data = r.json()
                if data:
                    loc = data[0]
                    lat = float(loc['lat'])
                    lon = float(loc['lon'])
                    matched = loc['display_name']
                    result_unit = self._apply_successful_geocode(unit, lat, lon, "Match:LibreStreet", matched)
                    results.append((True, result_unit))
                    continue
            except Exception as e:
                log_warning(f"LibreStreet failed {unit.geocoding_id}: {e}")
            results.append((False, unit))
        return results

    def _pending_api_fail_handler(self, batch: List[GeocodingWorkUnit]) -> List[tuple[bool, GeocodingWorkUnit]]:
        self.run_stats.pending_api_queued += len(batch)
        log_info(f"Pending API handler: {len(batch)} addresses queued for geolocate_api")
        print(f"[{self.pipeline_step}] pending_api batch={len(batch)}", flush=True)
        ctx = PendingDatabaseContext()
        now = datetime.now().isoformat()
        for unit in batch:
            gid = unit.geocoding_id
            ctx.addOperationToDatabase(DatabaseOperation(
                operation_type=DatabaseOperationType.GENERIC_UPDATE,
                data={
                    'table': 'Geocoding',
                    'updates': [{
                        'geocoding_id': gid,
                        'geocoding_status': GEOCODING_STATUS_PENDING_API,
                        'last_attempt': now,
                        'attempt_count': unit.attempt_count + 1,
                        'matched_address': None,
                    }],
                    'id_column': 'geocoding_id'
                }
            ))
            ctx.addOperationToDatabase(DatabaseOperation(
                operation_type=DatabaseOperationType.PROGRESS_UPDATE,
                data={'count': unit.address_count}
            ))
        result = ResultWorkUnit(ctx, stage='fail')
        return [(True, result)]

    def _grok_pending_fail_handler(self, batch: List[GeocodingWorkUnit]) -> List[tuple[bool, GeocodingWorkUnit]]:
        self.run_stats.grok_queued += len(batch)
        log_info(f"Grok pending handler: {len(batch)} addresses queued for geolocate_grok")
        print(f"[{self.pipeline_step}] grok_pending batch={len(batch)}", flush=True)
        ctx = PendingDatabaseContext()
        now = datetime.now().isoformat()
        for unit in batch:
            gid = unit.geocoding_id
            ctx.addOperationToDatabase(DatabaseOperation(
                operation_type=DatabaseOperationType.GENERIC_UPDATE,
                data={
                    'table': 'Geocoding',
                    'updates': [{
                        'geocoding_id': gid,
                        'geocoding_status': 'grok_pending',
                        'last_attempt': now,
                        'attempt_count': unit.attempt_count + 1,
                        'matched_address': None,
                    }],
                    'id_column': 'geocoding_id'
                }
            ))
            ctx.addOperationToDatabase(DatabaseOperation(
                operation_type=DatabaseOperationType.PROGRESS_UPDATE,
                data={'count': unit.address_count}
            ))
        result = ResultWorkUnit(ctx, stage='fail')
        return [(True, result)]

    def _grok_final_fail_handler(self, batch: List[GeocodingWorkUnit]) -> List[tuple[bool, GeocodingWorkUnit]]:
        self.run_stats.grok_fail += len(batch)
        log_info(f"Grok final fail: {len(batch)} addresses exhausted Grok stage")
        print(f"[geolocate_grok] final_fail batch={len(batch)}", flush=True)
        ctx = PendingDatabaseContext()
        now = datetime.now().isoformat()
        for unit in batch:
            gid = unit.geocoding_id
            ctx.addOperationToDatabase(DatabaseOperation(
                operation_type=DatabaseOperationType.GENERIC_UPDATE,
                data={
                    'table': 'Geocoding',
                    'updates': [{
                        'geocoding_id': gid,
                        'geocoding_status': 'No_Match',
                        'last_attempt': now,
                        'attempt_count': unit.attempt_count + 1,
                        'matched_address': 'Failed all stages',
                    }],
                    'id_column': 'geocoding_id'
                }
            ))
            ctx.addOperationToDatabase(DatabaseOperation(
                operation_type=DatabaseOperationType.PROGRESS_UPDATE,
                data={'count': unit.address_count}
            ))
        result = ResultWorkUnit(ctx, stage='fail')
        return [(True, result)]

    _WORK_ORDER = "geocoding_id"

    @staticmethod
    def _normalized_po_box(normalized_address: Any) -> str:
        if not normalized_address:
            return ""
        try:
            data = json.loads(normalized_address) if isinstance(normalized_address, str) else normalized_address
            return str((data or {}).get("po_box") or "").strip()
        except (json.JSONDecodeError, TypeError, AttributeError):
            return ""

    def _rows_to_work_units(self, rows) -> Tuple[List[GeocodingWorkUnit], Optional[str]]:
        work_units = []
        new_pk = None
        for row in rows:
            data = {
                'geocoding_id': row[0],
                'normalized_address': row[1],
                'attempt_count': row[2],
                'canonical_address': row[3],
                'address_count': row[4] or 0,
                'geocoding_status': row[5],
            }
            work_units.append(GeocodingWorkUnit.work_item("feed", data))
            new_pk = row[0]
        return work_units, new_pk

    def _fetch_work_batch(
        self,
        where_parts: List[str],
        params: List[Any],
        *,
        order_by: Optional[str] = None,
        label: str = "work",
    ) -> Tuple[List[GeocodingWorkUnit], Optional[str]]:
        order_clause = order_by or self._WORK_ORDER
        where_clause = " AND ".join(where_parts)
        query = f"""
            SELECT geocoding_id, normalized_address, attempt_count, canonical_address, address_count, geocoding_status
            FROM Geocoding
            WHERE {where_clause}
            ORDER BY {order_clause}
            LIMIT {self.batch_size}
        """
        result = self.db_ops.execute_query(query, tuple(params))
        rows = result.fetchall()
        if rows:
            po_ct = sum(
                1 for r in rows
                if self._normalized_po_box(r[1]) not in ('', '0')
            )
            log_debug(f"get_{label}_batch fetched {len(rows)} rows ({po_ct} with po_box flag)")
        return self._rows_to_work_units(rows)

    def get_work_batch(self, last_pk: Optional[str] = None) -> Tuple[List[GeocodingWorkUnit], Optional[str]]:
        log_debug(f"get_work_batch last_pk={last_pk} batch_size={self.batch_size}")
        where_parts = ["geocoding_status IS NULL OR geocoding_status IN ('pending', 'owners')"]
        params: List[Any] = []
        if last_pk is not None:
            where_parts.append("geocoding_id > ?")
            params.append(last_pk)
        return self._fetch_work_batch(where_parts, params, label="work")

    def get_api_work_batch(self, last_pk: Optional[str] = None) -> Tuple[List[GeocodingWorkUnit], Optional[str]]:
        log_debug(f"get_api_work_batch last_pk={last_pk} batch_size={self.batch_size}")
        where_parts = ["geocoding_status = ?"]
        params: List[Any] = [GEOCODING_STATUS_PENDING_API]
        if last_pk is not None:
            where_parts.append("geocoding_id > ?")
            params.append(last_pk)
        return self._fetch_work_batch(
            where_parts,
            params,
            order_by="address_count DESC NULLS LAST, geocoding_id",
            label="api",
        )

    def get_grok_work_batch(self, last_pk: Optional[str] = None) -> Tuple[List[GeocodingWorkUnit], Optional[str]]:
        log_debug(f"get_grok_work_batch last_pk={last_pk} batch_size={self.batch_size}")
        where_parts = ["geocoding_status = 'grok_pending'"]
        params: list = []
        if last_pk is not None:
            where_parts.append("geocoding_id > ?")
            params.append(last_pk)
        query = f"""
            SELECT geocoding_id, normalized_address, attempt_count, canonical_address, address_count, geocoding_status
            FROM Geocoding
            WHERE {' AND '.join(where_parts)}
            ORDER BY address_count DESC NULLS LAST, geocoding_id
            LIMIT {self.batch_size}
        """
        rows = self.db_ops.execute_query(query, tuple(params)).fetchall()
        if rows:
            log_debug(f"get_grok_work_batch fetched {len(rows)} grok_pending rows")
        work_units, new_pk = self._rows_to_work_units(rows)
        return work_units, new_pk

    def get_grok_total_work(self) -> int:
        result = self.db_ops.execute_query(
            "SELECT COUNT(*) FROM Geocoding WHERE geocoding_status = 'grok_pending'"
        )
        return int(result.fetchone()[0])
    
    def get_total_work(self) -> int:
        return self._count_geocoding_where(
            "geocoding_status IS NULL OR geocoding_status IN ('pending', 'owners')"
        )

    def get_api_total_work(self) -> int:
        return self._count_geocoding_where("geocoding_status = ?", (GEOCODING_STATUS_PENDING_API,))

    def _count_geocoding_where(self, where_clause: str, params: tuple = ()) -> int:
        result = self.db_ops.execute_query(
            f"SELECT COUNT(*) FROM Geocoding WHERE {where_clause}",
            params,
        )
        return int(result.fetchone()[0])

    def get_work_count(self, max_files=None) -> int:
        base_query = """
            SELECT COUNT(*)
            FROM Geocoding
            WHERE geocoding_status IS NULL OR geocoding_status IN ('pending', 'owners')
        """
        if max_files is None:
            result = self.db_ops.execute_query(base_query)
            return int(result.fetchone()[0])
        query = f"""
            SELECT COUNT(*)
            FROM (
                SELECT 1
                FROM Geocoding
                WHERE geocoding_status IS NULL OR geocoding_status IN ('pending', 'owners')
                ORDER BY {self._WORK_ORDER}
                LIMIT {max_files}
            ) sub
        """
        result = self.db_ops.execute_query(query)
        return result.fetchone()[0]

    def get_progress_config(self, max_files=None):
        total = self.get_work_count(max_files=(max_files or global_config.max_files))
        return total, "addresses", "Geocoding addresses"

    def _bulk_resolve_pending_po_boxes(self) -> int:
        """Resolve PO rows that should never hit census — normalized po_box flag only."""
        pending_po = self.db_ops.execute_query("""
            SELECT COUNT(*) FROM Geocoding
            WHERE geocoding_status IN ('pending', 'owners')
              AND LEFT(COALESCE(json_extract_string(normalized_address, '$.zip'), ''), 5) != ''
              AND COALESCE(json_extract_string(normalized_address, '$.po_box'), '') NOT IN ('', '0')
        """).fetchone()[0]
        if not pending_po:
            return 0
        log_info(f"Bulk-resolving {pending_po:,} pending PO box Geocoding rows → Match:PO")
        print(f"[geolocate_census] bulk PO resolve: {pending_po:,} rows → Match:PO", flush=True)
        self.db_ops.execute_query("""
            UPDATE Geocoding
            SET
                geocoding_status = 'Match:PO',
                colocator = CASE
                    WHEN json_extract_string(normalized_address, '$.po_box') = 'POBOX'
                        THEN 'PO:BOX:' || LEFT(json_extract_string(normalized_address, '$.zip'), 5)
                    ELSE 'PO:' || json_extract_string(normalized_address, '$.po_box')
                         || ':' || LEFT(json_extract_string(normalized_address, '$.zip'), 5)
                END,
                matched_address = canonical_address,
                last_attempt = CURRENT_TIMESTAMP
            WHERE geocoding_status IN ('pending', 'owners')
              AND LEFT(COALESCE(json_extract_string(normalized_address, '$.zip'), ''), 5) != ''
              AND COALESCE(json_extract_string(normalized_address, '$.po_box'), '') NOT IN ('', '0')
        """)
        return int(pending_po)

    def _prepare_geocode_run(self, *, census_resume: bool = False) -> None:
        if census_resume:
            log_info("Census resume: skipping address_count, archive, and PO prep")
            print("[geolocate_census] resume: skipping prep (address_count, archive, PO)", flush=True)
            return
        self.setup_address_counts()
        archive_done = self.db_ops.execute_query(
            "SELECT EXISTS(SELECT 1 FROM Geocoding WHERE geocoding_status = 'Match:Archive' LIMIT 1)"
        ).fetchone()[0]
        if archive_done:
            log_info("Skipping archive re-apply (Match:Archive already present)")
        else:
            log_info("Applying geocode archive cache...")
            self.apply_geocode_archive_full_propagation()
        resolved = self._bulk_resolve_pending_po_boxes()
        if resolved:
            log_info(f"Bulk PO resolve complete: {resolved:,} rows")

    def process_census_pending_records(self, max_files=None) -> int:
        self.run_stats = GeocodeRunStats()
        self.pipeline_step = "geolocate_census"
        self.pipeline = None
        self._prepare_geocode_run(census_resume=True)
        pending = self.get_work_count(max_files=max_files)
        self.run_stats.census_pending_total = pending
        log_info(f"Starting geolocate_census for {pending:,} pending addresses (max_files={max_files})")
        print(
            f"[geolocate_census] Starting census bulk pass: {pending:,} pending (max_files={max_files})",
            flush=True,
        )
        stop_heartbeat = threading.Event()

        def _census_heartbeat():
            while not stop_heartbeat.wait(120):
                self._log_census_progress(context="heartbeat")

        heartbeat = threading.Thread(
            target=_census_heartbeat, daemon=True, name="census_progress_heartbeat",
        )
        heartbeat.start()
        try:
            self.pipeline = self.census_pipeline
            processed = self.census_pipeline.run_with_provider(self, max_items=max_files) or 0
        finally:
            stop_heartbeat.set()
            heartbeat.join(timeout=1.0)
        self.run_stats.fed = processed
        self._log_census_progress(context="complete")
        self.run_stats.log_summary(step="geolocate_census")
        print(f"Geolocate_census complete: {processed} records processed")
        return processed

    def process_api_pending_records(self, max_files=None) -> int:
        self.run_stats = GeocodeRunStats()
        self.pipeline_step = "geolocate_api"
        self.pipeline = self.api_pipeline

        class _ApiProvider:
            def __init__(self, proc: "GeocodingAPIProcessor"):
                self._proc = proc

            def get_work_batch(self, last_pk):
                return self._proc.get_api_work_batch(last_pk)

            def get_total_work(self):
                return self._proc.get_api_total_work()

        pending = self.get_api_total_work()
        if max_files is not None:
            pending = min(pending, max_files)
        log_info(f"Starting geolocate_api for {pending:,} pending_api rows (max_files={max_files})")
        print(
            f"[geolocate_api] Starting API tail pass: {pending:,} pending_api (max_files={max_files})",
            flush=True,
        )
        provider = _ApiProvider(self)
        processed = self.api_pipeline.run_with_provider(provider, max_items=max_files) or 0
        self.run_stats.fed = processed
        self.run_stats.log_summary(step="geolocate_api")
        print(f"Geolocate_api complete: {processed} records processed")
        return processed

    def export_census_failures_for_patterns(
        self, output_file: str = CENSUS_FAILURES_EXPORT_FILE,
    ) -> int:
        """Export pending_api rows after census pass for pattern-rule mining."""
        output_path = os.path.join(global_config.final_dir, output_file)
        rows = self.db_ops.execute_query("""
            SELECT
                canonical_address,
                matched_address,
                normalized_address,
                address_count,
                geocoding_id
            FROM Geocoding
            WHERE geocoding_status = ?
            ORDER BY address_count DESC NULLS LAST, canonical_address
        """, (GEOCODING_STATUS_PENDING_API,)).fetchall()

        os.makedirs(global_config.final_dir or ".", exist_ok=True)
        tmp_path = output_path + ".tmp"
        try:
            with gzip.open(tmp_path, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
                writer.writerow([
                    "canonical_address",
                    "last_matched_address",
                    "address_count",
                    "normalized_address",
                    "geocoding_id",
                ])
                for canon, matched, norm, count, gid in rows:
                    writer.writerow([
                        canon or "",
                        matched or "",
                        count or 0,
                        norm or "",
                        gid or "",
                    ])
            shutil.move(tmp_path, output_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        log_info(f"Exported {len(rows):,} pending_api rows → {output_path}")
        print(
            f"[geolocate_census] exported {len(rows):,} pending_api failures → {output_path}",
            flush=True,
        )
        return len(rows)

    def process_pending_geocoding_records(self, max_files=None, progress_bar=None) -> int:
        """Legacy monolithic path — runs census bulk pass then API tail pass."""
        log_warning("process_pending_geocoding_records is deprecated; use census + api passes")
        census = self.process_census_pending_records(max_files=max_files)
        self.export_census_failures_for_patterns()
        api = self.process_api_pending_records(max_files=max_files)
        return census + api

    def process_grok_pending_realtime(self, max_files=None) -> int:
        """Realtime Grok pipeline — prefer geolocate_grok batch step for bulk."""
        self.run_stats = GeocodeRunStats()
        self.pipeline_step = "geolocate_grok"
        pending = self.get_grok_total_work()
        if max_files is not None:
            pending = min(pending, max_files)
        log_info(f"Starting geolocate_grok realtime pipeline for {pending:,} grok_pending rows")
        print(f"[geolocate_grok] Starting realtime pipeline: {pending:,} grok_pending", flush=True)

        class _GrokProvider:
            def __init__(self, proc: "GeocodingAPIProcessor"):
                self._proc = proc

            def get_work_batch(self, last_pk):
                return self._proc.get_grok_work_batch(last_pk)

            def get_total_work(self):
                return self._proc.get_grok_total_work()

        provider = _GrokProvider(self)
        processed = self.grok_pipeline.run_with_provider(provider, max_items=max_files) or 0
        self.run_stats.fed = processed
        self.run_stats.log_summary(step="geolocate_grok")
        print(f"Geolocate_grok realtime complete: {processed} records processed")
        return processed

    def setup_address_counts(self):
        stale_count = self.db_ops.execute_query(
            "SELECT COUNT(*) FROM Geocoding WHERE address_count IS NULL OR address_count = 0"
        ).fetchone()[0]
        if not stale_count:
            log_info("Skipping address_count backfill (all populated)")
            return
        log_info(f"Backfilling address_count for {stale_count:,} Geocoding rows")
        update_query = """
            UPDATE Geocoding
            SET address_count = (
                SELECT COUNT(*)
                FROM Addresses
                WHERE Addresses.geocoding_id = Geocoding.geocoding_id
            )
            WHERE address_count IS NULL OR address_count = 0
        """
        self.db_ops.execute_query(update_query)
            
    def apply_geocode_archive_full_propagation(self, cache_file: str = "geocode_archive_distinct.tsv.gz") -> int:
        """Load the pre-geocoded TSV.gz archive and perform FULL owner propagation using chunked processing to avoid memory exhaustion.

        Streams the archive via gzip + csv in 100000-row chunks, delegates to _apply_chunk_updates for each,
        and guarantees atomicity via a single outer transaction.
        """
        log_info(f"Applying full geocode archive cache + owner propagation from {cache_file} (chunked)...")
        actual_cache_file = os.path.join(global_config.final_dir, cache_file)

        with self.db_ops.acquire_write_conn() as conn:
            # === QUICK IDEMPOTENCY CHECK ===
            already_done = conn.execute("""
                SELECT COUNT(*) 
                FROM Geocoding 
                WHERE geocoding_status = 'Match:Archive'
                LIMIT 1
            """).fetchone()[0]

            if already_done > 0:
                log_info("Archive cache already applied (found 'Match:Archive' status). Skipping all work.")
                return 0
            conn.execute("BEGIN TRANSACTION")

            try:
                log_info(f"Streaming geocode cache from {actual_cache_file}...")
                chunk_size = 100000
                total_updated_geocoding = 0
                total_updated_addresses = 0
                chunk_num = 0
                with gzip.open(actual_cache_file, 'rt', encoding='utf-8', errors='replace') as f:
                    reader = csv.DictReader(f, delimiter='\t')
                    chunk = []
                    for row in reader:
                        if 'canonical_address' not in row or 'colocator' not in row:
                            continue
                        chunk.append((row['canonical_address'], row['colocator']))
                        if len(chunk) >= chunk_size:
                            chunk_num += 1
                            g_count, a_count = self._apply_chunk_updates(chunk, conn, chunk_num)
                            total_updated_geocoding += g_count
                            total_updated_addresses += a_count
                            chunk = []
                    if chunk:
                        chunk_num += 1
                        g_count, a_count = self._apply_chunk_updates(chunk, conn, chunk_num)
                        total_updated_geocoding += g_count
                        total_updated_addresses += a_count
                # Final cleanup and analyze
                for table in ['Geocoding', 'Addresses', 'Charities', 'Grants', 'Officers', 'Contractors', 'PoliticalContributions']:
                    log_info(f"Running VACUUM ANALYZE on {table}...")
                    conn.execute(f"VACUUM ANALYZE {table};")
                    conn.commit()
                log_info(f"Full archive cache + owner propagation complete (chunked)")
                log_info(f"   Updated {total_updated_geocoding:,} Geocoding records")
                log_info(f"   Updated {total_updated_addresses:,} Addresses with colocator")
                log_info(f"   Processed across {chunk_num} chunks")
                return total_updated_geocoding
            except Exception as e:
                conn.rollback()
                log_error(f"Full cache propagation failed: {e}", exc_info=True)
                raise

    def _apply_chunk_updates(self, chunk: list, conn, chunk_num: int) -> tuple[int, int]:
        """Process one chunk of (canonical_address, colocator) tuples from the archive.

        Stages data in a temporary DuckDB table, runs scoped update_map and owner propagations,
        then cleans up. Returns (updated_geocoding_count, updated_addresses_count).
        """
        if not chunk:
            return 0, 0
        log_info(f"Processing chunk {chunk_num} with {len(chunk):,} addresses...")
        # Robust staging using batched VALUES (avoids executemany issues on some DuckDB connections)
        conn.execute("""
            CREATE OR REPLACE TEMP TABLE chunk_cache (
                canonical_address VARCHAR,
                colocator VARCHAR
            )
        """)
        # Sanitize for SQL and batch to keep each INSERT query small
        safe_chunk = []
        for ca, co in chunk:
            ca = str(ca or "").replace("'", "''")
            co = str(co or "").replace("'", "''")
            safe_chunk.append((ca, co))
        batch_size = 2000  # keeps each VALUES clause well under parser limits
        for i in range(0, len(safe_chunk), batch_size):
            sub = safe_chunk[i : i + batch_size]
            values_clause = ", ".join(f"('{ca}', '{co}')" for ca, co in sub)
            conn.execute(f"INSERT INTO chunk_cache VALUES {values_clause}")
        conn.execute("""
            CREATE OR REPLACE TEMP TABLE update_map AS
            SELECT 
                g.geocoding_id,
                c.colocator,
                CASE 
                    WHEN c.colocator LIKE 'LL:%' 
                    THEN CAST(split_part(c.colocator, ':', 2) AS DOUBLE) 
                    ELSE NULL 
                END AS parsed_lat,
                CASE 
                    WHEN c.colocator LIKE 'LL:%' 
                    THEN CAST(split_part(c.colocator, ':', 3) AS DOUBLE) 
                    ELSE NULL 
                END AS parsed_lon
            FROM Geocoding g
            INNER JOIN chunk_cache c 
                    ON g.canonical_address = c.canonical_address
            WHERE g.geocoding_status IN (NULL, 'pending', 'owners', 'No_Match');
        """)
        map_count = conn.execute("SELECT COUNT(*) FROM update_map").fetchone()[0]
        if map_count == 0:
            conn.execute("DROP TABLE IF EXISTS chunk_cache;")
            conn.execute("DROP TABLE IF EXISTS update_map;")
            return 0, 0
        result = conn.execute("""
            UPDATE Geocoding g
            SET 
                geocoding_status = 'Match:Archive',
                last_attempt      = CURRENT_TIMESTAMP,
                attempt_count     = COALESCE(g.attempt_count, 0) + 1,
                matched_address   = 'Loaded from geocode_archive_distinct.tsv.gz',
                latitude          = m.parsed_lat,
                longitude         = m.parsed_lon
            FROM update_map m
            WHERE g.geocoding_id = m.geocoding_id
        """).fetchone()
        updated_geocoding = int(result[0]) if result and result[0] is not None else 0
        conn.execute("""
            UPDATE Addresses a
            SET colocator = m.colocator
            FROM update_map m
            WHERE a.geocoding_id = m.geocoding_id;
        """)
        actual_updated_addresses = conn.execute("""
            SELECT COUNT(*) 
            FROM Addresses 
            WHERE colocator IN (SELECT colocator FROM update_map)
        """).fetchone()[0]
        conn.execute("""
            UPDATE Charities ch
            SET colocator = m.colocator
            FROM (
                SELECT DISTINCT owner_id, ANY_VALUE(m.colocator) AS colocator
                FROM update_map m
                JOIN Addresses a ON a.geocoding_id = m.geocoding_id
                WHERE a.owner_id IS NOT NULL
                  AND a.address_type IN ('charity', 'filer')
                GROUP BY owner_id
            ) m
            WHERE ch.charity_id = m.owner_id;
        """)
        conn.execute("""
            UPDATE Grants gr
            SET colocator = m.colocator
            FROM (
                SELECT DISTINCT owner_id, ANY_VALUE(m.colocator) AS colocator
                FROM update_map m
                JOIN Addresses a ON a.geocoding_id = m.geocoding_id
                WHERE a.owner_id IS NOT NULL
                  AND a.address_type = 'grant'
                GROUP BY owner_id
            ) m
            WHERE gr.grant_id = m.owner_id;
        """)
        conn.execute("""
            UPDATE Contractors con
            SET colocator = m.colocator
            FROM (
                SELECT DISTINCT owner_id, ANY_VALUE(m.colocator) AS colocator
                FROM update_map m
                JOIN Addresses a ON a.geocoding_id = m.geocoding_id
                WHERE a.owner_id IS NOT NULL
                  AND a.address_type = 'contractor'
                GROUP BY owner_id
            ) m
            WHERE con.contractor_id = m.owner_id;
        """)
        conn.execute("""
            UPDATE Officers off
            SET colocator = m.colocator
            FROM (
                SELECT DISTINCT owner_id, ANY_VALUE(m.colocator) AS colocator
                FROM update_map m
                JOIN Addresses a ON a.geocoding_id = m.geocoding_id
                WHERE a.owner_id IS NOT NULL
                  AND a.address_type = 'officer'
                GROUP BY owner_id
            ) m
            WHERE off.officer_id = m.owner_id;
        """)
        conn.execute("""
            UPDATE PoliticalContributions pc
            SET colocator = m.colocator
            FROM (
                SELECT DISTINCT owner_id, ANY_VALUE(m.colocator) AS colocator
                FROM update_map m
                JOIN Addresses a ON a.geocoding_id = m.geocoding_id
                WHERE a.owner_id IS NOT NULL
                  AND a.address_type IN ('politicalcontribution', 'political')
                GROUP BY owner_id
            ) m
            WHERE pc.political_id = m.owner_id;
        """)
        conn.execute("DROP TABLE IF EXISTS chunk_cache;")
        conn.execute("DROP TABLE IF EXISTS update_map;")
        log_info(f"Chunk {chunk_num} complete: {updated_geocoding:,} Geocoding, {actual_updated_addresses:,} Addresses updated")
        return updated_geocoding, actual_updated_addresses

    def _get_custom_metrics(self) -> Dict[str, Any]:
        if not hasattr(self, 'pipeline'):
            return {'current_step': 'geolocate'}
        status = self.pipeline.get_status()
        metrics = status['metrics']
        metrics['current_step'] = 'geolocate'
        return metrics