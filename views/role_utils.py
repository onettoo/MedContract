from __future__ import annotations

import unicodedata


def normalize_role(nivel: str) -> str:
    txt = str(nivel or "").strip().lower()
    if not txt:
        return ""
    plain = "".join(
        ch for ch in unicodedata.normalize("NFKD", txt)
        if not unicodedata.combining(ch)
    )
    plain = plain.replace("Ã§", "c").replace("Ã£", "a").replace("ç", "c").replace("ã", "a")
    if plain in {"recepcao", "recepcionista"} or plain.startswith("recep"):
        return "recepcao"
    if plain in {"funcionario"} or plain.startswith("func"):
        return "funcionario"
    if plain in {"admin", "administrador"} or "admin" in plain:
        return "admin"
    return plain

