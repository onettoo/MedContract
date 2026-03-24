from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ContractTemplateProfile:
    contract_type: str
    operation: str
    candidates: tuple[Path, ...]

