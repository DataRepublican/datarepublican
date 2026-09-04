from dataclasses import dataclass
from typing import Optional

@dataclass
class AuthoritativeEin:
    """Simple record for AuthoritativeEin table inserts/updates."""
    name: str
    colocator: str          # 'NULL' for global rows
    ein: str
    count: int = 1