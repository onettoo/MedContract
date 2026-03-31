from __future__ import annotations

from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_base_qss() -> str:
    root = project_root()
    tokens = _read_text(root / "styles" / "tokens.qss")
    base = _read_text(root / "styles" / "base.qss")
    if tokens.strip():
        return f"{tokens}\n\n{base}"
    return base


def load_optional_qss(*relative_paths: str) -> str:
    root = project_root()
    chunks: list[str] = []
    for rel in relative_paths:
        text = _read_text(root / rel)
        if text.strip():
            chunks.append(text)
    return "\n\n".join(chunks)


def build_app_qss(*extra_relative_paths: str) -> str:
    base = load_base_qss()
    extras = load_optional_qss(*extra_relative_paths)
    if extras.strip():
        return f"{base}\n\n{extras}"
    return base


def build_view_qss(view_name: str, extra_qss: str) -> str:
    base = load_base_qss()
    extra = (extra_qss or "").strip()
    if not extra:
        return base
    return f"{base}\n\n/* {view_name} */\n{extra}"
