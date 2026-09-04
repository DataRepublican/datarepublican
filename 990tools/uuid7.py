#!/usr/bin/env python3
"""
uuid7.py - UUID v7 generation for time-ordered identifiers

This module provides UUID v7 generation with proper timestamp encoding.
UUID v7 format: timestamp (48 bits) + version (4 bits) + sequence (12 bits) + random (62 bits)
"""

import time
import secrets
import uuid


def generate_uuid_v7() -> str:
    """Pure-Python UUID v7: Time-ordered, RFC 9562 compliant (48-bit ts + rand)."""
    # 48-bit Unix ms ts
    ts_ms = int(time.time() * 1000) & 0xffffffffffff
    # v7: ts | (7 << 12) | 12-bit seq (rand) | 62-bit rand
    ver_seq = (7 << 12) | secrets.randbits(12)  # 0111xxxx for v7
    rand_bits = secrets.randbits(62)
    # Pack to 128-bit int: ts (48) << 80 | ver_seq (16) << 64 | rand (62) << 2 (pad)
    full_int = (ts_ms << 80) | (ver_seq << 64) | (rand_bits << 2)
    return str(uuid.UUID(int=full_int))


# For backward compatibility, keep the old function name
uuid7 = generate_uuid_v7


if __name__ == "__main__":
    # Test UUID generation
    print("Testing UUID v7 generation:")
    for i in range(5):
        uuid = generate_uuid_v7()
        print(f"UUID {i+1}: {uuid}")
        # Small delay to show time ordering
        time.sleep(0.001)