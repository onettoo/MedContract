from __future__ import annotations

import re
from typing import Optional, TypedDict

from PySide6.QtCore import QPoint, Qt, Signal, QTimer, QObject, QRunnable, QThreadPool, Slot, QSettings
from PySide6.QtGui import QAction, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import database.db as db
from views.role_utils import normalize_role as _normalize_role
from views.ui_tokens import PALETTE


_ACCENT = PALETTE.accent
_ACCENT_HOVER = PALETTE.accent_hover
_INK = PALETTE.ink
_INK2 = PALETTE.ink_2
_INK3 = PALETTE.ink_3
_LINE = PALETTE.line
_WHITE = PALETTE.white
_BG = PALETTE.bg
_GOOD = PALETTE.good
_GOOD_BG = PALETTE.good_bg
_GOOD_BORDER = PALETTE.good_border
_WARN = PALETTE.warn
_WARN_BG = PALETTE.warn_bg
_WARN_BORDER = PALETTE.warn_border
_DANGER = PALETTE.danger
_DANGER_BG = PALETTE.danger_bg
_DANGER_BORDER = PALETTE.danger_border


def _safe_text(value, default: str = "-") -> str:
    txt = str(value or "").strip()
    return txt if txt else default


def _format_moeda_brl(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "-"
    if raw.upper().startswith("R$"):
        raw = raw[2:].strip()

    normalized = raw.replace(" ", "")
    try:
        if "," in normalized and "." in normalized:
            if normalized.rfind(",") > normalized.rfind("."):
                normalized = normalized.replace(".", "").replace(",", ".")
            else:
                normalized = normalized.replace(",", "")
        elif "," in normalized:
            normalized = normalized.replace(".", "").replace(",", ".")

        amount = float(normalized)
        out = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {out}"
    except Exception:
        return f"R$ {raw}" if re.search(r"\d", raw) else raw


def _format_cnpj(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) != 14:
        return _safe_text(value, "-")
    return f"{digits[0:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:14]}"


def _format_phone(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) == 11:
        return f"({digits[0:2]}) {digits[2:7]}-{digits[7:11]}"
    if len(digits) == 10:
        return f"({digits[0:2]}) {digits[2:6]}-{digits[6:10]}"
    return _safe_text(value, "-")


def _format_date_br(value: str) -> str:
    txt = str(value or "").strip()
    if not txt:
        return "-"
    if len(txt) >= 10 and txt[4] == "-" and txt[7] == "-":
        yyyy, mm, dd = txt[:10].split("-")
        return f"{dd}/{mm}/{yyyy}"
    return txt


def _forma_label(value: str) -> str:
    txt = str(value or "").strip().lower()
    return {
        "pix": "Pix",
        "boleto": "Boleto",
        "recepcao": "Recepcao",
    }.get(txt, _safe_text(value))


def _status_label(value: str) -> str:
    txt = str(value or "").strip().lower()
    return {
        "em_dia": "Em dia",
        "pendente": "Pendente",
        "inadimplente": "Inadimplente",
    }.get(txt, _safe_text(value))


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
        except Exception:
            pass
        super().showPopup()


class _SectionHeader(QLabel):
    def __init__(self, text: str):
        super().__init__(text.upper())
        self.setObjectName("sectionHeader")


class EmpresaRow(TypedDict):
    id: int
    nome: str
    cnpj: str
    telefone: str
    email: str
    forma_pagamento: str
    forma_label: str
    status_pagamento: str
    status_label: str
    vencimento_dia: str
    vencimento_label: str
    valor_mensal: str
    data_cadastro: str
    endereco: str
    cidade_uf: str
    cep: str


class _WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)


class _DbWorker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.signals = _WorkerSignals()

    @Slot()
    def run(self):
        try:
            out = self._fn(*self._args, **self._kwargs)
            self.signals.result.emit(out)
        except Exception as e:
            self.signals.error.emit(str(e))


