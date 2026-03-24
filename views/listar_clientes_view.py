# -*- coding: utf-8 -*-
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TypedDict, Optional, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QComboBox, QToolButton, QScrollArea, QSizePolicy,
    QGraphicsDropShadowEffect, QMenu, QMessageBox, QStackedWidget, QSplitter,
    QDialog, QDoubleSpinBox, QCheckBox, QTextEdit
)
from PySide6.QtCore import Qt, Signal, QTimer, QPoint, QObject, QRunnable, QThreadPool, Slot, QSettings
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut, QAction, QFontDatabase

import database.db as db
from views.role_utils import normalize_role as _normalize_role
from views.ui_tokens import PALETTE

# ── Paleta unificada ──────────────────────────────────────────────────────────
_ACCENT        = PALETTE.accent
_ACCENT_HOVER  = PALETTE.accent_hover
_INK           = PALETTE.ink
_INK2          = PALETTE.ink_2
_INK3          = PALETTE.ink_3
_LINE          = PALETTE.line
_WHITE         = PALETTE.white
_BG            = PALETTE.bg
_GOOD          = PALETTE.good
_GOOD_BG       = PALETTE.good_bg
_GOOD_BORDER   = PALETTE.good_border
_DANGER        = PALETTE.danger
_DANGER_BG     = PALETTE.danger_bg
_DANGER_BORDER = PALETTE.danger_border


def _load_fonts() -> str:
    """Carrega DM Sans de assets/fonts/ e retorna o nome da família."""
    fonts_dir = Path(__file__).resolve().parent / "assets" / "fonts"
    family = "Segoe UI"
    if fonts_dir.exists():
        for ttf in fonts_dir.glob("*.ttf"):
            fid = QFontDatabase.addApplicationFont(str(ttf))
            if fid >= 0:
                fams = QFontDatabase.applicationFontFamilies(fid)
                if fams and "DM Sans" in fams[0]:
                    family = fams[0]
    return family


# ══════════════════════════════════════════════
# Tipos estruturados — elimina índices mágicos
# ══════════════════════════════════════════════
class ClienteRow(TypedDict):
    mat: int
    nome: str
    cpf: str
    telefone: str
    email: str
    data_inicio: str
    valor_mensal: Optional[float]
    status: str
    pag_status: str
    observacoes: str
    data_nascimento: str
    cep: str
    endereco: str
    plano: str
    dependentes: str
    vencimento: str
    forma_pagamento: str


class PagamentoRow(TypedDict):
    mes_ref: str
    data_pagamento: str
    valor_pago: Optional[float]


class DependenteRow(TypedDict):
    dep_id: int
    nome: str
    cpf: str
    idade: str


class ClienteListRow(TypedDict):
    mat: int
    nome: str
    cpf: str
    status: str
    pag_status: str
    mes_ref: str
    data_pagamento: str
    valor_pago: Optional[float]


