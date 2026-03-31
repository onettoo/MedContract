# -*- coding: utf-8 -*-
"""
Registrar Pagamento View - Modern SaaS Design
Complete redesign with premium aesthetics and enhanced UX
"""
from __future__ import annotations
from styles.theme import build_view_qss

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import threading
import unicodedata
from typing import Callable, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFrame, QGraphicsDropShadowEffect, QComboBox, QListWidget, QListWidgetItem,
    QToolButton, QSizePolicy, QMessageBox, QScrollArea
)
from PySide6.QtCore import (
    Qt, Signal, QTimer, QEvent, QRect, QEasingCurve, QPropertyAnimation, QPoint
)
from PySide6.QtGui import QColor, QKeySequence, QShortcut


# ══════════════════════════════════════════════════════════════════════════════
# DESIGN TOKENS - Modern Indigo SaaS Palette
# ══════════════════════════════════════════════════════════════════════════════
class Theme:
    """Modern SaaS design tokens - consistent with dashboard."""
    PRIMARY = "#1a6b7c"
    PRIMARY_HOVER = "#155e6d"
    PRIMARY_SOFT = "rgba(26,107,124,0.10)"
    PRIMARY_BORDER = "rgba(26,107,124,0.30)"
    
    SUCCESS = "#10b981"
    SUCCESS_SOFT = "rgba(16,185,129,0.08)"
    SUCCESS_BORDER = "rgba(16,185,129,0.25)"
    
    DANGER = "#c0392b"
    DANGER_SOFT = "rgba(192,57,43,0.08)"
    DANGER_BORDER = "rgba(192,57,43,0.25)"
    
    WARNING = "#f59e0b"
    WARNING_SOFT = "rgba(245,158,11,0.08)"
    WARNING_BORDER = "rgba(245,158,11,0.25)"
    
    INK = "#0f172a"
    INK2 = "#475569"
    INK3 = "#94a3b8"
    LINE = "#e2e8f0"
    BG = "#f8fafc"
    SURFACE = "#ffffff"


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS: Mês de referência
# ══════════════════════════════════════════════════════════════════════════════
_PT_BR_MONTHS = {
    "JAN": "01", "FEV": "02", "MAR": "03", "ABR": "04", "MAI": "05", "JUN": "06",
    "JUL": "07", "AGO": "08", "SET": "09", "OUT": "10", "NOV": "11", "DEZ": "12",
}
_NUM_TO_PT = {v: k for k, v in _PT_BR_MONTHS.items()}
_MONTHS_ORDER = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]


def iso_to_br(yyyy_mm: str) -> str:
    s = (yyyy_mm or "").strip()
    if len(s) == 7 and s[4] == "-":
        y, m = s.split("-", 1)
        m2 = f"{int(m):02d}"
        return f"{_NUM_TO_PT.get(m2, m2)}/{y}"
    return s


def br_to_iso(mmm_yyyy: str) -> str:
    s = (mmm_yyyy or "").strip().upper()
    if "/" not in s:
        raise ValueError("Formato inválido")
    mm, yy = s.split("/", 1)
    mm = mm.strip().upper()
    yy = yy.strip()
    if mm not in _PT_BR_MONTHS or (not yy.isdigit()) or len(yy) != 4:
        raise ValueError("Mês inválido")
    return f"{yy}-{_PT_BR_MONTHS[mm]}"


# ══════════════════════════════════════════════════════════════════════════════
# CPF (validação real)
# ══════════════════════════════════════════════════════════════════════════════
def _only_digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def cpf_is_valid(cpf_masked: str) -> bool:
    cpf = _only_digits(cpf_masked)
    if len(cpf) != 11:
        return False
    if cpf == cpf[0] * 11:
        return False

    def calc_digit(base: str, factors: list[int]) -> int:
        total = sum(int(d) * f for d, f in zip(base, factors))
        r = total % 11
        return 0 if r < 2 else 11 - r

    d1 = calc_digit(cpf[:9], list(range(10, 1, -1)))
    d2 = calc_digit(cpf[:9] + str(d1), list(range(11, 1, -1)))
    return cpf[-2:] == f"{d1}{d2}"