class ListarEmpresasView(QWidget):
    voltar_signal = Signal()
    novo_signal = Signal()
    importar_signal = Signal()
    editar_signal = Signal(int)
    excluir_signal = Signal(int)

    def __init__(self):
        super().__init__()
        self._page = 0
        self._page_size = 30
        self._total = 0
        self._rows_visible: list[EmpresaRow] = []
        self._selected_empresa_id: Optional[int] = None
        self._loading = False
        self._reload_pending = False
        self.nivel_usuario = ""
        self._is_recepcao = False
        self._can_delete_empresa = True
        self._can_create_empresa = True
        self._reload_seq = 0
        self.threadpool = QThreadPool.globalInstance()
        self._settings = QSettings("MedContract", "MedContract")
        self._settings_prefix = "views/listar_empresas"
        self._restoring_state = False

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._on_search_changed)

        self._msg_timer = QTimer(self)
        self._msg_timer.setSingleShot(True)
        self._msg_timer.timeout.connect(self._hide_message)

        self.setup_ui()
        self.apply_styles()
        self._wire_shortcuts()
        self._restore_view_state()

    def _settings_key(self, name: str) -> str:
        return f"{self._settings_prefix}/{name}"

    def _persist_view_state(self):
        if self._restoring_state:
            return
        self._settings.setValue(self._settings_key("search"), (self.search.text() or "").strip())
        self._settings.setValue(self._settings_key("forma"), str(self.filter_forma.currentData() or "").strip().lower())
        self._settings.setValue(self._settings_key("status"), str(self.filter_status.currentData() or "").strip().lower())
        self._settings.setValue(self._settings_key("page_size"), int(self._page_size))
        self._settings.setValue(self._settings_key("page"), int(self._page))
        self._settings.sync()

    def _restore_view_state(self):
        controls = (self.search, self.filter_forma, self.filter_status, self.page_size_combo)
        for control in controls:
            control.blockSignals(True)
        self._restoring_state = True
        try:
            search = self._settings.value(self._settings_key("search"), "", type=str) or ""
            forma = (self._settings.value(self._settings_key("forma"), "", type=str) or "").strip().lower()
            status = (self._settings.value(self._settings_key("status"), "", type=str) or "").strip().lower()
            try:
                page_size = int(self._settings.value(self._settings_key("page_size"), 30))
            except Exception:
                page_size = 30
            try:
                page = int(self._settings.value(self._settings_key("page"), 0))
            except Exception:
                page = 0

            if page_size not in (30, 50, 100):
                page_size = 30
            self._page_size = page_size
            self._page = max(0, page)
            self.search.setText(str(search).strip())

            idx_forma = self.filter_forma.findData(forma)
            self.filter_forma.setCurrentIndex(max(0, idx_forma))
            idx_status = self.filter_status.findData(status)
            self.filter_status.setCurrentIndex(max(0, idx_status))

            page_size_idx = {30: 0, 50: 1, 100: 2}.get(page_size, 0)
            self.page_size_combo.setCurrentIndex(page_size_idx)
            self._refresh_pagination()
        finally:
            self._restoring_state = False
            for control in controls:
                control.blockSignals(False)

    def setup_ui(self):
        self.setObjectName("ListarEmpresas")
        root = QVBoxLayout(self)
        self._root_layout = root
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(10)

        title_wrap = QVBoxLayout()
        title_wrap.setSpacing(2)
        self.breadcrumb = QLabel("Cadastro  /  Empresas")
        self.breadcrumb.setObjectName("breadcrumb")
        self.title = QLabel("Empresas")
        self.title.setObjectName("title")
        self.subtitle = QLabel("Gerencie empresas, contratos e status de pagamento.")
        self.subtitle.setObjectName("subtitle")
        title_wrap.addWidget(self.breadcrumb)
        title_wrap.addWidget(self.title)
        title_wrap.addWidget(self.subtitle)
        top.addLayout(title_wrap)
        top.addStretch()

        self.btn_voltar = QPushButton("Voltar")
        self.btn_voltar.setObjectName("btnSecondary")
        self.btn_voltar.setFixedHeight(36)
        self.btn_voltar.setMinimumWidth(96)
        self.btn_voltar.setCursor(Qt.PointingHandCursor)
        self.btn_voltar.setToolTip("Voltar para a tela anterior")
        self.btn_voltar.clicked.connect(self.voltar_signal.emit)
        top.addWidget(self.btn_voltar)
        root.addLayout(top)

        self.btn_novo = QPushButton("+ Novo")
        self.btn_novo.setObjectName("btnPrimary")
        self.btn_novo.setFixedHeight(36)
        self.btn_novo.setMinimumWidth(116)
        self.btn_novo.setCursor(Qt.PointingHandCursor)
        self.btn_novo.setToolTip("Cadastrar nova empresa")
        self.btn_novo.clicked.connect(self._novo_empresa)

        self.btn_importar = QPushButton("Importar")
        self.btn_importar.setObjectName("btnSecondary")
        self.btn_importar.setFixedHeight(36)
        self.btn_importar.setMinimumWidth(110)
        self.btn_importar.setCursor(Qt.PointingHandCursor)
        self.btn_importar.setToolTip("Importar empresas por planilha (.xlsx/.csv)")
        self.btn_importar.clicked.connect(self.importar_signal.emit)

        self.btn_editar_sel = QPushButton("Editar")
        self.btn_editar_sel.setObjectName("btnSecondary")
        self.btn_editar_sel.setFixedHeight(36)
        self.btn_editar_sel.setMinimumWidth(98)
        self.btn_editar_sel.setCursor(Qt.PointingHandCursor)
        self.btn_editar_sel.setToolTip("Editar empresa selecionada")
        self.btn_editar_sel.clicked.connect(self._editar_selecionado)

        self.btn_excluir_sel = QPushButton("Excluir")
        self.btn_excluir_sel.setObjectName("btnDanger")
        self.btn_excluir_sel.setFixedHeight(36)
        self.btn_excluir_sel.setMinimumWidth(98)
        self.btn_excluir_sel.setCursor(Qt.PointingHandCursor)
        self.btn_excluir_sel.setToolTip("Excluir empresa selecionada")
        self.btn_excluir_sel.clicked.connect(self._excluir_selecionado)

        action_strip = QFrame()
        action_strip.setObjectName("actionStrip")
        action_row = QHBoxLayout(action_strip)
        action_row.setContentsMargins(12, 10, 12, 10)
        action_row.setSpacing(10)

        lbl_selected = QLabel("Empresa selecionada:")
        lbl_selected.setObjectName("actionStripLabel")
        lbl_critical = QLabel("Acoes criticas:")
        lbl_critical.setObjectName("actionStripLabelWarn")
        action_divider = QFrame()
        action_divider.setObjectName("actionStripDivider")
        action_divider.setFixedWidth(1)

        action_row.addWidget(lbl_selected)
        action_row.addWidget(self.btn_editar_sel)
        action_row.addSpacing(4)
        action_row.addWidget(action_divider)
        action_row.addSpacing(4)
        action_row.addWidget(lbl_critical)
        action_row.addWidget(self.btn_excluir_sel)
        action_row.addStretch()
        action_row.addWidget(self.btn_importar)
        action_row.addWidget(self.btn_novo)
        root.addWidget(action_strip)

        line = QFrame()
        line.setObjectName("softLine")
        line.setFixedHeight(1)
        root.addWidget(line)

        chips = QHBoxLayout()
        chips.setSpacing(10)
        self.chip_total = QLabel("Total: -")
        self.chip_total.setObjectName("statChip")
        self.chip_em_dia = QLabel("Em dia: -")
        self.chip_em_dia.setObjectName("statChipOk")
        self.chip_pendente = QLabel("Pendente: -")
        self.chip_pendente.setObjectName("statChipWarn")
        self.chip_inadimplente = QLabel("Inadimplente: -")
        self.chip_inadimplente.setObjectName("statChipDanger")
        self.chip_visiveis = QLabel("Visiveis: -")
        self.chip_visiveis.setObjectName("statChipInfo")
        for chip in (
            self.chip_total,
            self.chip_em_dia,
            self.chip_pendente,
            self.chip_inadimplente,
            self.chip_visiveis,
        ):
            chips.addWidget(chip)
        chips.addStretch()
        root.addLayout(chips)

        filter_card = QFrame()
        filter_card.setObjectName("card")
        fl = QHBoxLayout(filter_card)
        fl.setContentsMargins(12, 10, 12, 10)
        fl.setSpacing(10)

        self.search = QLineEdit()
        self.search.setObjectName("fieldInput")
        self.search.setPlaceholderText("Buscar por nome da empresa ou CNPJ...")
        self.search.setFixedHeight(42)
        self.search.setAccessibleName("Campo de busca de empresas")
        self.search.textChanged.connect(self._on_search_typing)
        self.search.returnPressed.connect(self._on_search_changed)

        self.btn_clear = QToolButton()
        self.btn_clear.setObjectName("iconBtn")
        self.btn_clear.setText("x")
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

        self.filter_forma = StyledComboBox()
        self.filter_forma.setObjectName("filterCombo")
        self.filter_forma.setFixedHeight(42)
        self.filter_forma.addItem("Forma: todas", "")
        self.filter_forma.addItem("Pix", "pix")
        self.filter_forma.addItem("Boleto", "boleto")
        self.filter_forma.addItem("Recepcao", "recepcao")
        self.filter_forma.currentIndexChanged.connect(self._on_filter_changed)

        self.filter_status = StyledComboBox()
        self.filter_status.setObjectName("filterCombo")
        self.filter_status.setFixedHeight(42)
        self.filter_status.addItem("Status: todos", "")
        self.filter_status.addItem("Em dia", "em_dia")
        self.filter_status.addItem("Pendente", "pendente")
        self.filter_status.addItem("Inadimplente", "inadimplente")
        self.filter_status.currentIndexChanged.connect(self._on_filter_changed)

        self.page_size_combo = StyledComboBox()
        self.page_size_combo.setObjectName("filterCombo")
        self.page_size_combo.setFixedHeight(42)
        self.page_size_combo.addItems(["30 / pagina", "50 / pagina", "100 / pagina"])
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

        fl.addWidget(search_wrap, 1)
        fl.addWidget(self.filter_forma)
        fl.addWidget(self.filter_status)
        fl.addWidget(self.page_size_combo)
        fl.addWidget(self.btn_clear_filters)
        fl.addWidget(self.btn_reload)
        root.addWidget(filter_card)

        self.card_table = QFrame()
        self.card_table.setObjectName("card")
        table_layout = QVBoxLayout(self.card_table)
        table_layout.setContentsMargins(14, 14, 14, 14)
        table_layout.setSpacing(10)

        self._table_stack = QStackedWidget()

        table_page = QFrame()
        tpl = QVBoxLayout(table_page)
        tpl.setContentsMargins(0, 0, 0, 0)
        tpl.setSpacing(0)

        self.table = QTableWidget(0, 9)
        self.table.setObjectName("table")
        self.table.setHorizontalHeaderLabels(
            [
                "Empresa",
                "CNPJ",
                "Telefone",
                "E-mail",
                "Forma",
                "Status",
                "Vencimento",
                "Valor",
                "Acoes",
            ]
        )
        self.table.setSortingEnabled(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.verticalHeader().setMinimumSectionSize(36)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.setAccessibleName("Lista de empresas")
        self.table.setAccessibleDescription(
            "Tabela com nome, CNPJ, contato, forma, status e valor mensal das empresas."
        )

        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionsClickable(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3, 4, 5, 6, 7):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.Fixed)
        self.table.setColumnWidth(8, 176)

        self.table.itemSelectionChanged.connect(self._on_select_row)
        self.table.itemDoubleClicked.connect(self._editar_selecionado)
        self.table.customContextMenuRequested.connect(self._open_context_menu)
        tpl.addWidget(self.table)

        self._loading_page = QFrame()
        self._loading_page.setObjectName("loadingPage")
        ll = QVBoxLayout(self._loading_page)
        ll.setAlignment(Qt.AlignCenter)
        self._loading_label = QLabel("Carregando empresas...")
        self._loading_label.setObjectName("loadingLabel")
        self._loading_label.setAlignment(Qt.AlignCenter)
        ll.addWidget(self._loading_label)

        self._empty_page = QFrame()
        self._empty_page.setObjectName("emptyPage")
        el = QVBoxLayout(self._empty_page)
        el.setAlignment(Qt.AlignCenter)
        el.setSpacing(6)
        self._empty_title = QLabel("Nenhuma empresa encontrada")
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

        pager = QHBoxLayout()
        pager.setSpacing(10)
        self.lbl_visible = QLabel("Visiveis: 0")
        self.lbl_visible.setObjectName("pagerText")
        self.lbl_page = QLabel("Pagina 1 de 1")
        self.lbl_page.setObjectName("pagerText")
        self.btn_prev = QPushButton("Anterior")
        self.btn_prev.setObjectName("btnSecondary")
        self.btn_prev.setFixedHeight(38)
        self.btn_prev.clicked.connect(self._go_prev)
        self.btn_next = QPushButton("Proxima")
        self.btn_next.setObjectName("btnSecondary")
        self.btn_next.setFixedHeight(38)
        self.btn_next.clicked.connect(self._go_next)

        pager.addWidget(self.lbl_visible)
        pager.addStretch()
        pager.addWidget(self.lbl_page)
        pager.addWidget(self.btn_prev)
        pager.addWidget(self.btn_next)
        table_layout.addLayout(pager)

        self.card_side = QFrame()
        self.card_side.setObjectName("sideCard")
        self.card_side.setMinimumWidth(280)
        self.card_side.setMaximumWidth(460)
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

        self.side_title = QLabel("Detalhes da Empresa")
        self.side_title.setObjectName("sideTitle")
        self.side_sub = QLabel("Selecione uma empresa na tabela.")
        self.side_sub.setObjectName("sideSub")
        self.side_sub.setWordWrap(True)
        sl.addWidget(self.side_title)
        sl.addWidget(self.side_sub)

        def _div():
            d = QFrame()
            d.setObjectName("divider")
            d.setFixedHeight(1)
            return d

        sl.addWidget(_div())

        sl.addWidget(_SectionHeader("Contato"))
        self.det_nome = self._detail_field("Nome")
        self.det_cnpj = self._detail_field("CNPJ")
        self.det_telefone = self._detail_field("Telefone")
        self.det_email = self._detail_field("E-mail")
        for w in (self.det_nome, self.det_cnpj, self.det_telefone, self.det_email):
            sl.addWidget(w)

        sl.addWidget(_div())

        sl.addWidget(_SectionHeader("Financeiro"))
        self.det_forma = self._detail_field("Forma de pagamento")
        self.det_status = self._detail_field("Status de pagamento")
        self.det_vencimento = self._detail_field("Dia de vencimento")
        self.det_valor = self._detail_field("Valor mensal")
        for w in (self.det_forma, self.det_status, self.det_vencimento, self.det_valor):
            sl.addWidget(w)

        sl.addWidget(_div())

        sl.addWidget(_SectionHeader("Endereco"))
        self.det_endereco = self._detail_field("Endereco")
        self.det_cidade = self._detail_field("Cidade / UF")
        self.det_cep = self._detail_field("CEP")
        for w in (self.det_endereco, self.det_cidade, self.det_cep):
            sl.addWidget(w)

        sl.addWidget(_div())

        sl.addWidget(_SectionHeader("Cadastro"))
        self.det_data_cadastro = self._detail_field("Data de cadastro")
        sl.addWidget(self.det_data_cadastro)

        sl.addWidget(_div())

        sl.addWidget(_SectionHeader("Timeline"))
        self.timeline_labels: list[QLabel] = []
        for _ in range(4):
            lbl = QLabel("—")
            lbl.setObjectName("timelineItem")
            lbl.setWordWrap(True)
            lbl.setProperty("tone", "muted")
            self.timeline_labels.append(lbl)
            sl.addWidget(lbl)

        sl.addWidget(_div())

        quick = QGridLayout()
        quick.setHorizontalSpacing(10)
        quick.setVerticalSpacing(8)
        self.btn_quick_edit = QPushButton("Editar")
        self.btn_quick_edit.setObjectName("btnSecondary")
        self.btn_quick_edit.setFixedHeight(40)
        self.btn_quick_edit.setCursor(Qt.PointingHandCursor)
        self.btn_quick_edit.setToolTip("Editar empresa selecionada")
        self.btn_quick_edit.clicked.connect(self._editar_selecionado)

        self.btn_quick_del = QPushButton("Excluir")
        self.btn_quick_del.setObjectName("btnDanger")
        self.btn_quick_del.setFixedHeight(40)
        self.btn_quick_del.setCursor(Qt.PointingHandCursor)
        self.btn_quick_del.setToolTip("Excluir empresa selecionada")
        self.btn_quick_del.clicked.connect(self._excluir_selecionado)

        quick.addWidget(self.btn_quick_edit, 0, 0)
        quick.addWidget(self.btn_quick_del, 0, 1)
        quick.setColumnStretch(0, 1)
        quick.setColumnStretch(1, 1)
        sl.addLayout(quick)
        sl.addStretch()

        side_outer.addWidget(self.side_scroll)
        self.content_splitter = QSplitter(Qt.Horizontal)
        self.content_splitter.setObjectName("contentSplitter")
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(0)
        self.content_splitter.addWidget(self.card_table)
        self.content_splitter.addWidget(self.card_side)
        self.content_splitter.setStretchFactor(0, 7)
        self.content_splitter.setStretchFactor(1, 3)
        self.content_splitter.setSizes([980, 340])
        try:
            splitter_handle = self.content_splitter.handle(1)
            splitter_handle.setEnabled(False)
            splitter_handle.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        except Exception:
            pass
        root.addWidget(self.content_splitter, 1)

        self.inline_msg = QLabel("")
        self.inline_msg.setObjectName("inlineMessage")
        self.inline_msg.setVisible(False)
        self.inline_msg.setWordWrap(True)
        root.addWidget(self.inline_msg)

        self._set_actions_enabled(False)
        self._clear_details()
        self._apply_responsive_layout()

    def _detail_field(self, label_text: str) -> QFrame:
        wrap = QFrame()
        wrap.setObjectName("detailWrap")
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        lab = QLabel(label_text)
        lab.setObjectName("detailLabel")
        val = QLabel("-")
        val.setObjectName("detailValue")
        val.setWordWrap(True)
        lay.addWidget(lab)
        lay.addWidget(val)
        wrap._value_label = val
        return wrap

    def _set_detail(self, field: QFrame, value: str):
        field._value_label.setText(value if value else "-")

    def _set_timeline(self, rows: list[str] | None):
        items = list(rows or [])[:4]
        for i, lbl in enumerate(self.timeline_labels):
            if i < len(items):
                lbl.setText(str(items[i] or "").strip() or "—")
                lbl.setProperty("tone", "normal")
            else:
                lbl.setText("—")
                lbl.setProperty("tone", "muted")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

    def _wire_shortcuts(self):
        shortcuts = [
            ("F5", self.reload),
            ("Ctrl+F", lambda: self.search.setFocus()),
            ("Escape", self._clear_search),
            ("Ctrl+N", self._novo_empresa),
            ("Ctrl+E", self._editar_selecionado),
            ("Delete", self._excluir_selecionado),
        ]
        for key, slot in shortcuts:
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(slot)

    def _apply_responsive_layout(self):
        if not hasattr(self, "content_splitter"):
            return
        w = max(1, int(self.width()))
        h = max(1, int(self.height()))
        compact = bool(w < 1240 or h < 720)
        tiny = bool(w < 980 or h < 620)

        if hasattr(self, "_root_layout"):
            if tiny:
                self._root_layout.setContentsMargins(10, 8, 10, 8)
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
            self.content_splitter.setSizes([650, 230])
        elif compact:
            self.content_splitter.setOrientation(Qt.Vertical)
            self.card_side.setMinimumWidth(0)
            self.card_side.setMaximumWidth(16777215)
            self.card_side.setMinimumHeight(260)
            self.card_side.setMaximumHeight(460)
            self.content_splitter.setSizes([760, 260])
        else:
            self.content_splitter.setOrientation(Qt.Horizontal)
            self.card_side.setMinimumHeight(0)
            self.card_side.setMaximumHeight(16777215)
            self.card_side.setMinimumWidth(280)
            self.card_side.setMaximumWidth(460)
            self.content_splitter.setSizes([980, 340])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def open_with_filters(
        self,
        search_text: str = "",
        forma_pagamento: str = "",
        status_pagamento: str = "",
    ):
        self.search.setText(search_text or "")
        idx_forma = self.filter_forma.findData((forma_pagamento or "").strip().lower())
        self.filter_forma.setCurrentIndex(max(0, idx_forma))
        idx_status = self.filter_status.findData((status_pagamento or "").strip().lower())
        self.filter_status.setCurrentIndex(max(0, idx_status))
        self._page = 0
        self._persist_view_state()
        self.reload()

    def set_nivel_usuario(self, nivel: str):
        nivel_txt = str(nivel or "")
        role = _normalize_role(nivel_txt)
        is_recepcao = (role == "recepcao")
        changed = (
            self.nivel_usuario != nivel_txt
            or self._is_recepcao != is_recepcao
        )
        self.nivel_usuario = nivel_txt
        self._is_recepcao = is_recepcao
        # RBAC (Recepção): oculta +Novo e Excluir na listagem de empresas.
        self._can_create_empresa = not self._is_recepcao
        self._can_delete_empresa = not self._is_recepcao
        self.btn_novo.setVisible(self._can_create_empresa)
        self.btn_importar.setVisible(self._can_create_empresa)
        self.btn_excluir_sel.setVisible(self._can_delete_empresa)
        self.btn_quick_del.setVisible(self._can_delete_empresa)
        # Solicitação da regra de perfil: oculta a coluna de E-mail para recepção.
        self.table.setColumnHidden(3, self._is_recepcao)
        self._set_actions_enabled(bool(self._selected_empresa_id))
        if changed:
            self.reload()

    def _on_search_typing(self):
        self._search_timer.start()

    def _on_search_changed(self):
        self._page = 0
        self._persist_view_state()
        self.reload()

    def _on_filter_changed(self):
        self._page = 0
        self._persist_view_state()
        self.reload()

    def _on_page_size_changed(self):
        txt = str(self.page_size_combo.currentText() or "")
        if "100" in txt:
            self._page_size = 100
        elif "50" in txt:
            self._page_size = 50
        else:
            self._page_size = 30
        self._page = 0
        self._persist_view_state()
        self.reload()

    def _go_prev(self):
        if self._page > 0:
            self._page -= 1
            self._persist_view_state()
            self.reload()

    def _go_next(self):
        max_page = max(0, (max(0, self._total) - 1) // self._page_size)
        if self._page < max_page:
            self._page += 1
            self._persist_view_state()
            self.reload()

    def _make_table_item(self, text: str, align: Qt.AlignmentFlag = Qt.AlignLeft | Qt.AlignVCenter):
        item = QTableWidgetItem(str(text))
        item.setTextAlignment(int(align))
        return item

    def _status_item(self, status_value: str) -> QTableWidgetItem:
        status = str(status_value or "").strip().lower()
        text = _status_label(status)

        if status == "em_dia":
            fg, bg = _GOOD, _GOOD_BG
        elif status == "pendente":
            fg, bg = _WARN, _WARN_BG
        else:
            fg, bg = _DANGER, _DANGER_BG

        item = QTableWidgetItem(text)
        item.setTextAlignment(int(Qt.AlignCenter))
        item.setForeground(QColor(fg))
        item.setBackground(QColor(bg))
        f = item.font()
        f.setBold(True)
        item.setFont(f)
        return item

    def _map_empresa_row(self, row: tuple) -> EmpresaRow:
        emp_id = int(row[0])
        nome = _safe_text(row[2], "-")
        cnpj = _format_cnpj(str(row[1] or ""))
        telefone = _format_phone(str(row[3] or ""))
        email = _safe_text(row[4], "-")

        forma = str(row[11] or "").strip().lower()
        status = str(row[12] or "").strip().lower()
        dia_venc = str(row[13] or "").strip()
        valor_mensal = _format_moeda_brl(str(row[14] or ""))
        data_cadastro = _format_date_br(str(row[15] or ""))

        logradouro = _safe_text(row[5], "")
        numero = _safe_text(row[6], "")
        bairro = _safe_text(row[7], "")
        cep = _safe_text(row[8], "-")
        cidade = _safe_text(row[9], "")
        estado = _safe_text(row[10], "")

        endereco_parts = [p for p in [logradouro, f"No {numero}" if numero else "", bairro] if p]
        endereco = ", ".join(endereco_parts) if endereco_parts else "-"
        cidade_uf = " / ".join([p for p in [cidade, estado] if p]) or "-"

        return EmpresaRow(
            id=emp_id,
            nome=nome,
            cnpj=cnpj,
            telefone=telefone,
            email=email,
            forma_pagamento=forma,
            forma_label=_forma_label(forma),
            status_pagamento=status,
            status_label=_status_label(status),
            vencimento_dia=dia_venc,
            vencimento_label=(f"Dia {dia_venc}" if dia_venc else "-"),
            valor_mensal=valor_mensal,
            data_cadastro=data_cadastro,
            endereco=endereco,
            cidade_uf=cidade_uf,
            cep=cep,
        )

    def _actions_widget(self, empresa_id: int) -> QWidget:
        wrap = QFrame()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(4, 3, 4, 3)
        lay.setSpacing(6)

        btn_edit = QPushButton("Editar")
        btn_edit.setObjectName("btnTableEdit")
        btn_edit.setFixedHeight(28)
        btn_edit.setMinimumWidth(70)
        btn_edit.setCursor(Qt.PointingHandCursor)
        btn_edit.setAccessibleName(f"Editar empresa ID {empresa_id}")
        btn_edit.clicked.connect(lambda _=False, eid=int(empresa_id): self.editar_signal.emit(eid))

        lay.addWidget(btn_edit)
        total_width = btn_edit.minimumWidth() + 18
        if self._can_delete_empresa:
            btn_del = QPushButton("Excluir")
            btn_del.setObjectName("btnTableDelete")
            btn_del.setFixedHeight(28)
            btn_del.setMinimumWidth(70)
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.setAccessibleName(f"Excluir empresa ID {empresa_id}")
            btn_del.clicked.connect(lambda _=False, eid=int(empresa_id): self.excluir_signal.emit(eid))
            lay.addWidget(btn_del)
            total_width += btn_del.minimumWidth() + lay.spacing()
        self.table.setColumnWidth(8, max(128, total_width + 8))
        return wrap

    def _fill_table(self, rows: list[tuple]):
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        selected_first = False
        try:
            self.table.setRowCount(0)
            self._rows_visible = []
            self._selected_empresa_id = None
            self._set_actions_enabled(False)
            self._clear_details()

            for row in rows:
                emp = self._map_empresa_row(row)
                self._rows_visible.append(emp)
                r = self.table.rowCount()
                self.table.insertRow(r)
                self.table.setItem(r, 0, self._make_table_item(emp["nome"]))
                self.table.setItem(r, 1, self._make_table_item(emp["cnpj"], Qt.AlignCenter))
                self.table.setItem(r, 2, self._make_table_item(emp["telefone"], Qt.AlignCenter))
                self.table.setItem(r, 3, self._make_table_item(emp["email"]))
                self.table.setItem(r, 4, self._make_table_item(emp["forma_label"], Qt.AlignCenter))
                self.table.setItem(r, 5, self._status_item(emp["status_pagamento"]))
                self.table.setItem(r, 6, self._make_table_item(emp["vencimento_label"], Qt.AlignCenter))
                self.table.setItem(r, 7, self._make_table_item(emp["valor_mensal"], Qt.AlignRight | Qt.AlignVCenter))
                self.table.setCellWidget(r, 8, self._actions_widget(emp["id"]))

            if self._rows_visible:
                self.table.selectRow(0)
                selected_first = True

            self.table.resizeColumnsToContents()
            min_actions_width = 176 if self._can_delete_empresa else 128
            self.table.setColumnWidth(8, max(min_actions_width, self.table.columnWidth(8)))
            self.lbl_visible.setText(f"Visiveis: {len(self._rows_visible)}")
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)
        if selected_first:
            self._on_select_row()

    def _refresh_pagination(self):
        max_page = max(0, (max(0, self._total) - 1) // self._page_size)
        self.lbl_page.setText(f"Pagina {self._page + 1} de {max_page + 1} • Total {self._total}")
        self.btn_prev.setEnabled(self._page > 0 and not self._loading)
        self.btn_next.setEnabled(self._page < max_page and not self._loading)

    def _refresh_stats_chips(self, counts: Optional[dict] = None):
        if counts:
            em_dia = int((counts or {}).get("em_dia", 0) or 0)
            pendente = int((counts or {}).get("pendente", 0) or 0)
            inadimplente = int((counts or {}).get("inadimplente", 0) or 0)
        else:
            em_dia = 0
            pendente = 0
            inadimplente = 0
            for row in self._rows_visible:
                st = row["status_pagamento"]
                if st == "em_dia":
                    em_dia += 1
                elif st == "pendente":
                    pendente += 1
                elif st == "inadimplente":
                    inadimplente += 1

        self.chip_total.setText(f"Total: {self._total}")
        self.chip_em_dia.setText(f"Em dia: {em_dia}")
        self.chip_pendente.setText(f"Pendente: {pendente}")
        self.chip_inadimplente.setText(f"Inadimplente: {inadimplente}")
        self.chip_visiveis.setText(f"Visiveis: {len(self._rows_visible)}")

    def reload(self):
        if self._loading:
            self._reload_pending = True
            return

        self._reload_seq += 1
        seq = int(self._reload_seq)
        self._reload_pending = False
        self._show_loading(True)

        search = (self.search.text() or "").strip()
        forma = str(self.filter_forma.currentData() or "").strip().lower()
        status = str(self.filter_status.currentData() or "").strip().lower()
        page_size = int(self._page_size)
        page = int(self._page)

        def _fetch():
            payload = db.listar_empresas_payload(
                page=page,
                limit=page_size,
                search=search,
                forma_pagamento=forma,
                status_pagamento=status,
            )

            return {
                "seq": seq,
                "total": int((payload or {}).get("total", 0) or 0),
                "page_safe": int((payload or {}).get("page_safe", 0) or 0),
                "rows": list((payload or {}).get("rows", []) or []),
                "status_counts": dict((payload or {}).get("status_counts", {}) or {}),
            }

        worker = _DbWorker(_fetch)
        worker.signals.result.connect(self._on_reload_done)
        worker.signals.error.connect(lambda msg, s=seq: self._on_reload_error(s, msg))
        self.threadpool.start(worker)

    @Slot(object)
    def _on_reload_done(self, payload):
        seq = int((payload or {}).get("seq", 0) or 0)
        if seq != self._reload_seq:
            return

        self._total = int((payload or {}).get("total", 0) or 0)
        self._page = int((payload or {}).get("page_safe", 0) or 0)
        self._persist_view_state()
        rows = list((payload or {}).get("rows", []) or [])
        status_counts = dict((payload or {}).get("status_counts", {}) or {})

        self._fill_table(rows)
        self._refresh_pagination()
        self._refresh_stats_chips(status_counts)
        if not rows:
            has_filter = bool(
                (self.search.text() or "").strip()
                or str(self.filter_forma.currentData() or "").strip()
                or str(self.filter_status.currentData() or "").strip()
            )
            if has_filter:
                self._set_table_state(
                    "empty",
                    title="Nenhuma empresa encontrada",
                    subtitle="Tente remover filtros ou ajustar o termo de busca.",
                )
            else:
                self._set_table_state(
                    "empty",
                    title="Sem empresas cadastradas",
                    subtitle="Use “+ Novo” ou “Importar” para iniciar os cadastros.",
                )
            self._show_message("")
        else:
            self._set_table_state("table")
            self._show_message("")
        self._show_loading(False)
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
                title="Falha ao carregar empresas",
                subtitle="Não foi possível consultar os dados agora. Tente atualizar novamente.",
                tone="error",
            )
        self._show_message(f"Falha ao carregar empresas: {error_msg}", ok=False)
        if self._reload_pending:
            self._reload_pending = False
            self.reload()

    def _on_select_row(self):
        selected = self.table.selectedRanges()
        if not selected:
            self._selected_empresa_id = None
            self._set_actions_enabled(False)
            self._clear_details()
            return

        row_idx = int(selected[0].topRow())
        if row_idx < 0 or row_idx >= len(self._rows_visible):
            self._selected_empresa_id = None
            self._set_actions_enabled(False)
            self._clear_details()
            return

        empresa = self._rows_visible[row_idx]
        self._selected_empresa_id = int(empresa["id"])
        self._set_actions_enabled(True)
        self._apply_detail(empresa)

    def _apply_detail(self, empresa: EmpresaRow):
        self.side_sub.setText(f"{empresa['nome']} • ID {empresa['id']}")
        self._set_detail(self.det_nome, empresa["nome"])
        self._set_detail(self.det_cnpj, empresa["cnpj"])
        self._set_detail(self.det_telefone, empresa["telefone"])
        self._set_detail(self.det_email, empresa["email"])
        self._set_detail(self.det_forma, empresa["forma_label"])
        self._set_detail(self.det_status, empresa["status_label"])
        self._set_detail(self.det_vencimento, empresa["vencimento_label"])
        self._set_detail(self.det_valor, empresa["valor_mensal"])
        self._set_detail(self.det_endereco, empresa["endereco"])
        self._set_detail(self.det_cidade, empresa["cidade_uf"])
        self._set_detail(self.det_cep, empresa["cep"])
        self._set_detail(self.det_data_cadastro, empresa["data_cadastro"])
        timeline_rows = [
            f"Cadastro em {empresa['data_cadastro']}",
            f"Status atual: {empresa['status_label']}",
            f"Forma de pagamento: {empresa['forma_label']}  ·  {empresa['vencimento_label']}",
            f"Valor mensal vigente: {empresa['valor_mensal']}",
        ]
        self._set_timeline(timeline_rows)

    def _clear_details(self):
        self.side_sub.setText("Selecione uma empresa na tabela.")
        for field in (
            self.det_nome,
            self.det_cnpj,
            self.det_telefone,
            self.det_email,
            self.det_forma,
            self.det_status,
            self.det_vencimento,
            self.det_valor,
            self.det_endereco,
            self.det_cidade,
            self.det_cep,
            self.det_data_cadastro,
        ):
            self._set_detail(field, "-")
        self._set_timeline([])

    def _set_actions_enabled(self, enabled: bool):
        self.btn_editar_sel.setEnabled(enabled and not self._loading)
        self.btn_excluir_sel.setEnabled(enabled and not self._loading and self._can_delete_empresa)
        self.btn_quick_edit.setEnabled(enabled and not self._loading)
        self.btn_quick_del.setEnabled(enabled and not self._loading and self._can_delete_empresa)

    def _novo_empresa(self, *_):
        # RBAC (Recepção): bloqueio também no handler para evitar bypass via atalho/sinal.
        if not self._can_create_empresa:
            self._show_message("Perfil de recepção não pode cadastrar empresas.", ok=False)
            return
        self.novo_signal.emit()

    def _editar_selecionado(self, *_):
        if not self._selected_empresa_id:
            self._show_message("Selecione uma empresa primeiro.", ok=False)
            return
        self.editar_signal.emit(int(self._selected_empresa_id))

    def _excluir_selecionado(self, *_):
        # RBAC (Recepção): sem ação de exclusão na listagem.
        if not self._can_delete_empresa:
            self._show_message("Perfil de recepção não pode excluir empresas.", ok=False)
            return
        if not self._selected_empresa_id:
            self._show_message("Selecione uma empresa primeiro.", ok=False)
            return
        self.excluir_signal.emit(int(self._selected_empresa_id))

    def _open_context_menu(self, pos: QPoint):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        self.table.selectRow(row)

        menu = QMenu(self)
        menu.setObjectName("tableMenu")

        act_edit = QAction("Editar empresa", self)
        act_edit.triggered.connect(self._editar_selecionado)

        act_del = QAction("Excluir empresa", self)
        act_del.triggered.connect(self._excluir_selecionado)

        act_reload = QAction("Atualizar lista", self)
        act_reload.triggered.connect(self.reload)

        menu.addAction(act_edit)
        if self._can_delete_empresa:
            menu.addAction(act_del)
        menu.addSeparator()
        menu.addAction(act_reload)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _clear_search(self):
        if self.search.text():
            self.search.clear()
        self.search.setFocus()

    def _clear_all_filters(self):
        self.search.blockSignals(True)
        self.filter_forma.blockSignals(True)
        self.filter_status.blockSignals(True)
        self.page_size_combo.blockSignals(True)
        try:
            self.search.clear()
            self.filter_forma.setCurrentIndex(0)
            self.filter_status.setCurrentIndex(0)
            self.page_size_combo.setCurrentIndex(0)
        finally:
            self.search.blockSignals(False)
            self.filter_forma.blockSignals(False)
            self.filter_status.blockSignals(False)
            self.page_size_combo.blockSignals(False)

        self._page_size = 30
        self._page = 0
        self.search.setFocus()
        self._persist_view_state()
        self.reload()

    def _show_loading(self, loading: bool):
        self._loading = bool(loading)
        if self._loading:
            self._set_table_state("loading")
        elif self.table.rowCount() == 0:
            if self._table_stack.currentIndex() != 2:
                self._set_table_state(
                    "empty",
                    title="Nenhuma empresa encontrada",
                    subtitle="Ajuste os filtros ou limpe a busca para visualizar resultados.",
                )
        else:
            self._set_table_state("table")
        for w in (
            self.btn_reload,
            self.btn_importar,
            self.btn_novo,
            self.btn_prev,
            self.btn_next,
            self.btn_clear,
            self.btn_clear_filters,
            self.filter_forma,
            self.filter_status,
            self.page_size_combo,
            self.search,
        ):
            w.setEnabled(not self._loading)
        self.table.setEnabled(not self._loading)
        self._set_actions_enabled(bool(self._selected_empresa_id))
        self._refresh_pagination()

    def _set_table_state(self, state: str, *, title: str = "", subtitle: str = "", tone: str = "default"):
        key = str(state or "").strip().lower()
        if key == "loading":
            self._table_stack.setCurrentIndex(1)
            return
        if key == "empty":
            self._empty_title.setText(str(title or "Nenhuma empresa encontrada"))
            self._empty_sub.setText(str(subtitle or "Ajuste os filtros para visualizar resultados."))
            self._empty_title.setProperty("tone", tone or "default")
            self._empty_title.style().unpolish(self._empty_title)
            self._empty_title.style().polish(self._empty_title)
            self._table_stack.setCurrentIndex(2)
            return
        self._table_stack.setCurrentIndex(0)

    def _show_message(self, text: str, ok: bool = False, ms: int = 0):
        msg = str(text or "").strip()
        if not msg:
            self._hide_message()
            return
        if not ok:
            ms = 0
        self.inline_msg.setText(msg)
        self.inline_msg.setProperty("ok", bool(ok))
        self.inline_msg.style().unpolish(self.inline_msg)
        self.inline_msg.style().polish(self.inline_msg)
        self.inline_msg.setVisible(True)
        self._msg_timer.stop()
        if ms > 0:
            self._msg_timer.start(ms)

    def _hide_message(self):
        self._msg_timer.stop()
        self.inline_msg.setVisible(False)
        self.inline_msg.setText("")
        self.inline_msg.setProperty("ok", False)
        self.inline_msg.style().unpolish(self.inline_msg)
        self.inline_msg.style().polish(self.inline_msg)

    def apply_styles(self):
        self.setStyleSheet(
            f"""
            QWidget#ListarEmpresas {{
                background: {_BG};
            }}
            QLabel#breadcrumb {{
                color: {_INK3};
                font-size: 11px;
                font-weight: 700;
            }}
            QLabel#title {{
                color: {_INK};
                font-size: 22px;
                font-weight: 700;
            }}
            QLabel#subtitle {{
                color: {_INK2};
                font-size: 12px;
                font-weight: 600;
            }}

            QFrame#softLine, QFrame#divider {{
                background: {_LINE};
                border: none;
            }}
            QFrame#actionStrip {{
                background: rgba(255,255,255,0.90);
                border: 1px solid {_LINE};
                border-radius: 10px;
            }}
            QLabel#actionStripLabel {{
                font-size: 11px;
                font-weight: 700;
                color: {_INK2};
                letter-spacing: 0.2px;
            }}
            QLabel#actionStripLabelWarn {{
                font-size: 11px;
                font-weight: 700;
                color: {_WARN};
                letter-spacing: 0.2px;
            }}
            QFrame#actionStripDivider {{
                background: {_LINE};
                border: none;
                margin: 5px 0;
            }}

            QFrame#card, QFrame#sideCard {{
                background: {_WHITE};
                border: 1px solid {_LINE};
                border-radius: 12px;
            }}

            QLabel#loadingLabel {{
                font-size: 14px;
                font-weight: 700;
                color: {_INK2};
            }}
            QFrame#emptyPage {{
                background: transparent;
            }}
            QLabel#emptyStateTitle {{
                font-size: 15px;
                font-weight: 700;
                color: {_INK};
            }}
            QLabel#emptyStateTitle[tone="error"] {{
                color: {_DANGER};
            }}
            QLabel#emptyStateSub {{
                max-width: 620px;
                font-size: 12px;
                color: {_INK3};
            }}
            QLabel#pagerText {{
                font-size: 12px;
                color: {_INK2};
                font-weight: 600;
            }}

            QLabel#statChip {{
                border-radius: 20px;
                padding: 5px 14px;
                font-size: 12px;
                font-weight: 600;
                border: 1px solid {_LINE};
                background: {_WHITE};
                color: {_INK};
            }}
            QLabel#statChipOk {{
                border-radius: 20px;
                padding: 5px 14px;
                font-size: 12px;
                font-weight: 600;
                background: {_GOOD_BG};
                border: 1px solid {_GOOD_BORDER};
                color: {_GOOD};
            }}
            QLabel#statChipWarn {{
                border-radius: 20px;
                padding: 5px 14px;
                font-size: 12px;
                font-weight: 600;
                background: {_WARN_BG};
                border: 1px solid {_WARN_BORDER};
                color: {_WARN};
            }}
            QLabel#statChipDanger {{
                border-radius: 20px;
                padding: 5px 14px;
                font-size: 12px;
                font-weight: 600;
                background: {_DANGER_BG};
                border: 1px solid {_DANGER_BORDER};
                color: {_DANGER};
            }}
            QLabel#statChipInfo {{
                border-radius: 20px;
                padding: 5px 14px;
                font-size: 12px;
                font-weight: 600;
                background: rgba(37,99,235,0.08);
                border: 1px solid rgba(37,99,235,0.20);
                color: #1e3a8a;
            }}

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
                background: transparent;
                color: {_INK};
                font-size: 13px;
                min-height: 38px;
            }}
            QToolButton#iconBtn {{
                border: none;
                background: transparent;
                border-radius: 6px;
                padding: 4px 8px;
                color: {_INK3};
                font-size: 12px;
                font-weight: 700;
            }}
            QToolButton#iconBtn:hover {{
                background: rgba(15,23,42,0.06);
                color: {_INK};
            }}

            QComboBox#filterCombo {{
                border: 1px solid {_LINE};
                border-radius: 8px;
                padding: 0 30px 0 10px;
                background: {_WHITE};
                color: {_INK};
                font-size: 12px;
                font-weight: 600;
                min-height: 38px;
            }}
            QComboBox#filterCombo:hover {{
                border-color: #c0c7d0;
            }}
            QComboBox#filterCombo:focus {{
                border-color: {_ACCENT};
            }}
            QComboBox#filterCombo::drop-down {{
                width: 28px;
                border: none;
                background: transparent;
            }}
            QComboBox#filterCombo::down-arrow {{
                width: 0;
                height: 0;
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

            QPushButton#btnPrimary {{
                background: {_ACCENT};
                border: none;
                border-radius: 8px;
                padding: 0 16px;
                font-size: 13px;
                font-weight: 700;
                color: white;
            }}
            QPushButton#btnPrimary:hover {{
                background: {_ACCENT_HOVER};
            }}
            QPushButton#btnPrimary:disabled {{
                background: rgba(26,107,124,0.30);
                color: rgba(255,255,255,0.60);
            }}

            QPushButton#btnSecondary {{
                background: {_WHITE};
                border: 1px solid {_LINE};
                border-radius: 8px;
                padding: 0 14px;
                font-size: 13px;
                font-weight: 700;
                color: {_INK};
            }}
            QPushButton#btnSecondary:hover {{
                border-color: {_ACCENT};
                color: {_ACCENT};
            }}
            QPushButton#btnSecondary:disabled {{
                color: {_INK3};
                border-color: {_LINE};
            }}

            QPushButton#btnDanger {{
                background: {_DANGER_BG};
                border: 1px solid {_DANGER_BORDER};
                border-radius: 8px;
                padding: 0 14px;
                font-size: 13px;
                font-weight: 700;
                color: {_DANGER};
            }}
            QPushButton#btnDanger:hover {{
                background: rgba(192,57,43,0.14);
            }}
            QPushButton#btnDanger:disabled {{
                color: {_INK3};
                background: transparent;
                border-color: {_LINE};
            }}

            QPushButton#btnTableEdit {{
                background: rgba(26,107,124,0.09);
                border: 1px solid rgba(26,107,124,0.24);
                border-radius: 8px;
                padding: 0 10px;
                font-size: 11px;
                font-weight: 700;
                color: {_ACCENT};
            }}
            QPushButton#btnTableEdit:hover {{
                background: rgba(26,107,124,0.14);
                border-color: {_ACCENT};
            }}
            QPushButton#btnTableDelete {{
                background: {_DANGER_BG};
                border: 1px solid {_DANGER_BORDER};
                border-radius: 8px;
                padding: 0 10px;
                font-size: 11px;
                font-weight: 700;
                color: {_DANGER};
            }}
            QPushButton#btnTableDelete:hover {{
                background: rgba(192,57,43,0.14);
            }}

            QTableWidget#table {{
                border: 1px solid {_LINE};
                border-radius: 10px;
                background: {_WHITE};
                gridline-color: rgba(232,234,237,0.7);
                font-size: 12px;
                alternate-background-color: {_BG};
                selection-background-color: rgba(26,107,124,0.10);
                selection-color: {_INK};
            }}
            QTableWidget#table::item {{
                padding: 8px 10px;
                border-bottom: 1px solid rgba(232,234,237,0.5);
            }}
            QTableWidget#table::item:selected {{
                background: rgba(26,107,124,0.10);
                color: {_INK};
            }}
            QTableWidget#table::item:focus {{
                outline: none;
                border: none;
            }}
            QHeaderView::section {{
                background: {_BG};
                border: none;
                border-bottom: 1px solid {_LINE};
                padding: 8px 10px;
                font-size: 11px;
                font-weight: 700;
                color: {_INK2};
            }}

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

            QScrollArea#sideScroll {{
                background: transparent;
                border: none;
            }}
            QFrame#sideInner {{
                background: transparent;
            }}
            QLabel#sideTitle {{
                font-size: 14px;
                font-weight: 700;
                color: {_INK};
            }}
            QLabel#sideSub {{
                font-size: 12px;
                color: {_INK2};
            }}
            QLabel#sectionHeader {{
                font-size: 10px;
                font-weight: 600;
                color: {_INK3};
                letter-spacing: 0.8px;
                padding: 2px 0;
            }}
            QFrame#detailWrap {{
                background: {_BG};
                border: 1px solid {_LINE};
                border-radius: 10px;
            }}
            QLabel#detailLabel {{
                font-size: 10px;
                font-weight: 600;
                color: {_INK3};
            }}
            QLabel#detailValue {{
                font-size: 13px;
                font-weight: 500;
                color: {_INK};
            }}
            QLabel#timelineItem {{
                font-size: 11px;
                color: {_INK2};
                border-bottom: 1px dashed rgba(15,23,42,0.08);
                padding: 4px 0;
            }}
            QLabel#timelineItem[tone="muted"] {{
                color: {_INK3};
                border-bottom: none;
            }}

            QLabel#inlineMessage {{
                background: {_DANGER_BG};
                border: 1px solid {_DANGER_BORDER};
                border-left: 4px solid {_DANGER};
                color: {_DANGER};
                padding: 10px 14px;
                border-radius: 8px;
                font-size: 12px;
                font-weight: 600;
            }}
            QLabel#inlineMessage[ok="true"] {{
                background: {_GOOD_BG};
                border: 1px solid {_GOOD_BORDER};
                border-left: 4px solid {_GOOD};
                color: {_GOOD};
            }}
            """
        )
