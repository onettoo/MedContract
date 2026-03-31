# -*- coding: utf-8 -*-
"""
Dashboard View - Modern SaaS Design
Sistema de gestão clínica - Dashboard principal
Paleta: azul/teal profissional
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QLinearGradient
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QComboBox,
    QGraphicsDropShadowEffect,
    QMessageBox,
)

from utils import br_money
from views.role_utils import normalize_role as _normalize_role

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════
PERIOD_TODAY = "today"
PERIOD_7D = "7d"
PERIOD_MONTH = "month"


# ══════════════════════════════════════════════════════════════════════════════
# LOADING BAR
# ══════════════════════════════════════════════════════════════════════════════
class LoadingBar(QFrame):
    """Modern animated loading bar with gradient."""
    
    def __init__(self):
        super().__init__()
        self.setObjectName("loadingBar")
        self.setFixedHeight(3)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._bar = QProgressBar()
        self._bar.setObjectName("loadingBarInner")
        self._bar.setRange(0, 0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(3)
        lay.addWidget(self._bar)
        self.hide()

    def start(self):
        self.show()

    def stop(self):
        self.hide()


# ══════════════════════════════════════════════════════════════════════════════
# HEADER STRIP
# ══════════════════════════════════════════════════════════════════════════════
class HeaderStrip(QFrame):
    """Section header with icon and optional right text."""
    
    def __init__(self, text: str, icon: str = "", right_text: str = ""):
        super().__init__()
        self.setObjectName("headerStrip")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.setSpacing(6)
        
        if icon:
            ico = QLabel(icon)
            ico.setObjectName("headerStripIcon")
            lay.addWidget(ico)
            
        self.title = QLabel(text)
        self.title.setObjectName("headerStripText")
        self.right = QLabel(right_text)
        self.right.setObjectName("headerStripRight")
        
        lay.addWidget(self.title)
        lay.addStretch()
        lay.addWidget(self.right)


# ══════════════════════════════════════════════════════════════════════════════
# METRIC CARD (Status Chips)
# ══════════════════════════════════════════════════════════════════════════════
class MetricCard(QFrame):
    """Status metric card with hover effect."""
    
    clicked = Signal()

    def __init__(self, title: str, icon: str):
        super().__init__()
        self.setObjectName("metricCard")
        self.setProperty("severity", "neutral")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(70)
        
        # Shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(22, 78, 126, 30))
        self.setGraphicsEffect(shadow)
        
        lay = QHBoxLayout(self)
        lay.setContentsMargins(11, 9, 11, 9)
        lay.setSpacing(7)

        ico = QLabel(icon)
        ico.setObjectName("metricIcon")
        
        col = QVBoxLayout()
        col.setSpacing(2)
        
        self.value_lbl = QLabel("0")
        self.value_lbl.setObjectName("metricValue")
        
        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("metricTitle")

        self.trend_lbl = QLabel("")
        self.trend_lbl.setObjectName("metricTrend")
        self.trend_lbl.setVisible(False)

        col.addWidget(self.value_lbl)
        col.addWidget(self.title_lbl)
        col.addWidget(self.trend_lbl)

        lay.addWidget(ico)
        lay.addLayout(col)
        lay.addStretch()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def set_value(self, value: str):
        self.value_lbl.setText(str(value or "0"))

    def set_trend(self, text: str):
        if text:
            self.trend_lbl.setText(str(text))
            self.trend_lbl.setVisible(True)
        else:
            self.trend_lbl.setVisible(False)

    def set_severity(self, sev: str):
        self.setProperty("severity", sev)
        self.style().unpolish(self)
        self.style().polish(self)


# ══════════════════════════════════════════════════════════════════════════════
# LIVE METRIC CARD
# ══════════════════════════════════════════════════════════════════════════════
class LiveMetricCard(QFrame):
    """Live metric card with real-time data display."""
    
    def __init__(self, title: str, icon: str):
        super().__init__()
        self.setObjectName("liveMetricCard")
        self.setProperty("severity", "neutral")
        self.setMinimumHeight(78)
        
        # Shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(22, 78, 126, 30))
        self.setGraphicsEffect(shadow)
        
        lay = QVBoxLayout(self)
        lay.setContentsMargins(11, 9, 11, 9)
        lay.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(6)
        
        self.ico = QLabel(icon)
        self.ico.setObjectName("liveMetricIcon")
        
        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("liveMetricTitle")
        
        top.addWidget(self.ico)
        top.addWidget(self.title_lbl)
        top.addStretch()

        self.value_lbl = QLabel("0")
        self.value_lbl.setObjectName("liveMetricValue")
        
        self.sub_lbl = QLabel("—")
        self.sub_lbl.setObjectName("liveMetricSub")

        lay.addLayout(top)
        lay.addWidget(self.value_lbl)
        lay.addWidget(self.sub_lbl)

    def set_value(self, text: str, sub: Optional[str] = None):
        self.value_lbl.setText(str(text or "0"))
        if sub is not None:
            self.sub_lbl.setText(str(sub))

    def set_severity(self, sev: str):
        self.setProperty("severity", sev)
        self.style().unpolish(self)
        self.style().polish(self)


# ══════════════════════════════════════════════════════════════════════════════
# CARD BUTTON (Action Cards)
# ══════════════════════════════════════════════════════════════════════════════
class CardButton(QFrame):
    """Action card button with hover animation."""
    
    clicked = Signal()

    def __init__(self, title: str, desc: str, emoji: str):
        super().__init__()
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(76)
        self._hovered = False
        
        # Shadow effect
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(14)
        self.shadow.setOffset(0, 6)
        self.shadow.setColor(QColor(22, 78, 126, 28))
        self.setGraphicsEffect(self.shadow)
        
        lay = QVBoxLayout(self)
        lay.setContentsMargins(9, 8, 9, 8)
        lay.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(0)
        
        ico = QLabel(emoji)
        ico.setObjectName("cardEmoji")
        
        self.arrow = QLabel("→")
        self.arrow.setObjectName("cardArrow")
        
        top.addWidget(ico)
        top.addStretch()
        top.addWidget(self.arrow)

        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        
        self.desc = QLabel(desc)
        self.desc.setObjectName("cardDesc")
        self.desc.setWordWrap(True)

        lay.addLayout(top)
        lay.addWidget(self.title)
        lay.addWidget(self.desc)
        lay.addStretch()

    def enterEvent(self, event):
        super().enterEvent(event)
        if self.isEnabled():
            self._hovered = True
            self.shadow.setBlurRadius(24)
            self.shadow.setColor(QColor(22, 78, 126, 44))

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._hovered = False
        self.shadow.setBlurRadius(14)
        self.shadow.setColor(QColor(22, 78, 126, 28))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.clicked.emit()
        super().mousePressEvent(event)


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD VIEW - MAIN CLASS
# ══════════════════════════════════════════════════════════════════════════════
class DashboardView(QWidget):
    """
    Dashboard principal modernizado com design SaaS premium.
    Paleta azul/teal profissional e responsiva.
    """
    
    # ──────────────────────────────────────────────────────────────────────────
    # SIGNALS
    # ──────────────────────────────────────────────────────────────────────────
    logout_signal = Signal()
    ir_cadastro_signal = Signal()
    ir_novo_contrato_signal = Signal()
    ir_pagamento_signal = Signal()
    ir_listar_signal = Signal()
    ir_financeiro_signal = Signal()
    ir_cadastro_empresa_signal = Signal()
    ir_listar_empresas_signal = Signal()
    ir_relatorios_signal = Signal()
    ir_listar_filtrado_signal = Signal(str, str, str)
    busca_global_signal = Signal(str)
    export_clientes_signal = Signal()
    export_inadimplentes_signal = Signal()
    export_pagamentos_mes_signal = Signal()
    backup_now_signal = Signal()
    refresh_signal = Signal()
    period_changed_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self.nivel_usuario: Optional[str] = None
        self._is_recepcao = False
        self._is_loading = False
        self._last_updated_at: Optional[datetime] = None
        self._density_mode = "normal"

        # Timers
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(60000)
        self._refresh_timer.timeout.connect(self.refresh_signal.emit)
        
        self._error_clear_timer = QTimer(self)
        self._error_clear_timer.setSingleShot(True)
        self._error_clear_timer.timeout.connect(self._hide_error)

        self._setup_ui()
        self.apply_styles()
        self._tick_clock()
        self._clock_timer.start()
        self._refresh_timer.start()

    # ──────────────────────────────────────────────────────────────────────────
    # UI SETUP
    # ──────────────────────────────────────────────────────────────────────────
    def _setup_ui(self):
        """Build complete dashboard UI."""
        self.setObjectName("Dashboard")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Loading bar
        self.loading_bar = LoadingBar()
        root.addWidget(self.loading_bar)

        # Top bar
        root.addWidget(self._build_topbar())

        # Scroll area
        scroll = QScrollArea()
        scroll.setObjectName("dashScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        content = QWidget()
        scroll.setWidget(content)
        
        cl = QVBoxLayout(content)
        cl.setContentsMargins(14, 10, 14, 14)
        cl.setSpacing(10)
        self._content_layout = cl

        # Error banner
        self.error_banner = QLabel("")
        self.error_banner.setObjectName("dashError")
        self.error_banner.setWordWrap(True)
        self.error_banner.setVisible(False)
        cl.addWidget(self.error_banner)

        # Quick search
        cl.addWidget(self._build_quick_search())

        # Status metrics
        cl.addWidget(HeaderStrip("📊 Status dos contratos"))
        cl.addLayout(self._build_status_metrics())

        # Live metrics
        cl.addWidget(HeaderStrip("📈 Indicadores do período"))
        cl.addLayout(self._build_live_metrics())

        # Divider
        line = QFrame()
        line.setObjectName("softLine")
        line.setFixedHeight(1)
        cl.addWidget(line)

        # Main content (sidebar + actions)
        cl.addLayout(self._build_main_content())

        cl.addStretch()
        root.addWidget(scroll)

    def _build_topbar(self) -> QFrame:
        """Build top navigation bar."""
        topbar = QFrame()
        topbar.setObjectName("topbar")
        top = QHBoxLayout(topbar)
        top.setContentsMargins(14, 8, 14, 8)
        top.setSpacing(8)
        self._topbar_layout = top

        # Title section
        col = QVBoxLayout()
        col.setSpacing(0)
        
        self.title_lbl = QLabel("📊 Dashboard")
        self.title_lbl.setObjectName("dashTitle")
        
        self.subtitle_lbl = QLabel("Painel principal")
        self.subtitle_lbl.setObjectName("dashSubtitle")
        
        col.addWidget(self.title_lbl)
        col.addWidget(self.subtitle_lbl)
        
        top.addLayout(col)
        top.addStretch()

        # Updated label
        self.lbl_updated = QLabel("Atualizado: —")
        self.lbl_updated.setObjectName("updatedLabel")
        top.addWidget(self.lbl_updated)

        # Period selector
        self.period_combo = QComboBox()
        self.period_combo.setObjectName("periodCombo")
        self.period_combo.addItem("📅 Mês atual", PERIOD_MONTH)
        self.period_combo.addItem("📅 Últimos 7 dias", PERIOD_7D)
        self.period_combo.addItem("📅 Hoje", PERIOD_TODAY)
        self.period_combo.currentIndexChanged.connect(self._on_period_changed)
        top.addWidget(self.period_combo)

        # Refresh button
        self.btn_refresh = QPushButton("🔄 Atualizar")
        self.btn_refresh.setObjectName("btnRefresh")
        self.btn_refresh.clicked.connect(self.refresh_signal.emit)
        top.addWidget(self.btn_refresh)

        # Logout button
        self.btn_sair = QPushButton("🚪 Sair")
        self.btn_sair.setObjectName("btnLogout")
        self.btn_sair.clicked.connect(self._confirm_logout)
        top.addWidget(self.btn_sair)

        return topbar

    def _build_quick_search(self) -> QFrame:
        """Build quick search section."""
        frame = QFrame()
        frame.setObjectName("searchSection")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)

        hdr = HeaderStrip("🔍 Busca rápida", right_text="F5 · Atualizar")
        lay.addWidget(hdr)

        search = QHBoxLayout()
        search.setSpacing(5)
        
        self.search_input = QLineEdit()
        self.search_input.setObjectName("dashSearch")
        self.search_input.setPlaceholderText("Busca global — MAT, cliente, empresa, CPF ou CNPJ")
        self.search_input.returnPressed.connect(self._do_quick_search)
        
        self.btn_buscar = QPushButton("Buscar")
        self.btn_buscar.setObjectName("btnSearch")
        self.btn_buscar.clicked.connect(self._do_quick_search)
        
        self.btn_atrasados = QPushButton("⏰ Ver atrasados")
        self.btn_atrasados.setObjectName("btnFilterChip")
        self.btn_atrasados.clicked.connect(lambda: self.ir_listar_filtrado_signal.emit("", "", "atrasado"))
        
        self.btn_ativos = QPushButton("✅ Ver ativos")
        self.btn_ativos.setObjectName("btnFilterChip")
        self.btn_ativos.clicked.connect(lambda: self.ir_listar_filtrado_signal.emit("", "ativo", ""))
        
        search.addWidget(self.search_input, 1)
        search.addWidget(self.btn_buscar)
        search.addWidget(self.btn_atrasados)
        search.addWidget(self.btn_ativos)
        
        lay.addLayout(search)
        return frame

    def _build_status_metrics(self) -> QHBoxLayout:
        """Build status metrics row."""
        row = QHBoxLayout()
        row.setSpacing(8)
        self._status_metrics_layout = row
        
        self.metric_ativos = MetricCard("Clientes ativos", "🟢")
        self.metric_atrasados = MetricCard("Pagamentos atrasados", "🟠")
        self.metric_inativos = MetricCard("Inativos", "⚪")
        
        self.metric_ativos.clicked.connect(lambda: self.ir_listar_filtrado_signal.emit("", "ativo", ""))
        self.metric_atrasados.clicked.connect(lambda: self.ir_listar_filtrado_signal.emit("", "", "atrasado"))
        self.metric_inativos.clicked.connect(lambda: self.ir_listar_filtrado_signal.emit("", "inativo", ""))
        
        row.addWidget(self.metric_ativos)
        row.addWidget(self.metric_atrasados)
        row.addWidget(self.metric_inativos)
        
        return row

    def _build_live_metrics(self) -> QGridLayout:
        """Build live metrics grid."""
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self._live_metrics_layout = grid
        
        self.live_total = LiveMetricCard("Total de clientes", "👥")
        self.live_empresas = LiveMetricCard("Contratos de empresa", "🏢")
        self.live_qtd_pag = LiveMetricCard("Pagamentos do período", "🧾")
        self.live_atraso = LiveMetricCard("Atraso estimado", "⚠️")
        
        grid.addWidget(self.live_total, 0, 0)
        grid.addWidget(self.live_empresas, 0, 1)
        grid.addWidget(self.live_qtd_pag, 1, 0)
        grid.addWidget(self.live_atraso, 1, 1)
        
        return grid

    def _build_main_content(self) -> QHBoxLayout:
        """Build main content layout (sidebar + action cards)."""
        body = QHBoxLayout()
        body.setSpacing(10)
        self._main_content_layout = body

        # Left sidebar
        left = self._build_sidebar()
        body.addWidget(left, 0)

        # Right content (action cards)
        right = self._build_action_cards()
        body.addWidget(right, 1)

        return body

    def _build_sidebar(self) -> QFrame:
        """Build left sidebar with exports and summary."""
        left = QFrame()
        left.setObjectName("leftPanel")
        left.setMinimumWidth(342)
        left.setMaximumWidth(410)
        self._left_panel = left
        
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 12, 12)
        ll.setSpacing(8)

        # Brand section
        brand = QLabel("💼 Pronto Clínica")
        brand.setObjectName("brand")
        
        self.welcome_lbl = QLabel("Bem-vindo")
        self.welcome_lbl.setObjectName("welcome")
        
        self.status_lbl = QLabel("—")
        self.status_lbl.setObjectName("statusLine")
        
        ll.addWidget(brand)
        ll.addWidget(self.welcome_lbl)
        ll.addWidget(self.status_lbl)

        # Quick hub (left highlighted card)
        hub_card = QFrame()
        hub_card.setObjectName("hubCard")
        hub = QVBoxLayout(hub_card)
        hub.setContentsMargins(11, 11, 11, 11)
        hub.setSpacing(6)

        self.lbl_hub_title = QLabel("Avisos de contas a pagar")
        self.lbl_hub_title.setObjectName("hubTitle")

        self.hub_alert_card = QFrame()
        self.hub_alert_card.setObjectName("hubAlertCard")
        self.hub_alert_card.setProperty("tone", "warn")
        hub_alert = QVBoxLayout(self.hub_alert_card)
        hub_alert.setContentsMargins(9, 8, 9, 8)
        hub_alert.setSpacing(3)
        self.lbl_hub_alert_title = QLabel("⚠ Contas a pagar")
        self.lbl_hub_alert_title.setObjectName("hubAlertTitle")
        self.lbl_hub_alert_body = QLabel("Hoje: — · Próximos 7 dias: —")
        self.lbl_hub_alert_body.setObjectName("hubAlertBody")
        self.lbl_hub_alert_body.setWordWrap(True)
        hub_alert.addWidget(self.lbl_hub_alert_title)
        hub_alert.addWidget(self.lbl_hub_alert_body)

        hub.addWidget(self.lbl_hub_title)
        hub.addWidget(self.hub_alert_card)
        ll.addWidget(hub_card)

        # Operational pending box
        box_pending = QFrame()
        box_pending.setObjectName("quickBox")
        pl = QVBoxLayout(box_pending)
        pl.setContentsMargins(9, 9, 9, 9)
        pl.setSpacing(3)

        pt = QLabel("📌 Pendências operacionais")
        pt.setObjectName("quickTitle")
        pl.addWidget(pt)

        self._pending_labels: list[QLabel] = []
        for _ in range(4):
            lbl = QLabel("—")
            lbl.setObjectName("quickLineMuted")
            lbl.setWordWrap(True)
            self._pending_labels.append(lbl)
            pl.addWidget(lbl)
        ll.addWidget(box_pending)

        # Exports box
        box_exp = QFrame()
        box_exp.setObjectName("quickBox")
        ex = QVBoxLayout(box_exp)
        ex.setContentsMargins(9, 9, 9, 9)
        ex.setSpacing(5)
        
        t = QLabel("📤 Exportações rápidas")
        t.setObjectName("quickTitle")
        ex.addWidget(t)
        
        self.btn_exp_clientes = QPushButton("📄 Exportar clientes")
        self.btn_exp_clientes.setObjectName("btnQuick")
        self.btn_exp_clientes.clicked.connect(self.export_clientes_signal.emit)
        
        self.btn_exp_inad = QPushButton("⚠️ Exportar inadimplentes")
        self.btn_exp_inad.setObjectName("btnQuick")
        self.btn_exp_inad.clicked.connect(self.export_inadimplentes_signal.emit)
        
        self.btn_exp_pagmes = QPushButton("🧾 Exportar pagamentos")
        self.btn_exp_pagmes.setObjectName("btnQuick")
        self.btn_exp_pagmes.clicked.connect(self.export_pagamentos_mes_signal.emit)

        self.btn_backup_now = QPushButton("💾 Backup agora")
        self.btn_backup_now.setObjectName("btnQuick")
        self.btn_backup_now.clicked.connect(self.backup_now_signal.emit)

        ex.addWidget(self.btn_exp_clientes)
        ex.addWidget(self.btn_exp_inad)
        ex.addWidget(self.btn_exp_pagmes)
        ex.addWidget(self.btn_backup_now)
        ll.addWidget(box_exp)

        # Summary box
        box_resume = QFrame()
        box_resume.setObjectName("quickBox")
        rs = QVBoxLayout(box_resume)
        rs.setContentsMargins(9, 9, 9, 9)
        rs.setSpacing(3)
        
        qt = QLabel("📊 Resumo do período")
        qt.setObjectName("quickTitle")
        rs.addWidget(qt)
        
        self.lbl_pag_hoje = QLabel("Pagamentos no período: —")
        self.lbl_pag_hoje.setObjectName("quickLine")
        
        self.lbl_novos_mes = QLabel("Novos no período: —")
        self.lbl_novos_mes.setObjectName("quickLine")
        
        self.lbl_ult_backup = QLabel("Último backup: —")
        self.lbl_ult_backup.setObjectName("quickLine")
        
        self.lbl_ult_export = QLabel("Última exportação: —")
        self.lbl_ult_export.setObjectName("quickLine")
        
        rs.addWidget(self.lbl_pag_hoje)
        rs.addWidget(self.lbl_novos_mes)
        rs.addWidget(self.lbl_ult_backup)
        rs.addWidget(self.lbl_ult_export)

        # Sidebar section separator
        sep1 = QFrame()
        sep1.setObjectName("sidebarSep")
        sep1.setFixedHeight(1)
        rs.addWidget(sep1)

        # Jobs status
        jt = QLabel("⚙️ Jobs do sistema")
        jt.setObjectName("quickTitle")
        rs.addWidget(jt)
        
        self.lbl_job_backup = QLabel("Job backup: —")
        self.lbl_job_backup.setObjectName("quickLine")
        
        self.lbl_job_resumo = QLabel("Resumo operacional: —")
        self.lbl_job_resumo.setObjectName("quickLine")
        
        self.lbl_job_lembrete = QLabel("Lembrete diário: —")
        self.lbl_job_lembrete.setObjectName("quickLine")
        
        self.lbl_job_export = QLabel("Autoexport: —")
        self.lbl_job_export.setObjectName("quickLine")
        
        rs.addWidget(self.lbl_job_backup)
        rs.addWidget(self.lbl_job_resumo)
        rs.addWidget(self.lbl_job_lembrete)
        rs.addWidget(self.lbl_job_export)

        ll.addWidget(box_resume)
        ll.addStretch()

        return left

    def _build_action_cards(self) -> QFrame:
        """Build action cards grid."""
        right = QFrame()
        right.setObjectName("gridWrap")
        
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        
        rl.addWidget(HeaderStrip("⚡ Ações rápidas", right_text="Cadastros · Financeiro · Operação"))

        action_hint = QLabel("Ordem sugerida para rotina diária: cadastro, pagamento, acompanhamento financeiro e gestão de empresas.")
        action_hint.setObjectName("actionHint")
        action_hint.setWordWrap(True)
        rl.addWidget(action_hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        
        self.btn_novo_contrato = CardButton("＋ Novo Cliente", "Iniciar cadastro completo e contrato em poucos passos.", "🧭")
        self.btn_pagamento = CardButton("Registrar Pagamento", "Lançar pagamento confirmado e atualizar situação do cliente.", "💳")
        self.btn_financeiro = CardButton("Visão Financeira", "Abrir painel com fluxo de caixa, métricas e exportações.", "💼")
        self.btn_listar = CardButton("Clientes e Contratos", "Consultar carteira de clientes com filtros e ações rápidas.", "📋")
        self.btn_empresa_cadastrar = CardButton("＋ Nova Empresa Parceira", "Cadastrar empresa conveniada com dados financeiros.", "🏢")
        self.btn_empresa_listar = CardButton("Empresas Parceiras", "Listar, editar e acompanhar empresas cadastradas.", "🏛️")
        self.btn_relatorios = CardButton("Relatórios do Sistema", "Abrir central de relatórios e arquivos gerados.", "🗂️")

        # Hierarquia visual premium por contexto de ação
        self.btn_novo_contrato.setProperty("tone", "core")
        self.btn_novo_contrato.setProperty("featured", "true")
        self.btn_pagamento.setProperty("tone", "cash")
        self.btn_pagamento.setProperty("featured", "true")
        self.btn_listar.setProperty("tone", "ops")
        self.btn_financeiro.setProperty("tone", "finance")
        self.btn_empresa_cadastrar.setProperty("tone", "biz")
        self.btn_empresa_listar.setProperty("tone", "ops")
        self.btn_relatorios.setProperty("tone", "ops")
        
        self.btn_novo_contrato.clicked.connect(self.ir_novo_contrato_signal.emit)
        self.btn_pagamento.clicked.connect(self.ir_pagamento_signal.emit)
        self.btn_financeiro.clicked.connect(self.ir_financeiro_signal.emit)
        self.btn_listar.clicked.connect(self.ir_listar_signal.emit)
        self.btn_empresa_cadastrar.clicked.connect(self.ir_cadastro_empresa_signal.emit)
        self.btn_empresa_listar.clicked.connect(self.ir_listar_empresas_signal.emit)
        self.btn_relatorios.clicked.connect(self.ir_relatorios_signal.emit)

        grid.addWidget(self.btn_novo_contrato, 0, 0)
        grid.addWidget(self.btn_empresa_cadastrar, 0, 1)
        grid.addWidget(self.btn_listar, 1, 0)
        grid.addWidget(self.btn_empresa_listar, 1, 1)
        grid.addWidget(self.btn_pagamento, 2, 0)
        grid.addWidget(self.btn_financeiro, 2, 1)
        grid.addWidget(self.btn_relatorios, 3, 0, 1, 2)
        
        rl.addLayout(grid)

        return right

    # ──────────────────────────────────────────────────────────────────────────
    # STYLESHEET
    # ──────────────────────────────────────────────────────────────────────────
    def apply_styles(self):
        """Apply QSS stylesheet from file."""
        style_path = Path(__file__).parent / "styles" / "dashboard.qss"
        if style_path.exists():
            stylesheet = ""
            try:
                stylesheet = style_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                try:
                    stylesheet = style_path.read_text(encoding="utf-8-sig")
                except Exception:
                    stylesheet = style_path.read_text(encoding="latin-1")
            except Exception:
                stylesheet = ""
            if stylesheet:
                self.setStyleSheet(stylesheet)
        else:
            # Fallback if file not found
            pass

    def set_density(self, density: str):
        mode = str(density or "").strip().lower()
        if mode not in {"normal", "compact"}:
            mode = "normal"
        self._density_mode = mode
        compact = mode == "compact"

        try:
            if hasattr(self, "_topbar_layout"):
                if compact:
                    self._topbar_layout.setContentsMargins(10, 6, 10, 6)
                    self._topbar_layout.setSpacing(6)
                else:
                    self._topbar_layout.setContentsMargins(14, 8, 14, 8)
                    self._topbar_layout.setSpacing(8)
            if hasattr(self, "_content_layout"):
                if compact:
                    self._content_layout.setContentsMargins(10, 8, 10, 10)
                    self._content_layout.setSpacing(8)
                else:
                    self._content_layout.setContentsMargins(14, 10, 14, 14)
                    self._content_layout.setSpacing(10)
            if hasattr(self, "_main_content_layout"):
                self._main_content_layout.setSpacing(8 if compact else 10)
            if hasattr(self, "_status_metrics_layout"):
                self._status_metrics_layout.setSpacing(6 if compact else 8)
            if hasattr(self, "_live_metrics_layout"):
                self._live_metrics_layout.setHorizontalSpacing(6 if compact else 8)
                self._live_metrics_layout.setVerticalSpacing(6 if compact else 8)
            if hasattr(self, "_left_panel"):
                if compact:
                    self._left_panel.setMinimumWidth(320)
                    self._left_panel.setMaximumWidth(380)
                else:
                    self._left_panel.setMinimumWidth(342)
                    self._left_panel.setMaximumWidth(410)
        except Exception:
            return

        metric_h = 62 if compact else 70
        live_h = 68 if compact else 78
        action_h = 68 if compact else 76
        for card in (
            getattr(self, "metric_ativos", None),
            getattr(self, "metric_atrasados", None),
            getattr(self, "metric_inativos", None),
        ):
            if card is not None:
                card.setMinimumHeight(metric_h)
        for card in (
            getattr(self, "live_total", None),
            getattr(self, "live_empresas", None),
            getattr(self, "live_qtd_pag", None),
            getattr(self, "live_atraso", None),
        ):
            if card is not None:
                card.setMinimumHeight(live_h)
        for card in (
            getattr(self, "btn_novo_contrato", None),
            getattr(self, "btn_pagamento", None),
            getattr(self, "btn_listar", None),
            getattr(self, "btn_financeiro", None),
            getattr(self, "btn_empresa_cadastrar", None),
            getattr(self, "btn_empresa_listar", None),
            getattr(self, "btn_relatorios", None),
        ):
            if card is not None:
                card.setMinimumHeight(action_h)

    # ──────────────────────────────────────────────────────────────────────────
    # EVENT HANDLERS
    # ──────────────────────────────────────────────────────────────────────────
    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _clear_layout(layout):
        """Remove and delete all widgets from a layout."""
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _on_period_changed(self):
        p = self.period_combo.currentData()
        if p not in (PERIOD_MONTH, PERIOD_7D, PERIOD_TODAY):
            p = PERIOD_MONTH
        self.period_changed_signal.emit(p)
        self.refresh_signal.emit()

    def current_period(self) -> str:
        p = self.period_combo.currentData()
        if p not in (PERIOD_MONTH, PERIOD_7D, PERIOD_TODAY):
            return PERIOD_MONTH
        return str(p)

    def set_period(self, period_key: str, *, emit_signal: bool = False):
        target = str(period_key or "").strip().lower()
        if target not in (PERIOD_MONTH, PERIOD_7D, PERIOD_TODAY):
            target = PERIOD_MONTH
        idx = 0
        for i in range(self.period_combo.count()):
            if str(self.period_combo.itemData(i) or "") == target:
                idx = i
                break
        self.period_combo.blockSignals(True)
        self.period_combo.setCurrentIndex(idx)
        self.period_combo.blockSignals(False)
        if emit_signal:
            self.period_changed_signal.emit(target)

    def _do_quick_search(self):
        query = (self.search_input.text() or "").strip()
        self.busca_global_signal.emit(query)
        if query:
            self.search_input.clear()

    def _tick_clock(self):
        now = datetime.now()
        nivel = str(self.nivel_usuario or "-").upper()
        self.status_lbl.setText(f"👤 {nivel}  |  🕐 {now.strftime('%d/%m/%Y %H:%M:%S')}")
        
        if self._last_updated_at and not self._is_loading:
            diff = int((now - self._last_updated_at).total_seconds())
            remaining = max(0, 60 - diff)
            countdown = f" · próx. em {remaining}s" if remaining > 0 else ""
            if diff < 60:
                self.lbl_updated.setText(f"Atualizado há {diff}s{countdown}")
            else:
                self.lbl_updated.setText(f"Atualizado há {diff // 60}min{countdown}")

    def _hide_error(self):
        self.error_banner.setVisible(False)
        self.error_banner.setText("")

    def _confirm_logout(self):
        reply = QMessageBox.question(
            self,
            "Confirmar saída",
            "Deseja realmente sair do sistema?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.logout_signal.emit()

    def _mark_updated(self):
        self._last_updated_at = datetime.now()
        self.lbl_updated.setText("✓ Atualizado agora")

    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────────────────
    def _apply_role_restrictions(self):
        """Apply UI restrictions based on the current user role."""
        restricted = self._is_recepcao
        role = _normalize_role(self.nivel_usuario)

        for w in (self.btn_novo_contrato, self.btn_pagamento, self.btn_empresa_cadastrar):
            w.setVisible(not restricted)
            w.setEnabled(not restricted)

        for w in (self.btn_exp_clientes, self.btn_exp_inad, self.btn_exp_pagmes):
            w.setVisible(not restricted)
            w.setEnabled(not restricted)

        can_backup = role == "admin"
        self.btn_backup_now.setVisible(can_backup)
        self.btn_backup_now.setEnabled(can_backup and not self._is_loading)

        self.btn_financeiro.setVisible(not restricted)
        self.btn_financeiro.setEnabled(role not in {"funcionario", "recepcao"})

        if restricted:
            self.subtitle_lbl.setText("Painel principal | 🔒 Acesso recepção")
            self.lbl_ult_export.setText("Última exportação: restrito")
        else:
            self.subtitle_lbl.setText(f"Painel principal | Nível: {self.nivel_usuario or '-'}")

    def set_nivel_usuario(self, nivel: str):
        """Set user level and apply permissions."""
        self.nivel_usuario = str(nivel or "")
        role = _normalize_role(nivel)
        self._is_recepcao = role == "recepcao"
        role_label = str(self.nivel_usuario or "usuário").strip().upper()
        self.welcome_lbl.setText(f"Bem-vindo, {role_label}")
        self._apply_role_restrictions()

    def set_refresh_state(self, loading: bool, message: Optional[str] = None):
        """Set loading state for refresh operation."""
        self._is_loading = bool(loading)
        
        if loading:
            self.loading_bar.start()
        else:
            self.loading_bar.stop()
            
        for w in (self.btn_refresh, self.period_combo, self.search_input,
                  self.btn_buscar, self.btn_atrasados, self.btn_ativos):
            w.setEnabled(not self._is_loading)
        if hasattr(self, "btn_backup_now"):
            self.btn_backup_now.setEnabled((not self._is_loading) and self.btn_backup_now.isVisible())
            
        self.btn_refresh.setText("🔄 Atualizando..." if self._is_loading else "🔄 Atualizar")
        
        if message:
            self.lbl_updated.setText(str(message))

    def show_error(self, text: str, timeout_ms: int = 5500):
        """Show error banner with auto-dismiss."""
        msg = str(text or "").strip()
        if not msg:
            self._hide_error()
            return
            
        self.error_banner.setText(f"⚠️ {msg}")
        self.error_banner.setVisible(True)
        self._error_clear_timer.start(max(1500, int(timeout_ms)))

    def add_alert(self, severity: str, text: str) -> int:
        """Compat shim after dashboard alert panel removal."""
        _ = severity
        _ = text
        return 0

    def clear_alerts(self):
        """Compat shim after dashboard alert panel removal."""
        return

    def set_status_counts(self, ativos: int, atrasados: int, inativos: int):
        """Update status count metrics."""
        a = int(ativos or 0)
        at = int(atrasados or 0)
        i = int(inativos or 0)
        
        self.metric_ativos.set_value(str(a))
        self.metric_atrasados.set_value(str(at))
        self.metric_inativos.set_value(str(i))
        
        self.metric_ativos.set_severity("good" if a > 0 else "neutral")
        self.metric_atrasados.set_severity("danger" if at > 0 else "neutral")
        self.metric_inativos.set_severity("warn" if i > 0 else "neutral")

        self.metric_ativos.set_trend("" if a > 0 else "Nenhum cliente ativo")
        self.metric_atrasados.set_trend("" if at > 0 else "Sem atrasos")
        self.metric_inativos.set_trend("" if i > 0 else "")

        self._mark_updated()

    def set_live_metrics(self, m: dict):
        """Update live metrics cards."""
        data = dict(m or {})
        
        total = int(data.get("total_clientes", 0) or 0)
        empresas = int(data.get("contratos_empresa_total", 0) or 0)
        qtd = int(data.get("pagamentos_mes", 0) or 0)
        atraso = float(data.get("atraso_estimado", 0.0) or 0.0)
        desc = str(data.get("periodo_desc", "") or "Período selecionado")
        contratos_mes = int(data.get("contratos_mes", 0) or 0)
        contratos_prev = int(data.get("contratos_prev", 0) or 0)
        empresa_ativos = int(data.get("contratos_empresa_ativos", 0) or 0)
        empresa_atrasados = int(data.get("contratos_empresa_atrasados", 0) or 0)
        cobertura_pct = float(data.get("cobertura_pagamentos_pct", 0.0) or 0.0)
        cobertura_meta = float(data.get("meta_cobertura_pagamentos_pct", 85.0) or 85.0)
        atraso_ratio_pct = float(data.get("atraso_ratio_pct", 0.0) or 0.0)
        atraso_meta_pct = float(data.get("meta_atraso_pct", 10.0) or 10.0)

        contratos_delta = contratos_mes - contratos_prev
        delta_prefix = "+" if contratos_delta > 0 else ""
        self.live_total.set_value(str(total), f"{desc} · novos: {contratos_mes} ({delta_prefix}{contratos_delta})")
        self.live_empresas.set_value(str(empresas), f"Ativas: {empresa_ativos} · em risco: {empresa_atrasados}")
        self.live_qtd_pag.set_value(
            str(qtd),
            f"Cobertura: {cobertura_pct:.1f}% (meta {cobertura_meta:.0f}%)",
        )
        self.live_atraso.set_value(
            br_money(atraso),
            f"Risco da carteira: {atraso_ratio_pct:.1f}% (meta <= {atraso_meta_pct:.0f}%)",
        )

        self.live_total.set_severity("good" if total > 0 else "neutral")
        self.live_empresas.set_severity("good" if empresas > 0 else "neutral")
        self.live_qtd_pag.set_severity("good" if cobertura_pct >= cobertura_meta else "warn")
        self.live_atraso.set_severity("danger" if atraso_ratio_pct > atraso_meta_pct else ("warn" if atraso > 0 else "neutral"))

        self._mark_updated()

    def set_resumo_do_dia(self, resumo: dict):
        """Update daily summary section."""
        data = dict(resumo or {})
        
        pag_label = str(data.get("pagamentos_label", "Pagamentos no período") or "Pagamentos no período")
        self.lbl_pag_hoje.setText(f"{pag_label}: {data.get('pagamentos_periodo', '—')}")
        self.lbl_novos_mes.setText(f"Novos no período: {data.get('novos_mes', '—')}")
        self.lbl_ult_backup.setText(f"Último backup: {data.get('ultimo_backup', '—')}")

        contas_hoje = int(data.get("contas_pagar_hoje", 0) or 0)
        contas_semana = int(data.get("contas_pagar_semana", 0) or 0)
        contas_vencidas = int(data.get("contas_pagar_vencidas", 0) or 0)

        self.lbl_hub_title.setText("Avisos de contas a pagar")

        if contas_vencidas > 0:
            tone = "danger"
            self.lbl_hub_alert_title.setText("⛔ Contas pendentes críticas")
        elif contas_hoje > 0 or contas_semana > 0:
            tone = "warn"
            self.lbl_hub_alert_title.setText("⚠ Contas a pagar")
        else:
            tone = "ok"
            self.lbl_hub_alert_title.setText("✅ Contas sob controle")
        self.hub_alert_card.setProperty("tone", tone)
        self.hub_alert_card.style().unpolish(self.hub_alert_card)
        self.hub_alert_card.style().polish(self.hub_alert_card)
        self.lbl_hub_alert_body.setText(
            f"Hoje: {contas_hoje} · Próximos 7 dias: {contas_semana} · Vencidas: {contas_vencidas}"
        )

        self.set_pendencias_operacionais(data.get("pendencias_operacionais", []))

        if not self._is_recepcao:
            self.lbl_ult_export.setText(f"Última exportação: {data.get('ultima_export', '—')}")

        self._apply_role_restrictions()
        self._mark_updated()

    def set_export_history(self, entries: list[dict]):
        """Compat shim after export-history section removal."""
        _ = entries
        return

    def set_recent_activities(self, entries: list[dict]):
        """Compat shim after recent-activities section removal."""
        _ = entries
        return

    def set_pendencias_operacionais(self, entries: list[str]):
        """Render operational pending list in sidebar."""
        rows = [str(x or "").strip() for x in list(entries or []) if str(x or "").strip()]
        if not rows:
            rows = ["Sem pendências críticas no momento."]
        rows = rows[: len(self._pending_labels)]

        for idx, lbl in enumerate(self._pending_labels):
            if idx < len(rows):
                txt = rows[idx]
                lbl.setText(f"• {txt}")
                low = txt.lower()
                if any(k in low for k in ("vencid", "atras", "pendent", "risco")):
                    lbl.setObjectName("quickLineWarn")
                else:
                    lbl.setObjectName("quickLine")
            else:
                lbl.setText("—")
                lbl.setObjectName("quickLineMuted")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

    def set_jobs_status(self, payload: dict):
        """Update system jobs status."""
        data = dict(payload or {})
        specs = [
            ("backup", self.lbl_job_backup, "Job backup"),
            ("resumo", self.lbl_job_resumo, "Resumo operacional"),
            ("lembrete", self.lbl_job_lembrete, "Lembrete diário"),
            ("autoexport", self.lbl_job_export, "Autoexport"),
        ]
        
        for key, lbl, title in specs:
            raw = data.get(key, {})
            
            if isinstance(raw, str):
                text = raw.strip() or "—"
                level = "muted"
            else:
                raw_map = dict(raw or {})
                text = str(raw_map.get("text", "—") or "—").strip()
                level = str(raw_map.get("level", "muted") or "muted").lower()
                
            lbl.setText(f"{title}: {text}")
            
            if level in {"ok", "good", "success"}:
                lbl.setObjectName("quickLine")
            elif level in {"warn", "warning", "late", "pending", "error", "failed"}:
                lbl.setObjectName("quickLineWarn")
            else:
                lbl.setObjectName("quickLineMuted")
                
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
            
        self._mark_updated()