# ══════════════════════════════════════════════
# Estado de paginação
# ══════════════════════════════════════════════
class PaginationState:
    def __init__(self, page_size: int = 30):
        self.page: int = 0
        self.page_size: int = page_size
        self.total: int = 0

    @property
    def offset(self) -> int:
        return self.page * self.page_size

    @property
    def max_page(self) -> int:
        if self.total == 0:
            return 0
        return max(0, (self.total - 1) // self.page_size)

    def go_prev(self) -> bool:
        if self.page > 0:
            self.page -= 1
            return True
        return False

    def go_next(self) -> bool:
        if self.page < self.max_page:
            self.page += 1
            return True
        return False

    def reset(self):
        self.page = 0


# ══════════════════════════════════════════════
# Helpers de formatação
# ══════════════════════════════════════════════
def br_date(iso: str) -> str:
    if not iso:
        return "-"
    if "-" in iso:
        try:
            y, m, d = iso.split("-")
            return f"{d}/{m}/{y}"
        except Exception:
            return iso
    return iso


def br_month_ref(mes_ref: str) -> str:
    if not mes_ref:
        return "-"
    meses = {
        "01": "JAN", "02": "FEV", "03": "MAR", "04": "ABR",
        "05": "MAI", "06": "JUN", "07": "JUL", "08": "AGO",
        "09": "SET", "10": "OUT", "11": "NOV", "12": "DEZ",
    }
    s = str(mes_ref).strip()
    if "-" in s:
        try:
            y, m = s.split("-")
            return f"{meses.get(m, m)}/{y}"
        except Exception:
            return s
    return s


def br_money(value) -> str:
    if value in (None, ""):
        return "-"
    try:
        s = f"{float(value):,.2f}"
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {s}"
    except Exception:
        return str(value)


def safe_text(value, default="-") -> str:
    txt = (str(value).strip() if value is not None else "")
    return txt if txt else default


def _map_list_row(r) -> ClienteListRow:
    """Converte linha bruta para dict tipado. Centraliza mapeamento de índices."""
    def _s(v): return str(v).strip() if v is not None else ""
    if len(r) > 19:
        mes_ref, data_pag, valor = _s(r[17]), _s(r[18]), r[19]
    elif len(r) > 12:
        mes_ref, data_pag, valor = _s(r[10]), _s(r[11]), r[12]
    else:
        mes_ref, data_pag, valor = "", "", None
    return ClienteListRow(
        mat=int(r[0]), nome=_s(r[1]), cpf=_s(r[2]),
        status=_s(r[7]).lower(), pag_status=_s(r[8]).lower(),
        mes_ref=mes_ref, data_pagamento=data_pag, valor_pago=valor,
    )


def _map_cliente_row(r) -> ClienteRow:
    def _s(i): return str(r[i]).strip() if len(r) > i and r[i] is not None else ""
    return ClienteRow(
        mat=int(r[0]) if r else 0,
        nome=_s(1), cpf=_s(2), telefone=_s(3), email=_s(4),
        data_inicio=_s(5), valor_mensal=r[6] if len(r) > 6 else None,
        status=_s(7), pag_status=_s(8),
        observacoes=_s(9), data_nascimento=_s(10), cep=_s(11),
        endereco=_s(12), plano=_s(13), dependentes=_s(14),
        vencimento=_s(15), forma_pagamento=_s(16),
    )


def _map_pagamento_row(r) -> Optional[PagamentoRow]:
    if not r:
        return None
    def _s(i): return str(r[i]).strip() if len(r) > i and r[i] is not None else ""
    return PagamentoRow(mes_ref=_s(0), data_pagamento=_s(1), valor_pago=r[2] if len(r) > 2 else None)


def _map_dependente_row(r) -> DependenteRow:
    def _s(i): return str(r[i]).strip() if len(r) > i and r[i] is not None else ""
    return DependenteRow(dep_id=r[0] if r else 0, nome=_s(1), cpf=_s(2), idade=_s(3))


# ══════════════════════════════════════════════
# Workers assíncronos
# ══════════════════════════════════════════════
class _WorkerSignals(QObject):
    result = Signal(object)
    error  = Signal(str)


class _DbWorker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn     = fn
        self._args   = args
        self._kwargs = kwargs
        self.signals = _WorkerSignals()

    @Slot()
    def run(self):
        try:
            self.signals.result.emit(self._fn(*self._args, **self._kwargs))
        except Exception as e:
            self.signals.error.emit(str(e))


# ══════════════════════════════════════════════
# Componentes visuais auxiliares
# ══════════════════════════════════════════════
class StyledComboBox(QComboBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        view = self.view()
        view.setObjectName("comboPopupView")
        try:
            view.viewport().setAutoFillBackground(True)
        except Exception:
            pass

    def showPopup(self):
        try:
            popup = self.view().window()
            popup.setObjectName("comboPopupWindow")
            popup.setAttribute(Qt.WA_TranslucentBackground, False)
            popup.setAttribute(Qt.WA_NoSystemBackground, False)
            popup.setAutoFillBackground(True)
        except Exception:
            pass
        super().showPopup()


class PillItem(QTableWidgetItem):
    def __init__(self, text: str, fg: str, bg: str):
        super().__init__(text)
        self.setTextAlignment(Qt.AlignCenter)
        self.setForeground(QColor(fg))
        self.setBackground(QColor(bg))
        f = QFont()
        f.setBold(True)
        self.setFont(f)


class _SectionHeader(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("sectionHeader")


class _ReajustePlanosDialog(QDialog):
    """Dialog para pré-visualizar e aplicar reajuste seletivo."""

    def __init__(
        self,
        parent=None,
        sans: str = "Segoe UI",
        *,
        selected_ids: list[int] | None = None,
        current_cliente: dict | None = None,
    ):
        super().__init__(parent)
        self._sans = sans or "Segoe UI"
        self._preview: dict | None = None
        self._preview_sig: tuple | None = None
        self._payload: dict | None = None
        self._selected_ids = sorted({int(v) for v in (selected_ids or []) if int(v) > 0})
        self._current_cliente = dict(current_cliente or {})

        self.setObjectName("reajusteDialog")
        self.setWindowTitle("Reajuste de valores")
        self.setModal(True)
        self.setMinimumWidth(620)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title = QLabel("Reajuste seletivo de clientes")
        title.setObjectName("dlgTitle")
        subtitle = QLabel(
            "Escolha o modo, gere a prévia e confirme. "
            "Você pode reajustar por filtros, por clientes marcados ou definir valor individual."
        )
        subtitle.setObjectName("dlgSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        line = QFrame()
        line.setObjectName("dlgLine")
        line.setFixedHeight(1)
        root.addWidget(line)

        row = QHBoxLayout()
        row.setSpacing(10)

        mode_col = QVBoxLayout()
        mode_col.setSpacing(6)
        mode_lbl = QLabel("Modo")
        mode_lbl.setObjectName("dlgLabel")
        self.mode_combo = StyledComboBox()
        self.mode_combo.setObjectName("dlgCombo")
        self.mode_combo.setFixedHeight(40)
        self.mode_combo.addItem("Lote por filtros atuais", "filtros")
        self.mode_combo.addItem("Lote dos clientes marcados", "selecionados")
        self.mode_combo.addItem("Cliente específico (valor individual)", "individual")
        mode_col.addWidget(mode_lbl)
        mode_col.addWidget(self.mode_combo)

        plano_col = QVBoxLayout()
        plano_col.setSpacing(6)
        plano_lbl = QLabel("Plano")
        plano_lbl.setObjectName("dlgLabel")
        self.plano_combo = StyledComboBox()
        self.plano_combo.setObjectName("dlgCombo")
        self.plano_combo.setFixedHeight(40)
        self.plano_combo.addItem("Todos os planos", "todos")
        self.plano_combo.addItem("Classic", "classic")
        self.plano_combo.addItem("Master", "master")
        plano_col.addWidget(plano_lbl)
        plano_col.addWidget(self.plano_combo)

        pct_col = QVBoxLayout()
        pct_col.setSpacing(6)
        pct_lbl = QLabel("Reajuste (%)")
        pct_lbl.setObjectName("dlgLabel")
        self.percent_spin = QDoubleSpinBox()
        self.percent_spin.setObjectName("dlgSpin")
        self.percent_spin.setDecimals(2)
        self.percent_spin.setRange(-90.0, 500.0)
        self.percent_spin.setSingleStep(1.0)
        self.percent_spin.setValue(5.0)
        self.percent_spin.setSuffix(" %")
        self.percent_spin.setFixedHeight(40)
        pct_col.addWidget(pct_lbl)
        pct_col.addWidget(self.percent_spin)

        valor_col = QVBoxLayout()
        valor_col.setSpacing(6)
        valor_lbl = QLabel("Novo valor mensal")
        valor_lbl.setObjectName("dlgLabel")
        self.novo_valor_spin = QDoubleSpinBox()
        self.novo_valor_spin.setObjectName("dlgSpin")
        self.novo_valor_spin.setDecimals(2)
        self.novo_valor_spin.setRange(0.0, 999999.99)
        self.novo_valor_spin.setSingleStep(10.0)
        self.novo_valor_spin.setPrefix("R$ ")
        self.novo_valor_spin.setFixedHeight(40)
        valor_col.addWidget(valor_lbl)
        valor_col.addWidget(self.novo_valor_spin)

        self.mode_wrap = QFrame()
        mode_wrap_l = QVBoxLayout(self.mode_wrap)
        mode_wrap_l.setContentsMargins(0, 0, 0, 0)
        mode_wrap_l.addLayout(mode_col)

        self.percent_wrap = QFrame()
        pct_wrap_l = QVBoxLayout(self.percent_wrap)
        pct_wrap_l.setContentsMargins(0, 0, 0, 0)
        pct_wrap_l.addLayout(pct_col)

        self.plano_wrap = QFrame()
        plano_wrap_l = QVBoxLayout(self.plano_wrap)
        plano_wrap_l.setContentsMargins(0, 0, 0, 0)
        plano_wrap_l.addLayout(plano_col)

        self.valor_wrap = QFrame()
        valor_wrap_l = QVBoxLayout(self.valor_wrap)
        valor_wrap_l.setContentsMargins(0, 0, 0, 0)
        valor_wrap_l.addLayout(valor_col)

        row.addWidget(self.mode_wrap, 2)
        row.addWidget(self.percent_wrap, 1)
        row.addWidget(self.plano_wrap, 1)
        row.addWidget(self.valor_wrap, 1)
        root.addLayout(row)

        self.chk_ativos = QCheckBox("Aplicar somente em clientes ATIVOS")
        self.chk_ativos.setObjectName("dlgCheck")
        self.chk_ativos.setChecked(True)
        root.addWidget(self.chk_ativos)

        self.info_selected = QLabel("")
        self.info_selected.setObjectName("dlgInfo")
        self.info_selected.setWordWrap(True)
        root.addWidget(self.info_selected)

        self.info_current = QLabel("")
        self.info_current.setObjectName("dlgInfo")
        self.info_current.setWordWrap(True)
        root.addWidget(self.info_current)

        self.preview_card = QFrame()
        self.preview_card.setObjectName("previewCard")
        preview_l = QVBoxLayout(self.preview_card)
        preview_l.setContentsMargins(12, 10, 12, 10)
        preview_l.setSpacing(6)
        self.preview_title = QLabel("Prévia")
        self.preview_title.setObjectName("previewTitle")
        self.preview_body = QLabel("Clique em \"Pré-visualizar\" para calcular o impacto.")
        self.preview_body.setObjectName("previewBody")
        self.preview_body.setWordWrap(True)
        preview_l.addWidget(self.preview_title)
        preview_l.addWidget(self.preview_body)
        root.addWidget(self.preview_card)

        self.msg = QLabel("")
        self.msg.setObjectName("dlgMsg")
        self.msg.setVisible(False)
        self.msg.setWordWrap(True)
        root.addWidget(self.msg)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addStretch()

        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setObjectName("dlgSecondary")
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_preview = QPushButton("Pré-visualizar")
        self.btn_preview.setObjectName("dlgSecondary")
        self.btn_preview.clicked.connect(self._on_preview_clicked)

        self.btn_apply = QPushButton("Aplicar reajuste")
        self.btn_apply.setObjectName("dlgPrimary")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._on_apply_clicked)

        btns.addWidget(self.btn_cancel)
        btns.addWidget(self.btn_preview)
        btns.addWidget(self.btn_apply)
        root.addLayout(btns)

        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.mode_combo.currentIndexChanged.connect(self._invalidate_preview)
        self.plano_combo.currentIndexChanged.connect(self._invalidate_preview)
        self.percent_spin.valueChanged.connect(self._invalidate_preview)
        self.novo_valor_spin.valueChanged.connect(self._invalidate_preview)
        self.chk_ativos.stateChanged.connect(self._invalidate_preview)

        self._setup_mode_defaults()
        self._apply_styles()
        self._on_mode_changed()

    def _apply_styles(self):
        f = self._sans
        self.setStyleSheet(f"""
        QDialog#reajusteDialog {{
            background: {_WHITE};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#dlgTitle {{
            font-size: 17px;
            font-weight: 700;
            color: {_INK};
        }}
        QLabel#dlgSubtitle {{
            font-size: 12px;
            color: {_INK2};
        }}
        QFrame#dlgLine {{
            background: {_LINE};
            border: none;
        }}
        QLabel#dlgLabel {{
            font-size: 11px;
            font-weight: 700;
            color: {_INK2};
        }}
        QLabel#dlgInfo {{
            font-size: 11px;
            color: {_INK2};
            background: rgba(15,23,42,0.03);
            border: 1px solid {_LINE};
            border-radius: 8px;
            padding: 7px 10px;
        }}
        QComboBox#dlgCombo {{
            border: 1px solid {_LINE};
            border-radius: 8px;
            padding: 0 30px 0 10px;
            background: {_WHITE};
            color: {_INK};
            font-size: 12px;
            font-weight: 600;
        }}
        QComboBox#dlgCombo:hover {{
            border-color: #c0c7d0;
        }}
        QComboBox#dlgCombo:focus {{
            border-color: {_ACCENT};
        }}
        QDoubleSpinBox#dlgSpin {{
            border: 1px solid {_LINE};
            border-radius: 8px;
            padding: 0 10px;
            background: {_WHITE};
            color: {_INK};
            font-size: 12px;
            font-weight: 600;
        }}
        QDoubleSpinBox#dlgSpin:focus {{
            border-color: {_ACCENT};
        }}
        QCheckBox#dlgCheck {{
            color: {_INK2};
            font-size: 12px;
            spacing: 8px;
        }}
        QFrame#previewCard {{
            background: {_BG};
            border: 1px solid {_LINE};
            border-radius: 10px;
        }}
        QLabel#previewTitle {{
            font-size: 12px;
            font-weight: 700;
            color: {_INK};
        }}
        QLabel#previewBody {{
            font-size: 12px;
            color: {_INK2};
        }}
        QLabel#dlgMsg {{
            background: {_DANGER_BG};
            border: 1px solid {_DANGER_BORDER};
            border-left: 4px solid {_DANGER};
            border-radius: 8px;
            padding: 8px 12px;
            color: {_DANGER};
            font-size: 12px;
            font-weight: 600;
        }}
        QLabel#dlgMsg[ok="true"] {{
            background: {_GOOD_BG};
            border: 1px solid {_GOOD_BORDER};
            border-left: 4px solid {_GOOD};
            color: {_GOOD};
        }}
        QPushButton#dlgPrimary {{
            background: {_ACCENT};
            border: none;
            border-radius: 8px;
            padding: 0 14px;
            min-height: 36px;
            color: white;
            font-size: 12px;
            font-weight: 700;
        }}
        QPushButton#dlgPrimary:hover {{
            background: {_ACCENT_HOVER};
        }}
        QPushButton#dlgPrimary:disabled {{
            background: rgba(26,107,124,0.30);
            color: rgba(255,255,255,0.65);
        }}
        QPushButton#dlgSecondary {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 8px;
            padding: 0 14px;
            min-height: 36px;
            color: {_INK};
            font-size: 12px;
            font-weight: 700;
        }}
        QPushButton#dlgSecondary:hover {{
            border-color: {_ACCENT};
            color: {_ACCENT};
        }}
        """)

    def _setup_mode_defaults(self):
        has_selected = bool(self._selected_ids)
        has_current = bool(int(self._current_cliente.get("mat", 0) or 0))

        try:
            model = self.mode_combo.model()
            item_sel = model.item(1)
            if item_sel is not None:
                item_sel.setEnabled(has_selected)
            item_ind = model.item(2)
            if item_ind is not None:
                item_ind.setEnabled(has_current)
        except Exception:
            pass

        if has_selected:
            self.mode_combo.setCurrentIndex(1)
        elif has_current:
            self.mode_combo.setCurrentIndex(2)
        else:
            self.mode_combo.setCurrentIndex(0)

    def _mode(self) -> str:
        return str(self.mode_combo.currentData() or "filtros")

    def _on_mode_changed(self, *_):
        mode = self._mode()
        is_filtros = mode == "filtros"
        is_selecionados = mode == "selecionados"
        is_individual = mode == "individual"

        self.percent_wrap.setVisible(is_filtros or is_selecionados)
        self.plano_wrap.setVisible(is_filtros)
        self.valor_wrap.setVisible(is_individual)
        self.chk_ativos.setVisible(is_filtros or is_selecionados)

        if is_filtros:
            self.chk_ativos.setText("Aplicar somente em clientes ATIVOS")
            self.info_selected.setVisible(False)
            self.info_current.setVisible(False)
            self.btn_apply.setText("Aplicar reajuste")
        elif is_selecionados:
            self.chk_ativos.setText("Ignorar clientes INATIVOS entre os marcados")
            self.info_selected.setText(f"Clientes marcados para lote: {len(self._selected_ids)}")
            self.info_selected.setVisible(True)
            self.info_current.setVisible(False)
            self.btn_apply.setText("Aplicar em selecionados")
        else:
            mat = int(self._current_cliente.get("mat", 0) or 0)
            nome = str(self._current_cliente.get("nome", "") or "").strip() or f"MAT {mat}"
            self.info_current.setText(f"Cliente alvo: {nome} (MAT {mat})")
            self.info_current.setVisible(bool(mat))
            self.info_selected.setVisible(False)
            self.btn_apply.setText("Aplicar reajuste individual")

    def _build_preview_lines(self, prev: dict) -> list[str]:
        mode = str(prev.get("modo", self._mode()) or self._mode())
        qtd = int(prev.get("clientes_afetados", 0) or 0)
        soma_atual = float(prev.get("soma_atual", 0.0) or 0.0)
        soma_reajustada = float(prev.get("soma_reajustada", 0.0) or 0.0)
        dif = float(prev.get("diferenca_total", 0.0) or 0.0)

        if mode == "individual":
            nome = str(prev.get("cliente_nome", "-") or "-")
            mat = int(prev.get("cliente_id", 0) or 0)
            pct = float(prev.get("percentual_estimado", 0.0) or 0.0)
            return [
                f"Cliente: {nome} (MAT {mat})",
                f"Valor atual: {br_money(soma_atual)}",
                f"Novo valor: {br_money(soma_reajustada)}",
                f"Variação: {br_money(dif)} ({pct:.2f}%)",
            ]

        lines = []
        if mode == "selecionados":
            lines.append(f"Clientes marcados: {int(prev.get('clientes_solicitados', 0) or 0)}")
        else:
            lines.append(f"Plano alvo: {prev.get('plano_label', 'Todos os planos')}")
        lines.extend([
            f"Clientes afetados: {qtd}",
            f"Soma atual: {br_money(soma_atual)}",
            f"Soma reajustada: {br_money(soma_reajustada)}",
            f"Diferença total: {br_money(dif)}",
        ])
        if mode == "filtros":
            lines.append("Regra: valores-base dos planos permanecem inalterados.")
        return lines

    def _current_payload(self) -> dict:
        mode = self._mode()
        if mode == "selecionados":
            return {
                "modo": "selecionados",
                "percentual": float(self.percent_spin.value()),
                "somente_ativos": bool(self.chk_ativos.isChecked()),
                "cliente_ids": list(self._selected_ids),
            }
        if mode == "individual":
            return {
                "modo": "individual",
                "cliente_id": int(self._current_cliente.get("mat", 0) or 0),
                "novo_valor": float(self.novo_valor_spin.value()),
            }

        plan_data = self.plano_combo.currentData()
        plano = str(plan_data if plan_data is not None else "todos")
        return {
            "modo": "filtros",
            "plano": plano,
            "percentual": float(self.percent_spin.value()),
            "somente_ativos": bool(self.chk_ativos.isChecked()),
        }

    def _payload_signature(self) -> tuple:
        payload = self._current_payload()
        modo = str(payload.get("modo", "filtros") or "filtros")
        if modo == "selecionados":
            return (
                "selecionados",
                round(float(payload.get("percentual", 0.0) or 0.0), 6),
                bool(payload.get("somente_ativos", False)),
                tuple(sorted(int(v) for v in (payload.get("cliente_ids") or []))),
            )
        if modo == "individual":
            return (
                "individual",
                int(payload.get("cliente_id", 0) or 0),
                round(float(payload.get("novo_valor", 0.0) or 0.0), 6),
            )
        return (
            "filtros",
            payload["plano"],
            round(float(payload["percentual"]), 6),
            bool(payload["somente_ativos"]),
        )

    def _set_msg(self, text: str, ok: bool = False):
        text = str(text or "").strip()
        self.msg.setText(text)
        self.msg.setProperty("ok", bool(ok))
        self.msg.style().unpolish(self.msg)
        self.msg.style().polish(self.msg)
        self.msg.setVisible(bool(text))

    def _invalidate_preview(self, *_):
        self._preview = None
        self._preview_sig = None
        self.btn_apply.setEnabled(False)
        self.preview_body.setText("Clique em \"Pré-visualizar\" para calcular o impacto.")
        self._set_msg("")

    def _on_preview_clicked(self):
        payload = self._current_payload()
        mode = str(payload.get("modo", "filtros") or "filtros")
        try:
            if mode == "selecionados":
                prev = db.prever_reajuste_clientes_selecionados(
                    percentual=payload["percentual"],
                    cliente_ids=payload["cliente_ids"],
                    somente_ativos=payload["somente_ativos"],
                )
            elif mode == "individual":
                prev = db.prever_reajuste_cliente_especifico(
                    cliente_id=payload["cliente_id"],
                    novo_valor=payload["novo_valor"],
                )
            else:
                prev = db.prever_reajuste_planos(
                    percentual=payload["percentual"],
                    plano=payload["plano"],
                    somente_ativos=payload["somente_ativos"],
                )
                prev["modo"] = "filtros"
        except Exception as e:
            self._preview = None
            self._preview_sig = None
            self.btn_apply.setEnabled(False)
            self._set_msg(f"Não foi possível gerar prévia: {e}", ok=False)
            return

        self._preview = prev
        self._preview_sig = self._payload_signature()
        self.btn_apply.setEnabled(True)
        self.preview_body.setText("\n".join(self._build_preview_lines(prev)))

        qtd = int(prev.get("clientes_afetados", 0) or 0)
        if mode != "individual" and qtd <= 0:
            self._set_msg("Nenhum cliente será alterado com esta configuração.", ok=False)
        else:
            self._set_msg("Pré-visualização pronta. Revise e confirme a aplicação.", ok=True)

    def _on_apply_clicked(self):
        if not self._preview or self._preview_sig != self._payload_signature():
            self._set_msg("Atualize a pré-visualização antes de aplicar.", ok=False)
            self.btn_apply.setEnabled(False)
            return

        ask = QMessageBox(self)
        ask.setWindowTitle("Confirmar reajuste")
        ask.setIcon(QMessageBox.Warning)
        ask.setText("Deseja confirmar a aplicação deste reajuste?")
        ask.setInformativeText("\n".join(self._build_preview_lines(self._preview)))
        ask.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        ask.setDefaultButton(QMessageBox.Cancel)
        ask.button(QMessageBox.Yes).setText("Confirmar")
        ask.button(QMessageBox.Cancel).setText("Voltar")
        if ask.exec() != QMessageBox.Yes:
            return

        payload = self._current_payload()
        payload["preview"] = dict(self._preview)
        self._payload = payload
        self.accept()

    def payload(self) -> dict:
        return dict(self._payload or {})


class _EnviarEmailDialog(QDialog):
    """Dialog para composicao e envio de e-mail para um cliente."""

    def __init__(self, parent=None, *, sans: str = "Segoe UI", contexto: dict | None = None):
        super().__init__(parent)
        self._sans = sans or "Segoe UI"
        self._ctx = dict(contexto or {})
        self._payload: dict | None = None

        self.setObjectName("emailDialog")
        self.setWindowTitle("Enviar e-mail")
        self.setModal(True)
        self.setMinimumWidth(660)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title = QLabel("Enviar e-mail ao cliente")
        title.setObjectName("dlgTitle")
        subtitle = QLabel("Selecione um modelo, revise o texto e clique em enviar.")
        subtitle.setObjectName("dlgSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        line = QFrame()
        line.setObjectName("dlgLine")
        line.setFixedHeight(1)
        root.addWidget(line)

        row_top = QHBoxLayout()
        row_top.setSpacing(10)

        col_email = QVBoxLayout()
        col_email.setSpacing(6)
        lbl_email = QLabel("Destinatario")
        lbl_email.setObjectName("dlgLabel")
        self.to_input = QLineEdit()
        self.to_input.setObjectName("dlgInput")
        self.to_input.setFixedHeight(38)
        self.to_input.setText(str(self._ctx.get("email", "") or "").strip())
        col_email.addWidget(lbl_email)
        col_email.addWidget(self.to_input)

        col_model = QVBoxLayout()
        col_model.setSpacing(6)
        lbl_model = QLabel("Modelo")
        lbl_model.setObjectName("dlgLabel")
        self.template_combo = StyledComboBox()
        self.template_combo.setObjectName("dlgCombo")
        self.template_combo.setFixedHeight(38)
        self.template_combo.addItem("Lembrete de vencimento", "lembrete")
        self.template_combo.addItem("Cobrança de inadimplência", "cobranca")
        self.template_combo.addItem("Confirmação de pagamento", "confirmacao")
        self.template_combo.addItem("Comunicado personalizado", "custom")
        col_model.addWidget(lbl_model)
        col_model.addWidget(self.template_combo)

        row_top.addLayout(col_email, 2)
        row_top.addLayout(col_model, 1)
        root.addLayout(row_top)

        lbl_subject = QLabel("Assunto")
        lbl_subject.setObjectName("dlgLabel")
        self.subject_input = QLineEdit()
        self.subject_input.setObjectName("dlgInput")
        self.subject_input.setFixedHeight(38)
        root.addWidget(lbl_subject)
        root.addWidget(self.subject_input)

        lbl_body = QLabel("Mensagem")
        lbl_body.setObjectName("dlgLabel")
        self.body_input = QTextEdit()
        self.body_input.setObjectName("dlgText")
        self.body_input.setMinimumHeight(220)
        root.addWidget(lbl_body)
        root.addWidget(self.body_input, 1)

        self.msg = QLabel("")
        self.msg.setObjectName("dlgMsg")
        self.msg.setVisible(False)
        self.msg.setWordWrap(True)
        root.addWidget(self.msg)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addStretch()
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setObjectName("dlgSecondary")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_send = QPushButton("Enviar e-mail")
        self.btn_send.setObjectName("dlgPrimary")
        self.btn_send.clicked.connect(self._on_send_clicked)
        btns.addWidget(self.btn_cancel)
        btns.addWidget(self.btn_send)
        root.addLayout(btns)

        self.template_combo.currentIndexChanged.connect(self._apply_template)
        self._apply_template()
        self._apply_styles()

    @staticmethod
    def _month_ref_now() -> str:
        months = {
            "01": "JAN", "02": "FEV", "03": "MAR", "04": "ABR",
            "05": "MAI", "06": "JUN", "07": "JUL", "08": "AGO",
            "09": "SET", "10": "OUT", "11": "NOV", "12": "DEZ",
        }
        now = datetime.now()
        mm = f"{now.month:02d}"
        return f"{months.get(mm, mm)}/{now.year}"

    def _ctx_text(self, key: str, default: str = "-") -> str:
        txt = str(self._ctx.get(key, "") or "").strip()
        return txt or default

    @staticmethod
    def _month_ref_now_iso() -> str:
        return datetime.now().strftime("%Y-%m")

    @staticmethod
    def _is_valid_month_iso(value: str) -> bool:
        s = str(value or "").strip()
        return len(s) == 7 and s[4] == "-" and s[:4].isdigit() and s[5:7].isdigit()

    @staticmethod
    def _month_ref_to_iso(mes_ref: str) -> str:
        meses = {
            "JAN": "01", "FEV": "02", "MAR": "03", "ABR": "04",
            "MAI": "05", "JUN": "06", "JUL": "07", "AGO": "08",
            "SET": "09", "OUT": "10", "NOV": "11", "DEZ": "12",
        }
        txt = str(mes_ref or "").strip().upper()
        if len(txt) == 7 and txt[4] == "-" and txt[:4].isdigit() and txt[5:7].isdigit():
            return txt
        if "/" not in txt:
            return ""
        mm_txt, yyyy = txt.split("/", 1)
        mm = meses.get(mm_txt.strip()[:3], "")
        yyyy = yyyy.strip()
        if mm and len(yyyy) == 4 and yyyy.isdigit():
            return f"{yyyy}-{mm}"
        return ""

    @staticmethod
    def _filled_or_placeholder(value: str, placeholder: str) -> str:
        txt = str(value or "").strip()
        return txt if txt and txt != "-" else placeholder

    def _resolve_due_date(self, mes_ref_br: str) -> tuple[str, date | None]:
        raw_day = str(self._ctx.get("vencimento_dia", "") or "").strip()
        try:
            due_day = int(raw_day)
        except Exception:
            due_day = 0
        if due_day <= 0:
            return "[data de vencimento]", None

        mes_iso = str(self._ctx.get("mes_ref_iso", "") or "").strip()
        if not self._is_valid_month_iso(mes_iso):
            mes_iso = self._month_ref_to_iso(mes_ref_br)
        if not self._is_valid_month_iso(mes_iso):
            mes_iso = self._month_ref_now_iso()

        try:
            ano = int(mes_iso[:4])
            mes = int(mes_iso[5:7])
            dia = max(1, min(due_day, monthrange(ano, mes)[1]))
            venc = date(ano, mes, dia)
            return venc.strftime("%d/%m/%Y"), venc
        except Exception:
            return "[data de vencimento]", None

    @staticmethod
    def _atraso_context(vencimento: date | None) -> tuple[str, str]:
        if not vencimento:
            return "[X]", "[nova data limite]"
        hoje = date.today()
        dias = (hoje - vencimento).days
        if dias <= 0:
            return "[X]", "[nova data limite]"
        limite = hoje + timedelta(days=5)
        return str(dias), limite.strftime("%d/%m/%Y")

    def _template_for(self, template_key: str) -> tuple[str, str]:
        nome = self._filled_or_placeholder(self._ctx_text("nome", ""), "[Nome do Cliente]")
        titular = self._filled_or_placeholder(self._ctx_text("titular", nome), "[Nome do Titular]")
        plano = self._filled_or_placeholder(self._ctx_text("plano", ""), "[Nome/Tipo do Pacote]")
        mes_ref_base = self._ctx_text("mes_ref_br", self._month_ref_now())
        mes_ref = self._filled_or_placeholder(mes_ref_base, "[Mês]")
        valor_mensal = self._filled_or_placeholder(
            self._ctx_text("valor_mensal_br", self._ctx_text("valor_pago_br", "-")),
            "R$ [valor]",
        )
        valor_pago = self._filled_or_placeholder(
            self._ctx_text("valor_pago_br", self._ctx_text("valor_mensal_br", "-")),
            "R$ [valor]",
        )
        data_compensacao = self._filled_or_placeholder(
            self._ctx_text("data_pagamento_br", "-"),
            "[data de compensação]",
        )
        vencimento_br, vencimento_dt = self._resolve_due_date(mes_ref_base)
        dias_atraso, nova_data_limite = self._atraso_context(vencimento_dt)
        status_atraso = f"Em atraso há {dias_atraso} dia(s)"
        assinatura = "Equipe Pronto Clínica Arnaldo Quintela"

        if template_key == "cobranca":
            subject = f"Aviso de pagamento em atraso - Mensalidade {mes_ref}"
            body = (
                f"Prezado(a) {nome},\n\n"
                "Esperamos que esteja bem.\n\n"
                "Verificamos em nosso sistema que o pagamento da mensalidade do pacote, "
                f"com vencimento em {vencimento_br}, ainda não foi identificado. "
                f"Até o momento, o débito encontra-se em atraso há {dias_atraso} dia(s).\n\n"
                "Detalhes da pendência:\n\n"
                f"Titular: {titular}\n"
                f"Pacote: {plano}\n"
                f"Valor em aberto: {valor_mensal}\n"
                f"Vencimento original: {vencimento_br}\n"
                f"Status: {status_atraso}\n\n"
                "Para evitar suspensão do serviço e possíveis encargos adicionais, solicitamos a regularização "
                f"do pagamento até {nova_data_limite} ou o contato com nossa equipe para alinharmos "
                "a melhor forma de regularização.\n\n"
                "Caso o pagamento já tenha sido efetuado, pedimos a gentileza de desconsiderar este aviso. "
                "Se possível, encaminhe o comprovante para agilizar a baixa em nosso sistema.\n\n"
                "Permanecemos à disposição para qualquer esclarecimento.\n\n"
                "Atenciosamente,\n"
                f"{assinatura}"
            )
            return subject, body

        if template_key == "confirmacao":
            subject = f"Confirmação de pagamento - Mensalidade {mes_ref}"
            body = (
                f"Prezado(a) {nome},\n\n"
                "Tudo certo?\n\n"
                f"Identificamos o pagamento da sua mensalidade referente ao período {mes_ref}, "
                f"com vencimento em {vencimento_br}, e informamos que o seu cadastro encontra-se "
                "regular e ativo em nosso sistema.\n\n"
                "Resumo do pagamento:\n\n"
                f"Titular: {titular}\n"
                f"Pacote: {plano}\n"
                f"Valor pago: {valor_pago}\n"
                f"Vencimento: {vencimento_br}\n"
                f"Data de confirmação: {data_compensacao}\n\n"
                "Agradecemos a pontualidade e a confiança em nossos serviços.\n"
                "Sempre que precisar de qualquer suporte, alteração de dados ou esclarecimento, "
                "conte com a nossa equipe.\n\n"
                "Atenciosamente,\n"
                f"{assinatura}"
            )
            return subject, body

        if template_key == "custom":
            subject = f"Comunicado - Mensalidade {mes_ref}"
            body = (
                f"Prezado(a) {nome},\n\n"
                "Escreva aqui sua mensagem personalizada.\n\n"
                "Atenciosamente,\n"
                f"{assinatura}"
            )
            return subject, body

        subject = f"Lembrete de vencimento - Mensalidade {mes_ref}"
        body = (
            f"Prezado(a) {nome},\n\n"
            "Tudo bem?\n\n"
            "Este é um lembrete amigável de que a mensalidade do seu pacote, "
            f"referente ao período {mes_ref}, tem vencimento em {vencimento_br}.\n\n"
            "Detalhes da cobrança:\n\n"
            f"Titular: {titular}\n"
            f"Pacote: {plano}\n"
            f"Valor: {valor_mensal}\n"
            f"Vencimento: {vencimento_br}\n\n"
            "Para evitar qualquer interrupção no serviço, orientamos que o pagamento seja realizado "
            "até a data de vencimento.\n"
            "Caso já tenha feito o pagamento, por favor desconsidere este lembrete.\n\n"
            "Em caso de dúvidas ou necessidade de segunda via, estamos à disposição por este e-mail "
            "ou pelos nossos canais de atendimento.\n\n"
            "Atenciosamente,\n"
            f"{assinatura}"
        )
        return subject, body

    def _set_msg(self, text: str, ok: bool = False):
        text = str(text or "").strip()
        self.msg.setText(text)
        self.msg.setProperty("ok", bool(ok))
        self.msg.style().unpolish(self.msg)
        self.msg.style().polish(self.msg)
        self.msg.setVisible(bool(text))

    def _apply_template(self, *_):
        key = str(self.template_combo.currentData() or "lembrete")
        subject, body = self._template_for(key)
        self.subject_input.setText(subject)
        self.body_input.setPlainText(body)
        self._set_msg("")

    def _on_send_clicked(self):
        to_email = (self.to_input.text() or "").strip()
        subject = (self.subject_input.text() or "").strip()
        body = (self.body_input.toPlainText() or "").strip()
        template = str(self.template_combo.currentData() or "lembrete")

        if not to_email or "@" not in to_email:
            self._set_msg("Informe um e-mail valido para envio.", ok=False)
            self.to_input.setFocus()
            return
        if not subject:
            self._set_msg("Informe um assunto para o e-mail.", ok=False)
            self.subject_input.setFocus()
            return
        if not body:
            self._set_msg("Informe o texto do e-mail.", ok=False)
            self.body_input.setFocus()
            return

        self._payload = {
            "to_email": to_email,
            "subject": subject,
            "body_text": body,
            "template": template,
            "mat": self._ctx.get("mat"),
            "nome": self._ctx.get("nome"),
        }
        self.accept()

    def payload(self) -> dict:
        return dict(self._payload or {})

    def _apply_styles(self):
        f = self._sans
        self.setStyleSheet(f"""
        QDialog#emailDialog {{
            background: {_WHITE};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#dlgTitle {{
            font-size: 17px;
            font-weight: 700;
            color: {_INK};
        }}
        QLabel#dlgSubtitle {{
            font-size: 12px;
            color: {_INK2};
        }}
        QFrame#dlgLine {{
            background: {_LINE};
            border: none;
        }}
        QLabel#dlgLabel {{
            font-size: 11px;
            font-weight: 700;
            color: {_INK2};
        }}
        QLineEdit#dlgInput, QComboBox#dlgCombo {{
            border: 1px solid {_LINE};
            border-radius: 8px;
            padding: 0 10px;
            background: {_WHITE};
            color: {_INK};
            font-size: 12px;
            font-weight: 600;
        }}
        QLineEdit#dlgInput:focus, QComboBox#dlgCombo:focus {{
            border-color: {_ACCENT};
        }}
        QComboBox#dlgCombo {{
            padding: 0 30px 0 10px;
        }}
        QTextEdit#dlgText {{
            border: 1px solid {_LINE};
            border-radius: 10px;
            padding: 10px;
            background: {_WHITE};
            color: {_INK};
            font-size: 12px;
            selection-background-color: rgba(26,107,124,0.20);
        }}
        QTextEdit#dlgText:focus {{
            border-color: {_ACCENT};
        }}
        QLabel#dlgMsg {{
            background: {_DANGER_BG};
            border: 1px solid {_DANGER_BORDER};
            border-left: 4px solid {_DANGER};
            border-radius: 8px;
            padding: 8px 12px;
            color: {_DANGER};
            font-size: 12px;
            font-weight: 600;
        }}
        QLabel#dlgMsg[ok="true"] {{
            background: {_GOOD_BG};
            border: 1px solid {_GOOD_BORDER};
            border-left: 4px solid {_GOOD};
            color: {_GOOD};
        }}
        QPushButton#dlgPrimary {{
            background: {_ACCENT};
            border: none;
            border-radius: 8px;
            padding: 0 14px;
            min-height: 36px;
            color: white;
            font-size: 12px;
            font-weight: 700;
        }}
        QPushButton#dlgPrimary:hover {{
            background: {_ACCENT_HOVER};
        }}
        QPushButton#dlgSecondary {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 8px;
            padding: 0 14px;
            min-height: 36px;
            color: {_INK};
            font-size: 12px;
            font-weight: 700;
        }}
        QPushButton#dlgSecondary:hover {{
            border-color: {_ACCENT};
            color: {_ACCENT};
        }}
        """)


# ══════════════════════════════════════════════
# ListarClientesView
# ══════════════════════════════════════════════
class ListarClientesView(QWidget):
    voltar_signal  = Signal()
    novo_signal    = Signal()
    editar_signal  = Signal(int)
    excluir_signal = Signal(int)
    cancelar_plano_signal = Signal(int)
    reajuste_planos_signal = Signal(dict)
    enviar_email_signal = Signal(dict)
    baixar_contrato_signal = Signal(int)

    COL_SEL = 0
    COL_MAT = 1
    COL_NOME = 2
    COL_CPF = 3
    COL_STATUS = 4
    COL_PAG = 5
    COL_ULT_PAG = 6
    COL_MES_REF = 7
    COL_VALOR = 8
    COL_CONTRATO = 9

    def __init__(self):
        super().__init__()

        self._msg_timer = QTimer(self)
        self._msg_timer.setSingleShot(True)
        self._msg_timer.timeout.connect(self._hide_message)

        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.timeout.connect(self._on_search_changed)

        self._pagination  = PaginationState(page_size=30)
        self.current_mat: Optional[int] = None
        self._current_status = ""
        self._selected_cliente_ctx: dict | None = None
        self._search_mode = "local"
        self.nivel_usuario = ""
        self._is_recepcao = False
        self._can_edit_cliente = True
        self._can_send_email = True
        self._can_delete_cliente = True
        self._can_create_cliente = True
        self._loading = False
        self._reload_pending = False

        self._stats = {"total": 0, "ativo": 0, "inativo": 0, "em_dia": 0, "atrasado": 0}
        self._checked_mats: set[int] = set()
        self._contract_col_min_width = 84
        self._reload_seq = 0
        self._compact_layout = False
        self.threadpool = QThreadPool.globalInstance()
        self._sans = _load_fonts()
        self._settings = QSettings("MedContract", "MedContract")
        self._settings_prefix = "views/listar_clientes"
        self._restoring_state = False

        self.setup_ui()
        self.apply_styles()
        self._apply_card_shadow()
        self._wire_shortcuts()
        self._restore_view_state()
        QTimer.singleShot(0, self._apply_responsive_layout)

    def _settings_key(self, name: str) -> str:
        return f"{self._settings_prefix}/{name}"

    def _persist_view_state(self):
        if self._restoring_state:
            return
        status = self.filter_status.currentText()
        pag = self.filter_pag.currentText()
        status = "" if status.startswith("status:") else status
        pag = "" if pag.startswith("pagamento:") else pag
        self._settings.setValue(self._settings_key("search"), (self.search.text() or "").strip())
        self._settings.setValue(self._settings_key("status"), status)
        self._settings.setValue(self._settings_key("pagamento"), pag)
        self._settings.setValue(self._settings_key("page"), int(self._pagination.page))
        self._settings.setValue(self._settings_key("page_size"), int(self._pagination.page_size))
        self._settings.sync()

    def _restore_view_state(self):
        controls = (self.search, self.filter_status, self.filter_pag, self.page_size_combo)
        for control in controls:
            control.blockSignals(True)
        self._restoring_state = True
        try:
            search = self._settings.value(self._settings_key("search"), "", type=str) or ""
            status = (self._settings.value(self._settings_key("status"), "", type=str) or "").strip().lower()
            pag = (self._settings.value(self._settings_key("pagamento"), "", type=str) or "").strip().lower()
            try:
                page = int(self._settings.value(self._settings_key("page"), 0))
            except Exception:
                page = 0
            try:
                page_size = int(self._settings.value(self._settings_key("page_size"), 30))
            except Exception:
                page_size = 30

            if page_size not in (30, 50, 100):
                page_size = 30

            self.search.setText(str(search).strip())
            self.filter_status.setCurrentText(status if status in ("ativo", "inativo") else "status: todos")
            self.filter_pag.setCurrentText(pag if pag in ("em_dia", "atrasado") else "pagamento: todos")
            self._pagination.page = max(0, page)
            self._pagination.page_size = page_size
            page_size_idx = {30: 0, 50: 1, 100: 2}.get(page_size, 0)
            self.page_size_combo.setCurrentIndex(page_size_idx)
            self._search_mode = "server" if self.search.text().strip() else "local"
            self._update_pager()
        finally:
            self._restoring_state = False
            for control in controls:
                control.blockSignals(False)

    # ─────────────────────────────────────────
    # API pública
    # ─────────────────────────────────────────
    def open_with_filters(self, search_text="", status="", pagamento="", page=0):
        self._pagination.page = max(0, int(page))
        self.search.setText(search_text or "")
        self.filter_status.setCurrentText(status if status in ("ativo", "inativo") else "status: todos")
        self.filter_pag.setCurrentText(pagamento if pagamento in ("em_dia", "atrasado") else "pagamento: todos")
        self._search_mode = "server" if self.search.text().strip() else "local"
        self._persist_view_state()
        self.reload()

    def set_nivel_usuario(self, nivel: str):
        self.nivel_usuario = str(nivel or "")
        role = _normalize_role(self.nivel_usuario)
        self._is_recepcao = (role == "recepcao")
        self._can_edit_cliente = not self._is_recepcao
        # RBAC (Recepção): oculta ações sensíveis nas telas de listagem.
        self._can_send_email = not self._is_recepcao
        self._can_delete_cliente = not self._is_recepcao
        self._can_create_cliente = not self._is_recepcao

        self.btn_editar_sel.setVisible(self._can_edit_cliente)
        self.btn_cancelar_sel.setVisible(self._can_edit_cliente)
        self.btn_reajuste_sel.setVisible(self._can_edit_cliente)
        self.btn_mark_visible.setVisible(self._can_edit_cliente)
        self.btn_clear_marked.setVisible(self._can_edit_cliente)
        self.lbl_marked.setVisible(self._can_edit_cliente)
        self.btn_quick_edit.setVisible(self._can_edit_cliente)
        self.btn_quick_cancel.setVisible(self._can_edit_cliente)
        self.btn_email_sel.setVisible(self._can_send_email)
        self.btn_quick_email.setVisible(self._can_send_email)
        self.btn_excluir_sel.setVisible(self._can_delete_cliente)
        self.btn_quick_del.setVisible(self._can_delete_cliente)
        self.btn_novo.setVisible(self._can_create_cliente)
        self._sync_action_group_visibility()
        self._set_actions_enabled(bool(self.current_mat))

    def _sync_action_group_visibility(self):
        try:
            selected_visible = (
                (not self.btn_editar_sel.isHidden())
                or (not self.btn_reajuste_sel.isHidden())
                or (not self.btn_email_sel.isHidden())
            )
            batch_visible = (
                (not self.btn_mark_visible.isHidden())
                or (not self.btn_clear_marked.isHidden())
                or (not self.lbl_marked.isHidden())
            )
            critical_visible = (
                (not self.btn_cancelar_sel.isHidden())
                or (not self.btn_excluir_sel.isHidden())
            )
            create_visible = (not self.btn_novo.isHidden())

            self.grp_actions_selected.setVisible(bool(selected_visible))
            self.grp_actions_batch.setVisible(bool(batch_visible))
            self.grp_actions_critical.setVisible(bool(critical_visible))
            self.grp_actions_create.setVisible(bool(create_visible))
        except Exception:
            pass

    # ─────────────────────────────────────────
    # UI
    # ─────────────────────────────────────────
    def setup_ui(self):
        self.setObjectName("ListarClientes")
        host = QVBoxLayout(self)
        host.setContentsMargins(0, 0, 0, 0)
        host.setSpacing(0)

        self.main_scroll = QScrollArea()
        self.main_scroll.setObjectName("mainScroll")
        self.main_scroll.setWidgetResizable(True)
        self.main_scroll.setFrameShape(QFrame.NoFrame)
        self.main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.main_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        host.addWidget(self.main_scroll, 1)

        page = QWidget()
        page.setObjectName("mainPage")
        self.main_scroll.setWidget(page)

        root = QVBoxLayout(page)
        self._root_layout = root
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(12)

        # Topo
        top = QHBoxLayout()
        top.setSpacing(12)

        title_wrap = QVBoxLayout()
        title_wrap.setSpacing(2)
        self.breadcrumb = QLabel("Cadastro  /  Clientes")
        self.breadcrumb.setObjectName("breadcrumb")
        self.title = QLabel("Clientes")
        self.title.setObjectName("title")
        self.subtitle = QLabel("Gerencie clientes, pagamentos e dependentes.")
        self.subtitle.setObjectName("subtitle")
        title_wrap.addWidget(self.breadcrumb)
        title_wrap.addWidget(self.title)
        title_wrap.addWidget(self.subtitle)
        top.addLayout(title_wrap)
        top.addStretch()

        self.btn_novo = QPushButton("+ Novo")
        self.btn_novo.setObjectName("btnPrimary")
        self.btn_novo.setFixedHeight(36)
        self.btn_novo.setMinimumWidth(72)
        self.btn_novo.setCursor(Qt.PointingHandCursor)
        self.btn_novo.setAccessibleName("Cadastrar novo cliente")
        self.btn_novo.setToolTip("Cadastrar novo cliente")
        self.btn_novo.clicked.connect(self._novo_cliente)

        self.btn_editar_sel = QPushButton("Editar")
        self.btn_editar_sel.setObjectName("btnSecondary")
        self.btn_editar_sel.setFixedHeight(36)
        self.btn_editar_sel.setMinimumWidth(62)
        self.btn_editar_sel.setCursor(Qt.PointingHandCursor)
        self.btn_editar_sel.setAccessibleName("Editar cliente selecionado")
        self.btn_editar_sel.setToolTip("Editar cliente selecionado")
        self.btn_editar_sel.clicked.connect(self._editar_selecionado)

        self.btn_cancelar_sel = QPushButton("Cancelar")
        self.btn_cancelar_sel.setObjectName("btnDanger")
        self.btn_cancelar_sel.setFixedHeight(36)
        self.btn_cancelar_sel.setMinimumWidth(70)
        self.btn_cancelar_sel.setCursor(Qt.PointingHandCursor)
        self.btn_cancelar_sel.setAccessibleName("Cancelar plano do cliente selecionado")
        self.btn_cancelar_sel.setToolTip("Cancelar plano do cliente selecionado")
        self.btn_cancelar_sel.clicked.connect(self._cancelar_plano_selecionado)

        self.btn_excluir_sel = QPushButton("Excluir")
        self.btn_excluir_sel.setObjectName("btnDanger")
        self.btn_excluir_sel.setFixedHeight(36)
        self.btn_excluir_sel.setMinimumWidth(64)
        self.btn_excluir_sel.setCursor(Qt.PointingHandCursor)
        self.btn_excluir_sel.setAccessibleName("Excluir cliente selecionado")
        self.btn_excluir_sel.setToolTip("Excluir cliente selecionado")
        self.btn_excluir_sel.clicked.connect(self._excluir_selecionado)

        self.btn_reajuste_sel = QPushButton("Reajuste")
        self.btn_reajuste_sel.setObjectName("btnAccentSoft")
        self.btn_reajuste_sel.setFixedHeight(36)
        self.btn_reajuste_sel.setMinimumWidth(70)
        self.btn_reajuste_sel.setCursor(Qt.PointingHandCursor)
        self.btn_reajuste_sel.setAccessibleName("Aplicar reajuste percentual de planos")
        self.btn_reajuste_sel.setToolTip("Aplicar reajuste percentual de planos")
        self.btn_reajuste_sel.clicked.connect(self._abrir_reajuste_planos)

        self.btn_email_sel = QPushButton("E-mail")
        self.btn_email_sel.setObjectName("btnAccentSoft")
        self.btn_email_sel.setFixedHeight(36)
        self.btn_email_sel.setMinimumWidth(62)
        self.btn_email_sel.setCursor(Qt.PointingHandCursor)
        self.btn_email_sel.setAccessibleName("Enviar e-mail para cliente selecionado")
        self.btn_email_sel.setToolTip("Enviar e-mail para cliente selecionado")
        self.btn_email_sel.clicked.connect(self._enviar_email_selecionado)

        self.btn_mark_visible = QPushButton("Marcar visíveis")
        self.btn_mark_visible.setObjectName("btnSecondary")
        self.btn_mark_visible.setFixedHeight(32)
        self.btn_mark_visible.setMinimumWidth(72)
        self.btn_mark_visible.setCursor(Qt.PointingHandCursor)
        self.btn_mark_visible.setToolTip("Marcar/desmarcar clientes visíveis")
        self.btn_mark_visible.clicked.connect(self._toggle_marcar_visiveis)

        self.btn_clear_marked = QPushButton("Limpar marcações")
        self.btn_clear_marked.setObjectName("btnSecondary")
        self.btn_clear_marked.setFixedHeight(32)
        self.btn_clear_marked.setMinimumWidth(72)
        self.btn_clear_marked.setCursor(Qt.PointingHandCursor)
        self.btn_clear_marked.setToolTip("Limpar seleção de clientes marcados")
        self.btn_clear_marked.clicked.connect(self._clear_marcados)

        self.lbl_marked = QLabel("Marcados: 0")
        self.lbl_marked.setObjectName("actionStripMeta")

        self.btn_voltar = QPushButton("Voltar")
        self.btn_voltar.setObjectName("btnSecondary")
        self.btn_voltar.setFixedHeight(36)
        self.btn_voltar.setMinimumWidth(62)
        self.btn_voltar.setCursor(Qt.PointingHandCursor)
        self.btn_voltar.setToolTip("Voltar para a tela anterior")
        self.btn_voltar.clicked.connect(self.voltar_signal.emit)

        top.addWidget(self.btn_voltar)
        root.addLayout(top)

        action_strip = QFrame()
        action_strip.setObjectName("actionStrip")
        action_row = QHBoxLayout(action_strip)
        action_row.setContentsMargins(12, 10, 12, 10)
        action_row.setSpacing(10)

        self.grp_actions_selected = QFrame()
        self.grp_actions_selected.setObjectName("actionGroup")
        grp_sel_l = QHBoxLayout(self.grp_actions_selected)
        grp_sel_l.setContentsMargins(10, 8, 10, 8)
        grp_sel_l.setSpacing(8)
        self.lbl_group_selected = QLabel("Selecionado")
        self.lbl_group_selected.setObjectName("actionGroupTitle")
        grp_sel_l.addWidget(self.lbl_group_selected)
        grp_sel_l.addWidget(self.btn_editar_sel)
        grp_sel_l.addWidget(self.btn_reajuste_sel)
        grp_sel_l.addWidget(self.btn_email_sel)

        self.grp_actions_batch = QFrame()
        self.grp_actions_batch.setObjectName("actionGroup")
        grp_batch_l = QHBoxLayout(self.grp_actions_batch)
        grp_batch_l.setContentsMargins(10, 8, 10, 8)
        grp_batch_l.setSpacing(8)
        self.lbl_group_batch = QLabel("Lote")
        self.lbl_group_batch.setObjectName("actionGroupTitle")
        grp_batch_l.addWidget(self.lbl_group_batch)
        grp_batch_l.addWidget(self.btn_mark_visible)
        grp_batch_l.addWidget(self.btn_clear_marked)
        grp_batch_l.addWidget(self.lbl_marked)

        self.grp_actions_critical = QFrame()
        self.grp_actions_critical.setObjectName("actionGroupCritical")
        grp_critical_l = QHBoxLayout(self.grp_actions_critical)
        grp_critical_l.setContentsMargins(10, 8, 10, 8)
        grp_critical_l.setSpacing(8)
        self.lbl_group_critical = QLabel("Críticas")
        self.lbl_group_critical.setObjectName("actionGroupTitleWarn")
        grp_critical_l.addWidget(self.lbl_group_critical)
        grp_critical_l.addWidget(self.btn_cancelar_sel)
        grp_critical_l.addWidget(self.btn_excluir_sel)

        self.grp_actions_create = QFrame()
        self.grp_actions_create.setObjectName("actionGroup")
        grp_create_l = QHBoxLayout(self.grp_actions_create)
        grp_create_l.setContentsMargins(10, 8, 10, 8)
        grp_create_l.setSpacing(8)
        self.lbl_group_create = QLabel("Cadastro")
        self.lbl_group_create.setObjectName("actionGroupTitle")
        grp_create_l.addWidget(self.lbl_group_create)
        grp_create_l.addWidget(self.btn_novo)

        action_row.addWidget(self.grp_actions_selected, 0)
        action_row.addWidget(self.grp_actions_batch, 0)
        action_row.addWidget(self.grp_actions_critical, 0)
        action_row.addStretch(1)
        action_row.addWidget(self.grp_actions_create, 0)
        root.addWidget(action_strip)

        line = QFrame()
        line.setObjectName("softLine")
        line.setFixedHeight(1)
        root.addWidget(line)

        # Chips
        chips = QHBoxLayout()
        chips.setSpacing(10)
        self.chip_total    = QLabel("Total: —");    self.chip_total.setObjectName("statChip")
        self.chip_ativo    = QLabel("Ativos: —");   self.chip_ativo.setObjectName("statChipOk")
        self.chip_inativo  = QLabel("Inativos: —"); self.chip_inativo.setObjectName("statChipMuted")
        self.chip_em_dia   = QLabel("Em dia: —");   self.chip_em_dia.setObjectName("statChipInfo")
        self.chip_atrasado = QLabel("Atrasados: —");self.chip_atrasado.setObjectName("statChipWarn")
        for c in (self.chip_total, self.chip_ativo, self.chip_inativo, self.chip_em_dia, self.chip_atrasado):
            chips.addWidget(c)
        chips.addStretch()
        root.addLayout(chips)

        # Filtros
        filters = QHBoxLayout()
        filters.setSpacing(10)

        self.search = QLineEdit()
        self.search.setObjectName("fieldInput")
        self.search.setPlaceholderText("Buscar por MAT, nome ou CPF…")
        self.search.setFixedHeight(42)
        self.search.setAccessibleName("Campo de busca de clientes")
        self.search.textChanged.connect(lambda: self._search_debounce.start(300))

        self.btn_clear = QToolButton()
        self.btn_clear.setObjectName("iconBtn")
        self.btn_clear.setText("✕")
        self.btn_clear.setToolTip("Limpar busca")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.clicked.connect(self._clear_search)

        search_wrap = QFrame()
        search_wrap.setObjectName("searchWrap")
        sw = QHBoxLayout(search_wrap)
        sw.setContentsMargins(12, 0, 10, 0)
        sw.setSpacing(6)
        sw.addWidget(self.search, 1)
        sw.addWidget(self.btn_clear)

        self.filter_status = StyledComboBox()
        self.filter_status.setObjectName("filterCombo")
        self.filter_status.setFixedHeight(42)
        self.filter_status.addItems(["status: todos", "ativo", "inativo"])
        self.filter_status.currentIndexChanged.connect(self._on_filter_changed)

        self.filter_pag = StyledComboBox()
        self.filter_pag.setObjectName("filterCombo")
        self.filter_pag.setFixedHeight(42)
        self.filter_pag.addItems(["pagamento: todos", "em_dia", "atrasado"])
        self.filter_pag.currentIndexChanged.connect(self._on_filter_changed)

        self.page_size_combo = StyledComboBox()
        self.page_size_combo.setObjectName("filterCombo")
        self.page_size_combo.setFixedHeight(42)
        self.page_size_combo.addItems(["30 / página", "50 / página", "100 / página"])
        self.page_size_combo.currentIndexChanged.connect(self._on_page_size_changed)

        self.btn_reload = QPushButton("Atualizar")
        self.btn_reload.setObjectName("btnSecondary")
        self.btn_reload.setFixedHeight(42)
        self.btn_reload.setCursor(Qt.PointingHandCursor)
        self.btn_reload.clicked.connect(self.reload)

        self.btn_clear_filters = QPushButton("Limpar filtros")
        self.btn_clear_filters.setObjectName("btnSecondary")
        self.btn_clear_filters.setFixedHeight(42)
        self.btn_clear_filters.setCursor(Qt.PointingHandCursor)
        self.btn_clear_filters.clicked.connect(self._clear_all_filters)

        filters.addWidget(search_wrap, 1)
        filters.addWidget(self.filter_status)
        filters.addWidget(self.filter_pag)
        filters.addWidget(self.page_size_combo)
        filters.addWidget(self.btn_clear_filters)
        filters.addWidget(self.btn_reload)
        root.addLayout(filters)

        # Card tabela
        self.card_table = QFrame()
        self.card_table.setObjectName("card")
        table_layout = QVBoxLayout(self.card_table)
        table_layout.setContentsMargins(14, 14, 14, 14)
        table_layout.setSpacing(10)

        # Stack: tabela | overlay loading
        self._table_stack = QStackedWidget()

        table_page = QFrame()
        table_page.setObjectName("tablePage")
        tpl = QVBoxLayout(table_page)
        tpl.setContentsMargins(0, 0, 0, 0)
        tpl.setSpacing(0)

        self.table = QTableWidget(0, 10)
        self.table.setObjectName("table")
        self.table.setHorizontalHeaderLabels(["", "MAT", "Nome", "CPF", "Status", "Pagamento", "Último Pagto", "Mês Ref.", "Valor", "Contrato"])
        self.table.setSortingEnabled(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setAlternatingRowColors(True)
        self.table.setMouseTracking(True)
        vheader = self.table.verticalHeader()
        vheader.setVisible(False)
        vheader.setDefaultSectionSize(44)
        vheader.setMinimumSectionSize(40)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.setAccessibleName("Lista de clientes")
        self.table.setAccessibleDescription(
            "Tabela com seleção por checkbox, matrícula, nome, CPF, status, pagamento, último pagamento e contrato."
        )

        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionsClickable(False)
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setSectionResizeMode(self.COL_SEL, QHeaderView.Fixed)
        header.setSectionResizeMode(self.COL_NOME, QHeaderView.Stretch)
        for col in (self.COL_MAT, self.COL_CPF, self.COL_STATUS, self.COL_PAG, self.COL_ULT_PAG, self.COL_MES_REF, self.COL_VALOR):
            header.setSectionResizeMode(col, QHeaderView.Fixed)
        header.setSectionResizeMode(self.COL_CONTRATO, QHeaderView.Fixed)
        self._apply_table_column_widths()

        self.table.setMinimumHeight(220)
        self.table.itemSelectionChanged.connect(self._on_select_row)
        self.table.itemDoubleClicked.connect(self._editar_selecionado)
        self.table.customContextMenuRequested.connect(self._open_context_menu)
        tpl.addWidget(self.table)

        self._loading_page = QFrame()
        self._loading_page.setObjectName("loadingPage")
        ll = QVBoxLayout(self._loading_page)
        ll.setAlignment(Qt.AlignCenter)
        self._loading_label = QLabel("Carregando…")
        self._loading_label.setObjectName("loadingLabel")
        self._loading_label.setAlignment(Qt.AlignCenter)
        ll.addWidget(self._loading_label)

        self._empty_page = QFrame()
        self._empty_page.setObjectName("emptyPage")
        el = QVBoxLayout(self._empty_page)
        el.setAlignment(Qt.AlignCenter)
        el.setSpacing(6)
        self._empty_title = QLabel("Nenhum cliente encontrado")
        self._empty_title.setObjectName("emptyStateTitle")
        self._empty_title.setAlignment(Qt.AlignCenter)
        self._empty_sub = QLabel("Ajuste os filtros ou limpe a busca para visualizar resultados.")
        self._empty_sub.setObjectName("emptyStateSub")
        self._empty_sub.setAlignment(Qt.AlignCenter)
        self._empty_sub.setWordWrap(True)
        el.addWidget(self._empty_title)
        el.addWidget(self._empty_sub)

        self._table_stack.addWidget(table_page)
        self._table_stack.addWidget(self._loading_page)
        self._table_stack.addWidget(self._empty_page)
        self._table_stack.setCurrentIndex(0)
        table_layout.addWidget(self._table_stack)

        # Pager
        pager = QHBoxLayout()
        pager.setSpacing(10)
        self.lbl_visible = QLabel(""); self.lbl_visible.setObjectName("pagerText")
        self.lbl_pager   = QLabel(""); self.lbl_pager.setObjectName("pagerText")
        self.btn_prev = QPushButton("◀ Anterior"); self.btn_prev.setObjectName("btnSecondary"); self.btn_prev.setFixedHeight(38); self.btn_prev.clicked.connect(self._prev_page)
        self.btn_next = QPushButton("Próxima ▶");  self.btn_next.setObjectName("btnSecondary"); self.btn_next.setFixedHeight(38); self.btn_next.clicked.connect(self._next_page)
        pager.addWidget(self.lbl_visible); pager.addStretch()
        pager.addWidget(self.lbl_pager); pager.addWidget(self.btn_prev); pager.addWidget(self.btn_next)
        table_layout.addLayout(pager)

        # Painel lateral
        self.card_side = QFrame()
        self.card_side.setObjectName("sideCard")
        self.card_side.setMinimumWidth(180)
        self.card_side.setMaximumWidth(320)
        self.card_side.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        side_outer = QVBoxLayout(self.card_side)
        side_outer.setContentsMargins(0, 0, 0, 0)
        side_outer.setSpacing(0)

        self.side_scroll = QScrollArea()
        self.side_scroll.setObjectName("sideScroll")
        self.side_scroll.setWidgetResizable(True)
        self.side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.side_scroll.setFrameShape(QFrame.NoFrame)

        self.side_inner = QFrame()
        self.side_inner.setObjectName("sideInner")
        self.side_scroll.setWidget(self.side_inner)

        sl = QVBoxLayout(self.side_inner)
        sl.setContentsMargins(16, 16, 16, 16)
        sl.setSpacing(10)

        self.side_title = QLabel("Detalhes do Cliente"); self.side_title.setObjectName("sideTitle")
        self.side_sub   = QLabel("Selecione um cliente na tabela."); self.side_sub.setObjectName("sideSub"); self.side_sub.setWordWrap(True)
        sl.addWidget(self.side_title); sl.addWidget(self.side_sub)

        def _div():
            d = QFrame(); d.setObjectName("divider"); d.setFixedHeight(1); return d

        sl.addWidget(_div())

        # Seção: Identificação
        sl.addWidget(_SectionHeader("Identificação"))
        self.det_mat             = self._detail_field("MAT (Matrícula)")
        self.det_nome            = self._detail_field("Nome")
        self.det_cpf             = self._detail_field("CPF")
        self.det_telefone        = self._detail_field("Telefone")
        self.det_email           = self._detail_field("E-mail")
        self.det_data_nascimento = self._detail_field("Data de nascimento")
        for w in (self.det_mat, self.det_nome, self.det_cpf, self.det_telefone, self.det_email, self.det_data_nascimento):
            sl.addWidget(w)

        sl.addWidget(_div())

        # Seção: Contrato
        sl.addWidget(_SectionHeader("Contrato"))
        self.det_status      = self._detail_field("Status")
        self.det_pag         = self._detail_field("Pagamento")
        self.det_plano       = self._detail_field("Plano")
        self.det_dependentes = self._detail_field("Qtde. de dependentes")
        self.det_vencimento  = self._detail_field("Vencimento")
        self.det_forma_pag   = self._detail_field("Forma de pagamento")
        self.det_data_inicio = self._detail_field("Data de início")
        for w in (self.det_status, self.det_pag, self.det_plano, self.det_dependentes,
                  self.det_vencimento, self.det_forma_pag, self.det_data_inicio):
            sl.addWidget(w)

        sl.addWidget(_div())

        # Seção: Endereço
        sl.addWidget(_SectionHeader("Endereço"))
        self.det_cep     = self._detail_field("CEP")
        self.det_endereco = self._detail_field("Endereço")
        sl.addWidget(self.det_cep); sl.addWidget(self.det_endereco)

        sl.addWidget(_div())

        # Seção: Último Pagamento
        sl.addWidget(_SectionHeader("Último Pagamento"))
        self.det_ult = self._detail_field("Data")
        self.det_mes = self._detail_field("Mês Referência")
        self.det_val = self._detail_field("Valor")
        for w in (self.det_ult, self.det_mes, self.det_val):
            sl.addWidget(w)

        sl.addWidget(_div())

        # Seção: Observações
        sl.addWidget(_SectionHeader("Observações"))
        self.det_obs = self._detail_field("Observações")
        sl.addWidget(self.det_obs)

        sl.addWidget(_div())

        # Seção: Timeline
        sl.addWidget(_SectionHeader("Timeline"))
        self.timeline_items: list[QLabel] = []
        for _ in range(4):
            t = QLabel("—")
            t.setObjectName("timelineItem")
            t.setWordWrap(True)
            t.setProperty("tone", "muted")
            self.timeline_items.append(t)
            sl.addWidget(t)

        sl.addWidget(_div())

        # Seção: Dependentes
        dep_hdr = QHBoxLayout(); dep_hdr.setSpacing(10)
        self.dep_title = QLabel("Dependentes"); self.dep_title.setObjectName("sectionTitle")
        self.dep_count = QLabel("0"); self.dep_count.setObjectName("countChip")
        dep_hdr.addWidget(self.dep_title); dep_hdr.addWidget(self.dep_count); dep_hdr.addStretch()
        sl.addLayout(dep_hdr)

        self.dep_hint = QLabel("Nenhum dependente cadastrado.")
        self.dep_hint.setObjectName("mutedText"); self.dep_hint.setWordWrap(True)
        sl.addWidget(self.dep_hint)

        self.dep_list_wrap = QFrame(); self.dep_list_wrap.setObjectName("depListWrap")
        dwl = QVBoxLayout(self.dep_list_wrap); dwl.setContentsMargins(0, 0, 0, 0); dwl.setSpacing(8)
        self.dep_list_container = QVBoxLayout(); self.dep_list_container.setContentsMargins(0, 0, 0, 0); self.dep_list_container.setSpacing(8)
        dwl.addLayout(self.dep_list_container)
        sl.addWidget(self.dep_list_wrap)

        quick = QGridLayout(); quick.setHorizontalSpacing(10); quick.setVerticalSpacing(8)
        self.btn_quick_edit = QPushButton("Editar"); self.btn_quick_edit.setObjectName("btnSecondary"); self.btn_quick_edit.setFixedHeight(40); self.btn_quick_edit.setCursor(Qt.PointingHandCursor); self.btn_quick_edit.setAccessibleName("Editar cliente (painel lateral)"); self.btn_quick_edit.setToolTip("Editar cliente selecionado"); self.btn_quick_edit.clicked.connect(self._editar_selecionado)
        self.btn_quick_cancel = QPushButton("Cancelar"); self.btn_quick_cancel.setObjectName("btnDanger"); self.btn_quick_cancel.setFixedHeight(40); self.btn_quick_cancel.setCursor(Qt.PointingHandCursor); self.btn_quick_cancel.setAccessibleName("Cancelar plano do cliente (painel lateral)"); self.btn_quick_cancel.setToolTip("Cancelar plano do cliente selecionado"); self.btn_quick_cancel.clicked.connect(self._cancelar_plano_selecionado)
        self.btn_quick_email = QPushButton("E-mail"); self.btn_quick_email.setObjectName("btnAccentSoft"); self.btn_quick_email.setFixedHeight(40); self.btn_quick_email.setCursor(Qt.PointingHandCursor); self.btn_quick_email.setAccessibleName("Enviar e-mail para cliente (painel lateral)"); self.btn_quick_email.setToolTip("Enviar e-mail para cliente selecionado"); self.btn_quick_email.clicked.connect(self._enviar_email_selecionado)
        self.btn_quick_del  = QPushButton("Excluir"); self.btn_quick_del.setObjectName("btnDanger");    self.btn_quick_del.setFixedHeight(40);  self.btn_quick_del.setCursor(Qt.PointingHandCursor);  self.btn_quick_del.setAccessibleName("Excluir cliente (painel lateral)");  self.btn_quick_del.setToolTip("Excluir cliente selecionado");  self.btn_quick_del.clicked.connect(self._excluir_selecionado)
        quick.addWidget(self.btn_quick_edit, 0, 0)
        quick.addWidget(self.btn_quick_email, 0, 1)
        quick.addWidget(self.btn_quick_cancel, 1, 0)
        quick.addWidget(self.btn_quick_del, 1, 1)
        quick.setColumnStretch(0, 1)
        quick.setColumnStretch(1, 1)
        sl.addLayout(quick); sl.addStretch()

        side_outer.addWidget(self.side_scroll)

        self.inline_msg = QLabel("")
        self.inline_msg.setObjectName("inlineMessage")
        self.inline_msg.setVisible(False)

        self.content_splitter = QSplitter(Qt.Horizontal)
        self.content_splitter.setObjectName("contentSplitter")
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(0)
        self.content_splitter.addWidget(self.card_table)
        self.content_splitter.addWidget(self.card_side)
        self.content_splitter.setStretchFactor(0, 8)
        self.content_splitter.setStretchFactor(1, 2)
        self.content_splitter.setSizes([1250, 260])
        try:
            splitter_handle = self.content_splitter.handle(1)
            splitter_handle.setEnabled(False)
            splitter_handle.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        except Exception:
            pass
        root.addWidget(self.content_splitter, 1)
        root.addWidget(self.inline_msg)

        self._sync_action_group_visibility()
        self._set_actions_enabled(False)
        self._sync_marcados_ui()
        self._clear_dependentes_ui()

    def _detail_field(self, label_text: str) -> QFrame:
        wrap = QFrame(); wrap.setObjectName("detailWrap")
        lay = QVBoxLayout(wrap); lay.setContentsMargins(12, 10, 12, 10); lay.setSpacing(4)
        lab = QLabel(label_text); lab.setObjectName("detailLabel")
        val = QLabel("-"); val.setObjectName("detailValue"); val.setWordWrap(True)
        lay.addWidget(lab); lay.addWidget(val)
        wrap._value_label = val
        return wrap

    def _set_detail(self, field: QFrame, value: str):
        field._value_label.setText(value if value else "-")

    def _set_timeline(self, rows: list[str] | None):
        items = list(rows or [])[:4]
        for idx, lbl in enumerate(self.timeline_items):
            if idx < len(items):
                lbl.setText(str(items[idx] or "").strip() or "—")
                lbl.setProperty("tone", "normal")
            else:
                lbl.setText("—")
                lbl.setProperty("tone", "muted")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

    def _wire_shortcuts(self):
        shortcuts = [
            ("F5",       self.reload),
            ("Ctrl+F",   lambda: self.search.setFocus()),
            ("Escape",   self._clear_search),
            ("Ctrl+E",   self._editar_selecionado),
            ("Delete",   self._excluir_selecionado),
            ("Ctrl+N",   self._novo_cliente),
        ]
        for key, slot in shortcuts:
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(slot)

    def _apply_card_shadow(self):
        for card in (self.card_table, self.card_side):
            try:
                sh = QGraphicsDropShadowEffect(card)
                sh.setBlurRadius(34); sh.setOffset(0, 10)
                sh.setColor(QColor(15, 23, 42, 28))
                card.setGraphicsEffect(sh)
            except Exception:
                pass

    def _apply_table_column_widths(self):
        self.table.setColumnWidth(self.COL_SEL, 46)
        self.table.setColumnWidth(self.COL_MAT, 70)
        self.table.setColumnWidth(self.COL_CPF, 116)
        self.table.setColumnWidth(self.COL_STATUS, 96)
        self.table.setColumnWidth(self.COL_PAG, 100)
        self.table.setColumnWidth(self.COL_ULT_PAG, 98)
        self.table.setColumnWidth(self.COL_MES_REF, 82)
        self.table.setColumnWidth(self.COL_VALOR, 104)
        self.table.setColumnWidth(self.COL_CONTRATO, max(40, self._contract_col_min_width))

    def _apply_responsive_layout(self):
        if not hasattr(self, "content_splitter"):
            return
        w = max(1, int(self.width()))
        h = max(1, int(self.height()))
        ratio = float(w) / float(h)
        compact = bool(w < 1320 or h < 740 or ratio < 1.25)
        tiny = bool(w < 980 or h < 620 or ratio < 0.9)

        self._compact_layout = compact
        if hasattr(self, "_root_layout"):
            if tiny:
                self._root_layout.setContentsMargins(8, 8, 8, 8)
                self._root_layout.setSpacing(8)
            elif compact:
                self._root_layout.setContentsMargins(14, 12, 14, 12)
                self._root_layout.setSpacing(10)
            else:
                self._root_layout.setContentsMargins(24, 18, 24, 18)
                self._root_layout.setSpacing(12)

        if tiny:
            self.content_splitter.setOrientation(Qt.Vertical)
            self.card_side.setMinimumWidth(0)
            self.card_side.setMaximumWidth(16777215)
            self.card_side.setMinimumHeight(220)
            self.card_side.setMaximumHeight(420)
            self.content_splitter.setSizes([620, 220])
        elif compact:
            self.content_splitter.setOrientation(Qt.Vertical)
            self.card_side.setMinimumWidth(0)
            self.card_side.setMaximumWidth(16777215)
            self.card_side.setMinimumHeight(280)
            self.card_side.setMaximumHeight(460)
            self.content_splitter.setSizes([740, 250])
        else:
            self.content_splitter.setOrientation(Qt.Horizontal)
            self.card_side.setMinimumHeight(0)
            self.card_side.setMaximumHeight(16777215)
            self.card_side.setMinimumWidth(180)
            self.card_side.setMaximumWidth(320)
            self.content_splitter.setSizes([1250, 260])

        show_group_titles = not tiny
        for lab in (
            getattr(self, "lbl_group_selected", None),
            getattr(self, "lbl_group_batch", None),
            getattr(self, "lbl_group_critical", None),
            getattr(self, "lbl_group_create", None),
        ):
            if lab is not None:
                lab.setVisible(show_group_titles)

        if tiny:
            self.btn_novo.setText("+")
            self.btn_reajuste_sel.setText("Reaj.")
            self.btn_cancelar_sel.setText("Canc.")
            self.btn_mark_visible.setMinimumWidth(72)
            self.btn_clear_marked.setMinimumWidth(72)
        else:
            self.btn_novo.setText("+ Novo")
            self.btn_reajuste_sel.setText("Reajuste")
            self.btn_cancelar_sel.setText("Cancelar")
            self.btn_mark_visible.setMinimumWidth(92)
            self.btn_clear_marked.setMinimumWidth(98)

        self._sync_marcados_ui()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def _set_actions_enabled(self, enabled: bool):
        can_cancel = enabled and self._can_edit_cliente and self._current_status != "inativo"
        self.btn_editar_sel.setEnabled(enabled and self._can_edit_cliente)
        self.btn_cancelar_sel.setEnabled(can_cancel)
        self.btn_quick_edit.setEnabled(enabled and self._can_edit_cliente)
        self.btn_quick_cancel.setEnabled(can_cancel)
        self.btn_email_sel.setEnabled(enabled and self._can_send_email)
        self.btn_quick_email.setEnabled(enabled and self._can_send_email)
        self.btn_excluir_sel.setEnabled(enabled and self._can_delete_cliente)
        self.btn_quick_del.setEnabled(enabled and self._can_delete_cliente)

    # ─────────────────────────────────────────
    # Menu de contexto
    # ─────────────────────────────────────────
    def _open_context_menu(self, pos: QPoint):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        self.table.selectRow(row)
        status_row = self._status_from_table_row(row)
        menu = QMenu(self); menu.setObjectName("tableMenu")
        act_delete = QAction("Excluir cliente", self)
        act_reload = QAction("Atualizar lista", self)
        act_email = QAction("Enviar e-mail", self)
        act_delete.triggered.connect(self._excluir_selecionado)
        act_reload.triggered.connect(self.reload)
        act_email.triggered.connect(self._enviar_email_selecionado)
        if self._can_edit_cliente:
            act_edit = QAction("Editar cliente", self)
            act_edit.triggered.connect(self._editar_selecionado)
            menu.addAction(act_edit)
            act_cancel = QAction("Cancelar plano", self)
            act_cancel.setEnabled(status_row != "inativo")
            act_cancel.triggered.connect(self._cancelar_plano_selecionado)
            menu.addAction(act_cancel)
        if self._can_send_email:
            menu.addAction(act_email)
        act_contract = QAction("Baixar contrato", self)
        act_contract.triggered.connect(self._baixar_contrato_selecionado)
        menu.addAction(act_contract)
        if self._can_delete_cliente:
            menu.addAction(act_delete)
        menu.addSeparator(); menu.addAction(act_reload)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ─────────────────────────────────────────
    # Paginação
    # ─────────────────────────────────────────
    def _prev_page(self):
        if self._pagination.go_prev():
            self._persist_view_state()
            self.reload()

    def _next_page(self):
        if self._pagination.go_next():
            self._persist_view_state()
            self.reload()

    def _update_pager(self):
        p = self._pagination
        max_pg = p.max_page + 1
        self.lbl_pager.setText(f"Página {p.page + 1} de {max_pg} • Total {p.total}")
        self.btn_prev.setEnabled(p.page > 0)
        self.btn_next.setEnabled(p.page < p.max_page)

    def _on_page_size_changed(self):
        new_size = 50 if "50" in self.page_size_combo.currentText() else (100 if "100" in self.page_size_combo.currentText() else 30)
        if new_size == self._pagination.page_size:
            return
        self._pagination.page_size = new_size
        self._pagination.reset()
        self._persist_view_state()
        self.reload()

    def _on_search_changed(self):
        t = self.search.text().strip()
        self._search_mode = "server" if t else "local"
        self._pagination.reset()
        self._persist_view_state()
        self.reload()

    def _on_filter_changed(self):
        self._pagination.reset()
        self._persist_view_state()
        self.reload()

    # ─────────────────────────────────────────
    # Reload (assíncrono)
    # ─────────────────────────────────────────
    def reload(self):
        if self._loading:
            self._reload_pending = True
            return

        self._reload_seq += 1
        seq = int(self._reload_seq)
        self._reload_pending = False
        self._show_loading(True)
        p = self._pagination

        def _fetch():
            search_text = self.search.text().strip()
            status = self.filter_status.currentText()
            pag    = self.filter_pag.currentText()
            status = "" if status.startswith("status:") else status
            pag    = "" if pag.startswith("pagamento:") else pag
            search_db = search_text if (search_text and self._search_mode == "server") else ""
            total  = int(db.contar_clientes(search=search_db, status=status, pagamento=pag) or 0)
            kw = dict(limit=p.page_size, offset=p.offset, status=status, pagamento=pag)
            if search_db:
                kw.update(search=search_db)
            rows = db.listar_clientes_com_ultimo_pagamento(**kw)
            return {
                "seq": seq,
                "total": total,
                "rows": rows,
                "status_filter": status,
                "pag_filter": pag,
                "search_text": search_text,
            }

        worker = _DbWorker(_fetch)
        worker.signals.result.connect(self._on_reload_done)
        worker.signals.error.connect(lambda msg, s=seq: self._on_reload_error(s, msg))
        self.threadpool.start(worker)

    @Slot(object)
    def _on_reload_done(self, result):
        seq = int((result or {}).get("seq", 0) or 0)
        if seq != self._reload_seq:
            return
        total = int((result or {}).get("total", 0) or 0)
        rows = (result or {}).get("rows", []) or []
        status_filter = str((result or {}).get("status_filter", "") or "")
        pag_filter = str((result or {}).get("pag_filter", "") or "")
        search_text = str((result or {}).get("search_text", "") or "")
        self._pagination.total = total
        self._persist_view_state()
        self._populate(rows, status_filter, pag_filter, search_text)
        self._update_pager()
        self._show_loading(False)
        if self.table.rowCount() > 0:
            self._show_message("Lista atualizada.", ok=True, ms=1400)
        else:
            self._show_message("")
        if self._reload_pending:
            self._reload_pending = False
            self.reload()

    def _on_reload_error(self, seq: int, error_msg: str):
        if int(seq or 0) != self._reload_seq:
            return
        self._show_loading(False)
        if self.table.rowCount() == 0:
            self._set_table_state(
                "empty",
                title="Falha ao carregar clientes",
                subtitle="Não foi possível consultar os dados agora. Tente atualizar novamente.",
                tone="error",
            )
        self._show_message(f"Erro ao carregar clientes: {error_msg}", ok=False)
        if self._reload_pending:
            self._reload_pending = False
            self.reload()

    def _show_loading(self, loading: bool):
        self._loading = bool(loading)
        if loading:
            self._set_table_state("loading")
        elif self.table.rowCount() == 0:
            if self._table_stack.currentIndex() != 2:
                self._set_table_state(
                    "empty",
                    title="Nenhum cliente encontrado",
                    subtitle="Ajuste os filtros ou limpe a busca para visualizar resultados.",
                )
        else:
            self._set_table_state("table")
        for btn in (self.btn_reload, self.btn_prev, self.btn_next):
            btn.setEnabled(not loading)

    def _set_table_state(self, state: str, *, title: str = "", subtitle: str = "", tone: str = "default"):
        key = str(state or "").strip().lower()
        if key == "loading":
            self._table_stack.setCurrentIndex(1)
            return
        if key == "empty":
            self._empty_title.setText(str(title or "Nenhum cliente encontrado"))
            self._empty_sub.setText(str(subtitle or "Ajuste os filtros para visualizar resultados."))
            self._empty_title.setProperty("tone", tone or "default")
            self._empty_title.style().unpolish(self._empty_title)
            self._empty_title.style().polish(self._empty_title)
            self._table_stack.setCurrentIndex(2)
            return
        self._table_stack.setCurrentIndex(0)

    # ─────────────────────────────────────────
    # Populate — sem iteração dupla
    # ─────────────────────────────────────────
    def _populate(self, rows, status_filter: str, pag_filter: str, search_text: str):
        self.table.setRowCount(0)
        self.current_mat = None
        self._current_status = ""
        self._set_actions_enabled(False)
        self._clear_details()
        self._clear_dependentes_ui()

        stats = {"total": 0, "ativo": 0, "inativo": 0, "em_dia": 0, "atrasado": 0}
        search_lower = search_text.lower()
        first_visible = None

        for raw in rows:
            c = _map_list_row(raw)

            if self._search_mode == "local" and search_lower:
                if not (search_lower in str(c["mat"]).lower()
                        or search_lower in c["nome"].lower()
                        or search_lower in c["cpf"].lower()):
                    continue

            if status_filter and c["status"] != status_filter:
                continue
            if pag_filter:
                if pag_filter == "em_dia" and c["pag_status"] != "em_dia":
                    continue
                if pag_filter == "atrasado" and c["pag_status"] != "atrasado":
                    continue

            stats["total"] += 1
            if c["status"] == "ativo":       stats["ativo"] += 1
            elif c["status"] == "inativo":   stats["inativo"] += 1
            if c["pag_status"] == "em_dia":      stats["em_dia"] += 1
            elif c["pag_status"] == "atrasado":  stats["atrasado"] += 1

            row_idx = self.table.rowCount()
            self.table.insertRow(row_idx)
            self._set_select_checkbox(row_idx, int(c["mat"]))
            self._set_item(row_idx, self.COL_MAT, str(c["mat"]), center=True)
            self._set_item(row_idx, self.COL_NOME, c["nome"])
            self._set_item(row_idx, self.COL_CPF, c["cpf"], center=True)
            self._set_status_pill(row_idx, self.COL_STATUS, c["status"])
            self._set_pag_pill(row_idx, self.COL_PAG, c["pag_status"])
            self._set_item(row_idx, self.COL_ULT_PAG, br_date(c["data_pagamento"]), center=True)
            self._set_item(row_idx, self.COL_MES_REF, br_month_ref(c["mes_ref"]), center=True)
            self._set_item(row_idx, self.COL_VALOR, "-" if c["valor_pago"] is None else br_money(c["valor_pago"]), center=True)
            self._set_contract_btn(row_idx, int(c["mat"]))

            if first_visible is None:
                first_visible = row_idx

        self._stats = stats
        self._sync_stats_chips()
        self.lbl_visible.setText(f"Visíveis: {stats['total']}")

        if first_visible is not None:
            self.table.selectRow(first_visible)
            self._set_table_state("table")
        else:
            has_filter = bool((search_text or "").strip() or (status_filter or "").strip() or (pag_filter or "").strip())
            if has_filter:
                self._set_table_state(
                    "empty",
                    title="Nenhum cliente encontrado",
                    subtitle="Tente remover filtros ou ajustar o termo de busca.",
                )
            else:
                self._set_table_state(
                    "empty",
                    title="Sem clientes cadastrados",
                    subtitle="Use “+ Novo” para cadastrar o primeiro cliente.",
                )

        self._apply_table_column_widths()
        try:
            self.table.horizontalScrollBar().setValue(0)
        except Exception:
            pass
        self._sync_marcados_ui()

    def _sync_stats_chips(self):
        s = self._stats
        self.chip_total.setText(f"Total: {s.get('total',0)}")
        self.chip_ativo.setText(f"Ativos: {s.get('ativo',0)}")
        self.chip_inativo.setText(f"Inativos: {s.get('inativo',0)}")
        self.chip_em_dia.setText(f"Em dia: {s.get('em_dia',0)}")
        self.chip_atrasado.setText(f"Atrasados: {s.get('atrasado',0)}")

    def _set_item(self, row, col, text, center=False):
        it = QTableWidgetItem(text)
        if center: it.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, col, it)

    def _set_select_checkbox(self, row: int, mat: int):
        wrap = QFrame()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignCenter)

        chk = QCheckBox()
        chk.setObjectName("rowSelectCheck")
        chk.setChecked(int(mat) in self._checked_mats)
        chk.setToolTip(f"Selecionar cliente MAT {mat} para reajuste em lote")
        chk.toggled.connect(lambda checked, m=int(mat): self._on_checkbox_marcado(m, checked))
        lay.addWidget(chk, 0, Qt.AlignCenter)
        self.table.setCellWidget(row, self.COL_SEL, wrap)

    def _on_checkbox_marcado(self, mat: int, checked: bool):
        if checked:
            self._checked_mats.add(int(mat))
        else:
            self._checked_mats.discard(int(mat))
        self._sync_marcados_ui()

    def _visible_mats(self) -> list[int]:
        mats: list[int] = []
        for r in range(self.table.rowCount()):
            item = self.table.item(r, self.COL_MAT)
            if not item:
                continue
            try:
                mats.append(int(item.text()))
            except Exception:
                continue
        return mats

    def _toggle_marcar_visiveis(self):
        visible = self._visible_mats()
        if not visible:
            return
        all_marked = all(mat in self._checked_mats for mat in visible)
        mark_target = not all_marked
        for r in range(self.table.rowCount()):
            item = self.table.item(r, self.COL_MAT)
            if not item:
                continue
            try:
                mat = int(item.text())
            except Exception:
                continue
            cell = self.table.cellWidget(r, self.COL_SEL)
            if not cell:
                continue
            chk = cell.findChild(QCheckBox)
            if chk is None:
                continue
            chk.blockSignals(True)
            chk.setChecked(mark_target)
            chk.blockSignals(False)
            if mark_target:
                self._checked_mats.add(mat)
            else:
                self._checked_mats.discard(mat)
        self._sync_marcados_ui()

    def _clear_marcados(self):
        if not self._checked_mats:
            return
        self._checked_mats.clear()
        for r in range(self.table.rowCount()):
            cell = self.table.cellWidget(r, self.COL_SEL)
            if not cell:
                continue
            chk = cell.findChild(QCheckBox)
            if chk is None:
                continue
            chk.blockSignals(True)
            chk.setChecked(False)
            chk.blockSignals(False)
        self._sync_marcados_ui()

    def _sync_marcados_ui(self):
        total = len(self._checked_mats)
        self.lbl_marked.setText(f"Marcados: {total}")
        visible = self._visible_mats()
        all_marked = bool(visible) and all(mat in self._checked_mats for mat in visible)
        if self._compact_layout:
            self.btn_mark_visible.setText("Desmarcar" if all_marked else "Marcar")
            self.btn_clear_marked.setText("Limpar")
        else:
            self.btn_mark_visible.setText("Desmarcar visíveis" if all_marked else "Marcar visíveis")
            self.btn_clear_marked.setText("Limpar marcações")
        self.btn_clear_marked.setEnabled(total > 0)

    def _set_contract_btn(self, row: int, mat: int):
        wrap = QFrame()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignCenter)

        btn = QPushButton("PDF")
        btn.setObjectName("btnRowContract")
        btn.setFixedSize(46, 26)
        btn.setToolTip("Gerar e baixar contrato em PDF")
        btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setAccessibleName(f"Gerar e baixar contrato em PDF do cliente MAT {mat}")
        btn.clicked.connect(lambda _=False, m=int(mat), r=int(row): self._baixar_contrato_da_linha(m, r))

        lay.addWidget(btn)
        self.table.setCellWidget(row, self.COL_CONTRATO, wrap)
        margins = lay.contentsMargins()
        needed = btn.width() + margins.left() + margins.right()
        if needed > self._contract_col_min_width:
            self._contract_col_min_width = needed
        self.table.setColumnWidth(self.COL_CONTRATO, max(self._contract_col_min_width, self.table.columnWidth(self.COL_CONTRATO)))

    def _baixar_contrato_da_linha(self, mat: int, row: int):
        try:
            if row >= 0:
                self.table.selectRow(int(row))
        except Exception:
            pass
        self.baixar_contrato_signal.emit(int(mat))
        self._show_message(
            f"Gerando contrato em PDF do MAT {mat}. Aguarde a confirmação do download.",
            ok=True,
            ms=2200,
        )

    def _set_status_pill(self, row, col, status: str):
        if status == "ativo":
            it = PillItem("✓ ATIVO", "#065f46", "#dcfce7")
        elif status == "inativo":
            it = PillItem("✕ INATIVO", "#991b1b", "#fee2e2")
        else:
            it = PillItem(status.upper() or "-", "#334155", "#e2e8f0")
        self.table.setItem(row, col, it)

    def _set_pag_pill(self, row, col, pag: str):
        if pag == "em_dia":      it = PillItem("EM DIA",   "#1e3a8a", "#dbeafe")
        elif pag == "atrasado":  it = PillItem("ATRASADO", "#92400e", "#fef3c7")
        else:                    it = PillItem(pag.upper() or "-", "#334155", "#e2e8f0")
        self.table.setItem(row, col, it)

    # ─────────────────────────────────────────
    # Seleção de linha (assíncrona)
    # ─────────────────────────────────────────
    def _on_select_row(self):
        selected = self.table.selectedRanges()
        if not selected:
            self.current_mat = None
            self._current_status = ""
            self._selected_cliente_ctx = None
            self._set_actions_enabled(False)
            self._clear_details()
            self._clear_dependentes_ui()
            return

        r = selected[0].topRow()
        mat_item = self.table.item(r, self.COL_MAT)
        if not mat_item:
            return
        try:
            mat = int(mat_item.text())
        except Exception:
            return

        self.current_mat = mat
        self._current_status = self._status_from_table_row(r)
        self._set_actions_enabled(True)

        def _fetch_detail(target_mat=mat):
            return (
                int(target_mat),
                db.buscar_cliente_por_id(target_mat),
                db.buscar_ultimo_pagamento(target_mat),
                db.listar_dependentes(target_mat),
            )

        worker = _DbWorker(_fetch_detail)
        worker.signals.result.connect(self._on_detail_worker_result)
        worker.signals.error.connect(self._on_detail_worker_error)
        self.threadpool.start(worker)

    @Slot(object)
    def _on_detail_worker_result(self, payload):
        try:
            mat, raw_cliente, raw_pag, raw_deps = payload
        except Exception:
            return
        self._on_detail_loaded(int(mat), (raw_cliente, raw_pag, raw_deps))

    @Slot(str)
    def _on_detail_worker_error(self, error_msg: str):
        self._show_message(f"Erro ao carregar detalhes: {error_msg}", ok=False)

    def _on_detail_loaded(self, mat: int, data):
        if self.current_mat != mat:
            return

        raw_cliente, raw_pag, raw_deps = data

        if not raw_cliente:
            self._show_message("Cliente não encontrado.", ok=False)
            self._clear_details()
            self._clear_dependentes_ui()
            return

        c = _map_cliente_row(raw_cliente)
        self._current_status = (c["status"] or "").strip().lower()
        self.side_sub.setText(f"Cliente selecionado • MAT {mat}")

        self._set_detail(self.det_mat,             safe_text(c["mat"]))
        self._set_detail(self.det_nome,            safe_text(c["nome"]))
        self._set_detail(self.det_cpf,             safe_text(c["cpf"]))
        self._set_detail(self.det_telefone,        safe_text(c["telefone"]))
        self._set_detail(self.det_email,           safe_text(c["email"]))
        self._set_detail(self.det_status,          safe_text(c["status"]).upper())
        self._set_detail(self.det_pag,             safe_text(c["pag_status"]).replace("_", " ").upper())
        self._set_detail(self.det_plano,           safe_text(c["plano"]))
        self._set_detail(self.det_dependentes,     safe_text(c["dependentes"]))
        self._set_detail(self.det_vencimento,      f"Dia {c['vencimento']}" if c["vencimento"] else "-")
        self._set_detail(self.det_forma_pag,       safe_text(c["forma_pagamento"]))
        self._set_detail(self.det_data_inicio,     br_date(c["data_inicio"]))
        self._set_detail(self.det_data_nascimento, br_date(c["data_nascimento"]))
        self._set_detail(self.det_cep,             safe_text(c["cep"]))
        self._set_detail(self.det_endereco,        safe_text(c["endereco"]))
        self._set_detail(self.det_obs,             safe_text(c["observacoes"]))

        pag = _map_pagamento_row(raw_pag)
        if pag:
            self._set_detail(self.det_ult, br_date(pag["data_pagamento"]))
            self._set_detail(self.det_mes, br_month_ref(pag["mes_ref"]))
            self._set_detail(self.det_val, br_money(pag["valor_pago"]))
        else:
            for f in (self.det_ult, self.det_mes, self.det_val):
                self._set_detail(f, "-")

        self._load_dependentes([_map_dependente_row(r) for r in (raw_deps or [])])
        timeline_rows = [
            f"Cadastro iniciado em {br_date(c['data_inicio'])}",
            (
                f"Último pagamento em {br_date(pag['data_pagamento'])}  ·  {br_money(pag['valor_pago'])}"
                if pag
                else "Sem pagamento registrado até o momento."
            ),
            (
                f"Status atual: {safe_text(c['status']).replace('_', ' ').upper()}  ·  "
                f"Pagamento: {safe_text(c['pag_status']).replace('_', ' ').upper()}"
            ),
            f"Plano: {safe_text(c['plano'])}  ·  Vencimento: dia {safe_text(c['vencimento'])}",
        ]
        self._set_timeline(timeline_rows)

        self._selected_cliente_ctx = {
            "mat": mat,
            "nome": c["nome"],
            "titular": c["nome"],
            "email": c["email"],
            "status": c["status"],
            "pag_status": c["pag_status"],
            "pag_status_label": safe_text(c["pag_status"]).replace("_", " ").upper(),
            "plano": c["plano"],
            "vencimento_dia": c["vencimento"],
            "mes_ref_br": br_month_ref(pag["mes_ref"]) if pag else "-",
            "mes_ref_iso": pag["mes_ref"] if pag else datetime.now().strftime("%Y-%m"),
            "data_pagamento_br": br_date(pag["data_pagamento"]) if pag else "-",
            "valor_pago_br": br_money(pag["valor_pago"]) if pag else "-",
            "valor_mensal_br": br_money(c["valor_mensal"]),
        }

        try:
            self.side_scroll.verticalScrollBar().setValue(0)
        except Exception:
            pass

    def _clear_details(self):
        self._current_status = ""
        self._selected_cliente_ctx = None
        self.side_sub.setText("Selecione um cliente na tabela.")
        for f in (self.det_mat, self.det_nome, self.det_cpf, self.det_telefone,
                  self.det_email, self.det_status, self.det_pag, self.det_plano,
                  self.det_dependentes, self.det_vencimento, self.det_forma_pag,
                  self.det_data_inicio, self.det_data_nascimento, self.det_cep,
                  self.det_endereco, self.det_ult, self.det_mes, self.det_val, self.det_obs):
            self._set_detail(f, "-")
        self._set_timeline([])

    def _status_from_table_row(self, row: int) -> str:
        item = self.table.item(row, self.COL_STATUS)
        if not item:
            return ""
        text = (item.text() or "").strip().lower()
        if "inativo" in text:
            return "inativo"
        if "ativo" in text:
            return "ativo"
        return text

    # ─────────────────────────────────────────
    # Dependentes
    # ─────────────────────────────────────────
    def _clear_dependentes_ui(self):
        self.dep_count.setText("0")
        while self.dep_list_container.count():
            item = self.dep_list_container.takeAt(0)
            w = item.widget()
            if w: w.deleteLater()
        self.dep_hint.setVisible(True)
        self.dep_list_wrap.setVisible(False)

    def _load_dependentes(self, deps: List[DependenteRow]):
        while self.dep_list_container.count():
            item = self.dep_list_container.takeAt(0)
            w = item.widget()
            if w: w.deleteLater()

        if not deps:
            self.dep_count.setText("0")
            self.dep_hint.setVisible(True)
            self.dep_list_wrap.setVisible(False)
            return

        self.dep_count.setText(str(len(deps)))
        self.dep_hint.setVisible(False)
        self.dep_list_wrap.setVisible(True)

        for dep in deps:
            card = QFrame(); card.setObjectName("depCard")
            l = QVBoxLayout(card); l.setContentsMargins(12, 10, 12, 10); l.setSpacing(4)
            title = QLabel(dep["nome"] or "—"); title.setObjectName("depName")
            meta  = QLabel(f"ID: {dep['dep_id'] or '-'}  •  CPF: {dep['cpf'] or '-'}  •  Idade: {dep['idade'] or '-'}")
            meta.setObjectName("depMeta"); meta.setWordWrap(True)
            l.addWidget(title); l.addWidget(meta)
            self.dep_list_container.addWidget(card)

    # ─────────────────────────────────────────
    # Botões de ação
    # ─────────────────────────────────────────
    def _novo_cliente(self, *_):
        # RBAC (Recepção): bloqueio também no handler para evitar bypass via atalho/sinal.
        if not self._can_create_cliente:
            self._show_message("Perfil de recepção não pode cadastrar clientes.", ok=False)
            return
        self.novo_signal.emit()

    def _editar_selecionado(self, *_):
        if not self._can_edit_cliente:
            self._show_message("Perfil de recepção não pode editar clientes.", ok=False)
            return
        if not self.current_mat:
            self._show_message("Selecione um cliente primeiro.", ok=False)
            return
        self.editar_signal.emit(int(self.current_mat))
        self._show_message(f"Abrindo edição do MAT {self.current_mat}…", ok=True, ms=1400)

    def _cancelar_plano_selecionado(self, *_):
        if not self._can_edit_cliente:
            self._show_message("Perfil de recepção não pode editar clientes.", ok=False)
            return
        if not self.current_mat:
            self._show_message("Selecione um cliente primeiro.", ok=False)
            return
        if self._current_status == "inativo":
            self._show_message("Cliente ja esta com plano cancelado.", ok=False)
            return

        nome_item = self.table.item(self.table.currentRow(), self.COL_NOME)
        nome = nome_item.text() if nome_item else f"MAT {self.current_mat}"

        dlg = QMessageBox(self)
        dlg.setWindowTitle("Cancelar plano")
        dlg.setText(f"Deseja realmente cancelar o plano do cliente <b>{nome}</b> (MAT {self.current_mat})?")
        dlg.setInformativeText("O cliente sera marcado como INATIVO e nao podera receber novos pagamentos.")
        dlg.setIcon(QMessageBox.Warning)
        dlg.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        dlg.setDefaultButton(QMessageBox.Cancel)
        dlg.button(QMessageBox.Yes).setText("Cancelar plano")
        dlg.button(QMessageBox.Cancel).setText("Voltar")

        if dlg.exec() != QMessageBox.Yes:
            return

        self.cancelar_plano_signal.emit(int(self.current_mat))
        self._show_message(f"Solicitado cancelamento do plano MAT {self.current_mat}.", ok=True, ms=1800)

    def _abrir_reajuste_planos(self, *_):
        if not self._can_edit_cliente:
            self._show_message("Perfil de recepção não pode reajustar planos.", ok=False)
            return

        current_ctx = {}
        if self.current_mat:
            current_ctx["mat"] = int(self.current_mat)
            nome_item = self.table.item(self.table.currentRow(), self.COL_NOME)
            current_ctx["nome"] = nome_item.text() if nome_item else f"MAT {self.current_mat}"

        dlg = _ReajustePlanosDialog(
            self,
            sans=self._sans,
            selected_ids=sorted(self._checked_mats),
            current_cliente=current_ctx,
        )
        if dlg.exec() != QDialog.Accepted:
            return

        payload = dlg.payload() or {}
        if not payload:
            self._show_message("Reajuste cancelado.", ok=False)
            return

        self.reajuste_planos_signal.emit(payload)
        modo = str(payload.get("modo", "filtros") or "filtros")
        if modo == "individual":
            cid = int(payload.get("cliente_id", 0) or 0)
            novo = float(payload.get("novo_valor", 0.0) or 0.0)
            self._show_message(f"Solicitado reajuste individual MAT {cid} para {br_money(novo)}.", ok=True, ms=1800)
        elif modo == "selecionados":
            pct = float(payload.get("percentual", 0.0) or 0.0)
            qtd = len(payload.get("cliente_ids", []) or [])
            self._show_message(f"Solicitado reajuste de {pct:.2f}% para {qtd} cliente(s) marcado(s).", ok=True, ms=1800)
        else:
            pct = float(payload.get("percentual", 0.0) or 0.0)
            self._show_message(f"Solicitado reajuste de {pct:.2f}%...", ok=True, ms=1600)

    def _email_context_for_current(self) -> dict | None:
        if not self.current_mat:
            return None

        if self._selected_cliente_ctx and int(self._selected_cliente_ctx.get("mat") or 0) == int(self.current_mat):
            return dict(self._selected_cliente_ctx)

        raw = db.buscar_cliente_por_id(int(self.current_mat))
        if not raw:
            return None
        raw_pag = db.buscar_ultimo_pagamento(int(self.current_mat))

        c = _map_cliente_row(raw)
        pag = _map_pagamento_row(raw_pag)
        return {
            "mat": int(self.current_mat),
            "nome": c["nome"],
            "titular": c["nome"],
            "email": c["email"],
            "status": c["status"],
            "pag_status": c["pag_status"],
            "pag_status_label": safe_text(c["pag_status"]).replace("_", " ").upper(),
            "plano": c["plano"],
            "vencimento_dia": c["vencimento"],
            "mes_ref_br": br_month_ref(pag["mes_ref"]) if pag else "-",
            "mes_ref_iso": pag["mes_ref"] if pag else datetime.now().strftime("%Y-%m"),
            "data_pagamento_br": br_date(pag["data_pagamento"]) if pag else "-",
            "valor_pago_br": br_money(pag["valor_pago"]) if pag else "-",
            "valor_mensal_br": br_money(c["valor_mensal"]),
        }

    def _enviar_email_selecionado(self, *_):
        # RBAC (Recepção): sem ação de e-mail na listagem.
        if not self._can_send_email:
            self._show_message("Perfil de recepção não pode enviar e-mails por esta tela.", ok=False)
            return
        if not self.current_mat:
            self._show_message("Selecione um cliente primeiro.", ok=False)
            return

        try:
            ctx = self._email_context_for_current()
        except Exception as e:
            self._show_message(f"Nao foi possivel carregar o cliente: {e}", ok=False)
            return

        if not ctx:
            self._show_message("Cliente nao encontrado.", ok=False)
            return

        email = str(ctx.get("email", "") or "").strip()
        if not email:
            self._show_message("Cliente sem e-mail cadastrado.", ok=False)
            return

        dlg = _EnviarEmailDialog(self, sans=self._sans, contexto=ctx)
        if dlg.exec() != QDialog.Accepted:
            return

        payload = dlg.payload() or {}
        if not payload:
            self._show_message("Envio de e-mail cancelado.", ok=False)
            return

        self.enviar_email_signal.emit(payload)
        self._show_message("Solicitacao de envio de e-mail iniciada...", ok=True, ms=1800)

    def _excluir_selecionado(self, *_):
        # RBAC (Recepção): sem ação de exclusão na listagem.
        if not self._can_delete_cliente:
            self._show_message("Perfil de recepção não pode excluir clientes.", ok=False)
            return
        if not self.current_mat:
            self._show_message("Selecione um cliente primeiro.", ok=False)
            return

        nome_item = self.table.item(self.table.currentRow(), self.COL_NOME)
        nome = nome_item.text() if nome_item else f"MAT {self.current_mat}"

        dlg = QMessageBox(self)
        dlg.setWindowTitle("Confirmar exclusão")
        dlg.setText(f"Deseja realmente excluir o cliente <b>{nome}</b> (MAT {self.current_mat})?")
        dlg.setInformativeText("Esta ação não pode ser desfeita.")
        dlg.setIcon(QMessageBox.Warning)
        dlg.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        dlg.setDefaultButton(QMessageBox.Cancel)
        dlg.button(QMessageBox.Yes).setText("Excluir")
        dlg.button(QMessageBox.Cancel).setText("Cancelar")

        if dlg.exec() != QMessageBox.Yes:
            return

        self.excluir_signal.emit(int(self.current_mat))
        self._show_message(f"Solicitada exclusão MAT {self.current_mat}.", ok=False, ms=1600)

    def _baixar_contrato_selecionado(self, *_):
        if not self.current_mat:
            self._show_message("Selecione um cliente primeiro.", ok=False)
            return
        self.baixar_contrato_signal.emit(int(self.current_mat))
        self._show_message(
            f"Gerando contrato em PDF do MAT {self.current_mat}. Aguarde a confirmação do download.",
            ok=True,
            ms=2200,
        )

    def _clear_search(self):
        if self.search.text():
            self.search.clear()
        self.search.setFocus()

    def _clear_all_filters(self):
        self.search.blockSignals(True)
        self.filter_status.blockSignals(True)
        self.filter_pag.blockSignals(True)
        self.page_size_combo.blockSignals(True)
        try:
            self.search.clear()
            self.filter_status.setCurrentText("status: todos")
            self.filter_pag.setCurrentText("pagamento: todos")
            self.page_size_combo.setCurrentIndex(0)
        finally:
            self.search.blockSignals(False)
            self.filter_status.blockSignals(False)
            self.filter_pag.blockSignals(False)
            self.page_size_combo.blockSignals(False)

        self._search_mode = "local"
        self._pagination.page_size = 30
        self._pagination.reset()
        self.search.setFocus()
        self._persist_view_state()
        self.reload()

    # ─────────────────────────────────────────
    # Mensagem inline
    # ─────────────────────────────────────────
    def _show_message(self, text: str, ok: bool = False, ms: int = 0):
        msg = str(text or "").strip()
        if not msg:
            self._hide_message()
            return
        if not ok:
            ms = 0  # erros nunca somem automaticamente
        self.inline_msg.setText(msg)
        self.inline_msg.setProperty("ok", ok)
        self.inline_msg.style().unpolish(self.inline_msg)
        self.inline_msg.style().polish(self.inline_msg)
        self.inline_msg.setVisible(True)
        self._msg_timer.stop()
        if ms > 0:
            self._msg_timer.start(ms)

    def _hide_message(self):
        self.inline_msg.setVisible(False)
        self.inline_msg.setText("")
        self.inline_msg.setProperty("ok", False)

    # ─────────────────────────────────────────
    # Estilos
    # ─────────────────────────────────────────
    def apply_styles(self):
        f = self._sans
        self.setStyleSheet(f"""
        /* ── raiz ────────────────────────────────────────────────────────── */
        QWidget#ListarClientes {{
            background: {_BG};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QScrollArea#mainScroll {{
            background: transparent;
            border: none;
        }}
        QWidget#mainPage {{
            background: {_BG};
        }}

        /* ── cabeçalho ───────────────────────────────────────────────────── */
        QLabel#breadcrumb {{
            font-size: 11px;
            font-weight: 600;
            color: {_INK3};
            letter-spacing: 0.3px;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#title {{
            font-size: 22px;
            font-weight: 700;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#subtitle {{
            font-size: 12px;
            color: {_INK2};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}

        /* ── separadores ─────────────────────────────────────────────────── */
        QFrame#softLine, QFrame#divider {{
            background: {_LINE};
            border: none;
        }}
        QFrame#actionStrip {{
            background: rgba(255,255,255,0.90);
            border: 1px solid {_LINE};
            border-radius: 10px;
        }}
        QFrame#actionGroup {{
            background: rgba(248,250,252,0.94);
            border: 1px solid {_LINE};
            border-radius: 8px;
        }}
        QFrame#actionGroupCritical {{
            background: rgba(254,242,242,0.92);
            border: 1px solid {_DANGER_BORDER};
            border-radius: 8px;
        }}
        QLabel#actionGroupTitle {{
            font-size: 11px;
            font-weight: 700;
            color: {_INK2};
            letter-spacing: 0.2px;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#actionGroupTitleWarn {{
            font-size: 11px;
            font-weight: 700;
            color: #92400e;
            letter-spacing: 0.2px;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#actionStripLabel {{
            font-size: 11px;
            font-weight: 700;
            color: {_INK2};
            letter-spacing: 0.2px;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#actionStripLabelWarn {{
            font-size: 11px;
            font-weight: 700;
            color: #92400e;
            letter-spacing: 0.2px;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#actionStripMeta {{
            font-size: 11px;
            font-weight: 700;
            color: {_ACCENT};
            padding: 0 2px;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QFrame#actionStripDivider {{
            background: {_LINE};
            border: none;
            margin: 5px 0;
        }}

        /* ── cards principais ────────────────────────────────────────────── */
        QFrame#card, QFrame#sideCard {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 12px;
        }}
        QSplitter#contentSplitter::handle {{
            background: transparent;
        }}
        QSplitter#contentSplitter::handle:horizontal {{
            width: 8px;
            margin: 8px 2px;
            border-radius: 4px;
            background: rgba(148,163,184,0.24);
        }}
        QSplitter#contentSplitter::handle:vertical {{
            height: 8px;
            margin: 2px 8px;
            border-radius: 4px;
            background: rgba(148,163,184,0.24);
        }}
        QSplitter#contentSplitter::handle:hover {{
            background: rgba(26,107,124,0.35);
        }}

        /* ── loading overlay ─────────────────────────────────────────────── */
        QFrame#loadingPage {{ background: transparent; }}
        QLabel#loadingLabel {{
            font-size: 14px;
            font-weight: 600;
            color: {_INK2};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QFrame#emptyPage {{
            background: transparent;
        }}
        QLabel#emptyStateTitle {{
            font-size: 15px;
            font-weight: 700;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#emptyStateTitle[tone="error"] {{
            color: {_DANGER};
        }}
        QLabel#emptyStateSub {{
            max-width: 620px;
            font-size: 12px;
            color: {_INK3};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}

        /* ── scroll lateral ──────────────────────────────────────────────── */
        QScrollArea#sideScroll {{ background: transparent; border: none; }}
        QFrame#sideInner {{ background: transparent; }}
        QScrollBar:vertical {{
            background: transparent;
            width: 7px;
            margin: 4px 2px;
        }}
        QScrollBar::handle:vertical {{
            background: {_LINE};
            border-radius: 3px;
            min-height: 28px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {_ACCENT}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

        /* ── pager ───────────────────────────────────────────────────────── */
        QLabel#pagerText {{
            font-size: 12px;
            color: {_INK2};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}

        /* ── chips de estatísticas ───────────────────────────────────────── */
        QLabel#statChip {{
            border-radius: 20px;
            padding: 5px 14px;
            font-size: 12px;
            font-weight: 600;
            border: 1px solid {_LINE};
            background: {_WHITE};
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#statChipOk {{
            border-radius: 20px; padding: 5px 14px; font-size: 12px; font-weight: 600;
            background: {_GOOD_BG}; border: 1px solid {_GOOD_BORDER}; color: {_GOOD};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#statChipMuted {{
            border-radius: 20px; padding: 5px 14px; font-size: 12px; font-weight: 600;
            background: rgba(148,163,184,0.10); border: 1px solid rgba(148,163,184,0.25); color: {_INK2};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#statChipInfo {{
            border-radius: 20px; padding: 5px 14px; font-size: 12px; font-weight: 600;
            background: rgba(37,99,235,0.08); border: 1px solid rgba(37,99,235,0.20); color: #1e3a8a;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#statChipWarn {{
            border-radius: 20px; padding: 5px 14px; font-size: 12px; font-weight: 600;
            background: rgba(217,119,6,0.09); border: 1px solid rgba(217,119,6,0.22); color: #92400e;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}

        /* ── barra de pesquisa ───────────────────────────────────────────── */
        QFrame#searchWrap {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 8px;
        }}
        QFrame#searchWrap:focus-within {{
            border: 1px solid {_ACCENT};
        }}
        QLineEdit#fieldInput {{
            border: none;
            padding-left: 0;
            font-size: 13px;
            background: transparent;
            color: {_INK};
            min-height: 38px;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QToolButton#iconBtn {{
            border: none;
            background: transparent;
            border-radius: 6px;
            padding: 4px 8px;
            color: {_INK3};
            font-size: 12px;
        }}
        QToolButton#iconBtn:hover {{
            background: rgba(15,23,42,0.06);
            color: {_INK};
        }}

        /* ── combos de filtro ────────────────────────────────────────────── */
        QComboBox#filterCombo {{
            border: 1px solid {_LINE};
            border-radius: 8px;
            padding: 0 32px 0 12px;
            background: {_WHITE};
            font-size: 12px;
            font-weight: 500;
            color: {_INK};
            min-height: 38px;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QComboBox#filterCombo:hover  {{ border-color: #c0c7d0; }}
        QComboBox#filterCombo:focus  {{ border-color: {_ACCENT}; }}
        QComboBox#filterCombo::drop-down {{ width: 28px; border: none; background: transparent; }}
        QComboBox#filterCombo::down-arrow {{
            width: 0; height: 0;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid {_INK3};
            margin-right: 6px;
        }}
        QWidget#comboPopupWindow {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 10px;
        }}
        QAbstractItemView#comboPopupView {{
            background: {_WHITE};
            outline: none;
            border: none;
            selection-background-color: rgba(26,107,124,0.10);
            selection-color: {_INK};
            padding: 4px;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QAbstractItemView#comboPopupView::item {{
            padding: 8px 12px;
            border-radius: 6px;
            margin: 2px;
            font-size: 12px;
            color: {_INK};
        }}
        QAbstractItemView#comboPopupView::item:hover {{
            background: rgba(26,107,124,0.06);
        }}

        /* ── botões ──────────────────────────────────────────────────────── */
        QPushButton#btnPrimary {{
            background: {_ACCENT};
            border: none;
            border-radius: 8px;
            padding: 0 12px;
            font-size: 12px;
            font-weight: 600;
            color: white;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QPushButton#btnPrimary:hover    {{ background: {_ACCENT_HOVER}; }}
        QPushButton#btnPrimary:disabled {{ background: rgba(26,107,124,0.30); color: rgba(255,255,255,0.60); }}

        QPushButton#btnSecondary {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 8px;
            padding: 0 10px;
            font-size: 12px;
            font-weight: 600;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QPushButton#btnSecondary:hover    {{ border-color: {_ACCENT}; color: {_ACCENT}; }}
        QPushButton#btnSecondary:disabled {{ color: {_INK3}; border-color: {_LINE}; }}

        QPushButton#btnAccentSoft {{
            background: rgba(26,107,124,0.09);
            border: 1px solid rgba(26,107,124,0.24);
            border-radius: 8px;
            padding: 0 10px;
            font-size: 12px;
            font-weight: 700;
            color: {_ACCENT};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QPushButton#btnAccentSoft:hover {{
            background: rgba(26,107,124,0.14);
            border-color: {_ACCENT};
        }}
        QPushButton#btnAccentSoft:disabled {{
            color: {_INK3};
            border-color: {_LINE};
            background: transparent;
        }}

        QPushButton#btnRowContract {{
            background: rgba(26,107,124,0.08);
            border: 1px solid rgba(26,107,124,0.22);
            border-radius: 7px;
            padding: 0;
            font-size: 13px;
            font-weight: 700;
            color: {_ACCENT};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QPushButton#btnRowContract:hover {{
            background: rgba(26,107,124,0.14);
            border-color: {_ACCENT};
        }}

        QCheckBox#rowSelectCheck {{
            spacing: 0px;
            padding: 0;
        }}
        QCheckBox#rowSelectCheck::indicator {{
            width: 16px;
            height: 16px;
            border: 1px solid #b8c0cc;
            border-radius: 4px;
            background: {_WHITE};
        }}
        QCheckBox#rowSelectCheck::indicator:hover {{
            border-color: {_ACCENT};
        }}
        QCheckBox#rowSelectCheck::indicator:checked {{
            border-color: {_ACCENT};
            background: {_ACCENT};
            image: none;
        }}

        QPushButton#btnDanger {{
            background: {_DANGER_BG};
            border: 1px solid {_DANGER_BORDER};
            border-radius: 8px;
            padding: 0 10px;
            font-size: 12px;
            font-weight: 600;
            color: {_DANGER};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QPushButton#btnDanger:hover    {{ background: rgba(192,57,43,0.14); }}
        QPushButton#btnDanger:disabled {{ color: {_INK3}; background: transparent; border-color: {_LINE}; }}

        /* ── tabela ──────────────────────────────────────────────────────── */
        QTableWidget#table {{
            border: 1px solid {_LINE};
            border-radius: 10px;
            background: {_WHITE};
            gridline-color: rgba(207,214,224,0.95);
            font-size: 12px;
            font-family: '{f}', 'Segoe UI', sans-serif;
            alternate-background-color: #f4f7fb;
            selection-background-color: rgba(26,107,124,0.14);
            selection-color: #0a1720;
        }}
        QTableWidget#table::item {{
            padding: 11px 12px;
            border-bottom: 1px solid rgba(214,220,228,0.8);
            color: #0f172a;
        }}
        QTableWidget#table::item:hover {{
            background: rgba(26,107,124,0.08);
        }}
        QTableWidget#table::item:selected {{
            background: rgba(26,107,124,0.14);
            color: #0b1620;
        }}
        QTableWidget#table::item:focus {{
            outline: none;
            border: none;
        }}
        QHeaderView::section {{
            background: #eef2f7;
            border: none;
            border-bottom: 1px solid #d6dde7;
            padding: 10px 10px;
            font-size: 11px;
            font-weight: 700;
            color: #334155;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}

        /* ── menu de contexto ────────────────────────────────────────────── */
        QMenu#tableMenu {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 10px;
            padding: 4px;
        }}
        QMenu#tableMenu::item {{
            padding: 8px 14px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 500;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QMenu#tableMenu::item:selected {{
            background: rgba(26,107,124,0.10);
            color: {_INK};
        }}
        QMenu#tableMenu::separator {{
            background: {_LINE};
            height: 1px;
            margin: 3px 8px;
        }}

        /* ── painel lateral ──────────────────────────────────────────────── */
        QLabel#sideTitle {{
            font-size: 14px;
            font-weight: 700;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#sideSub {{
            font-size: 12px;
            color: {_INK2};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}

        /* ── cabeçalhos de seção no painel ───────────────────────────────── */
        QLabel#sectionHeader {{
            font-size: 10px;
            font-weight: 600;
            color: {_INK3};
            letter-spacing: 0.8px;
            padding: 2px 0;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}

        /* ── campos de detalhe ───────────────────────────────────────────── */
        QFrame#detailWrap {{
            background: {_BG};
            border: 1px solid {_LINE};
            border-radius: 10px;
        }}
        QLabel#detailLabel {{
            font-size: 10px;
            font-weight: 600;
            color: {_INK3};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#detailValue {{
            font-size: 13px;
            font-weight: 500;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}

        /* ── seção de dependentes ────────────────────────────────────────── */
        QLabel#sectionTitle {{
            font-size: 13px;
            font-weight: 600;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#countChip {{
            background: rgba(26,107,124,0.08);
            border: 1px solid rgba(26,107,124,0.18);
            border-radius: 20px;
            padding: 3px 10px;
            font-size: 12px;
            font-weight: 600;
            color: {_ACCENT};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#mutedText {{
            font-size: 12px;
            color: {_INK3};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QFrame#depCard {{
            background: {_BG};
            border: 1px solid {_LINE};
            border-radius: 10px;
        }}
        QLabel#depName {{
            font-size: 13px;
            font-weight: 600;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#depMeta {{
            font-size: 11px;
            color: {_INK2};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#timelineItem {{
            font-size: 11px;
            color: {_INK2};
            border-bottom: 1px dashed rgba(15,23,42,0.08);
            padding: 4px 0;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#timelineItem[tone="muted"] {{
            color: {_INK3};
            border-bottom: none;
        }}

        /* ── mensagem inline ─────────────────────────────────────────────── */
        QLabel#inlineMessage {{
            background: {_DANGER_BG};
            border: 1px solid {_DANGER_BORDER};
            border-left: 4px solid {_DANGER};
            color: {_DANGER};
            padding: 10px 14px;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 600;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#inlineMessage[ok="true"] {{
            background: {_GOOD_BG};
            border: 1px solid {_GOOD_BORDER};
            border-left: 4px solid {_GOOD};
            color: {_GOOD};
        }}
        """)
