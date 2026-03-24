from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ContaPagar:
    id: int
    descricao: str
    categoria: str
    fornecedor: str
    valor_previsto: float
    data_vencimento: str
    data_competencia: str
    forma_pagamento: str
    status: str
    recorrente: bool = False
    periodicidade: str | None = None
    parcela_atual: int | None = None
    total_parcelas: int | None = None
    data_pagamento_real: str | None = None
    valor_pago: float | None = None
    observacoes: str | None = None
    criado_em: str | None = None
    atualizado_em: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": int(self.id),
            "descricao": str(self.descricao or "").strip(),
            "categoria": str(self.categoria or "").strip(),
            "fornecedor": str(self.fornecedor or "").strip(),
            "valor_previsto": float(self.valor_previsto or 0.0),
            "data_vencimento": str(self.data_vencimento or "").strip(),
            "data_competencia": str(self.data_competencia or "").strip(),
            "forma_pagamento": str(self.forma_pagamento or "").strip(),
            "status": str(self.status or "").strip(),
            "recorrente": bool(self.recorrente),
            "periodicidade": self.periodicidade,
            "parcela_atual": self.parcela_atual,
            "total_parcelas": self.total_parcelas,
            "data_pagamento_real": self.data_pagamento_real,
            "valor_pago": self.valor_pago,
            "observacoes": self.observacoes,
            "criado_em": self.criado_em,
            "atualizado_em": self.atualizado_em,
        }

