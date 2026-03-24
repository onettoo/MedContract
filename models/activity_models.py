from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActivityEntry:
    when: str
    title: str
    detail: str = ""
    level: str = "info"
    source: str = "system"

    def to_dict(self) -> dict:
        return {
            "when": str(self.when or "").strip(),
            "title": str(self.title or "").strip(),
            "detail": str(self.detail or "").strip(),
            "level": str(self.level or "info").strip().lower(),
            "source": str(self.source or "system").strip().lower(),
        }