def cnpj_is_valid(cnpj_masked: str) -> bool:
    cnpj = _only_digits(cnpj_masked)
    if len(cnpj) != 14:
        return False
    if cnpj == cnpj[0] * 14:
        return False

    def calc_digit(base: str, factors: list[int]) -> int:
        total = sum(int(d) * f for d, f in zip(base, factors))
        r = total % 11
        return 0 if r < 2 else 11 - r

    d1 = calc_digit(cnpj[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = calc_digit(cnpj[:12] + str(d1), [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return cnpj[-2:] == f"{d1}{d2}"


# ══════════════════════════════════════════════════════════════════════════════
# VALOR (parsing/formatting BR)
# ══════════════════════════════════════════════════════════════════════════════
def money_parse_br(txt: str) -> Optional[float]:
    s = (txt or "").strip()
    if not s:
        return None

    s = s.replace("R$", "").replace("r$", "").replace(" ", "")
    if not s:
        return None
    if not re.fullmatch(r"[0-9.,]+", s):
        return None

    normalized = ""

    if "," in s and "." in s:
        last_sep_idx = max(s.rfind(","), s.rfind("."))
        int_part = re.sub(r"[.,]", "", s[:last_sep_idx])
        frac_raw = re.sub(r"[.,]", "", s[last_sep_idx + 1:])
        frac = (frac_raw + "00")[:2]
        normalized = f"{int_part}.{frac}"
    elif "," in s:
        if s.count(",") > 1:
            return None
        int_part, frac_part = s.split(",", 1)
        int_part = int_part or "0"
        if not int_part.isdigit() or (frac_part and not frac_part.isdigit()):
            return None
        frac = (frac_part + "00")[:2]
        normalized = f"{int_part}.{frac}"
    elif "." in s:
        if s.count(".") == 1:
            int_part, frac_part = s.split(".", 1)
            if len(frac_part) == 3 and int_part.isdigit() and frac_part.isdigit():
                normalized = f"{int_part}{frac_part}.00"
            elif int_part.isdigit() and frac_part.isdigit() and 1 <= len(frac_part) <= 2:
                frac = (frac_part + "00")[:2]
                normalized = f"{int_part}.{frac}"
            else:
                return None
        else:
            groups = s.split(".")
            if not all(g.isdigit() and g for g in groups):
                return None
            normalized = f"{''.join(groups)}.00"
    else:
        if not s.isdigit():
            return None
        normalized = f"{s}.00"

    try:
        v = Decimal(normalized)
        if v <= 0:
            return None
        return float(v)
    except (InvalidOperation, ValueError):
        return None


def money_format_br(v: float) -> str:
    try:
        d = Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        int_part, frac_part = format(d, "f").split(".")
        groups = []
        while int_part:
            groups.append(int_part[-3:])
            int_part = int_part[:-3]
        return f"{'.'.join(reversed(groups))},{frac_part}"
    except Exception:
        return "0,00"


def money_from_db(value) -> float:
    """Converte valor monetário vindo do banco sem aplicar cálculo de negócio."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float, Decimal)):
        try:
            return float(value)
        except Exception:
            return 0.0
    s = str(value).strip()
    if not s:
        return 0.0
    s = s.replace("R$", "").replace("r$", "").replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


# ══════════════════════════════════════════════════════════════════════════════
# SMART MASKED LINE EDITS (corrige cursor no Windows)
# ══════════════════════════════════════════════════════════════════════════════
class SmartMaskedLineEdit(QLineEdit):
    """Corrige problema do cursor indo pro final com inputMask no Windows."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _smart_pos(self) -> int:
        txt = self.text() or ""
        p = txt.find("_")
        if p != -1:
            return p
        only = txt.replace("_", "").replace(".", "").replace("-", "").replace("/", "").strip()
        if only == "":
            return 0
        return 0

    def _force_cursor_later(self):
        QTimer.singleShot(0, self._apply_cursor)
        QTimer.singleShot(1, self._apply_cursor)

    def _apply_cursor(self):
        try:
            self.setCursorPosition(self._smart_pos())
        except Exception:
            pass

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._force_cursor_later()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._force_cursor_later()

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        self._force_cursor_later()


class SmartCpfLineEdit(SmartMaskedLineEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setInputMask("000.000.000-00;_")


class SmartDateLineEdit(SmartMaskedLineEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setInputMask("00/00/0000;_")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Backspace:
            txt = self.text() or ""
            pos = self.cursorPosition()
            if pos > 0:
                pos2 = pos - 1
                while pos2 > 0 and txt[pos2] in ("/", ".", "-"):
                    pos2 -= 1
                if 0 <= pos2 < len(txt):
                    lst = list(txt)
                    if lst[pos2] not in ("/", ".", "-"):
                        lst[pos2] = "_"
                        self.setText("".join(lst))
                        self.setCursorPosition(pos2)
                        return
        super().keyPressEvent(event)


# ══════════════════════════════════════════════════════════════════════════════
# STYLED COMBO BOX (corrige popup preto no Windows)
# ══════════════════════════════════════════════════════════════════════════════
class StyledComboBox(QComboBox):
    """Força popup do QComboBox a ter fundo claro no Windows."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        v = self.view()
        v.setObjectName("comboPopupView")
        v.setUniformItemSizes(True)
        v.viewport().setAutoFillBackground(True)
        try:
            v.window().setAttribute(Qt.WA_TranslucentBackground, False)
        except Exception:
            pass

    def showPopup(self):
        v = self.view()
        w = v.window()
        try:
            w.setAttribute(Qt.WA_TranslucentBackground, False)
            w.setAttribute(Qt.WA_NoSystemBackground, False)
            w.setAutoFillBackground(True)
            w.setObjectName("comboPopupWindow")
        except Exception:
            pass
        super().showPopup()
        try:
            v.viewport().setStyleSheet("background: white;")
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# MONTH SELECTOR (UX aprimorado)
# ══════════════════════════════════════════════════════════════════════════════
class MonthSelector(QWidget):
    """Seletor de mês com navegação intuitiva."""
    
    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("monthSelector")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.btn_prev = QToolButton()
        self.btn_prev.setObjectName("monthNavBtn")
        self.btn_prev.setText("◀")
        self.btn_prev.setCursor(Qt.PointingHandCursor)
        self.btn_prev.clicked.connect(self._prev)

        self.combo_month = StyledComboBox()
        self.combo_month.setObjectName("monthCombo")
        self.combo_month.addItems(_MONTHS_ORDER)
        self.combo_month.currentIndexChanged.connect(lambda *_: self._emit_changed())

        self.combo_year = StyledComboBox()
        self.combo_year.setObjectName("yearCombo")
        self.combo_year.currentIndexChanged.connect(lambda *_: self._emit_changed())

        self.btn_next = QToolButton()
        self.btn_next.setObjectName("monthNavBtn")
        self.btn_next.setText("▶")
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.clicked.connect(self._next)

        self.chip = QLabel("—")
        self.chip.setObjectName("monthChip")
        self.chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        lay.addWidget(self.btn_prev)
        lay.addWidget(self.combo_month, 1)
        lay.addWidget(self.combo_year, 1)
        lay.addWidget(self.btn_next)
        lay.addWidget(self.chip)

        self._build_years()
        self.set_current_month(datetime.now())

    def _build_years(self):
        now = datetime.now().year
        start = now - 5
        end = now + 1
        self.combo_year.clear()
        for y in range(start, end + 1):
            self.combo_year.addItem(str(y), y)

    def set_current_month(self, dt: datetime):
        mm = dt.strftime("%m")
        yy = dt.year
        mon = _NUM_TO_PT.get(mm, "JAN")
        idx_m = self.combo_month.findText(mon)
        if idx_m >= 0:
            self.combo_month.setCurrentIndex(idx_m)
        idx_y = self.combo_year.findText(str(yy))
        if idx_y >= 0:
            self.combo_year.setCurrentIndex(idx_y)
        else:
            self._build_years()
            idx_y = self.combo_year.findText(str(yy))
            if idx_y >= 0:
                self.combo_year.setCurrentIndex(idx_y)
        self._sync_chip()

    def _emit_changed(self):
        self._sync_chip()
        self.changed.emit()

    def _sync_chip(self):
        self.chip.setText(self.mes_br())

    def mes_br(self) -> str:
        mmm = self.combo_month.currentText().strip().upper()
        yy = self.combo_year.currentText().strip()
        return f"{mmm}/{yy}"

    def mes_iso(self) -> str:
        return br_to_iso(self.mes_br())

    def _prev(self):
        i = self.combo_month.currentIndex()
        if i <= 0:
            self.combo_month.setCurrentIndex(11)
            y = int(self.combo_year.currentText())
            self._set_year(y - 1)
        else:
            self.combo_month.setCurrentIndex(i - 1)

    def _next(self):
        i = self.combo_month.currentIndex()
        if i >= 11:
            self.combo_month.setCurrentIndex(0)
            y = int(self.combo_year.currentText())
            self._set_year(y + 1)
        else:
            self.combo_month.setCurrentIndex(i + 1)

    def _set_year(self, year: int):
        idx = self.combo_year.findText(str(year))
        if idx >= 0:
            self.combo_year.setCurrentIndex(idx)
            return
        current_years = [int(self.combo_year.itemText(i)) for i in range(self.combo_year.count())]
        if not current_years:
            self._build_years()
            idx = self.combo_year.findText(str(year))
            if idx >= 0:
                self.combo_year.setCurrentIndex(idx)
            return
        min_y = min(current_years)
        max_y = max(current_years)
        if year < min_y:
            for y in range(min_y - 1, year - 1, -1):
                self.combo_year.insertItem(0, str(y), y)
        elif year > max_y:
            for y in range(max_y + 1, year + 1):
                self.combo_year.addItem(str(y), y)
        idx = self.combo_year.findText(str(year))
        if idx >= 0:
            self.combo_year.setCurrentIndex(idx)

    def set_enabled(self, enabled: bool):
        for w in (self.btn_prev, self.combo_month, self.combo_year, self.btn_next):
            w.setEnabled(enabled)

    def set_error(self, has_error: bool):
        err = bool(has_error)
        for combo in (self.combo_month, self.combo_year):
            combo.setProperty("error", err)
            combo.style().unpolish(combo)
            combo.style().polish(combo)


# ══════════════════════════════════════════════════════════════════════════════
# NAME RESULTS POPUP (busca por nome)
# ══════════════════════════════════════════════════════════════════════════════
class NameResultsPopup(QFrame):
    """Popup de resultados da busca por nome."""
    
    picked = Signal(dict)

    def __init__(self, parent: QWidget):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("namePopup")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        self.title = QLabel("Selecione o cliente")
        self.title.setObjectName("namePopupTitle")

        self.list = QListWidget()
        self.list.setObjectName("namePopupList")
        self.list.itemClicked.connect(self._on_item_clicked)
        self.list.itemActivated.connect(self._on_item_clicked)
        self.list.installEventFilter(self)

        lay.addWidget(self.title)
        lay.addWidget(self.list)

        self.setFixedWidth(540)

    def set_title(self, text: str):
        self.title.setText(str(text or "Selecione"))

    def set_results(self, items: list[dict]):
        self.list.clear()
        for it in items or []:
            nome = str(it.get("nome") or "—")
            cpf = str(it.get("cpf") or "")
            cnpj = str(it.get("cnpj") or "")
            doc = cnpj or cpf
            doc_label = "CNPJ" if cnpj else "CPF"
            mat = it.get("id")
            sub = f"{doc_label}: {doc}" if doc else "Documento: -"
            if mat is not None:
                sub += f"  •  ID: {mat}"
            item = QListWidgetItem(f"{nome}\n{sub}")
            item.setData(Qt.UserRole, it)
            self.list.addItem(item)
        if self.list.count() > 0:
            self.list.setCurrentRow(0)

    def _on_item_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole) or {}
        self.picked.emit(data)
        self.hide()

    def eventFilter(self, obj, event):
        if obj is self.list and event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Return, Qt.Key_Enter):
                item = self.list.currentItem()
                if item is not None:
                    self._on_item_clicked(item)
                    return True
            if key == Qt.Key_Escape:
                self.hide()
                return True
        return super().eventFilter(obj, event)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN VIEW - REGISTRAR PAGAMENTO
# ══════════════════════════════════════════════════════════════════════════════
class RegistrarPagamentoView(QWidget):
    """Modern SaaS payment registration view with enhanced UX."""
    
    voltar_signal = Signal()
    registrar_signal = Signal(dict)
    name_search_done = Signal(int, str, object)
    name_search_error = Signal(int, str)

    def __init__(self):
        super().__init__()

        # Loading state
        self._loading = False
        self._spinner_frames = ["◐", "◓", "◑", "◒"]
        self._spinner_i = 0
        self._loading_timer = QTimer(self)
        self._loading_timer.timeout.connect(self._tick_loading)

        # Message timer
        self._msg_timer = QTimer(self)
        self._msg_timer.setSingleShot(True)
        self._msg_timer.timeout.connect(self._hide_message)

        # Search debounce
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.timeout.connect(self._emit_search_request)

        # Callbacks
        self.on_preview_request: Optional[Callable[[str], None]] = None
        self.on_preview_empresa_request: Optional[Callable[[str], None]] = None
        self.on_search_name_request: Optional[Callable[[str], list[dict]]] = None
        self.on_search_empresa_name_request: Optional[Callable[[str], list[dict]]] = None
        self.on_check_duplicate: Optional[Callable[[int, str], tuple[bool, dict | None]]] = None
        self.on_check_duplicate_empresa: Optional[Callable[[int, str], tuple[bool, dict | None]]] = None

        # Cliente state
        self._cliente = {
            "ok": False,
            "tipo": "cliente",
            "id": None,
            "nome": None,
            "status": None,
            "pag_status": None,
            "plano": None,
            "dependentes": 0,
            "forma_pagamento": None,
            "dia_vencimento": 0,
            "documento": "",
            "valor_mensal": 0.0,
            "ultimo_pagamento": None,
        }

        # Name search state
        self._name_search_token = 0
        self.name_search_done.connect(self._on_name_search_done)
        self.name_search_error.connect(self._on_name_search_error)

        self.setup_ui()
        self.apply_styles()
        self._apply_shadows()

        # Event filters
        self.search_input.installEventFilter(self)
        self.valor_input.installEventFilter(self)

        self.set_defaults()
        self._update_register_enabled()

        # Shortcuts
        self._shortcut_clear = QShortcut(QKeySequence("Ctrl+L"), self)
        self._shortcut_clear.activated.connect(self.clear_form_full)

        self._shortcut_back = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._shortcut_back.activated.connect(self.voltar_signal.emit)

        self._shortcut_register = QShortcut(QKeySequence("Ctrl+Return"), self)
        self._shortcut_register.activated.connect(lambda: self._on_registrar() if self.btn_registrar.isEnabled() else None)

        self.valor_input.returnPressed.connect(self._try_register_from_enter)

    # ══════════════════════════════════════════════════════════════════════════
    # UI SETUP
    # ══════════════════════════════════════════════════════════════════════════
    def setup_ui(self):
        self.setObjectName("RegistrarPagamento")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Scroll area wrapper
        scroll = QScrollArea()
        scroll.setObjectName("mainScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        scroll.setWidget(content)

        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(32, 28, 32, 28)
        content_layout.setSpacing(20)

        # ── Header ──────────────────────────────────────────────────────────
        header = self._build_header()
        content_layout.addWidget(header)

        # Divider
        line = QFrame()
        line.setObjectName("softLine")
        line.setFixedHeight(1)
        content_layout.addWidget(line)

        # ── Main Card ───────────────────────────────────────────────────────
        self.card = QFrame()
        self.card.setObjectName("card")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        card_layout.setSpacing(20)

        # Search section
        self.search_header = self._section_header("🔍  Buscar cliente")
        card_layout.addWidget(self.search_header)
        card_layout.addLayout(self._build_search_section())

        # Preview card
        card_layout.addWidget(self.preview_card)
        card_layout.addWidget(self.preview_state)

        # Payment details section
        self.payment_header = self._section_header("📅  Detalhes do pagamento")
        card_layout.addWidget(self.payment_header)
        card_layout.addLayout(self._build_payment_section())

        # Messages
        self.inline_msg = QLabel("")
        self.inline_msg.setObjectName("inlineMessage")
        self.inline_msg.setVisible(False)

        self.register_hint = QLabel("")
        self.register_hint.setObjectName("registerHint")
        self.register_hint.setVisible(False)

        card_layout.addWidget(self.inline_msg)
        card_layout.addWidget(self.register_hint)

        # Actions
        card_layout.addLayout(self._build_actions())

        # Loading overlay
        self.loading_overlay = QFrame(self.card)
        self.loading_overlay.setObjectName("loadingOverlay")
        self.loading_overlay.setVisible(False)
        self._build_loading_overlay()

        content_layout.addWidget(self.card)
        content_layout.addStretch()

        root.addWidget(scroll)

        self._reset_preview_ui()
        self._on_entity_mode_changed()

    def _build_header(self) -> QFrame:
        """Build modern header with breadcrumb and title."""
        header = QFrame()
        header.setObjectName("header")
        
        lay = QHBoxLayout(header)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        # Left: Title block
        title_block = QVBoxLayout()
        title_block.setSpacing(4)

        self.breadcrumb = QLabel("Financeiro  /  Pagamentos")
        self.breadcrumb.setObjectName("breadcrumb")

        title_row = QHBoxLayout()
        title_row.setSpacing(12)

        self.title_icon = QLabel("💳")
        self.title_icon.setObjectName("titleIcon")

        self.title = QLabel("Registrar pagamento")
        self.title.setObjectName("title")

        title_row.addWidget(self.title_icon)
        title_row.addWidget(self.title)
        title_row.addStretch()

        self.subtitle = QLabel("Busque cliente ou empresa e registre o pagamento do mês de forma rápida e segura.")
        self.subtitle.setObjectName("subtitle")

        title_block.addWidget(self.breadcrumb)
        title_block.addLayout(title_row)
        title_block.addWidget(self.subtitle)

        lay.addLayout(title_block, 1)

        # Right: Action button
        self.btn_voltar = QPushButton("← Voltar")
        self.btn_voltar.setObjectName("btnSecondary")
        self.btn_voltar.setFixedHeight(40)
        self.btn_voltar.setCursor(Qt.PointingHandCursor)
        self.btn_voltar.clicked.connect(self.voltar_signal.emit)
        
        lay.addWidget(self.btn_voltar)

        return header

    def _build_search_section(self) -> QVBoxLayout:
        """Build search section with mode switcher and input."""
        section = QVBoxLayout()
        section.setSpacing(12)

        search_row = QHBoxLayout()
        search_row.setSpacing(12)

        self.entity_mode = StyledComboBox()
        self.entity_mode.setObjectName("searchMode")
        self.entity_mode.addItem("👤  CLIENTE", "cliente")
        self.entity_mode.addItem("🏢  EMPRESA", "empresa")
        self.entity_mode.setFixedWidth(164)
        self.entity_mode.setFixedHeight(46)
        self.entity_mode.currentIndexChanged.connect(self._on_entity_mode_changed)

        self.search_mode = StyledComboBox()
        self.search_mode.setObjectName("searchMode")
        self.search_mode.setFixedWidth(140)
        self.search_mode.setFixedHeight(46)
        self.search_mode.currentIndexChanged.connect(self._on_search_mode_changed)

        self.search_input = SmartMaskedLineEdit()
        self.search_input.setObjectName("fieldInput")
        self.search_input.setFixedHeight(46)
        self.search_input.setPlaceholderText("Digite o CPF (000.000.000-00) ou nome...")
        self.search_input.textChanged.connect(self._on_search_text_changed)
        self.search_input.textChanged.connect(self._hide_message)

        search_row.addWidget(self.entity_mode)
        search_row.addWidget(self.search_mode)
        search_row.addWidget(self.search_input, 1)

        # Hidden document fields (compatibility)
        self.cpf = QLineEdit()
        self.cpf.setObjectName("fieldInput")
        self.cpf.setInputMask("000.000.000-00;_")
        self.cpf.textChanged.connect(self._on_cpf_changed)
        self.cpf.setVisible(False)

        self.cnpj = QLineEdit()
        self.cnpj.setObjectName("fieldInput")
        self.cnpj.setInputMask("00.000.000/0000-00;_")
        self.cnpj.textChanged.connect(self._on_cnpj_changed)
        self.cnpj.setVisible(False)

        # Name popup
        self.name_popup = NameResultsPopup(self)
        self.name_popup.picked.connect(self._on_name_picked)

        # Preview card
        self.preview_card = QFrame()
        self.preview_card.setObjectName("previewCard")
        self._build_preview_card()

        # Preview state
        self.preview_state = QLabel("Digite um CPF ou Nome para carregar o cliente...")
        self.preview_state.setObjectName("previewState")
        self.preview_state.setWordWrap(True)

        section.addLayout(search_row)
        section.addWidget(self.cpf)
        section.addWidget(self.cnpj)

        return section

    def _build_preview_card(self):
        """Build client preview card with modern layout."""
        layout = QVBoxLayout(self.preview_card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(16)

        # Client name with status badge
        name_row = QHBoxLayout()
        name_row.setSpacing(12)

        self.p_nome = QLabel("—")
        self.p_nome.setObjectName("pTitle")

        self.p_status_badge = QLabel("—")
        self.p_status_badge.setObjectName("statusBadge")
        self.p_status_badge.setVisible(False)

        name_row.addWidget(self.p_nome)
        name_row.addWidget(self.p_status_badge)
        name_row.addStretch()

        layout.addLayout(name_row)

        # Info grid
        grid = QHBoxLayout()
        grid.setSpacing(24)

        # Left column
        left_col = QVBoxLayout()
        left_col.setSpacing(10)

        self.p_plano = self._info_row("📋", "Plano", "—", key="plano")
        self.p_deps = self._info_row("👥", "Dependentes", "—", key="dependentes")
        self.p_valor = self._info_row("💰", "Mensalidade", "—", key="mensalidade")

        left_col.addLayout(self.p_plano)
        left_col.addLayout(self.p_deps)
        left_col.addLayout(self.p_valor)

        # Right column
        right_col = QVBoxLayout()
        right_col.setSpacing(10)

        self.p_status = self._info_row("📊", "Status", "—", key="status")
        self.p_pag = self._info_row("💳", "Pagamento", "—", key="pagamento")
        self.p_last = self._info_row("📅", "Último pag.", "—", key="ultimo_pag")

        right_col.addLayout(self.p_status)
        right_col.addLayout(self.p_pag)
        right_col.addLayout(self.p_last)

        grid.addLayout(left_col, 1)
        grid.addLayout(right_col, 1)

        layout.addLayout(grid)

    def _info_row(self, icon: str, label: str, value: str, key: str | None = None) -> QHBoxLayout:
        """Create info row with icon, label and value."""
        row = QHBoxLayout()
        row.setSpacing(8)

        icon_lbl = QLabel(icon)
        icon_lbl.setObjectName("pIcon")
        icon_lbl.setFixedWidth(20)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        label_lbl = QLabel(label)
        label_lbl.setObjectName("pLabel")

        value_lbl = QLabel(value)
        value_lbl.setObjectName("pValue")

        text_col.addWidget(label_lbl)
        text_col.addWidget(value_lbl)

        row.addWidget(icon_lbl)
        row.addLayout(text_col)
        row.addStretch()

        # Store value label for updates using a stable key.
        attr_key = (key or label.lower().replace(" ", "_"))
        setattr(self, f"_p_{attr_key}_value", value_lbl)
        setattr(self, f"_p_{attr_key}_label", label_lbl)

        return row

    def _build_payment_section(self) -> QVBoxLayout:
        """Build payment details section."""
        section = QVBoxLayout()
        section.setSpacing(16)

        # Month and date row
        row = QHBoxLayout()
        row.setSpacing(16)

        # Month selector
        month_block = self._field_block("Mês de referência", None)
        self.month_selector = MonthSelector()
        month_block.layout().addWidget(self.month_selector)
        self.month_selector.changed.connect(self._on_any_edited)

        # Date input
        self.data = SmartDateLineEdit()
        self.data.setObjectName("fieldInput")
        self.data.setFixedHeight(46)
        self.data.textChanged.connect(self._on_any_edited)
        date_block = self._field_block("Data do pagamento", self.data)

        row.addWidget(month_block, 1)
        row.addWidget(date_block, 1)

        section.addLayout(row)

        # Value input with prefix
        self.valor_wrap = QFrame()
        self.valor_wrap.setObjectName("moneyWrap")
        money_layout = QHBoxLayout(self.valor_wrap)
        money_layout.setContentsMargins(16, 0, 16, 0)
        money_layout.setSpacing(10)

        self.valor_prefix = QLabel("R$")
        self.valor_prefix.setObjectName("moneyPrefix")

        self.valor_input = QLineEdit()
        self.valor_input.setObjectName("moneyInput")
        self.valor_input.setPlaceholderText("Ex: 149,90")
        self.valor_input.setFixedHeight(46)
        self.valor_input.textEdited.connect(self._on_valor_edited)
        self.valor_input.editingFinished.connect(self._on_valor_finished)
        self.valor_input.textChanged.connect(self._hide_message)

        money_layout.addWidget(self.valor_prefix)
        money_layout.addWidget(self.valor_input, 1)

        section.addWidget(self._field_block("Valor pago", self.valor_wrap))

        return section

    def _build_actions(self) -> QHBoxLayout:
        """Build action buttons."""
        actions = QHBoxLayout()
        actions.setSpacing(12)
        actions.addStretch()

        self.btn_limpar = QPushButton("🗑  Limpar")
        self.btn_limpar.setObjectName("btnSecondary")
        self.btn_limpar.setFixedHeight(46)
        self.btn_limpar.setFixedWidth(130)
        self.btn_limpar.setCursor(Qt.PointingHandCursor)
        self.btn_limpar.clicked.connect(self.clear_form_full)

        self.btn_registrar = QPushButton("✓  Registrar pagamento")
        self.btn_registrar.setObjectName("btnPrimary")
        self.btn_registrar.setFixedHeight(46)
        self.btn_registrar.setFixedWidth(220)
        self.btn_registrar.setCursor(Qt.PointingHandCursor)
        self.btn_registrar.clicked.connect(self._on_registrar)

        actions.addWidget(self.btn_limpar)
        actions.addWidget(self.btn_registrar)

        return actions

    def _build_loading_overlay(self):
        """Build loading overlay."""
        layout = QVBoxLayout(self.loading_overlay)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addStretch()

        self.loading_spinner = QLabel("◐")
        self.loading_spinner.setObjectName("loadingSpinner")
        self.loading_spinner.setAlignment(Qt.AlignHCenter)

        self.loading_text = QLabel("Registrando pagamento...")
        self.loading_text.setObjectName("loadingText")
        self.loading_text.setAlignment(Qt.AlignHCenter)

        layout.addWidget(self.loading_spinner)
        layout.addWidget(self.loading_text)
        layout.addStretch()

    def _section_header(self, text: str) -> QLabel:
        """Create section header."""
        lbl = QLabel(text)
        lbl.setObjectName("sectionHeader")
        return lbl

    def _field_block(self, title: str, widget: QWidget | None) -> QFrame:
        """Create field block with label."""
        wrap = QFrame()
        wrap.setObjectName("fieldBlock")
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        label = QLabel(title)
        label.setObjectName("fieldLabel")

        layout.addWidget(label)
        if widget:
            layout.addWidget(widget)

        return wrap

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            self.loading_overlay.setGeometry(0, 0, self.card.width(), self.card.height())
        except Exception:
            pass

    def _apply_shadows(self):
        """Apply modern shadow effects."""
        try:
            # Card shadow
            sh = QGraphicsDropShadowEffect(self.card)
            sh.setBlurRadius(32)
            sh.setOffset(0, 10)
            sh.setColor(QColor(26, 107, 124, 30))
            self.card.setGraphicsEffect(sh)

            # Preview card shadow
            sh2 = QGraphicsDropShadowEffect(self.preview_card)
            sh2.setBlurRadius(16)
            sh2.setOffset(0, 4)
            sh2.setColor(QColor(15, 23, 42, 15))
            self.preview_card.setGraphicsEffect(sh2)
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════════
    # DEFAULTS AND STATE MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════
    def set_defaults(self):
        hoje = datetime.now()
        self.month_selector.set_current_month(hoje)
        self.data.setText(hoje.strftime("%d/%m/%Y"))

    def clear_form_keep_context(self, hide_message: bool = True):
        self.data.setText(datetime.now().strftime("%d/%m/%Y"))
        self.valor_input.clear()
        self.valor_input.setFocus()
        if hide_message:
            self._hide_message()
        self._update_register_enabled()

    def clear_form_full(self, hide_message: bool = True):
        """Clear entire form and return to default state."""
        self.name_popup.hide()
        self._name_search_token += 1

        self.set_defaults()
        self.valor_input.clear()

        if self.entity_mode.currentIndex() != 0:
            self.entity_mode.setCurrentIndex(0)
        else:
            self._on_entity_mode_changed()

        self._clear_all_errors()
        if hide_message:
            self._hide_message()
        self.search_input.setFocus()
        self._update_register_enabled()

    def _reset_cliente_state(self):
        self._cliente = {
            "ok": False,
            "tipo": self._target_type(),
            "id": None,
            "nome": None,
            "status": None,
            "pag_status": None,
            "plano": None,
            "dependentes": 0,
            "forma_pagamento": None,
            "dia_vencimento": 0,
            "documento": "",
            "valor_mensal": 0.0,
            "ultimo_pagamento": None,
        }

    def _target_type(self) -> str:
        if hasattr(self, "entity_mode"):
            v = str(self.entity_mode.currentData() or "").strip().lower()
            if v in {"cliente", "empresa"}:
                return v
        return "cliente"

    def _target_label(self) -> str:
        return "empresa" if self._target_type() == "empresa" else "cliente"

    def _target_label_plural(self) -> str:
        return "empresas" if self._target_type() == "empresa" else "clientes"

    def _document_label(self) -> str:
        return "CNPJ" if self._target_type() == "empresa" else "CPF"

    def _is_name_mode(self) -> bool:
        mode_text = (self.search_mode.currentText() or "").strip().upper()
        return "NOME" in mode_text

    def _sync_preview_labels(self):
        if self._target_type() == "empresa":
            if hasattr(self, "_p_plano_label"):
                self._p_plano_label.setText("Forma pag.")
            if hasattr(self, "_p_dependentes_label"):
                self._p_dependentes_label.setText("Vencimento")
            if hasattr(self, "_p_status_label"):
                self._p_status_label.setText("Status pag.")
            if hasattr(self, "_p_pagamento_label"):
                self._p_pagamento_label.setText("Tipo")
        else:
            if hasattr(self, "_p_plano_label"):
                self._p_plano_label.setText("Plano")
            if hasattr(self, "_p_dependentes_label"):
                self._p_dependentes_label.setText("Dependentes")
            if hasattr(self, "_p_status_label"):
                self._p_status_label.setText("Status")
            if hasattr(self, "_p_pagamento_label"):
                self._p_pagamento_label.setText("Pagamento")

    def _on_entity_mode_changed(self):
        self._hide_message()
        self.name_popup.hide()
        self._name_search_token += 1

        is_empresa = (self._target_type() == "empresa")
        doc_label = self._document_label()
        entidade = self._target_label()

        if hasattr(self, "search_header"):
            self.search_header.setText(f"🔍  Buscar {entidade}")

        if hasattr(self, "name_popup"):
            self.name_popup.set_title(f"Selecione a {entidade}" if is_empresa else f"Selecione o {entidade}")

        self.search_mode.blockSignals(True)
        self.search_mode.clear()
        if is_empresa:
            self.search_mode.addItems(["🏷️  CNPJ", "🏢  NOME"])
        else:
            self.search_mode.addItems(["🔢  CPF", "👤  NOME"])
        self.search_mode.setCurrentIndex(0)
        self.search_mode.blockSignals(False)

        self.search_input.clear()
        self.cpf.clear()
        self.cnpj.clear()
        self._reset_cliente_state()
        self._sync_preview_labels()
        self._reset_preview_ui()
        self._on_search_mode_changed()
        self._update_register_enabled()

        if is_empresa:
            self.preview_state.setText(f"Digite um {doc_label} ou Nome para carregar a empresa...")
        else:
            self.preview_state.setText(f"Digite um {doc_label} ou Nome para carregar o cliente...")

    def _reset_preview_ui(self):
        self.p_nome.setText("—")
        self.p_status_badge.setVisible(False)
        
        # Update info rows (stored as attributes during creation)
        if hasattr(self, '_p_plano_value'):
            self._p_plano_value.setText("—")
        if hasattr(self, '_p_dependentes_value'):
            self._p_dependentes_value.setText("—")
        if hasattr(self, '_p_mensalidade_value'):
            self._p_mensalidade_value.setText("—")
        if hasattr(self, '_p_status_value'):
            self._p_status_value.setText("—")
        if hasattr(self, '_p_pagamento_value'):
            self._p_pagamento_value.setText("—")
        if hasattr(self, '_p_ultimo_pag_value'):
            self._p_ultimo_pag_value.setText("—")

        artigo = "a" if self._target_type() == "empresa" else "o"
        self.preview_state.setText(f"Digite um {self._document_label()} ou Nome para carregar {artigo} {self._target_label()}...")
        self.preview_state.setProperty("ok", False)
        self.preview_state.setProperty("warn", False)
        self.preview_state.setProperty("loading", False)
        self._polish(self.preview_state)
        self._set_ok_state(self.search_input, False)

    # ══════════════════════════════════════════════════════════════════════════
    # SEARCH LOGIC (CPF/NOME)
    # ══════════════════════════════════════════════════════════════════════════
    def _on_search_mode_changed(self):
        is_name_mode = self._is_name_mode()
        is_empresa = (self._target_type() == "empresa")
        doc_label = self._document_label()
        
        self._hide_message()
        self.name_popup.hide()
        self._name_search_token += 1

        if not is_name_mode:
            if is_empresa:
                self.search_input.setPlaceholderText(f"Digite o {doc_label} (00.000.000/0000-00)...")
                self.search_input.setInputMask("00.000.000/0000-00;_")
                self.cnpj.setText(self.search_input.text())
                self.cpf.clear()
            else:
                self.search_input.setPlaceholderText(f"Digite o {doc_label} (000.000.000-00)...")
                self.search_input.setInputMask("000.000.000-00;_")
                self.cpf.setText(self.search_input.text())
                self.cnpj.clear()
            self.search_input._force_cursor_later()
        else:
            self.search_input.setInputMask("")
            prep = "da" if self._target_type() == "empresa" else "do"
            self.search_input.setPlaceholderText(f"Digite o nome {prep} {self._target_label()}...")
            self.cpf.clear()
            self.cnpj.clear()
            self._reset_preview_ui()
            self._update_register_enabled()

    def _on_search_text_changed(self, txt: str):
        self._hide_message()
        is_name_mode = self._is_name_mode()

        if not is_name_mode:
            if self._target_type() == "empresa":
                self.cnpj.setText(txt)
            else:
                self.cpf.setText(txt)
            self.name_popup.hide()
            return

        # NOME mode
        self._reset_cliente_state()
        self._reset_preview_ui()
        self._name_search_token += 1

        t = (txt or "").strip()
        if len(t) < 3:
            self.name_popup.hide()
            self.preview_state.setText("Digite pelo menos 3 letras para buscar por nome...")
            self.preview_state.setProperty("loading", False)
            self.preview_state.setProperty("warn", False)
            self.preview_state.setProperty("ok", False)
            self._polish(self.preview_state)
            return

        self.preview_state.setText(f"🔍  Buscando {self._target_label_plural()}...")
        self.preview_state.setProperty("loading", True)
        self.preview_state.setProperty("warn", False)
        self.preview_state.setProperty("ok", False)
        self._polish(self.preview_state)

        self._search_debounce.start(220)

    def _emit_search_request(self):
        if not self._is_name_mode():
            return

        name = (self.search_input.text() or "").strip()
        if len(name) < 3:
            return

        cb = self.on_search_empresa_name_request if self._target_type() == "empresa" else self.on_search_name_request
        if not callable(cb):
            self.preview_state.setText(f"⚠️  Busca por nome de {self._target_label()} não configurada.")
            self.preview_state.setProperty("loading", False)
            self.preview_state.setProperty("warn", True)
            self._polish(self.preview_state)
            return

        token = self._name_search_token

        def _worker():
            try:
                results = cb(name) or []
                self.name_search_done.emit(token, name, results)
            except Exception as exc:
                self.name_search_error.emit(token, str(exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_name_search_done(self, token: int, query: str, results_obj):
        if token != self._name_search_token:
            return
        if not self._is_name_mode():
            return
        if (self.search_input.text() or "").strip().lower() != (query or "").strip().lower():
            return

        results = list(results_obj or [])
        is_empresa = (self._target_type() == "empresa")
        if not results:
            self.name_popup.hide()
            if is_empresa:
                self.preview_state.setText("❌  Nenhuma empresa encontrada com esse nome.")
            else:
                self.preview_state.setText("❌  Nenhum cliente encontrado com esse nome.")
            self.preview_state.setProperty("loading", False)
            self.preview_state.setProperty("warn", True)
            self.preview_state.setProperty("ok", False)
            self._polish(self.preview_state)
            return

        self.name_popup.set_results(results)
        self._show_name_popup()

        suf = "encontradas" if is_empresa else "encontrados"
        self.preview_state.setText(f"✓  {len(results)} {self._target_label_plural()} {suf}. Selecione na lista.")
        self.preview_state.setProperty("loading", False)
        self.preview_state.setProperty("warn", False)
        self.preview_state.setProperty("ok", True)
        self._polish(self.preview_state)

    def _on_name_search_error(self, token: int, _err: str):
        if token != self._name_search_token:
            return
        self.name_popup.hide()
        self.preview_state.setText(f"⚠️  Falha ao buscar {self._target_label_plural()}.")
        self.preview_state.setProperty("loading", False)
        self.preview_state.setProperty("warn", True)
        self._polish(self.preview_state)

    def _show_name_popup(self):
        try:
            p = self.search_input.mapToGlobal(QPoint(0, self.search_input.height() + 8))
            self.name_popup.move(p)
            self.name_popup.show()
            self.name_popup.raise_()
        except Exception:
            pass

    def _on_name_picked(self, data: dict):
        doc_key = "cnpj" if self._target_type() == "empresa" else "cpf"
        documento = str(data.get(doc_key) or "").strip()
        if not documento:
            return
        # Switch to document mode and set selected value.
        self.search_mode.setCurrentIndex(0)
        self.search_input.setText(documento)

    # ══════════════════════════════════════════════════════════════════════════
    # CPF PREVIEW LOGIC
    # ══════════════════════════════════════════════════════════════════════════
    def _on_cpf_changed(self):
        txt = self.cpf.text()
        self._reset_cliente_state()
        self._clear_error(self.search_input)
        self._set_ok_state(self.search_input, False)

        if "_" in txt or len(txt.strip()) < 14:
            self._reset_preview_ui()
            self._update_register_enabled()
            return

        if not cpf_is_valid(txt):
            self._reset_preview_ui()
            self.preview_state.setText("❌  CPF inválido.")
            self.preview_state.setProperty("warn", True)
            self.preview_state.setProperty("loading", False)
            self.preview_state.setProperty("ok", False)
            self._polish(self.preview_state)
            self._mark_error(self.search_input)
            self._update_register_enabled()
            return

        self.preview_state.setText("🔍  Buscando cliente...")
        self.preview_state.setProperty("loading", True)
        self.preview_state.setProperty("warn", False)
        self.preview_state.setProperty("ok", False)
        self._polish(self.preview_state)

        if callable(self.on_preview_request):
            try:
                self.on_preview_request(txt)
            except Exception:
                self.preview_state.setText("⚠️  Erro ao consultar CPF.")
                self.preview_state.setProperty("warn", True)
                self.preview_state.setProperty("loading", False)
                self._polish(self.preview_state)

    def _on_cnpj_changed(self):
        txt = self.cnpj.text()
        self._reset_cliente_state()
        self._clear_error(self.search_input)
        self._set_ok_state(self.search_input, False)

        if "_" in txt or len(txt.strip()) < 18:
            self._reset_preview_ui()
            self._update_register_enabled()
            return

        if not cnpj_is_valid(txt):
            self._reset_preview_ui()
            self.preview_state.setText("❌  CNPJ inválido.")
            self.preview_state.setProperty("warn", True)
            self.preview_state.setProperty("loading", False)
            self.preview_state.setProperty("ok", False)
            self._polish(self.preview_state)
            self._mark_error(self.search_input)
            self._update_register_enabled()
            return

        self.preview_state.setText("🔍  Buscando empresa...")
        self.preview_state.setProperty("loading", True)
        self.preview_state.setProperty("warn", False)
        self.preview_state.setProperty("ok", False)
        self._polish(self.preview_state)

        if callable(self.on_preview_empresa_request):
            try:
                self.on_preview_empresa_request(txt)
            except Exception:
                self.preview_state.setText("⚠️  Erro ao consultar CNPJ.")
                self.preview_state.setProperty("warn", True)
                self.preview_state.setProperty("loading", False)
                self._polish(self.preview_state)

    def set_cliente_preview(
        self,
        ok: bool,
        text: str,
        *,
        warn: bool = False,
        cliente_id=None,
        nome=None,
        status=None,
        pagamento_status=None,
        plano=None,
        dependentes=0,
        valor_mensal=0.0,
        ultimo_pagamento: dict | None = None,
        auto_fill_valor: bool = True,
    ):
        """Set client preview data."""
        self.preview_state.setText(text)
        self.preview_state.setProperty("ok", ok)
        self.preview_state.setProperty("warn", warn)
        self.preview_state.setProperty("loading", False)
        self._polish(self.preview_state)

        if ok:
            self._cliente["ok"] = True
            self._cliente["tipo"] = "cliente"
            self._cliente["id"] = cliente_id
            self._cliente["nome"] = nome
            self._cliente["status"] = status
            self._cliente["pag_status"] = pagamento_status
            self._cliente["plano"] = plano
            self._cliente["dependentes"] = int(dependentes or 0)
            self._cliente["forma_pagamento"] = None
            self._cliente["dia_vencimento"] = 0
            self._cliente["documento"] = self.cpf.text().strip()
            self._cliente["valor_mensal"] = money_from_db(valor_mensal)
            self._cliente["ultimo_pagamento"] = ultimo_pagamento

            # Update preview card
            self.p_nome.setText(str(nome or "—"))
            
            # Status badge
            st = (str(status or "—")).upper()
            self.p_status_badge.setText(st)
            self.p_status_badge.setProperty("status", st.lower())
            self.p_status_badge.setVisible(True)
            self._polish(self.p_status_badge)

            # Update info rows
            if hasattr(self, '_p_plano_value'):
                self._p_plano_value.setText(str(plano or "—"))
            if hasattr(self, '_p_dependentes_value'):
                self._p_dependentes_value.setText(str(int(dependentes or 0)))
            if hasattr(self, '_p_mensalidade_value'):
                if self._cliente["valor_mensal"] > 0:
                    self._p_mensalidade_value.setText(f"R$ {money_format_br(self._cliente['valor_mensal'])}")
                else:
                    self._p_mensalidade_value.setText("—")
            if hasattr(self, '_p_status_value'):
                self._p_status_value.setText(st)
            if hasattr(self, '_p_pagamento_value'):
                pg = (str(pagamento_status or "—")).replace("_", " ").upper()
                self._p_pagamento_value.setText(pg)

            # Último pagamento
            if hasattr(self, '_p_ultimo_pag_value'):
                up = ultimo_pagamento or {}
                if up:
                    mes = up.get("mes_referencia") or up.get("mes") or ""
                    data_pag = up.get("data_pagamento") or up.get("data") or ""
                    if mes:
                        mes = iso_to_br(str(mes))
                    if data_pag:
                        try:
                            if len(str(data_pag)) == 10 and str(data_pag)[4] == "-":
                                y, m, d = str(data_pag).split("-", 2)
                                data_pag = f"{d}/{m}/{y}"
                        except Exception:
                            pass
                    if mes or data_pag:
                        self._p_ultimo_pag_value.setText(f"{mes or '—'} • {data_pag or '—'}")
                    else:
                        self._p_ultimo_pag_value.setText("—")
                else:
                    self._p_ultimo_pag_value.setText("—")

            # Auto-fill valor
            if auto_fill_valor and (not self.valor_input.text().strip()):
                if self._cliente["valor_mensal"] and self._cliente["valor_mensal"] > 0:
                    self.valor_input.setText(money_format_br(self._cliente["valor_mensal"]))

            self._set_ok_state(self.search_input, True)

        self._update_register_enabled()

    def set_empresa_preview(
        self,
        ok: bool,
        text: str,
        *,
        warn: bool = False,
        empresa_id=None,
        nome=None,
        status_pagamento=None,
        forma_pagamento=None,
        dia_vencimento=0,
        valor_mensal=0.0,
        ultimo_pagamento: dict | None = None,
        auto_fill_valor: bool = True,
    ):
        self.preview_state.setText(text)
        self.preview_state.setProperty("ok", ok)
        self.preview_state.setProperty("warn", warn)
        self.preview_state.setProperty("loading", False)
        self._polish(self.preview_state)

        if ok:
            self._cliente["ok"] = True
            self._cliente["tipo"] = "empresa"
            self._cliente["id"] = empresa_id
            self._cliente["nome"] = nome
            self._cliente["status"] = status_pagamento
            self._cliente["pag_status"] = status_pagamento
            self._cliente["plano"] = None
            self._cliente["dependentes"] = 0
            self._cliente["forma_pagamento"] = forma_pagamento
            self._cliente["dia_vencimento"] = int(dia_vencimento or 0)
            self._cliente["documento"] = self.cnpj.text().strip()
            self._cliente["valor_mensal"] = money_from_db(valor_mensal)
            self._cliente["ultimo_pagamento"] = ultimo_pagamento

            self.p_nome.setText(str(nome or "—"))

            st_raw = str(status_pagamento or "—").strip().lower()
            st_txt = st_raw.replace("_", " ").upper()
            self.p_status_badge.setText(st_txt)
            self.p_status_badge.setProperty("status", st_raw)
            self.p_status_badge.setVisible(True)
            self._polish(self.p_status_badge)

            if hasattr(self, "_p_plano_value"):
                fp = str(forma_pagamento or "—").replace("_", " ").upper()
                self._p_plano_value.setText(fp)
            if hasattr(self, "_p_dependentes_value"):
                dia_txt = f"Dia {int(dia_vencimento)}" if int(dia_vencimento or 0) > 0 else "—"
                self._p_dependentes_value.setText(dia_txt)
            if hasattr(self, "_p_mensalidade_value"):
                if self._cliente["valor_mensal"] > 0:
                    self._p_mensalidade_value.setText(f"R$ {money_format_br(self._cliente['valor_mensal'])}")
                else:
                    self._p_mensalidade_value.setText("—")
            if hasattr(self, "_p_status_value"):
                self._p_status_value.setText(st_txt)
            if hasattr(self, "_p_pagamento_value"):
                self._p_pagamento_value.setText("EMPRESA")

            if hasattr(self, "_p_ultimo_pag_value"):
                up = ultimo_pagamento or {}
                if up:
                    mes = up.get("mes_referencia") or up.get("mes") or ""
                    data_pag = up.get("data_pagamento") or up.get("data") or ""
                    if mes:
                        mes = iso_to_br(str(mes))
                    if data_pag:
                        try:
                            if len(str(data_pag)) == 10 and str(data_pag)[4] == "-":
                                y, m, d = str(data_pag).split("-", 2)
                                data_pag = f"{d}/{m}/{y}"
                        except Exception:
                            pass
                    if mes or data_pag:
                        self._p_ultimo_pag_value.setText(f"{mes or '—'} • {data_pag or '—'}")
                    else:
                        self._p_ultimo_pag_value.setText("—")
                else:
                    self._p_ultimo_pag_value.setText("—")

            if auto_fill_valor and (not self.valor_input.text().strip()):
                if self._cliente["valor_mensal"] and self._cliente["valor_mensal"] > 0:
                    self.valor_input.setText(money_format_br(self._cliente["valor_mensal"]))

            self._set_ok_state(self.search_input, True)

        self._update_register_enabled()

    # ══════════════════════════════════════════════════════════════════════════
    # VALOR UX
    # ══════════════════════════════════════════════════════════════════════════
    def _on_valor_edited(self, txt: str):
        cleaned = []
        for ch in txt:
            if ch.isdigit() or ch in ",.":
                cleaned.append(ch)
        out = "".join(cleaned)
        if out != txt:
            cursor = self.valor_input.cursorPosition()
            self.valor_input.setText(out)
            self.valor_input.setCursorPosition(max(0, cursor - 1))
        self._clear_error(self.valor_input)
        self._update_register_enabled()

    def _on_valor_finished(self):
        v = money_parse_br(self.valor_input.text())
        if v is None:
            return
        self.valor_input.setText(money_format_br(v))
        self._update_register_enabled()

    # ══════════════════════════════════════════════════════════════════════════
    # VALIDATION AND ENABLE LOGIC
    # ══════════════════════════════════════════════════════════════════════════
    def _on_any_edited(self, *_):
        self._hide_message()
        self._update_register_enabled()

    def _update_register_enabled(self):
        if self._loading:
            self.btn_registrar.setEnabled(False)
            self.btn_registrar.setToolTip("Aguarde o processamento...")
            self.register_hint.setText("Processando registro...")
            self.register_hint.setVisible(True)
            return

        is_name_mode = self._is_name_mode()
        is_empresa = (self._target_type() == "empresa")
        entidade = self._target_label()
        doc_label = self._document_label()

        if is_empresa:
            doc_txt = self.cnpj.text().strip()
            doc_ok = (len(doc_txt) == 18 and "_" not in doc_txt and cnpj_is_valid(doc_txt))
        else:
            doc_txt = self.cpf.text().strip()
            doc_ok = (len(doc_txt) == 14 and "_" not in doc_txt and cpf_is_valid(doc_txt))

        entidade_ok = bool(self._cliente.get("ok"))

        try:
            mes_iso = self.month_selector.mes_iso()
            mes_ok = bool(mes_iso)
        except Exception:
            mes_ok = False

        data_txt = self.data.text().strip()
        data_ok = ("_" not in data_txt and len(data_txt) == 10)
        if data_ok:
            try:
                d, m, y = data_txt.split("/")
                dt = datetime(int(y), int(m), int(d))
                if dt.date() > datetime.now().date():
                    data_ok = False
            except Exception:
                data_ok = False

        valor_ok = money_parse_br(self.valor_input.text()) is not None
        inativo = (not is_empresa) and (str(self._cliente.get("status") or "").lower() == "inativo")

        enabled = (not is_name_mode) and doc_ok and entidade_ok and mes_ok and data_ok and valor_ok and not inativo
        self.btn_registrar.setEnabled(enabled)

        reason = ""
        if is_name_mode:
            reason = f"Selecione {entidade} por {doc_label} para registrar"
        elif not doc_ok:
            reason = f"Informe um {doc_label} válido"
        elif not entidade_ok:
            reason = "Carregue uma empresa válida" if is_empresa else "Carregue um cliente válido"
        elif not mes_ok:
            reason = "Selecione um mês válido"
        elif not data_ok:
            reason = "Informe uma data válida (não futura)"
        elif not valor_ok:
            reason = "Informe um valor válido"
        elif inativo:
            reason = "Cliente inativo não pode receber pagamento"

        if enabled:
            self.btn_registrar.setToolTip("Registrar pagamento (Ctrl+Enter)")
            self.register_hint.setVisible(False)
        else:
            self.btn_registrar.setToolTip(reason or "Preencha todos os campos")
            self.register_hint.setText(reason or "Preencha todos os campos")
            self.register_hint.setVisible(True)

        if not is_name_mode:
            self._set_ok_state(self.search_input, bool(doc_ok and entidade_ok and not inativo))
        else:
            self._set_ok_state(self.search_input, False)

        try:
            self.month_selector.set_error(not bool(mes_ok))
        except Exception:
            pass
        self._set_ok_state(self.data, bool(data_ok))
        self._set_ok_state(self.valor_input, bool(valor_ok))

    def _try_register_from_enter(self):
        if self.btn_registrar.isEnabled() and (not self._loading):
            self._on_registrar()

    # ══════════════════════════════════════════════════════════════════════════
    # REGISTER LOGIC
    # ══════════════════════════════════════════════════════════════════════════
    def _on_registrar(self):
        """Handle registration."""
        if self._loading:
            return

        is_name_mode = self._is_name_mode()
        is_empresa = (self._target_type() == "empresa")
        entidade = self._target_label()
        doc_label = self._document_label()

        if is_name_mode:
            self._show_message(f"Selecione {entidade} (modo {doc_label}) antes de registrar.", ok=False, ms=3200)
            return

        documento = self.cnpj.text().strip() if is_empresa else self.cpf.text().strip()
        data_br = self.data.text().strip()
        valor_txt = self.valor_input.text().strip()

        self._clear_all_errors()

        # Validations
        if is_empresa:
            doc_ok = ("_" not in documento and len(documento) == 18 and cnpj_is_valid(documento))
        else:
            doc_ok = ("_" not in documento and len(documento) == 14 and cpf_is_valid(documento))

        if not doc_ok:
            self._mark_error(self.search_input)
            self._show_message(f"{doc_label} inválido.", ok=False)
            self.search_input.setFocus()
            return

        if not self._cliente.get("ok"):
            self._mark_error(self.search_input)
            self._show_message(f"Carregue {entidade} válido(a) pelo {doc_label}.", ok=False)
            self.search_input.setFocus()
            return

        if (not is_empresa) and str(self._cliente.get("status") or "").lower() == "inativo":
            self._show_message("Cliente INATIVO. Não é possível registrar pagamento.", ok=False)
            return

        try:
            mes_iso = self.month_selector.mes_iso()
            mes_br = self.month_selector.mes_br()
        except Exception:
            self._show_message("Mês inválido.", ok=False)
            return

        if "_" in data_br or len(data_br) != 10:
            self._mark_error(self.data)
            self._show_message("Data inválida (DD/MM/AAAA).", ok=False)
            self.data.setFocus()
            return

        try:
            d, m, y = data_br.split("/")
            dt = datetime(int(y), int(m), int(d))
            if dt.date() > datetime.now().date():
                raise ValueError("Data futura")
            data_iso = dt.strftime("%Y-%m-%d")
        except Exception:
            self._mark_error(self.data)
            self._show_message("Data inválida.", ok=False)
            self.data.setFocus()
            return

        valor = money_parse_br(valor_txt)
        if valor is None:
            self._mark_error(self.valor_input)
            self._show_message("Valor inválido. Ex: 149,90", ok=False)
            self.valor_input.setFocus()
            return

        entidade_id = int(self._cliente["id"])

        # Check duplicate
        duplicate_cb = self.on_check_duplicate_empresa if is_empresa else self.on_check_duplicate
        if callable(duplicate_cb):
            try:
                exists, existing = duplicate_cb(entidade_id, mes_iso)
            except Exception:
                exists, existing = (False, None)

            if exists:
                data_e = "—"
                val_e = 0.0
                if existing:
                    data_e = str(existing.get("data_pagamento", "—") or "—")
                    if len(data_e) == 10 and data_e[4] == "-":
                        y, m, d = data_e.split("-", 2)
                        data_e = f"{d}/{m}/{y}"
                    val_e = float(existing.get("valor_pago", 0.0) or 0.0)

                msg = (
                    f"Já existe pagamento para {mes_br}.\n\n"
                    f"Atual: {data_e} - R$ {money_format_br(val_e)}\n\n"
                    "Deseja atualizar este pagamento?"
                )
                resp = QMessageBox.question(
                    self,
                    "Atualizar pagamento",
                    msg,
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if resp != QMessageBox.Yes:
                    self._show_message("Atualização cancelada.", ok=False, ms=3200)
                    return

        dados = {
            "tipo_pagador": "empresa" if is_empresa else "cliente",
            "mes_referencia": mes_br,
            "mes_iso": mes_iso,
            "data_pagamento": data_iso,
            "valor_pago": float(valor),
            "valor_texto": valor_txt,
        }
        if is_empresa:
            dados["cnpj"] = documento
            dados["empresa_id"] = entidade_id
            dados["nome_empresa"] = self._cliente.get("nome") or ""
        else:
            dados["cpf"] = documento
            dados["cliente_id"] = entidade_id
            dados["nome_cliente"] = self._cliente.get("nome") or ""

        self._set_loading(True)
        QTimer.singleShot(120, lambda: self.registrar_signal.emit(dados))

    def finish_register(self, ok: bool, msg: str):
        """Finish registration with result."""
        self._set_loading(False)

        if ok:
            self.clear_form_keep_context(hide_message=False)
            self._refresh_current_preview()
            self._show_message(msg or "✓  Pagamento registrado com sucesso!", ok=True, ms=3200)
        else:
            self._apply_backend_error(msg or "✗  Não foi possível registrar o pagamento.")

    @staticmethod
    def _normalize_error_text(msg: str) -> str:
        txt = unicodedata.normalize("NFKD", str(msg or ""))
        txt = "".join(ch for ch in txt if not unicodedata.combining(ch))
        txt = txt.lower()
        txt = re.sub(r"[^a-z0-9\s]+", " ", txt)
        return " ".join(txt.split())

    def _apply_backend_error(self, msg: str):
        message = str(msg or "Nao foi possivel registrar o pagamento.")
        norm = self._normalize_error_text(message)
        self._clear_all_errors()

        focused = False
        if "mes de referencia" in norm or "mes invalido" in norm:
            try:
                self.month_selector.set_error(True)
            except Exception:
                pass
        elif (
            "cpf" in norm
            or "cnpj" in norm
            or "cliente nao encontrado" in norm
            or "empresa nao encontrada" in norm
            or "carregue cliente valido" in norm
            or "carregue empresa valida" in norm
        ):
            self._mark_error(self.search_input)
            self.search_input.setFocus()
            focused = True
        elif "data de pagamento" in norm or "data invalida" in norm or "data nao pode ser futura" in norm:
            self._mark_error(self.data)
            self.data.setFocus()
            focused = True
        elif "valor do pagamento" in norm or "valor invalido" in norm or "maior que zero" in norm:
            self._mark_error(self.valor_input)
            self.valor_input.setFocus()
            focused = True

        if not focused:
            self.search_input.setFocus()
        self._show_message(message, ok=False, ms=3200)

    def _refresh_current_preview(self):
        """Refresh current target preview after save."""
        is_empresa = (self._target_type() == "empresa")
        documento = self.cnpj.text().strip() if is_empresa else self.cpf.text().strip()
        if is_empresa:
            if "_" in documento or len(documento) != 18 or not cnpj_is_valid(documento):
                return
        else:
            if "_" in documento or len(documento) != 14 or not cpf_is_valid(documento):
                return

        cb = self.on_preview_empresa_request if is_empresa else self.on_preview_request
        if not callable(cb):
            return

        self.preview_state.setText("🔄  Atualizando preview...")
        self.preview_state.setProperty("loading", True)
        self._polish(self.preview_state)
        try:
            cb(documento)
        except Exception:
            self.preview_state.setText("Pagamento salvo, mas não foi possível atualizar o preview.")
            self.preview_state.setProperty("warn", True)
            self.preview_state.setProperty("loading", False)
            self._polish(self.preview_state)

    # ══════════════════════════════════════════════════════════════════════════
    # LOADING STATE
    # ══════════════════════════════════════════════════════════════════════════
    def _set_loading(self, loading: bool):
        """Set loading state."""
        self._loading = loading

        self.entity_mode.setEnabled(not loading)
        self.search_mode.setEnabled(not loading)
        self.search_input.setEnabled(not loading)
        self.month_selector.set_enabled(not loading)
        self.data.setEnabled(not loading)
        self.valor_input.setEnabled(not loading)
        self.btn_limpar.setEnabled(not loading)

        if loading:
            self._spinner_i = 0
            self.btn_registrar.setEnabled(False)
            self.btn_registrar.setToolTip("Aguarde o processamento...")
            self.register_hint.setText("Processando registro...")
            self.register_hint.setVisible(True)
            self.loading_overlay.setVisible(True)
            self.loading_spinner.setText(self._spinner_frames[self._spinner_i])
            self._loading_timer.start(120)
        else:
            self._loading_timer.stop()
            self.loading_overlay.setVisible(False)
            self._update_register_enabled()

    def _tick_loading(self):
        """Update loading spinner."""
        self._spinner_i = (self._spinner_i + 1) % len(self._spinner_frames)
        self.loading_spinner.setText(self._spinner_frames[self._spinner_i])

    # ══════════════════════════════════════════════════════════════════════════
    # EVENT FILTERS
    # ══════════════════════════════════════════════════════════════════════════
    def eventFilter(self, obj, event):
        if obj is self.valor_input:
            if event.type() == QEvent.FocusIn:
                QTimer.singleShot(0, lambda: self.valor_input.setCursorPosition(0))
                return False

        if obj is self.search_input and event.type() == QEvent.KeyPress:
            mode_text = self.search_mode.currentText().strip()
            if "NOME" in mode_text.upper():
                key = event.key()
                if key in (Qt.Key_Down, Qt.Key_Up) and self.name_popup.isVisible() and self.name_popup.list.count() > 0:
                    self.name_popup.list.setFocus()
                    if key == Qt.Key_Down:
                        self.name_popup.list.setCurrentRow(0)
                    else:
                        self.name_popup.list.setCurrentRow(self.name_popup.list.count() - 1)
                    return True
                if key == Qt.Key_Escape and self.name_popup.isVisible():
                    self.name_popup.hide()
                    return True
                if key in (Qt.Key_Return, Qt.Key_Enter) and self.name_popup.isVisible():
                    item = self.name_popup.list.currentItem()
                    if item is not None:
                        self.name_popup._on_item_clicked(item)
                        return True
        return super().eventFilter(obj, event)

    # ══════════════════════════════════════════════════════════════════════════
    # UI HELPERS
    # ══════════════════════════════════════════════════════════════════════════
    def _show_message(self, text: str, ok: bool = False, ms: int = 2800):
        """Show inline message."""
        if not hasattr(self, "inline_msg") or self.inline_msg is None:
            return
        self.inline_msg.setText(text)
        self.inline_msg.setProperty("ok", ok)
        self._polish(self.inline_msg)
        self.inline_msg.setVisible(True)
        self._msg_timer.start(ms)

    def _hide_message(self):
        """Hide inline message."""
        self._msg_timer.stop()
        if not hasattr(self, "inline_msg") or self.inline_msg is None:
            return
        self.inline_msg.setVisible(False)
        self.inline_msg.setText("")

    def _mark_error(self, widget: QWidget):
        """Mark widget as error."""
        widget.setProperty("error", True)
        self._polish(widget)

    def _clear_error(self, widget: QWidget):
        """Clear error state."""
        if widget.property("error"):
            widget.setProperty("error", False)
            self._polish(widget)

    def _clear_all_errors(self):
        """Clear all error states."""
        for w in (self.search_input, self.data, self.valor_input):
            self._clear_error(w)
        try:
            self.month_selector.set_error(False)
        except Exception:
            pass

    def _set_ok_state(self, widget: QWidget, ok: bool):
        """Set OK state."""
        widget.setProperty("ok", bool(ok))
        self._polish(widget)

    def _polish(self, widget: QWidget):
        """Force style refresh."""
        try:
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════════
    # STYLES - MODERN SAAS DESIGN
    # ══════════════════════════════════════════════════════════════════════════
    def apply_styles(self):
        """Apply modern SaaS stylesheet."""
        base_qss = build_view_qss("RegistrarPagamento", f"""
        /* ══════════════════════════════════════════════════════════════
           MODERN SAAS PAYMENT REGISTRATION - Indigo Design System
           Premium aesthetics with enhanced UX
           ══════════════════════════════════════════════════
        QWidget#RegistrarPagamento {{
            background: {Theme.BG};
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
        }}

        QScrollArea#mainScroll {{
            border: none;
            background: transparent;
        }}

        QScrollArea#mainScroll > QWidget > QWidget {{
            background: transparent;
        }}

        /* ── Header ────────────────────────────────────────────────── */
        QFrame#header {{
            background: transparent;
            border: none;
        }}

        QLabel#breadcrumb {{
            font-size: 11px;
            font-weight: 600;
            color: {Theme.INK3};
            letter-spacing: 0.5px;
            text-transform: uppercase;
        }}

        QLabel#titleIcon {{
            font-size: 28px;
        }}

        QLabel#title {{
            font-size: 28px;
            font-weight: 700;
            color: {Theme.INK};
            letter-spacing: -0.7px;
        }}

        QLabel#subtitle {{
            font-size: 13px;
            color: {Theme.INK2};
            font-weight: 500;
        }}

        /* ── Divider ───────────────────────────────────────────────── */
        QFrame#softLine {{
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:0,
                stop:0 transparent,
                stop:0.2 {Theme.LINE},
                stop:0.8 {Theme.LINE},
                stop:1 transparent
            );
            border: none;
        }}

        /* ── Main Card ─────────────────────────────────────────────── */
        QFrame#card {{
            background: {Theme.SURFACE};
            border: 2px solid {Theme.LINE};
            border-radius: 16px;
        }}

        /* ── Section Headers ───────────────────────────────────────── */
        QLabel#sectionHeader {{
            font-size: 14px;
            font-weight: 700;
            color: {Theme.INK};
            padding: 4px 0;
        }}

        /* ── Field Blocks ──────────────────────────────────────────── */
        QFrame#fieldBlock {{
            background: transparent;
            border: none;
        }}

        QLabel#fieldLabel {{
            font-size: 12px;
            font-weight: 600;
            color: {Theme.INK2};
            padding-left: 2px;
            letter-spacing: 0.2px;
        }}

        /* ── Input Fields ──────────────────────────────────────────── */
        QLineEdit#fieldInput, QLineEdit#moneyInput {{
            background: {Theme.SURFACE};
            border: 1.5px solid {Theme.LINE};
            border-radius: 10px;
            padding: 12px 16px;
            font-size: 14px;
            color: {Theme.INK};
            selection-background-color: {Theme.PRIMARY_SOFT};
            selection-color: {Theme.INK};
        }}

        QLineEdit::placeholder {{
            color: {Theme.INK3};
        }}

        QLineEdit:hover {{
            border-color: rgba(99,102,241,0.35);
        }}

        QLineEdit:focus {{
            border: 2px solid {Theme.PRIMARY};
            padding: 11px 15px;
        }}

        QLineEdit[error="true"] {{
            border: 1.5px solid {Theme.DANGER_BORDER};
            background: {Theme.DANGER_SOFT};
        }}

        QLineEdit[ok="true"] {{
            border: 1.5px solid {Theme.SUCCESS_BORDER};
            background: {Theme.SUCCESS_SOFT};
        }}

        /* ── Search Mode Combo ─────────────────────────────────────── */
        QComboBox#searchMode {{
            background: {Theme.SURFACE};
            border: 1.5px solid {Theme.LINE};
            border-radius: 10px;
            padding: 0 36px 0 14px;
            font-size: 13px;
            font-weight: 600;
            color: {Theme.INK};
            min-height: 44px;
        }}

        QComboBox#searchMode:hover {{
            border-color: {Theme.PRIMARY};
            background: {Theme.PRIMARY_SOFT};
        }}

        QComboBox#searchMode::drop-down {{
            border: none;
            width: 30px;
        }}

        QComboBox#searchMode::down-arrow {{
            width: 0;
            height: 0;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid {Theme.INK3};
        }}

        /* ── Month/Year Combos ─────────────────────────────────────── */
        QComboBox#monthCombo, QComboBox#yearCombo {{
            background: {Theme.SURFACE};
            border: 1.5px solid {Theme.LINE};
            border-radius: 10px;
            padding: 0 36px 0 14px;
            font-size: 13px;
            font-weight: 600;
            color: {Theme.INK};
            min-height: 44px;
        }}

        QComboBox#monthCombo:hover, QComboBox#yearCombo:hover {{
            border-color: {Theme.PRIMARY};
        }}

        QComboBox#monthCombo[error="true"], QComboBox#yearCombo[error="true"] {{
            border: 1.5px solid {Theme.DANGER_BORDER};
            background: {Theme.DANGER_SOFT};
        }}

        QComboBox#monthCombo::drop-down, QComboBox#yearCombo::drop-down {{
            border: none;
            width: 28px;
        }}

        QComboBox#monthCombo::down-arrow, QComboBox#yearCombo::down-arrow {{
            width: 0;
            height: 0;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid {Theme.INK3};
        }}

        /* ── Combo Popup ───────────────────────────────────────────── */
        QWidget#comboPopupWindow {{
            background: {Theme.SURFACE};
            border: 2px solid {Theme.LINE};
            border-radius: 12px;
        }}

        QAbstractItemView#comboPopupView {{
            background: {Theme.SURFACE};
            border: none;
            outline: none;
            padding: 6px;
            selection-background-color: {Theme.PRIMARY_SOFT};
            selection-color: {Theme.INK};
        }}

        QAbstractItemView#comboPopupView::item {{
            padding: 10px 12px;
            border-radius: 8px;
            margin: 2px;
            font-size: 13px;
            color: {Theme.INK};
        }}

        QAbstractItemView#comboPopupView::item:hover {{
            background: {Theme.PRIMARY_SOFT};
        }}

        /* ── Month Selector ────────────────────────────────────────── */
        QWidget#monthSelector {{
            background: transparent;
        }}

        QToolButton#monthNavBtn {{
            background: {Theme.SURFACE};
            border: 1.5px solid {Theme.LINE};
            border-radius: 10px;
            min-width: 44px;
            min-height: 44px;
            font-size: 14px;
            font-weight: 700;
            color: {Theme.INK2};
        }}

        QToolButton#monthNavBtn:hover {{
            border-color: {Theme.PRIMARY};
            color: {Theme.PRIMARY};
            background: {Theme.PRIMARY_SOFT};
        }}

        QToolButton#monthNavBtn:pressed {{
            background: rgba(99,102,241,0.18);
        }}

        QLabel#monthChip {{
            background: {Theme.PRIMARY_SOFT};
            border: 1.5px solid {Theme.PRIMARY_BORDER};
            border-radius: 20px;
            padding: 6px 16px;
            font-size: 12px;
            font-weight: 700;
            color: {Theme.PRIMARY};
        }}

        /* ── Money Wrapper ─────────────────────────────────────────── */
        QFrame#moneyWrap {{
            background: {Theme.SURFACE};
            border: 1.5px solid {Theme.LINE};
            border-radius: 10px;
        }}

        QFrame#moneyWrap:focus-within {{
            border: 2px solid {Theme.PRIMARY};
        }}

        QLabel#moneyPrefix {{
            font-size: 16px;
            font-weight: 700;
            color: {Theme.INK2};
        }}

        QLineEdit#moneyInput {{
            border: none;
            background: transparent;
            padding-left: 0;
            font-size: 16px;
            font-weight: 600;
        }}

        QLineEdit#moneyInput[error="true"],
        QLineEdit#moneyInput[ok="true"] {{
            background: transparent;
        }}

        /* ── Preview Card ──────────────────────────────────────────── */
        QFrame#previewCard {{
            background: {Theme.SURFACE};
            border: 2px solid {Theme.LINE};
            border-radius: 12px;
        }}

        QLabel#pTitle {{
            font-size: 18px;
            font-weight: 700;
            color: {Theme.INK};
            letter-spacing: -0.3px;
        }}

        QLabel#statusBadge {{
            background: {Theme.PRIMARY_SOFT};
            border: 1.5px solid {Theme.PRIMARY_BORDER};
            border-radius: 16px;
            padding: 4px 14px;
            font-size: 11px;
            font-weight: 700;
            color: {Theme.PRIMARY};
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        QLabel#statusBadge[status="inativo"] {{
            background: {Theme.DANGER_SOFT};
            border-color: {Theme.DANGER_BORDER};
            color: {Theme.DANGER};
        }}

        QLabel#statusBadge[status="ativo"] {{
            background: {Theme.SUCCESS_SOFT};
            border-color: {Theme.SUCCESS_BORDER};
            color: {Theme.SUCCESS};
        }}

        QLabel#statusBadge[status="em_dia"] {{
            background: {Theme.SUCCESS_SOFT};
            border-color: {Theme.SUCCESS_BORDER};
            color: {Theme.SUCCESS};
        }}

        QLabel#statusBadge[status="pendente"] {{
            background: {Theme.WARNING_SOFT};
            border-color: {Theme.WARNING_BORDER};
            color: {Theme.WARNING};
        }}

        QLabel#statusBadge[status="inadimplente"] {{
            background: {Theme.DANGER_SOFT};
            border-color: {Theme.DANGER_BORDER};
            color: {Theme.DANGER};
        }}

        QLabel#statusBadge[status="em_atraso"] {{
            background: {Theme.DANGER_SOFT};
            border-color: {Theme.DANGER_BORDER};
            color: {Theme.DANGER};
        }}

        QLabel#pIcon {{
            font-size: 16px;
        }}

        QLabel#pLabel {{
            font-size: 11px;
            font-weight: 600;
            color: {Theme.INK3};
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        QLabel#pValue {{
            font-size: 14px;
            font-weight: 600;
            color: {Theme.INK};
        }}

        /* ── Preview State ─────────────────────────────────────────── */
        QLabel#previewState {{
            background: {Theme.BG};
            border: 1.5px solid {Theme.LINE};
            border-radius: 10px;
            padding: 12px 16px;
            font-size: 13px;
            color: {Theme.INK2};
            font-weight: 500;
        }}

        QLabel#previewState[ok="true"] {{
            background: {Theme.SUCCESS_SOFT};
            border-color: {Theme.SUCCESS_BORDER};
            color: {Theme.SUCCESS};
        }}

        QLabel#previewState[warn="true"] {{
            background: {Theme.WARNING_SOFT};
            border-color: {Theme.WARNING_BORDER};
            color: {Theme.WARNING};
        }}

        QLabel#previewState[loading="true"] {{
            background: {Theme.PRIMARY_SOFT};
            border-color: {Theme.PRIMARY_BORDER};
            color: {Theme.PRIMARY};
        }}

        /* ── Buttons ───────────────────────────────────────────────── */
        QPushButton#btnPrimary {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {Theme.PRIMARY},
                stop:1 {Theme.PRIMARY_HOVER}
            );
            color: white;
            border: none;
            border-radius: 10px;
            padding: 0 24px;
            font-size: 14px;
            font-weight: 700;
            letter-spacing: 0.2px;
        }}

        QPushButton#btnPrimary:hover {{
            background: {Theme.PRIMARY_HOVER};
        }}

        QPushButton#btnPrimary:pressed {{
            background: #4338ca;
        }}

        QPushButton#btnPrimary:disabled {{
            background: {Theme.INK3};
            color: rgba(255,255,255,0.85);
        }}

        QPushButton#btnSecondary {{
            background: {Theme.SURFACE};
            color: {Theme.INK};
            border: 1.5px solid {Theme.LINE};
            border-radius: 10px;
            padding: 0 20px;
            font-size: 14px;
            font-weight: 700;
        }}

        QPushButton#btnSecondary:hover {{
            border-color: {Theme.PRIMARY};
            color: {Theme.PRIMARY};
            background: {Theme.PRIMARY_SOFT};
        }}

        QPushButton#btnSecondary:pressed {{
            background: rgba(99,102,241,0.18);
        }}

        /* ── Messages ──────────────────────────────────────────────── */
        QLabel#inlineMessage {{
            background: {Theme.DANGER_SOFT};
            border: 1.5px solid {Theme.DANGER_BORDER};
            border-radius: 10px;
            padding: 12px 18px;
            font-size: 13px;
            font-weight: 600;
            color: {Theme.DANGER};
        }}

        QLabel#inlineMessage[ok="true"] {{
            background: {Theme.SUCCESS_SOFT};
            border-color: {Theme.SUCCESS_BORDER};
            color: {Theme.SUCCESS};
        }}

        QLabel#registerHint {{
            color: {Theme.INK3};
            font-size: 12px;
            font-weight: 500;
            padding: 0 2px;
        }}

        /* ── Name Popup ────────────────────────────────────────────── */
        QFrame#namePopup {{
            background: {Theme.SURFACE};
            border: 2px solid {Theme.LINE};
            border-radius: 14px;
        }}

        QLabel#namePopupTitle {{
            font-size: 13px;
            font-weight: 700;
            color: {Theme.INK};
        }}

        QListWidget#namePopupList {{
            border: none;
            background: transparent;
            outline: none;
        }}

        QListWidget#namePopupList::item {{
            padding: 12px 14px;
            border-radius: 8px;
            margin: 3px;
            font-size: 13px;
            color: {Theme.INK};
            background: {Theme.BG};
        }}

        QListWidget#namePopupList::item:hover {{
            background: {Theme.PRIMARY_SOFT};
        }}

        QListWidget#namePopupList::item:selected {{
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:0,
                stop:0 {Theme.PRIMARY_SOFT},
                stop:1 rgba(99,102,241,0.15)
            );
            color: {Theme.PRIMARY};
            font-weight: 600;
        }}

        /* ── Loading Overlay ───────────────────────────────────────── */
        QFrame#loadingOverlay {{
            background: rgba(248,250,252,0.92);
            border-radius: 16px;
        }}

        QLabel#loadingSpinner {{
            font-size: 42px;
            font-weight: 700;
            color: {Theme.PRIMARY};
        }}

        QLabel#loadingText {{
            font-size: 14px;
            font-weight: 600;
            color: {Theme.INK2};
        }}

        /* ── Scrollbar ─────────────────────────────────────────────── */
        QScrollBar:vertical {{
            background: transparent;
            width: 8px;
            margin: 4px 2px;
        }}

        QScrollBar::handle:vertical {{
            background: {Theme.LINE};
            border-radius: 4px;
            min-height: 40px;
        }}

        QScrollBar::handle:vertical:hover {{
            background: rgba(99,102,241,0.40);
        }}

        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{
            height: 0px;
        }}

        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {{
            background: transparent;
        }}
        """)
        self._base_qss = base_qss
        self.setStyleSheet(base_qss)

