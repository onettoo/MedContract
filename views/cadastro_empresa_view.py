# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal, QRegularExpression, QTimer, QUrl, QPoint
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFrame,
    QComboBox,
    QSpinBox,
    QGridLayout,
    QScrollArea,
    QProgressBar,
)

from views.cadastro_cliente_view import ViaCepService, only_digits


# Modern SaaS Color Palette
_ACCENT = "#6366f1"  # Vibrant indigo
_ACCENT_HOVER = "#4f46e5"
_ACCENT_LIGHT = "rgba(99,102,241,0.10)"
_ACCENT_BORDER = "rgba(99,102,241,0.30)"
_INK = "#0f172a"  # Deep slate
_INK2 = "#475569"
_INK3 = "#94a3b8"
_LINE = "#e2e8f0"
_WHITE = "#ffffff"
_BG = "#f8fafc"
_CARD_BG = "#ffffff"
_GOOD = "#10b981"
_GOOD_BG = "rgba(16,185,129,0.08)"
_GOOD_BORDER = "rgba(16,185,129,0.25)"
_DANGER = "#ef4444"
_DANGER_BG = "rgba(239,68,68,0.08)"
_DANGER_BORDER = "rgba(239,68,68,0.25)"
_WARNING = "#f59e0b"
_WARNING_BG = "rgba(245,158,11,0.08)"
_WARNING_BORDER = "rgba(245,158,11,0.25)"


