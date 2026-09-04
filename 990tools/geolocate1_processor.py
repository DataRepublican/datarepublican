#!/usr/bin/env python3
"""Backward-compat shim — use geolocate_prev_processor.GeolocatePrevProcessor."""

from geolocate_prev_processor import GeolocatePrevProcessor as Geolocate1Processor

__all__ = ["Geolocate1Processor"]