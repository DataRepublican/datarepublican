#!/usr/bin/env python3
"""
config.py - Global configuration system for IRS 990 processing

This module provides a singleton GlobalConfig class to centralize
configuration management and eliminate the need to pass command-line
arguments around the codebase.
"""

from typing import Optional, List


class GlobalConfig:
    """Singleton class for global configuration"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GlobalConfig, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # Default values
        self.db_path: str = "irs990.duckdb"
        self.zips_dir: str = "/Volumes/Data/irs_zips"
        self.out_dir: str = "/Volumes/Data/tsvs"
        self.anal_dir: str = "/Volumes/Data/atsvs"
        self.final_dir: str = "/Volumes/Data/final"
        self.verbose: bool = False
        self.quiet: bool = False
        self.max_files: Optional[int] = None
        self.log_sql: bool = False
        self.workers: int = 16
        self.dbUI: bool = False
        self.profile_seconds: Optional[int] = None
        self.progress: str = "files"  # "files" or "bytes"
        self.extract: Optional[List[str]] = None
        self.extract_dest: Optional[str] = None
        self.nostats: bool = False
        self.no_backpressure: bool = False
        self.collect_xpath_stats: bool = False
        self.db_threads: int = 4

    @classmethod
    def get_instance(cls):
        """Get the singleton instance"""
        return cls()

    def set_from_args(self, args):
        """Set configuration from parsed command-line arguments"""
        self.db_path = getattr(args, 'db_path', self.db_path)
        self.zips_dir = getattr(args, 'zips_dir', self.zips_dir)
        self.out_dir = getattr(args, 'out_dir', self.out_dir)
        self.anal_dir = getattr(args, 'anal_dir', self.anal_dir)
        self.final_dir = getattr(args, 'final_dir', self.final_dir)
        self.verbose = getattr(args, 'verbose', self.verbose)
        self.quiet = getattr(args, 'quiet', self.quiet)
        self.max_files = getattr(args, 'max_files', self.max_files)
        self.log_sql = getattr(args, 'log_sql', self.log_sql)
        self.workers = getattr(args, 'workers', self.workers)
        self.dbUI = getattr(args, 'dbUI', self.dbUI)
        self.profile_seconds = getattr(args, 'profile', self.profile_seconds)
        self.progress = getattr(args, 'progress', self.progress)
        self.extract = getattr(args, 'extract', self.extract)
        self.extract_dest = getattr(args, 'extract_dest', self.extract_dest)
        self.nostats = getattr(args, 'nostats', self.nostats)
        self.no_backpressure = getattr(args, 'no_backpressure', self.no_backpressure)
        self.collect_xpath_stats = getattr(args, 'collect_xpath_stats', self.collect_xpath_stats)
        self.db_threads = getattr(args, 'db_threads', self.db_threads)

    def is_quiet(self) -> bool:
        """Check if quiet mode is enabled"""
        return self.quiet

    def is_verbose(self) -> bool:
        """Check if verbose mode is enabled"""
        return self.verbose


# Global instance for easy access
global_config = GlobalConfig.get_instance()