def _only_digits(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _is_valid_cnpj(cnpj: str) -> bool:
    digits = _only_digits(cnpj)
    if len(digits) != 14:
        return False
    if digits == digits[0] * 14:
        return False

    def _calc_digit(base: str, weights: list[int]) -> int:
        total = sum(int(num) * weight for num, weight in zip(base, weights))
        mod = total % 11
        return 0 if mod < 2 else 11 - mod

    d1 = _calc_digit(digits[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = _calc_digit(digits[:12] + str(d1), [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return digits[-2:] == f"{d1}{d2}"


def _fmt_cep(raw: str) -> str:
    digits = _only_digits(raw)
    if len(digits) != 8:
        return str(raw or "").strip()
    return f"{digits[:5]}-{digits[5:]}"


def _fmt_phone(raw: str) -> str:
    digits = _only_digits(raw)
    if len(digits) == 11:
        return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return str(raw or "").strip()


@dataclass(frozen=True)
class CnpjPublicData:
    razao_social: str
    nome_fantasia: str
    telefone: str
    email: str
    logradouro: str
    numero: str
    bairro: str
    cidade: str
    uf: str
    cep: str

    def is_empty(self) -> bool:
        return not any(
            [
                self.razao_social,
                self.nome_fantasia,
                self.telefone,
                self.email,
                self.logradouro,
                self.numero,
                self.bairro,
                self.cidade,
                self.uf,
                self.cep,
            ]
        )


class CnpjLookupService:
    def __init__(self, parent: QWidget, timeout_ms: int = 6500):
        self._net = QNetworkAccessManager(parent)
        self._timeout_ms = int(timeout_ms)
        self._cache: dict[str, CnpjPublicData] = {}
        self._active_reply: QNetworkReply | None = None
        self._timeout_timer = QTimer(parent)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)
        self._ctx: dict | None = None

    def abort(self):
        self._timeout_timer.stop()
        if self._active_reply is not None:
            try:
                self._active_reply.abort()
                self._active_reply.deleteLater()
            except Exception:
                pass
        self._active_reply = None
        self._ctx = None

    def lookup(self, cnpj_num: str, on_ok, on_err, on_status=None):
        cnpj_num = _only_digits(cnpj_num)
        if len(cnpj_num) != 14:
            on_err("CNPJ invalido para consulta.")
            return

        if cnpj_num in self._cache:
            if on_status:
                on_status("Dados carregados do cache.")
            on_ok(self._cache[cnpj_num])
            return

        self.abort()
        if on_status:
            on_status("Consultando CNPJ...")

        self._ctx = {
            "cnpj": cnpj_num,
            "on_ok": on_ok,
            "on_err": on_err,
            "on_status": on_status,
        }
        req = QNetworkRequest(QUrl(f"https://minhareceita.org/{cnpj_num}"))
        req.setHeader(QNetworkRequest.UserAgentHeader, "MedContract/2.0 (PySide6)")
        self._active_reply = self._net.get(req)
        self._active_reply.finished.connect(self._on_finished)
        self._timeout_timer.start(self._timeout_ms)

    def _on_timeout(self):
        if not self._ctx:
            return
        on_err = self._ctx["on_err"]
        self.abort()
        on_err("Tempo esgotado ao consultar CNPJ.")

    @staticmethod
    def _pick(data: dict, *keys: str) -> str:
        for k in keys:
            v = data.get(k)
            if v is None:
                continue
            t = str(v).strip()
            if t:
                return t
        return ""

    def _parse_payload(self, data: dict) -> CnpjPublicData:
        tipo_log = self._pick(data, "descricao_tipo_de_logradouro", "tipo_logradouro")
        logr = self._pick(data, "logradouro")
        logradouro = f"{tipo_log} {logr}".strip() if tipo_log else logr

        cidade = self._pick(data, "municipio", "cidade", "nome_municipio")
        uf = self._pick(data, "uf", "sigla_uf").upper()
        cep = _fmt_cep(self._pick(data, "cep"))

        return CnpjPublicData(
            razao_social=self._pick(data, "razao_social", "nome"),
            nome_fantasia=self._pick(data, "nome_fantasia", "fantasia"),
            telefone=_fmt_phone(self._pick(data, "ddd_telefone_1", "telefone")),
            email=self._pick(data, "email"),
            logradouro=logradouro,
            numero=self._pick(data, "numero"),
            bairro=self._pick(data, "bairro"),
            cidade=cidade,
            uf=uf,
            cep=cep,
        )

    def _on_finished(self):
        if not self._active_reply or not self._ctx:
            return
        reply = self._active_reply
        ctx = self._ctx
        self._timeout_timer.stop()
        try:
            if reply.error() != QNetworkReply.NoError:
                ctx["on_err"](f"Falha ao consultar CNPJ: {reply.errorString() or 'erro de rede'}")
                return

            raw = bytes(reply.readAll()).decode("utf-8", errors="replace").strip()
            if not raw.startswith("{"):
                ctx["on_err"]("Resposta inesperada ao consultar CNPJ.")
                return

            payload = json.loads(raw)
            if not isinstance(payload, dict):
                ctx["on_err"]("Resposta invalida da consulta de CNPJ.")
                return

            msg = str(payload.get("message") or "").strip().lower()
            if msg and any(tag in msg for tag in ("nao encontrado", "not found", "inexistente")):
                ctx["on_err"]("CNPJ nao encontrado na base publica.")
                return

            info = self._parse_payload(payload)
            if info.is_empty():
                ctx["on_err"]("CNPJ consultado, mas sem dados publicos suficientes.")
                return

            self._cache[ctx["cnpj"]] = info
            ctx["on_ok"](info)
        except Exception as e:
            ctx["on_err"](f"Erro ao processar consulta de CNPJ: {e}")
        finally:
            try:
                reply.deleteLater()
            except Exception:
                pass
            self._active_reply = None
            self._ctx = None


class FocusStartLineEdit(QLineEdit):
    def _first_edit_pos(self) -> int:
        txt = self.displayText() or ""
        i = txt.find("_")
        if i != -1:
            return i
        return 0

    def _go_first_pos(self):
        self.setSelection(0, 0)
        self.setCursorPosition(self._first_edit_pos())
        self.setSelection(0, 0)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        QTimer.singleShot(0, self._go_first_pos)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setFocus()
            QTimer.singleShot(0, self._go_first_pos)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            QTimer.singleShot(0, self._go_first_pos)


class CadastroEmpresaView(QWidget):
    voltar_signal = Signal()
    cancelar_signal = Signal()
    salvar_signal = Signal(dict)

    def __init__(self):
        super().__init__()
        self._modo = "create"
        self._edit_id: int | None = None

        self.cnpj = None
        self.nome = None
        self.telefone = None
        self.email = None
        self.logradouro = None
        self.numero = None
        self.bairro = None
        self.cep = None
        self.cidade = None
        self.estado = None
        self.forma_pagamento = None
        self.status_pagamento = None
        self.dia_vencimento = None
        self.valor_mensal = None
        self.inline_msg = None
        self.endereco_status = None
        self.cnpj_status = None
        self._save_btn_label_before_busy = ""
        self.form_progress = None
        self.progress_count = None
        self.step_row = None
        self.step_chips: dict[str, QPushButton] = {}
        self._section_cards: dict[str, QFrame] = {}
        self.scroll = None

        self._cep_debounce = QTimer(self)
        self._cep_debounce.setSingleShot(True)
        self._cep_debounce.timeout.connect(self._busca_cep)
        self._cnpj_debounce = QTimer(self)
        self._cnpj_debounce.setSingleShot(True)
        self._cnpj_debounce.timeout.connect(self._busca_cnpj)
        self._viacep = ViaCepService(self, timeout_ms=4500)
        self._cnpj_lookup = CnpjLookupService(self, timeout_ms=6500)
        self._cnpj_autofill = False
        self._address_autofill = False
        self._endereco_manual = False
        self._last_cep_filled = ""
        self._last_cnpj_filled = ""

        self.setup_ui()
        self.apply_styles()
        self._wire_behaviors()
        self.set_create_mode()

    def setup_ui(self):
        self.setObjectName("CadastroEmpresa")
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(20)

        # Header with gradient accent
        header_container = QWidget()
        header_container.setObjectName("headerContainer")
        header_layout = QVBoxLayout(header_container)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)

        top = QHBoxLayout()
        top.setSpacing(16)

        title_wrap = QVBoxLayout()
        title_wrap.setSpacing(6)
        self.title = QLabel("Cadastrar Empresa")
        self.title.setObjectName("pageTitle")
        self.subtitle = QLabel("Preencha os dados com atenção. Você poderá editar depois.")
        self.subtitle.setObjectName("pageSubtitle")

        title_wrap.addWidget(self.title)
        title_wrap.addWidget(self.subtitle)
        top.addLayout(title_wrap)
        top.addStretch()

        self.btn_voltar = QPushButton("← Voltar")
        self.btn_voltar.setObjectName("btnGhost")
        self.btn_voltar.setFixedHeight(40)
        self.btn_voltar.setCursor(Qt.PointingHandCursor)
        self.btn_voltar.clicked.connect(self.voltar_signal.emit)
        top.addWidget(self.btn_voltar)
        
        header_layout.addLayout(top)
        root.addWidget(header_container)

        # Divider with gradient
        divider = QFrame()
        divider.setObjectName("gradientDivider")
        divider.setFixedHeight(2)
        root.addWidget(divider)

        # Scroll area with enhanced styling
        scroll = QScrollArea()
        scroll.setObjectName("cadScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll = scroll

        content = QWidget()
        content.setObjectName("contentWidget")
        scroll.setWidget(content)

        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)

        self.progress_count = QLabel("Seções concluídas: 0/3")
        self.progress_count.setObjectName("progressHint")
        self.form_progress = QProgressBar()
        self.form_progress.setObjectName("formProgress")
        self.form_progress.setRange(0, 100)
        self.form_progress.setTextVisible(False)
        self.form_progress.setFixedHeight(8)
        self.step_row = QHBoxLayout()
        self.step_row.setSpacing(8)
        content_layout.addWidget(self.progress_count)
        content_layout.addWidget(self.form_progress)
        content_layout.addLayout(self.step_row)

        # Company Data Card
        card_empresa, empresa_grid = self._build_card("🏢  Dados da Empresa", "Informações básicas da organização")
        self._section_cards["empresa"] = card_empresa
        self.cnpj = self._mk_text_field("CNPJ", "00.000.000/0000-00", mask="00.000.000/0000-00;_")
        self.nome = self._mk_text_field("Razão Social", "Nome completo da empresa")
        self.telefone = self._mk_text_field("Telefone", "(00) 00000-0000", mask="(00) 00000-0000;_")
        self.email = self._mk_text_field("E-mail Corporativo", "contato@empresa.com.br")

        empresa_grid.addLayout(self.cnpj["layout"], 0, 0)
        empresa_grid.addLayout(self.nome["layout"], 0, 1)
        empresa_grid.addLayout(self.telefone["layout"], 1, 0)
        empresa_grid.addLayout(self.email["layout"], 1, 1)

        self.cnpj_status = QLabel("")
        self.cnpj_status.setObjectName("cnpjStatus")
        self.cnpj_status.setVisible(False)
        card_empresa.layout().addWidget(self.cnpj_status)
        content_layout.addWidget(card_empresa)

        # Address Card
        card_endereco, endereco_grid = self._build_card("📍  Endereço", "Localização e dados de entrega")
        self._section_cards["endereco"] = card_endereco
        endereco_grid.setColumnStretch(0, 2)
        endereco_grid.setColumnStretch(1, 1)
        endereco_grid.setColumnStretch(2, 1)
        self.logradouro = self._mk_text_field("Logradouro", "Rua, avenida, travessa...")
        self.numero = self._mk_text_field("Número", "Nº")
        self.bairro = self._mk_text_field("Bairro", "Nome do bairro")
        self.cep = self._mk_text_field("CEP", "00000-000", mask="00000-000;_")
        self.cidade = self._mk_text_field("Cidade", "Município")
        self.estado = self._mk_text_field(
            "UF",
            "SP",
            validator=QRegularExpressionValidator(QRegularExpression("[A-Za-z]{0,2}")),
        )

        endereco_grid.addLayout(self.cep["layout"], 0, 0)
        endereco_grid.addLayout(self.estado["layout"], 0, 1)
        endereco_grid.addLayout(self.numero["layout"], 0, 2)
        endereco_grid.addLayout(self.logradouro["layout"], 1, 0, 1, 3)
        endereco_grid.addLayout(self.bairro["layout"], 2, 0, 1, 2)
        endereco_grid.addLayout(self.cidade["layout"], 2, 2)

        self.endereco_status = QLabel("")
        self.endereco_status.setObjectName("addressStatus")
        self.endereco_status.setVisible(False)
        card_endereco.layout().addWidget(self.endereco_status)

        self.cep["input"].textChanged.connect(self._on_cep_changed)
        self.cep["input"].editingFinished.connect(self._busca_cep)
        self.logradouro["input"].textEdited.connect(self._on_endereco_edited)
        self.bairro["input"].textEdited.connect(self._on_endereco_edited)
        self.cidade["input"].textEdited.connect(self._on_endereco_edited)
        self.numero["input"].textEdited.connect(self._on_endereco_edited)
        self.estado["input"].textEdited.connect(self._on_endereco_edited)
        content_layout.addWidget(card_endereco)

        # Contract Card
        card_contrato, contrato_grid = self._build_card("💳  Informações de Pagamento", "Gestão financeira e cobrança")
        self._section_cards["pagamento"] = card_contrato
        self.forma_pagamento = self._mk_combo_field(
            "Forma de Pagamento",
            [
                ("💳  Pix", "pix"),
                ("📄  Boleto", "boleto"),
                ("🏪  Recepção", "recepcao"),
            ],
        )
        self.status_pagamento = self._mk_combo_field(
            "Status",
            [
                ("✓  Em dia", "em_dia"),
                ("⏱  Pendente", "pendente"),
                ("⚠  Inadimplente", "inadimplente"),
            ],
        )
        self.dia_vencimento = self._mk_spin_field("Dia do Vencimento", 1, 31, 10)
        self.valor_mensal = self._mk_text_field("Valor Mensal (R$)", "0,00")

        contrato_grid.addLayout(self.forma_pagamento["layout"], 0, 0)
        contrato_grid.addLayout(self.status_pagamento["layout"], 0, 1)
        contrato_grid.addLayout(self.dia_vencimento["layout"], 1, 0)
        contrato_grid.addLayout(self.valor_mensal["layout"], 1, 1)
        content_layout.addWidget(card_contrato)

        self.step_chips = {
            "empresa": self._make_step_chip("1 · Empresa", card_empresa),
            "endereco": self._make_step_chip("2 · Endereço", card_endereco),
            "pagamento": self._make_step_chip("3 · Pagamento", card_contrato),
        }
        for chip in self.step_chips.values():
            self.step_row.addWidget(chip)
        self.step_row.addStretch()

        # Inline message
        self.inline_msg = QLabel("")
        self.inline_msg.setObjectName("inlineMessage")
        self.inline_msg.setVisible(False)
        self.inline_msg.setWordWrap(True)
        content_layout.addWidget(self.inline_msg)

        # Action buttons
        actions = QHBoxLayout()
        actions.setSpacing(12)

        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setObjectName("btnSecondary")
        self.btn_cancelar.setFixedHeight(44)
        self.btn_cancelar.setMinimumWidth(120)
        self.btn_cancelar.setCursor(Qt.PointingHandCursor)
        self.btn_cancelar.clicked.connect(self.cancelar_signal.emit)

        self.btn_salvar = QPushButton("✓  Cadastrar Empresa")
        self.btn_salvar.setObjectName("btnPrimary")
        self.btn_salvar.setFixedHeight(44)
        self.btn_salvar.setMinimumWidth(180)
        self.btn_salvar.setCursor(Qt.PointingHandCursor)
        self.btn_salvar.clicked.connect(self._on_save_clicked)

        actions.addStretch()
        actions.addWidget(self.btn_cancelar)
        actions.addWidget(self.btn_salvar)
        content_layout.addLayout(actions)

        root.addWidget(scroll)

    def _build_card(self, title: str, subtitle: str = ""):
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(16)

        # Card header
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)
        
        lbl = QLabel(title)
        lbl.setObjectName("cardTitle")
        header_layout.addWidget(lbl)
        
        if subtitle:
            sub_lbl = QLabel(subtitle)
            sub_lbl.setObjectName("cardSubtitle")
            header_layout.addWidget(sub_lbl)
        
        lay.addLayout(header_layout)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(14)
        lay.addLayout(grid)
        return card, grid

    def _make_step_chip(self, text: str, target_widget: QFrame) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("stepChip")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _=False, w=target_widget: self._scroll_to_widget(w))
        return btn

    def _scroll_to_widget(self, widget: QFrame | None):
        if widget is None or self.scroll is None:
            return
        viewport = self.scroll.viewport()
        top_left = widget.mapTo(viewport, QPoint(0, 0))
        y = max(0, int(top_left.y()) + int(self.scroll.verticalScrollBar().value()) - 20)
        self.scroll.verticalScrollBar().setValue(y)

    def _is_step_empresa_ok(self) -> bool:
        cnpj = (self.cnpj["input"].text() or "").strip()
        nome = (self.nome["input"].text() or "").strip()
        telefone = (self.telefone["input"].text() or "").strip()
        email = (self.email["input"].text() or "").strip()
        if self._is_blank_masked(cnpj) or self._is_blank_masked(nome) or self._is_blank_masked(telefone) or self._is_blank_masked(email):
            return False
        if "_" in cnpj or not _is_valid_cnpj(cnpj):
            return False
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return False
        return True

    def _is_step_endereco_ok(self) -> bool:
        logradouro = (self.logradouro["input"].text() or "").strip()
        numero = (self.numero["input"].text() or "").strip()
        bairro = (self.bairro["input"].text() or "").strip()
        cep = (self.cep["input"].text() or "").strip()
        cidade = (self.cidade["input"].text() or "").strip()
        estado = (self.estado["input"].text() or "").strip().upper()
        if any(not value for value in (logradouro, numero, bairro, cep, cidade, estado)):
            return False
        if "_" in cep or len(only_digits(cep)) != 8:
            return False
        if len(estado) != 2:
            return False
        return True

    def _is_step_pagamento_ok(self) -> bool:
        valor = (self.valor_mensal["input"].text() or "").strip()
        if not valor:
            return False
        return bool(self.forma_pagamento["combo"].currentData()) and bool(self.status_pagamento["combo"].currentData())

    def _refresh_step_progress(self):
        checks = {
            "empresa": self._is_step_empresa_ok(),
            "endereco": self._is_step_endereco_ok(),
            "pagamento": self._is_step_pagamento_ok(),
        }
        done = sum(1 for ok in checks.values() if ok)
        total = len(checks)
        if self.progress_count is not None:
            self.progress_count.setText(f"Seções concluídas: {done}/{total}")
        if self.form_progress is not None:
            pct = int(round((done / total) * 100)) if total > 0 else 0
            self.form_progress.setValue(pct)
        for key, chip in self.step_chips.items():
            chip.setProperty("done", bool(checks.get(key)))
            chip.setProperty("active", False)
            chip.style().unpolish(chip)
            chip.style().polish(chip)

    def _focus_first_incomplete_step(self):
        for chip in self.step_chips.values():
            chip.setProperty("active", False)
            chip.style().unpolish(chip)
            chip.style().polish(chip)
        ordered = (
            ("empresa", self._is_step_empresa_ok()),
            ("endereco", self._is_step_endereco_ok()),
            ("pagamento", self._is_step_pagamento_ok()),
        )
        for key, ok in ordered:
            chip = self.step_chips.get(key)
            if chip is None:
                continue
            chip.setProperty("active", not ok)
            chip.style().unpolish(chip)
            chip.style().polish(chip)
            if not ok:
                self._scroll_to_widget(self._section_cards.get(key))
                break

    def _mk_text_field(self, label: str, placeholder: str = "", mask: str | None = None, validator=None):
        wrapper = QVBoxLayout()
        wrapper.setSpacing(6)

        lab = QLabel(label)
        lab.setObjectName("fieldLabel")

        inp = FocusStartLineEdit()
        inp.setObjectName("fieldInput")
        inp.setPlaceholderText(placeholder)
        inp.setFixedHeight(42)
        if mask:
            inp.setInputMask(mask)
        if validator:
            inp.setValidator(validator)

        err = QLabel("")
        err.setObjectName("fieldError")
        err.setVisible(False)

        wrapper.addWidget(lab)
        wrapper.addWidget(inp)
        wrapper.addWidget(err)
        return {"layout": wrapper, "label": lab, "input": inp, "error_label": err}

    def _mk_combo_field(self, label: str, items: list[tuple[str, str]]):
        wrapper = QVBoxLayout()
        wrapper.setSpacing(6)

        lab = QLabel(label)
        lab.setObjectName("fieldLabel")

        cb = QComboBox()
        cb.setObjectName("saasCombo")
        cb.setFixedHeight(42)
        for text, data in items:
            cb.addItem(text, data)

        err = QLabel("")
        err.setObjectName("fieldError")
        err.setVisible(False)

        wrapper.addWidget(lab)
        wrapper.addWidget(cb)
        wrapper.addWidget(err)
        return {"layout": wrapper, "label": lab, "combo": cb, "error_label": err}

    def _mk_spin_field(self, label: str, min_value: int, max_value: int, default: int):
        wrapper = QVBoxLayout()
        wrapper.setSpacing(6)

        lab = QLabel(label)
        lab.setObjectName("fieldLabel")

        sp = QSpinBox()
        sp.setObjectName("saasSpin")
        sp.setRange(int(min_value), int(max_value))
        sp.setValue(int(default))
        sp.setFixedHeight(42)

        err = QLabel("")
        err.setObjectName("fieldError")
        err.setVisible(False)

        wrapper.addWidget(lab)
        wrapper.addWidget(sp)
        wrapper.addWidget(err)
        return {"layout": wrapper, "label": lab, "spin": sp, "error_label": err}

    def _wire_behaviors(self):
        text_fields = [
            self.cnpj,
            self.nome,
            self.telefone,
            self.email,
            self.logradouro,
            self.numero,
            self.bairro,
            self.cep,
            self.cidade,
            self.estado,
            self.valor_mensal,
        ]
        for f in text_fields:
            f["input"].textChanged.connect(self._clear_errors)
            f["input"].textChanged.connect(self._refresh_step_progress)

        self.forma_pagamento["combo"].currentIndexChanged.connect(self._clear_errors)
        self.status_pagamento["combo"].currentIndexChanged.connect(self._clear_errors)
        self.dia_vencimento["spin"].valueChanged.connect(self._clear_errors)
        self.forma_pagamento["combo"].currentIndexChanged.connect(self._refresh_step_progress)
        self.status_pagamento["combo"].currentIndexChanged.connect(self._refresh_step_progress)
        self.dia_vencimento["spin"].valueChanged.connect(self._refresh_step_progress)
        self.cnpj["input"].textChanged.connect(self._on_cnpj_changed)
        self.cnpj["input"].editingFinished.connect(self._busca_cnpj)
        self._refresh_step_progress()

    def _set_address_status(self, text: str, ok: bool = True):
        if not self.endereco_status:
            return
        self.endereco_status.setText(str(text or ""))
        self.endereco_status.setProperty("ok", bool(ok))
        self.endereco_status.style().unpolish(self.endereco_status)
        self.endereco_status.style().polish(self.endereco_status)
        self.endereco_status.setVisible(bool((text or "").strip()))

    def _set_busy_cep(self, busy: bool, msg: str | None = None):
        for field in (self.logradouro, self.bairro, self.cidade, self.estado):
            if field and "input" in field:
                field["input"].setEnabled(not busy)
        if msg:
            self._set_address_status(msg, ok=True)

    def _on_endereco_edited(self, _=None):
        if self._address_autofill or self._cnpj_autofill:
            return
        self._endereco_manual = True
        self._set_address_status("✏️  Endereço editado manualmente", ok=True)

    def _on_cep_changed(self, _=None):
        cep_txt = (self.cep["input"].text() or "").strip()
        if "_" in cep_txt:
            self._set_address_status("")
            return
        cep_num = only_digits(cep_txt)
        if len(cep_num) != 8:
            self._set_address_status("")
            return
        if cep_num != self._last_cep_filled:
            self._endereco_manual = False
        if self._endereco_manual:
            self._set_address_status("✏️  Endereço editado manualmente", ok=True)
        else:
            self._set_address_status("🔍  Consultando CEP...", ok=True)
        self._cep_debounce.start(350)

    def _busca_cep(self):
        cep_txt = (self.cep["input"].text() or "").strip()
        cep_num = only_digits(cep_txt)
        if len(cep_num) != 8:
            return

        if self._endereco_manual and cep_num == self._last_cep_filled:
            return

        def on_ok(addr):
            self._set_busy_cep(False)
            if not self._endereco_manual:
                self._address_autofill = True
                try:
                    self.logradouro["input"].setText((addr.logradouro or "").strip())
                    self.bairro["input"].setText((addr.bairro or "").strip())
                    self.cidade["input"].setText((addr.cidade or "").strip())
                    self.estado["input"].setText((addr.uf or "").strip().upper())
                finally:
                    self._address_autofill = False
                self._last_cep_filled = cep_num
                self._set_address_status("✓  Endereço preenchido automaticamente", ok=True)
                self.numero["input"].setFocus()

        def on_err(msg):
            self._set_busy_cep(False)
            self._set_address_status(str(msg or "❌  Falha ao consultar CEP"), ok=False)

        def on_status(msg):
            self._set_busy_cep(True, msg=str(msg or ""))

        self._viacep.lookup(
            cep_num=cep_num,
            on_ok=on_ok,
            on_err=on_err,
            on_status=on_status,
        )

    def _set_cnpj_status(self, text: str, ok: bool = True):
        if not self.cnpj_status:
            return
        self.cnpj_status.setText(str(text or ""))
        self.cnpj_status.setProperty("ok", bool(ok))
        self.cnpj_status.style().unpolish(self.cnpj_status)
        self.cnpj_status.style().polish(self.cnpj_status)
        self.cnpj_status.setVisible(bool((text or "").strip()))

    def _on_cnpj_changed(self, _=None):
        cnpj_txt = (self.cnpj["input"].text() or "").strip()
        if "_" in cnpj_txt:
            self._set_cnpj_status("")
            return

        cnpj_num = _only_digits(cnpj_txt)
        if len(cnpj_num) != 14:
            self._set_cnpj_status("")
            return

        if not _is_valid_cnpj(cnpj_txt):
            self._set_cnpj_status("CNPJ invalido.", ok=False)
            return

        if cnpj_num != self._last_cnpj_filled:
            self._endereco_manual = False
        self._set_cnpj_status("Consultando CNPJ...", ok=True)
        self._cnpj_debounce.start(450)

    def _busca_cnpj(self):
        cnpj_txt = (self.cnpj["input"].text() or "").strip()
        cnpj_num = _only_digits(cnpj_txt)
        if len(cnpj_num) != 14 or not _is_valid_cnpj(cnpj_txt):
            return
        if cnpj_num == self._last_cnpj_filled and self.cnpj_status and self.cnpj_status.property("ok"):
            return

        def on_ok(info: CnpjPublicData):
            self._cnpj_autofill = True
            try:
                if info.razao_social and not (self.nome["input"].text() or "").strip():
                    self.nome["input"].setText(info.razao_social)
                elif info.nome_fantasia and not (self.nome["input"].text() or "").strip():
                    self.nome["input"].setText(info.nome_fantasia)

                if info.telefone and not (self.telefone["input"].text() or "").strip():
                    self.telefone["input"].setText(info.telefone)
                if info.email and not (self.email["input"].text() or "").strip():
                    self.email["input"].setText(info.email)

                if not self._endereco_manual:
                    if info.cep:
                        self.cep["input"].setText(info.cep)
                    if info.logradouro:
                        self.logradouro["input"].setText(info.logradouro)
                    if info.numero:
                        self.numero["input"].setText(info.numero)
                    if info.bairro:
                        self.bairro["input"].setText(info.bairro)
                    if info.cidade:
                        self.cidade["input"].setText(info.cidade)
                    if info.uf:
                        self.estado["input"].setText(info.uf)
            finally:
                self._cnpj_autofill = False

            self._last_cnpj_filled = cnpj_num
            self._set_cnpj_status("CNPJ validado na base publica.", ok=True)

        def on_err(msg: str):
            self._set_cnpj_status(str(msg or "Falha ao consultar CNPJ."), ok=False)

        def on_status(msg: str):
            self._set_cnpj_status(str(msg or ""), ok=True)

        self._cnpj_lookup.lookup(
            cnpj_num=cnpj_num,
            on_ok=on_ok,
            on_err=on_err,
            on_status=on_status,
        )

    def set_create_mode(self):
        self._modo = "create"
        self._edit_id = None
        self.title.setText("Cadastrar Empresa")
        self.subtitle.setText("Preencha os dados com atenção. Você poderá editar depois.")
        self.btn_salvar.setText("✓  Cadastrar Empresa")
        self._save_btn_label_before_busy = self.btn_salvar.text()
        self.limpar_campos()

    def set_edit_mode(self, empresa: dict):
        self._modo = "edit"
        self._edit_id = int(empresa.get("id", 0) or 0)

        self.title.setText("Editar Empresa")
        self.subtitle.setText(f"Editando empresa #{self._edit_id}")
        self.btn_salvar.setText("💾  Salvar Alterações")
        self._save_btn_label_before_busy = self.btn_salvar.text()
        self._address_autofill = True
        try:
            self.cnpj["input"].setText(str(empresa.get("cnpj", "") or ""))
            self.nome["input"].setText(str(empresa.get("nome", "") or ""))
            self.telefone["input"].setText(str(empresa.get("telefone", "") or ""))
            self.email["input"].setText(str(empresa.get("email", "") or ""))
            self.logradouro["input"].setText(str(empresa.get("logradouro", "") or ""))
            self.numero["input"].setText(str(empresa.get("numero", "") or ""))
            self.bairro["input"].setText(str(empresa.get("bairro", "") or ""))
            self.cep["input"].setText(str(empresa.get("cep", "") or ""))
            self.cidade["input"].setText(str(empresa.get("cidade", "") or ""))
            self.estado["input"].setText(str(empresa.get("estado", "") or "").upper())
            self.valor_mensal["input"].setText(str(empresa.get("valor_mensal", "") or ""))
        finally:
            self._address_autofill = False
        self._endereco_manual = True
        self._last_cep_filled = only_digits(self.cep["input"].text() or "")
        self._last_cnpj_filled = _only_digits(self.cnpj["input"].text() or "")
        self._set_cnpj_status("")

        forma = str(empresa.get("forma_pagamento", "") or "").strip().lower()
        idx_forma = self.forma_pagamento["combo"].findData(forma)
        self.forma_pagamento["combo"].setCurrentIndex(max(0, idx_forma))

        status = str(empresa.get("status_pagamento", "") or "").strip().lower()
        idx_status = self.status_pagamento["combo"].findData(status)
        self.status_pagamento["combo"].setCurrentIndex(max(0, idx_status))

        try:
            self.dia_vencimento["spin"].setValue(int(empresa.get("dia_vencimento", 10) or 10))
        except Exception:
            self.dia_vencimento["spin"].setValue(10)

        self._clear_errors()

    def limpar_campos(self):
        for field in (
            self.cnpj,
            self.nome,
            self.telefone,
            self.email,
            self.logradouro,
            self.numero,
            self.bairro,
            self.cep,
            self.cidade,
            self.estado,
            self.valor_mensal,
        ):
            field["input"].clear()
        self.estado["input"].setText("")
        self.forma_pagamento["combo"].setCurrentIndex(0)
        self.status_pagamento["combo"].setCurrentIndex(0)
        self.dia_vencimento["spin"].setValue(10)
        self._endereco_manual = False
        self._address_autofill = False
        self._last_cep_filled = ""
        self._last_cnpj_filled = ""
        self._set_address_status("", ok=True)
        self._set_cnpj_status("", ok=True)
        self._clear_errors()

    def _is_blank_masked(self, text: str) -> bool:
        t = str(text or "").strip()
        return (not t) or ("_" in t)

    def _set_field_error(self, field: dict | None, text: str):
        if not field:
            return
        err = field.get("error_label")
        if err is None:
            return
        msg = str(text or "").strip()
        if msg:
            err.setText(msg)
            err.setVisible(True)
        else:
            err.setText("")
            err.setVisible(False)

    def _mark_error(self, field: dict, msg: str):
        widget = field.get("input") or field.get("combo") or field.get("spin")
        if widget is not None:
            widget.setProperty("error", True)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self._set_field_error(field, msg)

    def _clear_field(self, field: dict):
        widget = field.get("input") or field.get("combo") or field.get("spin")
        if widget is not None and widget.property("error"):
            widget.setProperty("error", False)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self._set_field_error(field, "")

    def _clear_errors(self):
        for field in (
            self.cnpj,
            self.nome,
            self.telefone,
            self.email,
            self.logradouro,
            self.numero,
            self.bairro,
            self.cep,
            self.cidade,
            self.estado,
            self.forma_pagamento,
            self.status_pagamento,
            self.dia_vencimento,
            self.valor_mensal,
        ):
            self._clear_field(field)
        self._hide_message()
        self._refresh_step_progress()

    def _validate(self) -> bool:
        self._clear_errors()
        ok = True

        required_text = [
            (self.cnpj, "CNPJ é obrigatório"),
            (self.nome, "Razão social é obrigatória"),
            (self.telefone, "Telefone é obrigatório"),
            (self.email, "E-mail é obrigatório"),
            (self.logradouro, "Logradouro é obrigatório"),
            (self.numero, "Número é obrigatório"),
            (self.bairro, "Bairro é obrigatório"),
            (self.cep, "CEP é obrigatório"),
            (self.cidade, "Cidade é obrigatória"),
            (self.estado, "UF é obrigatória"),
            (self.valor_mensal, "Valor mensal é obrigatório"),
        ]
        for field, msg in required_text:
            if self._is_blank_masked(field["input"].text()):
                self._mark_error(field, msg)
                ok = False

        cnpj = self.cnpj["input"].text().strip()
        if not self._is_blank_masked(cnpj):
            if not re.fullmatch(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", cnpj):
                self._mark_error(self.cnpj, "CNPJ deve estar no formato correto")
                ok = False
            elif not _is_valid_cnpj(cnpj):
                self._mark_error(self.cnpj, "CNPJ inválido")
                ok = False

        email = self.email["input"].text().strip()
        if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            self._mark_error(self.email, "E-mail inválido")
            ok = False

        estado = self.estado["input"].text().strip()
        if estado and len(estado) != 2:
            self._mark_error(self.estado, "UF deve ter 2 letras")
            ok = False

        if not ok:
            self._show_message("⚠️  Corrija os campos destacados para continuar", ok=False)
            self._focus_first_incomplete_step()
        return ok

    def _collect_payload(self) -> dict:
        payload = {
            "modo": self._modo,
            "id": self._edit_id,
            "cnpj": self.cnpj["input"].text().strip(),
            "nome": self.nome["input"].text().strip(),
            "telefone": self.telefone["input"].text().strip(),
            "email": self.email["input"].text().strip(),
            "logradouro": self.logradouro["input"].text().strip(),
            "numero": self.numero["input"].text().strip(),
            "bairro": self.bairro["input"].text().strip(),
            "cep": self.cep["input"].text().strip(),
            "cidade": self.cidade["input"].text().strip(),
            "estado": self.estado["input"].text().strip().upper(),
            "forma_pagamento": self.forma_pagamento["combo"].currentData(),
            "status_pagamento": self.status_pagamento["combo"].currentData(),
            "dia_vencimento": int(self.dia_vencimento["spin"].value()),
            "valor_mensal": self.valor_mensal["input"].text().strip(),
        }
        return payload

    def _on_save_clicked(self):
        if not self._validate():
            return
        self.salvar_signal.emit(self._collect_payload())

    def set_save_busy(self, busy: bool, msg: str | None = None):
        is_busy = bool(busy)
        if self.btn_salvar:
            self.btn_salvar.setEnabled(not is_busy)
            if is_busy:
                self._save_btn_label_before_busy = self.btn_salvar.text()
                self.btn_salvar.setText("Salvando...")
            else:
                restore = getattr(self, "_save_btn_label_before_busy", "")
                if restore:
                    self.btn_salvar.setText(str(restore))
                elif str(self._modo).strip().lower() == "edit":
                    self.btn_salvar.setText("Salvar alteracoes")
                else:
                    self.btn_salvar.setText("Cadastrar empresa")
        if self.btn_cancelar:
            self.btn_cancelar.setEnabled(not is_busy)
        if msg:
            self._show_message(str(msg), ok=True)

    def sucesso_salvo(self, msg: str = "✓  Empresa cadastrada com sucesso!"):
        self.set_save_busy(False)
        self._show_message(msg, ok=True)

    def erro_salvo(self, msg: str = "❌  Não foi possível salvar a empresa"):
        self.set_save_busy(False)
        self._apply_backend_error(msg)

    @staticmethod
    def _normalize_error_text(msg: str) -> str:
        txt = unicodedata.normalize("NFKD", str(msg or ""))
        txt = "".join(ch for ch in txt if not unicodedata.combining(ch))
        txt = txt.lower()
        txt = re.sub(r"[^a-z0-9\s]+", " ", txt)
        return " ".join(txt.split())

    def _apply_backend_error(self, msg: str):
        message = str(msg or "Nao foi possivel salvar a empresa.")
        norm = self._normalize_error_text(message)
        self._clear_errors()

        target = None
        if "cnpj" in norm:
            target = self.cnpj
        elif "razao social" in norm or "nome" in norm:
            target = self.nome
        elif "telefone" in norm:
            target = self.telefone
        elif "e mail" in norm or "email" in norm:
            target = self.email
        elif "logradouro" in norm:
            target = self.logradouro
        elif "numero" in norm:
            target = self.numero
        elif "bairro" in norm:
            target = self.bairro
        elif "cep" in norm:
            target = self.cep
        elif "cidade" in norm:
            target = self.cidade
        elif "uf" in norm or "estado" in norm:
            target = self.estado
        elif "forma de pagamento" in norm:
            target = self.forma_pagamento
        elif "status de pagamento" in norm:
            target = self.status_pagamento
        elif "dia de vencimento" in norm:
            target = self.dia_vencimento
        elif "valor mensal" in norm:
            target = self.valor_mensal

        if isinstance(target, dict):
            self._mark_error(target, message)
            widget = target.get("input") or target.get("combo") or target.get("spin")
            if widget is not None:
                try:
                    widget.setFocus()
                except Exception:
                    pass
        self._show_message(message, ok=False)

    def _show_message(self, text: str, ok: bool = False):
        if not self.inline_msg:
            return
        self.inline_msg.setText(str(text or ""))
        self.inline_msg.setProperty("ok", bool(ok))
        self.inline_msg.style().unpolish(self.inline_msg)
        self.inline_msg.style().polish(self.inline_msg)
        self.inline_msg.setVisible(bool(text))

    def _hide_message(self):
        if not self.inline_msg:
            return
        self.inline_msg.setVisible(False)
        self.inline_msg.setText("")
        self.inline_msg.setProperty("ok", False)

    def apply_styles(self):
        self.setStyleSheet(
            f"""
            /* ========================================
               MODERN SAAS DESIGN SYSTEM
               ======================================== */
            
            /* Base container */
            QWidget#CadastroEmpresa {{
                background: {_BG};
            }}
            
            /* Header with subtle gradient background */
            QWidget#headerContainer {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {_WHITE},
                    stop:1 rgba(99,102,241,0.02)
                );
                border-radius: 16px;
                padding: 4px 0px;
            }}
            
            /* Gradient divider */
            QFrame#gradientDivider {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 transparent,
                    stop:0.2 {_ACCENT},
                    stop:0.8 {_ACCENT},
                    stop:1 transparent
                );
                border: none;
                border-radius: 1px;
            }}
            
            /* Scroll area */
            QScrollArea#cadScroll, QScrollArea#cadScroll > QWidget > QWidget {{
                background: transparent;
                border: none;
            }}
            
            /* Typography - Page level */
            QLabel#pageTitle {{
                color: {_INK};
                font-size: 32px;
                font-weight: 700;
                letter-spacing: -0.5px;
            }}
            
            QLabel#pageSubtitle {{
                color: {_INK2};
                font-size: 14px;
                font-weight: 500;
                letter-spacing: -0.2px;
            }}

            QLabel#progressHint {{
                color: {_INK2};
                font-size: 12px;
                font-weight: 600;
            }}

            QProgressBar#formProgress {{
                background: rgba(99,102,241,0.12);
                border: none;
                border-radius: 4px;
            }}
            QProgressBar#formProgress::chunk {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {_ACCENT},
                    stop:1 {_ACCENT_HOVER}
                );
                border-radius: 4px;
            }}

            QPushButton#stepChip {{
                background: {_WHITE};
                border: 1px solid {_LINE};
                border-radius: 999px;
                padding: 8px 14px;
                color: {_INK2};
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton#stepChip:hover {{
                border-color: {_ACCENT_BORDER};
                color: {_ACCENT_HOVER};
            }}
            QPushButton#stepChip[active="true"] {{
                border: 1px solid {_ACCENT};
                color: {_ACCENT_HOVER};
                background: {_ACCENT_LIGHT};
            }}
            QPushButton#stepChip[done="true"] {{
                background: {_GOOD_BG};
                border: 1px solid {_GOOD_BORDER};
                color: {_GOOD};
            }}
            
            /* Card design with enhanced shadow */
            QFrame#card {{
                background: {_CARD_BG};
                border: 1px solid {_LINE};
                border-radius: 16px;
                /* Soft shadow for depth */
            }}
            
            QLabel#cardTitle {{
                color: {_INK};
                font-size: 16px;
                font-weight: 700;
                letter-spacing: -0.3px;
            }}
            
            QLabel#cardSubtitle {{
                color: {_INK3};
                font-size: 13px;
                font-weight: 500;
            }}
            
            /* Form fields */
            QLabel#fieldLabel {{
                color: {_INK2};
                font-size: 13px;
                font-weight: 600;
                letter-spacing: -0.1px;
            }}
            
            QLabel#fieldError {{
                color: {_DANGER};
                font-size: 12px;
                font-weight: 600;
            }}
            
            /* Input fields with modern styling */
            QLineEdit#fieldInput {{
                background: {_WHITE};
                border: 1.5px solid {_LINE};
                border-radius: 10px;
                padding: 0 14px;
                color: {_INK};
                font-size: 14px;
                font-weight: 500;
                selection-background-color: {_ACCENT_LIGHT};
                selection-color: {_INK};
            }}
            
            QLineEdit#fieldInput:hover {{
                border-color: {_INK3};
            }}
            
            QLineEdit#fieldInput:focus {{
                border: 2px solid {_ACCENT};
                padding: 0 13px;
                background: {_WHITE};
            }}
            
            QLineEdit#fieldInput[error="true"] {{
                border: 1.5px solid {_DANGER};
                background: {_DANGER_BG};
            }}
            
            QLineEdit#fieldInput::placeholder {{
                color: {_INK3};
            }}
            
            /* ComboBox styling */
            QComboBox#saasCombo {{
                background: {_WHITE};
                border: 1.5px solid {_LINE};
                border-radius: 10px;
                padding: 0 14px;
                color: {_INK};
                font-size: 14px;
                font-weight: 500;
            }}
            
            QComboBox#saasCombo:hover {{
                border-color: {_INK3};
            }}
            
            QComboBox#saasCombo:focus {{
                border: 2px solid {_ACCENT};
                padding: 0 13px;
            }}
            
            QComboBox#saasCombo[error="true"] {{
                border: 1.5px solid {_DANGER};
                background: {_DANGER_BG};
            }}
            
            QComboBox#saasCombo::drop-down {{
                border: none;
                width: 32px;
            }}
            
            QComboBox#saasCombo::down-arrow {{
                width: 0;
                height: 0;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid {_INK2};
                margin-right: 8px;
            }}
            
            QComboBox#saasCombo QAbstractItemView {{
                background: {_WHITE};
                border: 1px solid {_LINE};
                border-radius: 12px;
                padding: 6px;
                outline: none;
                selection-background-color: {_ACCENT_LIGHT};
                selection-color: {_INK};
            }}
            
            QComboBox#saasCombo QAbstractItemView::item {{
                padding: 8px 12px;
                border-radius: 8px;
                min-height: 32px;
            }}
            
            QComboBox#saasCombo QAbstractItemView::item:hover {{
                background: rgba(99,102,241,0.06);
            }}
            
            /* SpinBox styling */
            QSpinBox#saasSpin {{
                background: {_WHITE};
                border: 1.5px solid {_LINE};
                border-radius: 10px;
                padding: 0 14px;
                color: {_INK};
                font-size: 14px;
                font-weight: 500;
            }}
            
            QSpinBox#saasSpin:hover {{
                border-color: {_INK3};
            }}
            
            QSpinBox#saasSpin:focus {{
                border: 2px solid {_ACCENT};
                padding: 0 13px;
            }}
            
            QSpinBox#saasSpin[error="true"] {{
                border: 1.5px solid {_DANGER};
                background: {_DANGER_BG};
            }}
            
            QSpinBox#saasSpin::up-button, QSpinBox#saasSpin::down-button {{
                width: 20px;
                border: none;
                background: transparent;
            }}
            
            QSpinBox#saasSpin::up-button:hover, QSpinBox#saasSpin::down-button:hover {{
                background: rgba(99,102,241,0.08);
            }}
            
            QSpinBox#saasSpin::up-arrow {{
                width: 0;
                height: 0;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-bottom: 5px solid {_INK2};
            }}
            
            QSpinBox#saasSpin::down-arrow {{
                width: 0;
                height: 0;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {_INK2};
            }}
            
            /* Primary button - Modern gradient */
            QPushButton#btnPrimary {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {_ACCENT},
                    stop:1 {_ACCENT_HOVER}
                );
                color: white;
                border: none;
                border-radius: 12px;
                padding: 0 24px;
                font-size: 14px;
                font-weight: 700;
                letter-spacing: -0.2px;
            }}
            
            QPushButton#btnPrimary:hover {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {_ACCENT_HOVER},
                    stop:1 #4338ca
                );
            }}
            
            QPushButton#btnPrimary:pressed {{
                background: #4338ca;
                transform: translateY(1px);
            }}
            
            /* Secondary button */
            QPushButton#btnSecondary {{
                background: {_WHITE};
                color: {_INK};
                border: 1.5px solid {_LINE};
                border-radius: 12px;
                padding: 0 20px;
                font-size: 14px;
                font-weight: 600;
                letter-spacing: -0.2px;
            }}
            
            QPushButton#btnSecondary:hover {{
                background: {_BG};
                border-color: {_INK3};
            }}
            
            QPushButton#btnSecondary:pressed {{
                background: {_LINE};
            }}
            
            /* Ghost button */
            QPushButton#btnGhost {{
                background: transparent;
                color: {_INK2};
                border: 1.5px solid {_LINE};
                border-radius: 10px;
                padding: 0 18px;
                font-size: 13px;
                font-weight: 600;
            }}
            
            QPushButton#btnGhost:hover {{
                background: {_WHITE};
                border-color: {_INK3};
                color: {_INK};
            }}
            
            /* Address status badge */
            QLabel#addressStatus {{
                background: {_ACCENT_LIGHT};
                border: 1px solid {_ACCENT_BORDER};
                border-radius: 10px;
                color: {_ACCENT};
                padding: 10px 14px;
                font-size: 12px;
                font-weight: 600;
            }}
            
            QLabel#addressStatus[ok="false"] {{
                background: {_DANGER_BG};
                border: 1px solid {_DANGER_BORDER};
                color: {_DANGER};
            }}

            QLabel#cnpjStatus {{
                background: {_ACCENT_LIGHT};
                border: 1px solid {_ACCENT_BORDER};
                border-radius: 10px;
                color: {_ACCENT};
                padding: 10px 14px;
                font-size: 12px;
                font-weight: 600;
            }}

            QLabel#cnpjStatus[ok="false"] {{
                background: {_DANGER_BG};
                border: 1px solid {_DANGER_BORDER};
                color: {_DANGER};
            }}
            
            /* Inline message banner */
            QLabel#inlineMessage {{
                background: {_DANGER_BG};
                border: 1px solid {_DANGER_BORDER};
                border-radius: 12px;
                color: {_DANGER};
                padding: 14px 16px;
                font-size: 13px;
                font-weight: 700;
            }}
            
            QLabel#inlineMessage[ok="true"] {{
                background: {_GOOD_BG};
                border: 1px solid {_GOOD_BORDER};
                color: {_GOOD};
            }}
            """
        )

