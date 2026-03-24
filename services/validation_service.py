# -*- coding: utf-8 -*-
"""Validacao e normalizacao centralizadas para camada de backend."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import unicodedata
from typing import Any


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MONTHS_PT_BR = {
    "JAN": "01",
    "FEV": "02",
    "MAR": "03",
    "ABR": "04",
    "MAI": "05",
    "JUN": "06",
    "JUL": "07",
    "AGO": "08",
    "SET": "09",
    "OUT": "10",
    "NOV": "11",
    "DEZ": "12",
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _collapse_spaces(value: Any) -> str:
    return " ".join(_text(value).strip().split())


def only_digits(value: Any) -> str:
    return "".join(ch for ch in _text(value) if ch.isdigit())


def _fold_text(value: Any) -> str:
    txt = unicodedata.normalize("NFKD", _text(value))
    txt = "".join(ch for ch in txt if not unicodedata.combining(ch))
    txt = txt.lower().strip()
    return txt


def _choice_key(value: Any) -> str:
    txt = _fold_text(value)
    return re.sub(r"[^a-z0-9]+", "", txt)


def _parse_positive_int(value: Any, field_label: str) -> int:
    try:
        out = int(_text(value).strip())
    except Exception as exc:  # pragma: no cover - branch defensivo
        raise ValueError(f"{field_label} invalido.") from exc
    if out <= 0:
        raise ValueError(f"{field_label} invalido.")
    return out


def _parse_non_negative_int(value: Any, field_label: str, default: int = 0) -> int:
    txt = _text(value).strip()
    if not txt:
        return int(default)
    try:
        out = int(txt)
    except Exception as exc:
        raise ValueError(f"{field_label} invalido.") from exc
    if out < 0:
        raise ValueError(f"{field_label} invalido.")
    return out


def _parse_int_range(value: Any, field_label: str, minimum: int, maximum: int, default: int) -> int:
    txt = _text(value).strip()
    if not txt:
        out = int(default)
    else:
        try:
            out = int(txt)
        except Exception as exc:
            raise ValueError(f"{field_label} invalido.") from exc
    if out < int(minimum) or out > int(maximum):
        raise ValueError(f"{field_label} invalido.")
    return out


def parse_date_iso(
    value: Any,
    *,
    field_label: str,
    required: bool,
    reject_future: bool,
) -> str:
    txt = _text(value).strip()
    if not txt:
        if required:
            raise ValueError(f"{field_label} obrigatoria.")
        return ""

    dt: datetime
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", txt):
            dt = datetime.strptime(txt, "%Y-%m-%d")
        elif re.fullmatch(r"\d{2}/\d{2}/\d{4}", txt):
            dt = datetime.strptime(txt, "%d/%m/%Y")
        else:
            raise ValueError
    except Exception as exc:
        raise ValueError(f"{field_label} invalida.") from exc

    if reject_future and dt.date() > date.today():
        raise ValueError(f"{field_label} nao pode ser futura.")
    return dt.strftime("%Y-%m-%d")


def parse_month_reference_iso(value: Any) -> str:
    txt = _text(value).strip().upper()
    if not txt:
        raise ValueError("Mes de referencia invalido. Use AAAA-MM ou JAN/AAAA.")

    if re.fullmatch(r"\d{4}-\d{2}", txt):
        year = int(txt[:4])
        month = int(txt[5:7])
        if year < 1900 or year > 2999 or month < 1 or month > 12:
            raise ValueError("Mes de referencia invalido. Use AAAA-MM ou JAN/AAAA.")
        return f"{year:04d}-{month:02d}"

    if "/" in txt:
        raw_month, raw_year = txt.split("/", 1)
        mm = raw_month.strip().upper()
        yy = raw_year.strip()
        if yy.isdigit() and len(yy) == 4:
            if mm in _MONTHS_PT_BR:
                return f"{yy}-{_MONTHS_PT_BR[mm]}"
            if mm.isdigit():
                month_i = int(mm)
                if 1 <= month_i <= 12:
                    return f"{yy}-{month_i:02d}"

    raise ValueError("Mes de referencia invalido. Use AAAA-MM ou JAN/AAAA.")


def parse_money(value: Any, *, field_label: str, allow_zero: bool) -> float:
    if isinstance(value, (int, float, Decimal)):
        dec = Decimal(str(value))
    else:
        raw = _text(value).strip()
        if not raw:
            raise ValueError(f"{field_label} obrigatorio.")

        cleaned = raw.replace("R$", "").replace("r$", "").replace(" ", "")
        if not cleaned or not re.fullmatch(r"[0-9.,]+", cleaned):
            raise ValueError(f"{field_label} invalido.")

        normalized = ""
        if "," in cleaned and "." in cleaned:
            last_sep_idx = max(cleaned.rfind(","), cleaned.rfind("."))
            int_part = re.sub(r"[.,]", "", cleaned[:last_sep_idx]) or "0"
            frac_raw = re.sub(r"[.,]", "", cleaned[last_sep_idx + 1 :])
            frac = (frac_raw + "00")[:2]
            normalized = f"{int_part}.{frac}"
        elif "," in cleaned:
            if cleaned.count(",") > 1:
                raise ValueError(f"{field_label} invalido.")
            int_part, frac_part = cleaned.split(",", 1)
            int_part = int_part or "0"
            if not int_part.isdigit() or (frac_part and not frac_part.isdigit()):
                raise ValueError(f"{field_label} invalido.")
            frac = (frac_part + "00")[:2]
            normalized = f"{int_part}.{frac}"
        elif "." in cleaned:
            if cleaned.count(".") == 1:
                int_part, frac_part = cleaned.split(".", 1)
                if len(frac_part) == 3 and int_part.isdigit() and frac_part.isdigit():
                    normalized = f"{int_part}{frac_part}.00"
                elif int_part.isdigit() and frac_part.isdigit() and 1 <= len(frac_part) <= 2:
                    frac = (frac_part + "00")[:2]
                    normalized = f"{int_part}.{frac}"
                else:
                    raise ValueError(f"{field_label} invalido.")
            else:
                groups = cleaned.split(".")
                if not all(g.isdigit() and g for g in groups):
                    raise ValueError(f"{field_label} invalido.")
                normalized = f"{''.join(groups)}.00"
        else:
            if not cleaned.isdigit():
                raise ValueError(f"{field_label} invalido.")
            normalized = f"{cleaned}.00"

        try:
            dec = Decimal(normalized)
        except InvalidOperation as exc:
            raise ValueError(f"{field_label} invalido.") from exc

    quantized = dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if allow_zero:
        if quantized < 0:
            raise ValueError(f"{field_label} invalido.")
    else:
        if quantized <= 0:
            raise ValueError(f"{field_label} invalido.")
    return float(quantized)


def format_money_decimal(value: Any) -> str:
    out = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(out, "f")


def _cpf_digits_valid(cpf_digits: str) -> bool:
    if len(cpf_digits) != 11:
        return False
    if cpf_digits == cpf_digits[0] * 11:
        return False

    def calc_digit(base: str, factors: list[int]) -> int:
        total = sum(int(d) * f for d, f in zip(base, factors))
        mod = total % 11
        return 0 if mod < 2 else 11 - mod

    d1 = calc_digit(cpf_digits[:9], list(range(10, 1, -1)))
    d2 = calc_digit(cpf_digits[:9] + str(d1), list(range(11, 1, -1)))
    return cpf_digits[-2:] == f"{d1}{d2}"


def _cnpj_digits_valid(cnpj_digits: str) -> bool:
    if len(cnpj_digits) != 14:
        return False
    if cnpj_digits == cnpj_digits[0] * 14:
        return False

    def calc_digit(base: str, factors: list[int]) -> int:
        total = sum(int(d) * f for d, f in zip(base, factors))
        mod = total % 11
        return 0 if mod < 2 else 11 - mod

    d1 = calc_digit(cnpj_digits[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = calc_digit(cnpj_digits[:12] + str(d1), [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return cnpj_digits[-2:] == f"{d1}{d2}"


def validate_cpf(value: Any, *, field_label: str = "CPF", required: bool = True) -> tuple[str, str]:
    raw = _collapse_spaces(value)
    digits = only_digits(raw)
    if not digits:
        if required:
            raise ValueError(f"{field_label} obrigatorio.")
        return "", ""
    if len(digits) != 11 or not _cpf_digits_valid(digits):
        raise ValueError(f"{field_label} invalido.")
    return raw, digits


def validate_cnpj(value: Any, *, field_label: str = "CNPJ", required: bool = True) -> tuple[str, str]:
    raw = _collapse_spaces(value)
    digits = only_digits(raw)
    if not digits:
        if required:
            raise ValueError(f"{field_label} obrigatorio.")
        return "", ""
    if len(digits) != 14 or not _cnpj_digits_valid(digits):
        raise ValueError(f"{field_label} invalido.")
    return raw, digits


def _normalize_phone(value: Any, *, required: bool, field_label: str) -> str:
    raw = _collapse_spaces(value)
    digits = only_digits(raw)
    if not digits:
        if required:
            raise ValueError(f"{field_label} obrigatorio.")
        return ""
    if len(digits) < 10 or len(digits) > 11:
        raise ValueError(f"{field_label} invalido.")
    return raw


def _normalize_email(value: Any, *, required: bool, field_label: str) -> str:
    raw = _collapse_spaces(value)
    if not raw:
        if required:
            raise ValueError(f"{field_label} obrigatorio.")
        return ""
    if not _EMAIL_RE.fullmatch(raw):
        raise ValueError(f"{field_label} invalido.")
    return raw


def _normalize_cep(value: Any, *, required: bool, field_label: str) -> str:
    raw = _collapse_spaces(value)
    digits = only_digits(raw)
    if not digits:
        if required:
            raise ValueError(f"{field_label} obrigatorio.")
        return ""
    if len(digits) != 8:
        raise ValueError(f"{field_label} invalido.")
    return raw


def _normalize_uf(value: Any, *, required: bool, field_label: str) -> str:
    raw = _collapse_spaces(value).upper()
    if not raw:
        if required:
            raise ValueError(f"{field_label} obrigatoria.")
        return ""
    if not re.fullmatch(r"[A-Z]{2}", raw):
        raise ValueError(f"{field_label} invalida.")
    return raw


def _normalize_cliente_status(value: Any) -> str:
    key = _choice_key(value)
    if not key:
        return "ativo"
    if key == "ativo":
        return "ativo"
    if key == "inativo":
        return "inativo"
    raise ValueError("Status do cliente invalido.")


def _normalize_cliente_pagamento_status(value: Any) -> str:
    key = _choice_key(value)
    if not key:
        return "em_dia"
    if key == "emdia":
        return "em_dia"
    if key in {"atrasado", "inadimplente"}:
        return "atrasado"
    if key == "emdiaatrasado":
        return "atrasado"
    raise ValueError("Status de pagamento do cliente invalido.")


def _normalize_cliente_forma_pagamento(value: Any) -> str:
    key = _choice_key(value)
    if not key:
        return "Boleto"
    if "pix" in key:
        return "Pix"
    if "boleto" in key:
        return "Boleto"
    if key.startswith("recep"):
        return "Recepção"
    raise ValueError("Forma de pagamento do cliente invalida.")


def _normalize_empresa_forma_pagamento(value: Any) -> str:
    key = _choice_key(value)
    if key == "pix":
        return "pix"
    if key == "boleto":
        return "boleto"
    if key.startswith("recep"):
        return "recepcao"
    raise ValueError("Forma de pagamento da empresa invalida.")


def _normalize_empresa_pagamento_status(value: Any) -> str:
    key = _choice_key(value)
    if key == "emdia":
        return "em_dia"
    if key == "pendente":
        return "pendente"
    if key in {"inadimplente", "atrasado"}:
        return "inadimplente"
    raise ValueError("Status de pagamento da empresa invalido.")


def _age_from_iso(date_iso: str) -> int:
    born = datetime.strptime(date_iso, "%Y-%m-%d").date()
    today = date.today()
    return max(today.year - born.year - ((today.month, today.day) < (born.month, born.day)), 0)


def _normalize_dependentes(value: Any) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("Lista de dependentes invalida.")

    out: list[dict[str, Any]] = []
    seen_cpfs: set[str] = set()

    for idx, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Dependente #{idx} invalido.")
        nome = _collapse_spaces(item.get("nome"))
        if not nome:
            raise ValueError(f"Dependente #{idx}: nome obrigatorio.")
        cpf_raw, cpf_digits = validate_cpf(item.get("cpf"), field_label=f"Dependente #{idx} CPF")
        if cpf_digits in seen_cpfs:
            raise ValueError(f"Dependente #{idx}: CPF duplicado.")
        seen_cpfs.add(cpf_digits)

        data_iso = parse_date_iso(
            item.get("data_nascimento"),
            field_label=f"Dependente #{idx} data de nascimento",
            required=True,
            reject_future=True,
        )
        idade = _age_from_iso(data_iso)
        out.append(
            {
                "nome": nome,
                "cpf": cpf_raw,
                "data_nascimento": data_iso,
                "idade": idade,
            }
        )
    return out


def normalize_cliente_payload(dados: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(dados, dict):
        raise ValueError("Dados do cliente invalidos.")

    modo = _collapse_spaces(dados.get("modo")).lower() or "create"
    if modo not in {"create", "edit"}:
        raise ValueError("Modo de operacao do cliente invalido.")

    matricula_raw = dados.get("matricula", dados.get("id"))
    matricula: int | None = None
    if _text(matricula_raw).strip():
        matricula = _parse_positive_int(matricula_raw, "Matricula")
    if modo == "edit":
        if matricula is None:
            raise ValueError("ID do cliente obrigatorio para edicao.")
    if modo == "create" and matricula is None:
        matricula = None

    nome = _collapse_spaces(dados.get("nome"))
    if not nome:
        raise ValueError("Nome obrigatorio.")

    cpf_raw, _cpf_digits = validate_cpf(dados.get("cpf"))
    telefone = _normalize_phone(dados.get("telefone"), required=True, field_label="Telefone")
    email = _normalize_email(dados.get("email"), required=False, field_label="E-mail")
    status = _normalize_cliente_status(dados.get("status"))
    pagamento_status = _normalize_cliente_pagamento_status(dados.get("pagamento_status"))
    data_inicio = parse_date_iso(
        dados.get("data_inicio"),
        field_label="Data de inicio",
        required=False,
        reject_future=False,
    ) or date.today().strftime("%Y-%m-%d")
    observacoes = _collapse_spaces(dados.get("observacoes"))
    data_nascimento = parse_date_iso(
        dados.get("data_nascimento"),
        field_label="Data de nascimento",
        required=True,
        reject_future=True,
    )
    cep = _normalize_cep(dados.get("cep"), required=True, field_label="CEP")
    endereco = _collapse_spaces(dados.get("endereco"))
    if not endereco:
        raise ValueError("Endereco obrigatorio.")

    plano = _collapse_spaces(dados.get("plano"))
    forma_pagamento = _normalize_cliente_forma_pagamento(dados.get("forma_pagamento"))
    vencimento_dia = _parse_int_range(
        dados.get("vencimento_dia"),
        field_label="Dia de vencimento",
        minimum=1,
        maximum=31,
        default=10,
    )
    valor_mensal = parse_money(dados.get("valor_mensal"), field_label="Valor mensal", allow_zero=True)

    deps_input = dados.get("dependentes_lista", None)
    if deps_input is None:
        deps_list = []
        deps_count = _parse_non_negative_int(dados.get("dependentes"), "Dependentes", default=0)
    else:
        deps_list = _normalize_dependentes(deps_input)
        deps_count = len(deps_list)

    normalized: dict[str, Any] = {
        "modo": modo,
        "id": matricula,
        "matricula": matricula,
        "nome": nome,
        "cpf": cpf_raw,
        "telefone": telefone,
        "email": email,
        "status": status,
        "pagamento_status": pagamento_status,
        "data_inicio": data_inicio,
        "observacoes": observacoes,
        "data_nascimento": data_nascimento,
        "cep": cep,
        "endereco": endereco,
        "plano": plano,
        "dependentes": deps_count,
        "dependentes_lista": deps_list,
        "vencimento_dia": vencimento_dia,
        "forma_pagamento": forma_pagamento,
        "valor_mensal": float(valor_mensal),
    }
    return normalized


def normalize_empresa_payload(dados: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(dados, dict):
        raise ValueError("Dados da empresa invalidos.")

    modo = _collapse_spaces(dados.get("modo")).lower() or "create"
    if modo not in {"create", "edit"}:
        raise ValueError("Modo de operacao da empresa invalido.")

    empresa_id: int | None = None
    if modo == "edit":
        empresa_id = _parse_positive_int(dados.get("id"), "ID da empresa")

    cnpj_raw, _cnpj_digits = validate_cnpj(dados.get("cnpj"))
    nome = _collapse_spaces(dados.get("nome"))
    if not nome:
        raise ValueError("Razao social obrigatoria.")

    telefone = _normalize_phone(dados.get("telefone"), required=True, field_label="Telefone")
    email = _normalize_email(dados.get("email"), required=True, field_label="E-mail")
    logradouro = _collapse_spaces(dados.get("logradouro"))
    numero = _collapse_spaces(dados.get("numero"))
    bairro = _collapse_spaces(dados.get("bairro"))
    cep = _normalize_cep(dados.get("cep"), required=True, field_label="CEP")
    cidade = _collapse_spaces(dados.get("cidade"))
    estado = _normalize_uf(dados.get("estado"), required=True, field_label="UF")
    if not logradouro:
        raise ValueError("Logradouro obrigatorio.")
    if not numero:
        raise ValueError("Numero obrigatorio.")
    if not bairro:
        raise ValueError("Bairro obrigatorio.")
    if not cidade:
        raise ValueError("Cidade obrigatoria.")

    forma_pagamento = _normalize_empresa_forma_pagamento(dados.get("forma_pagamento"))
    status_pagamento = _normalize_empresa_pagamento_status(dados.get("status_pagamento"))
    dia_vencimento = _parse_int_range(
        dados.get("dia_vencimento"),
        field_label="Dia de vencimento",
        minimum=1,
        maximum=31,
        default=10,
    )
    valor_mensal_float = parse_money(dados.get("valor_mensal"), field_label="Valor mensal", allow_zero=False)
    valor_mensal = format_money_decimal(valor_mensal_float)

    out: dict[str, Any] = {
        "modo": modo,
        "id": empresa_id,
        "cnpj": cnpj_raw,
        "nome": nome,
        "telefone": telefone,
        "email": email,
        "logradouro": logradouro,
        "numero": numero,
        "bairro": bairro,
        "cep": cep,
        "cidade": cidade,
        "estado": estado,
        "forma_pagamento": forma_pagamento,
        "status_pagamento": status_pagamento,
        "dia_vencimento": dia_vencimento,
        "valor_mensal": valor_mensal,
    }
    return out


def normalize_pagamento_payload(dados: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(dados, dict):
        raise ValueError("Dados do pagamento invalidos.")

    tipo_pagador = _collapse_spaces(dados.get("tipo_pagador")).lower() or "cliente"
    if tipo_pagador not in {"cliente", "empresa"}:
        raise ValueError("Tipo de pagador invalido.")

    mes_iso_raw = _collapse_spaces(dados.get("mes_iso"))
    mes_iso = parse_month_reference_iso(mes_iso_raw or dados.get("mes_referencia"))
    data_pagamento = parse_date_iso(
        dados.get("data_pagamento"),
        field_label="Data de pagamento",
        required=True,
        reject_future=True,
    )
    valor_pago = parse_money(dados.get("valor_pago"), field_label="Valor do pagamento", allow_zero=False)

    out: dict[str, Any] = {
        "tipo_pagador": tipo_pagador,
        "mes_iso": mes_iso,
        "data_pagamento": data_pagamento,
        "valor_pago": float(valor_pago),
    }

    if tipo_pagador == "empresa":
        empresa_id_raw = _text(dados.get("empresa_id")).strip()
        if empresa_id_raw:
            out["empresa_id"] = _parse_positive_int(empresa_id_raw, "ID da empresa")
        else:
            cnpj_raw, _digits = validate_cnpj(dados.get("cnpj"))
            out["cnpj"] = cnpj_raw
    else:
        cliente_id_raw = _text(dados.get("cliente_id")).strip()
        if cliente_id_raw:
            out["cliente_id"] = _parse_positive_int(cliente_id_raw, "ID do cliente")
        else:
            cpf_raw, _digits = validate_cpf(dados.get("cpf"))
            out["cpf"] = cpf_raw

    return out
