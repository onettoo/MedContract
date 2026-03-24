# -*- coding: utf-8 -*-
from __future__ import annotations

import unicodedata
import csv
import io
import os
from datetime import datetime, timedelta, date
from pathlib import Path
from calendar import monthrange

from PySide6.QtCore import (
    Qt, Signal, QTimer, Property, QPropertyAnimation, QEasingCurve,
    QObject, QRunnable, QThreadPool, Slot, QRectF, QPointF, QDate, QUrl, QRect,
)
from PySide6.QtGui import (
    QColor, QPainter, QPen, QLinearGradient, QBrush, QFont, QFontDatabase,
    QKeySequence, QShortcut, QPainterPath, QDesktopServices, QTextDocument,
)
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QDialog, QTextEdit, QFileDialog, QMessageBox,
    QScrollArea, QCheckBox, QSpinBox, QProgressBar, QDateEdit, QDoubleSpinBox, QTabWidget,
)
from PySide6.QtPrintSupport import QPrinter

import database.db as db

# ── Paleta idêntica ao login / dashboard ──────────────────────────────────────
_ACCENT       = "#1a6b7c"
_ACCENT_HOVER = "#155e6d"
_INK          = "#0c0f12"
_INK2         = "#4a5260"
_INK3         = "#9199a6"
_LINE         = "#e8eaed"
_WHITE        = "#ffffff"
_BG           = "#f9fafb"
_GOOD         = "#1a7a47"
_WARN         = "#d97706"
_DANGER       = "#c0392b"
_CARD_BG      = "#ffffff"


# ── Helpers de mês ────────────────────────────────────────────────────────────
_NUM_TO_PT = {
    "01": "JAN", "02": "FEV", "03": "MAR", "04": "ABR",
    "05": "MAI", "06": "JUN", "07": "JUL", "08": "AGO",
    "09": "SET", "10": "OUT", "11": "NOV", "12": "DEZ",
}


def _iso_to_mes_br(yyyy_mm: str) -> str:
    s = (yyyy_mm or "").strip()
    if len(s) == 7 and s[4] == "-":
        y, m = s.split("-")
        return f"{_NUM_TO_PT.get(m, m)}/{y}"
    return s or "—"


def _date_to_br(iso_date: str) -> str:
    s = (iso_date or "").strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        y, m, d = s.split("-")
        return f"{d}/{m}/{y}"
    return s or "—"


def br_money(value) -> str:
    """Formata valor monetário em padrão BRL."""
    try:
        num = float(value or 0.0)
    except Exception:
        return "R$ 0,00"
    s = f"{num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def _parse_any_money(value) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return 0.0
    s = s.replace("R$", "").replace("r$", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def _month_shift(yyyy_mm: str, delta: int) -> str:
    base = str(yyyy_mm or "").strip()
    if len(base) != 7 or base[4] != "-":
        base = datetime.now().strftime("%Y-%m")
    year = int(base[:4])
    month = int(base[5:7])
    month += int(delta)
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    return f"{year:04d}-{month:02d}"


def _months_range(end_month: str, count: int) -> list[str]:
    total = max(1, int(count or 1))
    return [_month_shift(end_month, -(total - 1 - i)) for i in range(total)]


def _status_text(value: str) -> str:
    s = (value or "").strip().replace("_", " ")
    return s.upper() if s else "—"


def _parse_money_input(text: str) -> float | None:
    s = (text or "").strip()
    if not s:
        return None
    s = s.replace("R$", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def _only_digits(text: str) -> str:
    return "".join(ch for ch in (text or "") if ch.isdigit())


def _norm_text(text: str) -> str:
    base = str(text or "").strip().lower()
    if not base:
        return ""
    nfd = unicodedata.normalize("NFD", base)
    return "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")


def _load_fonts() -> str:
    """Carrega DM Sans e retorna o nome da família."""
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


# ══════════════════════════════════════════════════════════════════════════════
# NOVO: Mini Gráfico de Pizza para Distribuição
# ══════════════════════════════════════════════════════════════════════════════
class MiniPieChart(QWidget):
    """Gráfico de pizza compacto para status/distribuição"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(80, 80)
        self._segments = []  # [(valor, cor, label)]
        self._total = 0.0
        
    def set_data(self, segments: list[tuple[float, str, str]]):
        """segments = [(valor, cor_hex, label)]"""
        self._segments = list(segments)
        self._total = sum(v for v, _, _ in self._segments)
        self.update()
    
    def paintEvent(self, event):
        if not self._segments or self._total <= 0:
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        
        rect = QRectF(10, 10, 60, 60)
        start_angle = 90 * 16  # Qt usa 1/16 de grau
        
        for valor, cor, _ in self._segments:
            span = int((valor / self._total) * 360 * 16)
            painter.setBrush(QColor(cor))
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.drawPie(rect, start_angle, -span)
            start_angle -= span
        
        # Círculo central branco (donut)
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(Qt.NoPen)
        inner_rect = QRectF(25, 25, 30, 30)
        painter.drawEllipse(inner_rect)
        
        painter.end()


# ══════════════════════════════════════════════════════════════════════════════
# NOVO: Widget de Tendência (seta + percentual)
# ══════════════════════════════════════════════════════════════════════════════
class TrendWidget(QWidget):
    """Mostra tendência com seta e percentual"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        self.arrow = QLabel("")
        self.arrow.setFont(QFont("Segoe UI", 14))
        
        self.label = QLabel("—")
        self.label.setObjectName("trendLabel")
        self.label.setFont(QFont("Segoe UI", 11, QFont.DemiBold))
        
        layout.addWidget(self.arrow)
        layout.addWidget(self.label)
        layout.addStretch()
    
    def set_trend(self, current: float, previous: float):
        """Calcula e exibe tendência"""
        if previous <= 0:
            self.arrow.setText("—")
            self.label.setText("Sem comparação")
            self.label.setStyleSheet("color: #9199a6;")
            return
        
        diff_pct = ((current - previous) / previous) * 100
        
        if diff_pct > 0:
            self.arrow.setText("↗")
            self.label.setText(f"+{diff_pct:.1f}%")
            self.label.setStyleSheet("color: #1a7a47;")
        elif diff_pct < 0:
            self.arrow.setText("↘")
            self.label.setText(f"{diff_pct:.1f}%")
            self.label.setStyleSheet("color: #c0392b;")
        else:
            self.arrow.setText("→")
            self.label.setText("0%")
            self.label.setStyleSheet("color: #9199a6;")


# ══════════════════════════════════════════════════════════════════════════════
# NOVO: Insight Cards - Análises automáticas
# ══════════════════════════════════════════════════════════════════════════════
class InsightCard(QFrame):
    """Card de insight/análise automática"""
    
    def __init__(self, icon: str, title: str, message: str, kind: str = "info"):
        super().__init__()
        self.setObjectName("insightCard")
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        
        # Ícone
        icon_label = QLabel(icon)
        icon_label.setFont(QFont("Segoe UI", 18))
        icon_label.setFixedSize(32, 32)
        icon_label.setAlignment(Qt.AlignCenter)
        
        # Textos
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        
        title_label = QLabel(title)
        title_label.setObjectName("insightTitle")
        title_label.setFont(QFont("Segoe UI", 11, QFont.DemiBold))
        
        msg_label = QLabel(message)
        msg_label.setObjectName("insightMsg")
        msg_label.setFont(QFont("Segoe UI", 10))
        msg_label.setWordWrap(True)
        
        text_layout.addWidget(title_label)
        text_layout.addWidget(msg_label)
        
        layout.addWidget(icon_label)
        layout.addLayout(text_layout, 1)
        
        # Estilo baseado no tipo
        colors = {
            "success": ("#1a7a47", "#e8f5e9"),
            "warning": ("#d97706", "#fff8e1"),
            "danger": ("#c0392b", "#ffebee"),
            "info": ("#1a6b7c", "#e1f5f0"),
        }
        color, bg = colors.get(kind, colors["info"])
        
        self.setStyleSheet(f"""
            QFrame#insightCard {{
                background: {bg};
                border-left: 3px solid {color};
                border-radius: 8px;
            }}
            QLabel#insightTitle {{ color: {color}; }}
            QLabel#insightMsg {{ color: {_INK2}; }}
        """)


# ══════════════════════════════════════════════════════════════════════════════
# NOVO: Diálogo de Exportação Avançada
# ══════════════════════════════════════════════════════════════════════════════
class ExportDialog(QDialog):
    """Diálogo para configurar exportação com opções avançadas"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Exportar Dados")
        self.setModal(True)
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        
        # Título
        title = QLabel("Configurar Exportação")
        title.setFont(QFont("Segoe UI", 16, QFont.DemiBold))
        layout.addWidget(title)
        
        # Formato
        format_group = QFrame()
        format_layout = QVBoxLayout(format_group)
        format_layout.setSpacing(8)
        
        format_label = QLabel("Formato do arquivo:")
        format_label.setFont(QFont("Segoe UI", 11, QFont.DemiBold))
        format_layout.addWidget(format_label)
        
        self.format_combo = QComboBox()
        self.format_combo.addItem("📊 Excel (.xlsx)", "xlsx")
        self.format_combo.addItem("📄 CSV (.csv)", "csv")
        self.format_combo.addItem("📋 PDF Relatório (.pdf)", "pdf")
        format_layout.addWidget(self.format_combo)
        
        layout.addWidget(format_group)
        
        # Opções de colunas
        cols_group = QFrame()
        cols_layout = QVBoxLayout(cols_group)
        cols_layout.setSpacing(8)
        
        cols_label = QLabel("Colunas para exportar:")
        cols_label.setFont(QFont("Segoe UI", 11, QFont.DemiBold))
        cols_layout.addWidget(cols_label)
        
        self.col_checks = {}
        for col_id, col_name in [
            ("data", "Data do Pagamento"),
            ("mat", "Matrícula"),
            ("nome", "Nome do Cliente"),
            ("cpf", "CPF"),
            ("status", "Status do Cliente"),
            ("pag_status", "Status do Pagamento"),
            ("valor", "Valor Pago"),
            ("mes_ref", "Mês de Referência"),
        ]:
            cb = QCheckBox(col_name)
            cb.setChecked(True)
            self.col_checks[col_id] = cb
            cols_layout.addWidget(cb)
        
        layout.addWidget(cols_group)
        
        # Opções adicionais
        opts_group = QFrame()
        opts_layout = QVBoxLayout(opts_group)
        opts_layout.setSpacing(8)
        
        opts_label = QLabel("Opções adicionais:")
        opts_label.setFont(QFont("Segoe UI", 11, QFont.DemiBold))
        opts_layout.addWidget(opts_label)
        
        self.include_summary = QCheckBox("Incluir resumo estatístico")
        self.include_summary.setChecked(True)
        opts_layout.addWidget(self.include_summary)
        
        self.include_chart = QCheckBox("Incluir gráfico de distribuição (apenas PDF/Excel)")
        self.include_chart.setChecked(True)
        opts_layout.addWidget(self.include_chart)
        
        layout.addWidget(opts_group)
        
        # Botões
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_export = QPushButton("Exportar")
        self.btn_export.setObjectName("btnPrimary")
        self.btn_export.clicked.connect(self.accept)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_export)
        
        layout.addLayout(btn_layout)
        
        self._apply_styles()
    
    def _apply_styles(self):
        self.setStyleSheet(f"""
            QDialog {{
                background: {_WHITE};
            }}
            QPushButton {{
                padding: 8px 20px;
                border-radius: 6px;
                font-size: 13px;
                min-height: 36px;
            }}
            QPushButton#btnPrimary {{
                background: {_ACCENT};
                color: white;
                border: none;
                font-weight: 600;
            }}
            QPushButton#btnPrimary:hover {{
                background: {_ACCENT_HOVER};
            }}
            QCheckBox {{
                font-size: 12px;
                spacing: 8px;
            }}
            QComboBox {{
                padding: 6px 10px;
                border: 1px solid {_LINE};
                border-radius: 6px;
                min-height: 36px;
            }}
        """)
    
    def get_config(self) -> dict:
        """Retorna configuração da exportação"""
        return {
            "format": self.format_combo.currentData(),
            "columns": [k for k, cb in self.col_checks.items() if cb.isChecked()],
            "include_summary": self.include_summary.isChecked(),
            "include_chart": self.include_chart.isChecked(),
        }


# ══════════════════════════════════════════════════════════════════════════════
# Registro de Conta a Pagar
# ══════════════════════════════════════════════════════════════════════════════
class ContaRegistroDialog(QDialog):
    def __init__(self, parent=None, conta: dict | None = None):
        super().__init__(parent)
        self._conta = dict(conta or {})
        self.setWindowTitle("Registrar conta a pagar")
        self.setModal(True)
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        title = QLabel("Nova conta")
        title.setFont(QFont("Segoe UI", 14, QFont.DemiBold))
        root.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        self.descricao = QLineEdit()
        self.descricao.setPlaceholderText("Descrição da conta")
        grid.addWidget(QLabel("Descrição"), 0, 0)
        grid.addWidget(self.descricao, 0, 1, 1, 3)

        self.categoria = QComboBox()
        self.categoria.addItems(
            ["Outros", "Aluguel", "Energia", "Água", "Folha de Pagamento", "Impostos", "Servicos de Ti", "Laboratorio"]
        )
        grid.addWidget(QLabel("Categoria"), 1, 0)
        grid.addWidget(self.categoria, 1, 1)

        self.fornecedor = QLineEdit()
        self.fornecedor.setPlaceholderText("Fornecedor")
        grid.addWidget(QLabel("Fornecedor"), 1, 2)
        grid.addWidget(self.fornecedor, 1, 3)

        self.valor_previsto = QDoubleSpinBox()
        self.valor_previsto.setPrefix("R$ ")
        self.valor_previsto.setDecimals(2)
        self.valor_previsto.setMaximum(99999999.99)
        self.valor_previsto.setSingleStep(10.0)
        grid.addWidget(QLabel("Valor previsto"), 2, 0)
        grid.addWidget(self.valor_previsto, 2, 1)

        self.data_venc = QDateEdit()
        self.data_venc.setCalendarPopup(True)
        self.data_venc.setDisplayFormat("dd/MM/yyyy")
        self.data_venc.setDate(QDate.currentDate())
        grid.addWidget(QLabel("Vencimento"), 2, 2)
        grid.addWidget(self.data_venc, 2, 3)

        self.forma_pag = QComboBox()
        self.forma_pag.addItems(["Pix", "Boleto", "Débito", "Crédito", "Outro"])
        grid.addWidget(QLabel("Forma pagto"), 3, 0)
        grid.addWidget(self.forma_pag, 3, 1)

        self.status = QComboBox()
        self.status.addItems(["Pendente", "Paga", "Vencida"])
        grid.addWidget(QLabel("Status"), 3, 2)
        grid.addWidget(self.status, 3, 3)

        self.obs = QTextEdit()
        self.obs.setPlaceholderText("Observações (opcional)")
        self.obs.setFixedHeight(88)
        grid.addWidget(QLabel("Observações"), 4, 0)
        grid.addWidget(self.obs, 4, 1, 1, 3)

        root.addLayout(grid)

        actions = QHBoxLayout()
        actions.addStretch()
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("Salvar")
        btn_ok.setObjectName("btnPrimary")
        btn_ok.clicked.connect(self._accept_if_valid)
        actions.addWidget(btn_cancel)
        actions.addWidget(btn_ok)
        root.addLayout(actions)

        self._apply_styles()
        self._load_conta()

    def _apply_styles(self):
        self.setStyleSheet(f"""
            QDialog {{ background: {_WHITE}; }}
            QLabel {{ color: {_INK}; font-size: 12px; }}
            QLineEdit, QComboBox, QDateEdit, QDoubleSpinBox, QTextEdit {{
                border: 1px solid {_LINE};
                border-radius: 8px;
                padding: 6px 8px;
                background: {_WHITE};
                font-size: 12px;
            }}
            QPushButton {{
                min-height: 34px;
                padding: 0 14px;
                border-radius: 8px;
                font-size: 12px;
            }}
            QPushButton#btnPrimary {{
                background: {_ACCENT};
                color: white;
                border: none;
                font-weight: 600;
            }}
            QPushButton#btnPrimary:hover {{ background: {_ACCENT_HOVER}; }}
        """)

    def _load_conta(self):
        if not self._conta:
            return
        self.descricao.setText(str(self._conta.get("descricao", "") or ""))
        self.fornecedor.setText(str(self._conta.get("fornecedor", "") or ""))
        self.obs.setPlainText(str(self._conta.get("observacoes", "") or ""))
        try:
            self.valor_previsto.setValue(float(self._conta.get("valor_previsto", 0.0) or 0.0))
        except Exception:
            pass

        cat = str(self._conta.get("categoria", "") or "").strip()
        if cat:
            idx = self.categoria.findText(cat, Qt.MatchFixedString)
            if idx >= 0:
                self.categoria.setCurrentIndex(idx)
        forma = str(self._conta.get("forma_pagamento", "") or "").strip()
        if forma:
            idx = self.forma_pag.findText(forma, Qt.MatchFixedString)
            if idx >= 0:
                self.forma_pag.setCurrentIndex(idx)
        status = str(self._conta.get("status", "Pendente") or "Pendente").strip()
        idx = self.status.findText(status, Qt.MatchFixedString)
        if idx >= 0:
            self.status.setCurrentIndex(idx)
        venc = str(self._conta.get("data_vencimento", "") or "").strip()
        if len(venc) == 10 and venc[4] == "-" and venc[7] == "-":
            try:
                y, m, d = venc.split("-")
                self.data_venc.setDate(QDate(int(y), int(m), int(d)))
            except Exception:
                pass

    def _accept_if_valid(self):
        if not (self.descricao.text() or "").strip():
            QMessageBox.warning(self, "Conta a pagar", "Informe a descrição da conta.")
            return
        self.accept()

    def payload(self) -> dict:
        status = str(self.status.currentText() or "Pendente").strip()
        valor_prev = float(self.valor_previsto.value() or 0.0)
        out = {
            "id": int(self._conta.get("id", 0) or 0),
            "descricao": (self.descricao.text() or "").strip(),
            "categoria": str(self.categoria.currentText() or "Outros"),
            "fornecedor": (self.fornecedor.text() or "").strip(),
            "valor_previsto": valor_prev,
            "data_vencimento": self.data_venc.date().toString("yyyy-MM-dd"),
            "forma_pagamento": str(self.forma_pag.currentText() or "Outro"),
            "status": status,
            "recorrente": False,
            "periodicidade": "",
            "total_parcelas": 1,
            "observacoes": (self.obs.toPlainText() or "").strip(),
        }
        if status == "Paga":
            out["data_pagamento_real"] = datetime.now().strftime("%Y-%m-%d")
            out["valor_pago"] = valor_prev
        return out


# ══════════════════════════════════════════════════════════════════════════════
# NOVO: Worker para análise de dados em background
# ══════════════════════════════════════════════════════════════════════════════
class DataAnalysisSignals(QObject):
    finished = Signal(dict)


class DataAnalysisWorker(QRunnable):
    """Analisa dados financeiros em background"""
    
    def __init__(self, rows: list[dict], ticket_medio: float):
        super().__init__()
        self.rows = rows
        self.ticket_medio = ticket_medio
        self.signals = DataAnalysisSignals()
    
    @Slot()
    def run(self):
        insights = []
        try:
            if not self.rows:
                self.signals.finished.emit({"insights": insights})
                return

            # Análise 1: Concentração de receita
            valores = [float(r.get("valor_pago", 0) or 0) for r in self.rows]
            total = sum(valores)

            if total > 0:
                valores_ordenados = sorted(valores, reverse=True)
                top_20_pct = sum(valores_ordenados[:max(1, len(valores) // 5)])
                concentracao = (top_20_pct / total) * 100

                if concentracao > 50:
                    insights.append({
                        "icon": "⚠️",
                        "title": "Concentração de receita",
                        "message": f"{concentracao:.0f}% da receita vem de 20% dos pagamentos. Considere diversificar.",
                        "kind": "warning"
                    })

            # Análise 2: Taxa de inadimplência
            atrasados = sum(1 for r in self.rows if r.get("pagamento_status", "").lower() == "atrasado")
            if len(self.rows) > 0:
                taxa = (atrasados / len(self.rows)) * 100
                if taxa > 15:
                    insights.append({
                        "icon": "🔴",
                        "title": "Alta inadimplência",
                        "message": f"{taxa:.1f}% dos pagamentos estão atrasados. Ação urgente recomendada.",
                        "kind": "danger"
                    })
                elif taxa > 5:
                    insights.append({
                        "icon": "⚠️",
                        "title": "Inadimplência moderada",
                        "message": f"{taxa:.1f}% dos pagamentos estão atrasados. Monitore de perto.",
                        "kind": "warning"
                    })
                else:
                    insights.append({
                        "icon": "✅",
                        "title": "Baixa inadimplência",
                        "message": f"Apenas {taxa:.1f}% de atraso. Excelente gestão!",
                        "kind": "success"
                    })

            # Análise 3: Clientes acima do ticket
            if self.ticket_medio > 0:
                acima = sum(1 for v in valores if v >= self.ticket_medio)
                if acima > 0:
                    pct = (acima / len(valores)) * 100
                    insights.append({
                        "icon": "💎",
                        "title": "Clientes premium",
                        "message": f"{acima} pagamentos ({pct:.0f}%) acima do ticket médio.",
                        "kind": "success"
                    })

            # Análise 4: Distribuição temporal (tolerante a datas inválidas)
            hoje = datetime.now().date()
            ultimos_7_dias = 0
            for r in self.rows:
                try:
                    dt = datetime.strptime(str(r.get("data_pagamento", "") or ""), "%Y-%m-%d").date()
                except Exception:
                    continue
                if (hoje - dt).days <= 7:
                    ultimos_7_dias += 1

            if len(self.rows) > 0:
                pct_recente = (ultimos_7_dias / len(self.rows)) * 100
                if pct_recente > 40:
                    insights.append({
                        "icon": "📈",
                        "title": "Receita concentrada no final",
                        "message": f"{pct_recente:.0f}% dos pagamentos nos últimos 7 dias.",
                        "kind": "info"
                    })

            self.signals.finished.emit({"insights": insights})
        except Exception as exc:
            self.signals.finished.emit({
                "insights": [{
                    "icon": "⚠️",
                    "title": "Falha ao gerar insights",
                    "message": f"Não foi possível concluir a análise automática: {str(exc)}",
                    "kind": "danger",
                }]
            })


# ── Gráfico de barras melhorado ───────────────────────────────────────────────
class DailyRevenueChart(QFrame):
    """Gráfico de barras diárias com visual SaaS melhorado"""

    def __init__(self):
        super().__init__()
        self.setObjectName("finChart")
        self._series: list[tuple[str, float]] = []
        self._max = 1.0
        self._bar_rects: list[tuple[int, int, int, int, str, float]] = []
        self._hover_index = -1

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(4)

        hdr = QHBoxLayout()
        hdr.setSpacing(0)

        self.title = QLabel("Receita diária por pagamento")
        self.title.setObjectName("finChartTitle")

        self.badge = QLabel("")
        self.badge.setObjectName("finChartBadge")
        self.badge.setVisible(False)

        hdr.addWidget(self.title)
        hdr.addStretch()
        hdr.addWidget(self.badge)
        lay.addLayout(hdr)

        self.sub = QLabel("—")
        self.sub.setObjectName("finChartSub")
        lay.addWidget(self.sub)

        self._canvas = QWidget()
        self._canvas.setMinimumHeight(140)  # Aumentado
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._canvas.paintEvent   = self._paint_canvas
        self._canvas.mouseMoveEvent = self._on_mouse_move
        self._canvas.leaveEvent = self._on_mouse_leave
        self._canvas.setMouseTracking(True)
        lay.addWidget(self._canvas)

    def set_series(self, series: list[tuple[str, float]], mes_ref: str):
        self._series = list(series or [])
        vals = [float(v or 0.0) for _, v in self._series]
        self._max = max(vals, default=1.0) or 1.0

        total = sum(vals)
        if total > 0 and self._series:
            dia_top, val_top = max(self._series, key=lambda x: float(x[1] or 0.0))
            media = total / len(self._series)
            self.sub.setText(
                f"Total: {br_money(total)}  ·  Pico dia {dia_top}: {br_money(float(val_top or 0.0))}  ·  Média: {br_money(media)}"
            )
            self.badge.setText(br_money(total))
            self.badge.setVisible(True)
        else:
            self.sub.setText("Sem pagamentos no mês")
            self.badge.setVisible(False)

        self.title.setText(f"Receita diária · {_iso_to_mes_br(mes_ref)}")
        self._canvas.update()

    def _paint_canvas(self, _event):
        painter = QPainter(self._canvas)
        painter.setRenderHint(QPainter.Antialiasing, True)

        W = self._canvas.width()
        H = self._canvas.height()

        # Fundo suave
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(249, 250, 251))
        painter.drawRoundedRect(0, 0, W, H, 10, 10)

        if not self._series:
            painter.setPen(QColor(_INK3))
            font = painter.font()
            font.setPointSize(9)
            painter.setFont(font)
            painter.drawText(self._canvas.rect(), Qt.AlignCenter, "Sem dados para o período")
            painter.end()
            return

        left, right = 12, W - 12
        top, bottom = 15, H - 28

        width  = max(1, right - left)
        height = max(1, bottom - top)
        count  = len(self._series)
        gap    = 2 if count > 20 else 3
        bar_w  = max(3, int((width - gap * (count - 1)) / count))

        # Linha de base
        painter.setPen(QPen(QColor(_LINE), 1.5))
        painter.drawLine(left, bottom, right, bottom)

        # Guias horizontais sutis
        painter.setPen(QPen(QColor(15, 23, 42, 20), 1, Qt.DotLine))
        for frac in (0.25, 0.5, 0.75):
            y = bottom - int(height * frac)
            painter.drawLine(left, y, right, y)
            # Labels de valor
            painter.setPen(QColor(_INK3))
            font = painter.font()
            font.setPointSize(7)
            painter.setFont(font)
            val_at_line = self._max * frac
            painter.drawText(left - 8, y - 2, left, y + 2, Qt.AlignRight | Qt.AlignVCenter, 
                           f"{br_money(val_at_line)}")
            painter.setPen(QPen(QColor(15, 23, 42, 20), 1, Qt.DotLine))

        self._bar_rects = []
        x = left
        for idx, (dia, val) in enumerate(self._series):
            numeric = float(val or 0.0)
            ratio   = 0.0 if self._max <= 0 else min(1.0, numeric / self._max)
            bar_h   = max(2, int(height * ratio)) if numeric > 0 else 0

            bx, by = x, bottom - bar_h
            bw, bh = bar_w, bar_h

            painter.setPen(Qt.NoPen)
            
            # Efeito hover
            is_hover = (idx == self._hover_index)
            
            if numeric >= self._max and numeric > 0:
                # barra de pico
                grad = QLinearGradient(bx, by, bx, by + bh)
                grad.setColorAt(0, QColor("#e67e22") if not is_hover else QColor("#ff8c42"))
                grad.setColorAt(1, QColor("#d35400") if not is_hover else QColor("#e67e22"))
                painter.setBrush(QBrush(grad))
            elif numeric > 0:
                grad = QLinearGradient(bx, by, bx, by + bh)
                grad.setColorAt(0, QColor("#2b9ab0") if not is_hover else QColor("#3bbcc9"))
                grad.setColorAt(1, QColor("#1a6b7c") if not is_hover else QColor("#2b9ab0"))
                painter.setBrush(QBrush(grad))
            else:
                painter.setBrush(QColor(15, 23, 42, 12))

            if bh > 0:
                painter.drawRoundedRect(bx, by, bw, bh, 3, 3)
                
                # Label no topo da barra se hover
                if is_hover and numeric > 0:
                    painter.setPen(QColor(_INK))
                    font = painter.font()
                    font.setPointSize(8)
                    font.setBold(True)
                    painter.setFont(font)
                    painter.drawText(bx - 20, by - 15, bw + 40, 12, 
                                   Qt.AlignCenter, br_money(numeric))
                    painter.setPen(Qt.NoPen)

            self._bar_rects.append((bx, by, bw, bh, dia, numeric))
            x += bar_w + gap

        # Rótulos de eixo
        painter.setPen(QColor(_INK3))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        label_indices = [0, count // 4, count // 2, 3 * count // 4, count - 1]
        for i in label_indices:
            if 0 <= i < len(self._series):
                dia, _ = self._series[i]
                rx = left + i * (bar_w + gap)
                painter.drawText(rx - 10, bottom + 18, 30, 12, Qt.AlignCenter, dia)

        painter.end()

    def _on_mouse_move(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        old_hover = self._hover_index
        self._hover_index = -1
        
        for idx, (bx, by, bw, bh, dia, val) in enumerate(self._bar_rects):
            if bx <= pos.x() <= bx + bw and by <= pos.y() <= by + bh:
                self._hover_index = idx
                break
        
        if old_hover != self._hover_index:
            self._canvas.update()
    
    def _on_mouse_leave(self, event):
        if self._hover_index != -1:
            self._hover_index = -1
            self._canvas.update()


class SimpleTrendChart(QWidget):
    """Gráfico simples (linha ou barras) para modal de insights."""

    def __init__(self, parent=None, mode: str = "line"):
        super().__init__(parent)
        self.mode = str(mode or "line").strip().lower()
        self._labels: list[str] = []
        self._values: list[float] = []
        self._line_color = QColor(_ACCENT)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_series(self, labels: list[str], values: list[float], color: str = _ACCENT):
        self._labels = [str(x or "") for x in (labels or [])]
        out: list[float] = []
        for v in (values or []):
            try:
                out.append(float(v or 0.0))
            except Exception:
                out.append(0.0)
        self._values = out
        self._line_color = QColor(str(color or _ACCENT))
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(10, 10, -10, -26)
        if rect.width() <= 0 or rect.height() <= 0:
            painter.end()
            return

        painter.setPen(QPen(QColor(220, 228, 236), 1))
        for i in range(5):
            y = rect.top() + int((rect.height() / 4) * i)
            painter.drawLine(rect.left(), y, rect.right(), y)

        if not self._values:
            painter.setPen(QColor(_INK3))
            painter.drawText(rect, Qt.AlignCenter, "Sem dados")
            painter.end()
            return

        max_v = max(self._values) if self._values else 0.0
        if max_v <= 0:
            max_v = 1.0
        n = len(self._values)
        step = rect.width() / max(1, n - 1 if self.mode == "line" else n)

        if self.mode == "bar":
            bw = max(6, int(step * 0.62))
            for i, v in enumerate(self._values):
                h = int((v / max_v) * rect.height())
                x = rect.left() + int(i * step) + max(0, (int(step) - bw) // 2)
                y = rect.bottom() - h
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(_ACCENT))
                painter.drawRoundedRect(x, y, bw, h, 3, 3)
        else:
            points = []
            for i, v in enumerate(self._values):
                x = rect.left() + int(i * step)
                y = rect.bottom() - int((v / max_v) * rect.height())
                points.append(QPointF(float(x), float(y)))
            painter.setPen(QPen(self._line_color, 2))
            for i in range(1, len(points)):
                painter.drawLine(points[i - 1], points[i])
            painter.setBrush(QBrush(self._line_color))
            painter.setPen(Qt.NoPen)
            for p in points:
                painter.drawEllipse(QRectF(p.x() - 2.8, p.y() - 2.8, 5.6, 5.6))

        painter.setPen(QColor(_INK3))
        f = painter.font()
        f.setPointSize(8)
        painter.setFont(f)
        idxs = sorted(set([0, max(0, n // 2), n - 1]))
        for idx in idxs:
            if idx < 0 or idx >= n:
                continue
            lbl = self._labels[idx] if idx < len(self._labels) else str(idx + 1)
            x = rect.left() + int(idx * step)
            painter.drawText(x - 24, rect.bottom() + 6, 48, 14, Qt.AlignCenter, lbl)
        painter.end()


class SimplePieChart(QWidget):
    """Gráfico de pizza simples para distribuição por categoria."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slices: list[tuple[str, float, str]] = []
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_slices(self, slices: list[tuple[str, float, str]]):
        self._slices = list(slices or [])
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        if not self._slices:
            p.setPen(QColor(_INK3))
            p.drawText(self.rect(), Qt.AlignCenter, "Sem dados")
            p.end()
            return

        total = sum(max(0.0, float(v or 0.0)) for _, v, _ in self._slices)
        if total <= 0:
            p.setPen(QColor(_INK3))
            p.drawText(self.rect(), Qt.AlignCenter, "Sem dados")
            p.end()
            return

        pie_rect = QRectF(12, 16, min(180, self.width() - 24), min(180, self.height() - 32))
        start = 90 * 16
        for label, val, color in self._slices:
            span = int((float(val or 0.0) / total) * 360 * 16)
            p.setBrush(QColor(color))
            p.setPen(QPen(QColor(_WHITE), 1.5))
            p.drawPie(pie_rect, start, -span)
            start -= span

        lx = int(pie_rect.right()) + 14
        ly = int(pie_rect.top()) + 2
        p.setPen(QColor(_INK))
        f = p.font()
        f.setPointSize(9)
        p.setFont(f)
        for label, val, color in self._slices[:8]:
            pct = (float(val or 0.0) / total) * 100.0 if total > 0 else 0.0
            p.setBrush(QColor(color))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(lx, ly + 3, 10, 10, 2, 2)
            p.setPen(QColor(_INK))
            txt = f"{label}: {br_money(val)} ({pct:.1f}%)"
            p.drawText(lx + 16, ly, max(0, self.width() - lx - 20), 16, Qt.AlignLeft | Qt.AlignVCenter, txt)
            ly += 18
        p.end()


class InsightsTabSignals(QObject):
    finished = Signal(str, dict)
    error = Signal(str, str)


class InsightsTabWorker(QRunnable):
    def __init__(self, key: str, fn):
        super().__init__()
        self.key = str(key or "")
        self.fn = fn
        self.signals = InsightsTabSignals()

    @Slot()
    def run(self):
        try:
            result = self.fn()
            self.signals.finished.emit(self.key, dict(result or {}))
        except Exception as exc:
            self.signals.error.emit(self.key, str(exc))


class FinanceInsightsModal(QDialog):
    TAB_ORDER = [
        ("resumo", "Resumo do Mês"),
        ("inadimplencia", "Inadimplência"),
        ("receita", "Receita"),
        ("despesas", "Despesas"),
        ("fluxo", "Fluxo de Caixa"),
        ("kpi", "Indicadores KPI"),
    ]

    def __init__(self, mes_ref: str, parent=None):
        super().__init__(parent)
        self._mes_ref = str(mes_ref or "").strip()
        if len(self._mes_ref) != 7 or self._mes_ref[4] != "-":
            self._mes_ref = datetime.now().strftime("%Y-%m")
        self._pool = QThreadPool.globalInstance()
        self._tab_layouts: dict[str, QVBoxLayout] = {}
        self._tab_loaded: dict[str, bool] = {}
        self._tab_loading: dict[str, bool] = {}
        self._tab_data: dict[str, dict] = {}
        self._expense_limit = 5000.0
        self._fade_anim = None
        self._slide_anim = None
        self._opening_animated = False

        self._compute_map = {
            "resumo": self._compute_resumo_data,
            "inadimplencia": self._compute_inadimplencia_data,
            "receita": self._compute_receita_data,
            "despesas": self._compute_despesas_data,
            "fluxo": self._compute_fluxo_data,
            "kpi": self._compute_kpi_data,
        }
        self._render_map = {
            "resumo": self._render_resumo_tab,
            "inadimplencia": self._render_inadimplencia_tab,
            "receita": self._render_receita_tab,
            "despesas": self._render_despesas_tab,
            "fluxo": self._render_fluxo_tab,
            "kpi": self._render_kpi_tab,
        }

        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._build_ui()
        self._apply_styles()
        self._sync_modal_geometry()
        self._ensure_tab_loaded(0)

    # ── construção / visual ────────────────────────────────────────────────
    def _build_ui(self):
        self.modal_card = QFrame(self)
        self.modal_card.setObjectName("insightsModalCard")

        card_layout = QVBoxLayout(self.modal_card)
        card_layout.setContentsMargins(16, 14, 16, 12)
        card_layout.setSpacing(10)

        hdr = QHBoxLayout()
        hdr.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("Insights Financeiros")
        title.setObjectName("insightsTitle")
        subtitle = QLabel(f"Clínica · {_iso_to_mes_br(self._mes_ref)}")
        subtitle.setObjectName("insightsSubtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        hdr.addLayout(title_col)
        hdr.addStretch()

        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("insightsCloseBtn")
        self.btn_close.setFixedSize(28, 28)
        self.btn_close.clicked.connect(self.reject)
        hdr.addWidget(self.btn_close)
        card_layout.addLayout(hdr)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("insightsTabs")
        self.tabs.currentChanged.connect(self._ensure_tab_loaded)
        card_layout.addWidget(self.tabs, 1)

        for key, label in self.TAB_ORDER:
            page = QWidget()
            wrap = QVBoxLayout(page)
            wrap.setContentsMargins(0, 0, 0, 0)
            wrap.setSpacing(0)

            scroll = QScrollArea()
            scroll.setObjectName("insightsScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

            body = QWidget()
            body.setObjectName("insightsBody")
            body_lay = QVBoxLayout(body)
            body_lay.setContentsMargins(8, 8, 8, 8)
            body_lay.setSpacing(10)
            scroll.setWidget(body)
            wrap.addWidget(scroll)
            self.tabs.addTab(page, label)

            self._tab_layouts[key] = body_lay
            self._tab_loaded[key] = False
            self._tab_loading[key] = False
            self._set_tab_loading(key, "Aguarde, carregando dados...")

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.footer_hint = QLabel("Dados calculados dinamicamente com base no banco.")
        self.footer_hint.setObjectName("insightsFooterHint")
        footer.addWidget(self.footer_hint, 1)

        self.btn_pdf = QPushButton("Gerar Relatório PDF")
        self.btn_pdf.setObjectName("insightsPrimaryBtn")
        self.btn_pdf.setFixedHeight(34)
        self.btn_pdf.clicked.connect(self._export_pdf_report)
        footer.addWidget(self.btn_pdf)
        card_layout.addLayout(footer)

    def _apply_styles(self):
        self.setStyleSheet(f"""
        QFrame#insightsModalCard {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 14px;
        }}
        QLabel#insightsTitle {{
            color: {_INK};
            font-size: 19px;
            font-weight: 700;
        }}
        QLabel#insightsSubtitle {{
            color: {_INK2};
            font-size: 12px;
        }}
        QPushButton#insightsCloseBtn {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 14px;
            color: {_INK2};
            font-size: 14px;
            font-weight: 700;
        }}
        QPushButton#insightsCloseBtn:hover {{
            border-color: {_DANGER};
            color: {_DANGER};
            background: rgba(192,57,43,0.07);
        }}
        QTabWidget#insightsTabs::pane {{
            border: 1px solid {_LINE};
            border-radius: 10px;
            background: {_BG};
            top: -1px;
        }}
        QTabWidget#insightsTabs::tab-bar {{
            left: 6px;
        }}
        QTabBar::tab {{
            background: transparent;
            color: {_INK2};
            border: none;
            padding: 8px 11px;
            font-size: 12px;
            font-weight: 600;
            margin-right: 2px;
            border-bottom: 2px solid transparent;
        }}
        QTabBar::tab:selected {{
            color: {_ACCENT};
            border-bottom: 2px solid {_ACCENT};
        }}
        QTabBar::tab:hover {{
            color: {_INK};
        }}
        QScrollArea#insightsScroll {{
            border: none;
            background: transparent;
        }}
        QWidget#insightsBody {{
            background: transparent;
        }}
        QLabel#insightsFooterHint {{
            color: {_INK3};
            font-size: 11px;
        }}
        QPushButton#insightsPrimaryBtn {{
            background: {_ACCENT};
            color: {_WHITE};
            border: none;
            border-radius: 8px;
            padding: 0 14px;
            font-size: 12px;
            font-weight: 700;
        }}
        QPushButton#insightsPrimaryBtn:hover {{
            background: {_ACCENT_HOVER};
        }}
        """)

    def _sync_modal_geometry(self):
        parent_window = self.parentWidget().window() if self.parentWidget() else None
        if parent_window is not None:
            self.setGeometry(parent_window.frameGeometry())
        else:
            self.resize(960, 680)
        self._position_card()

    def _position_card(self):
        max_w = max(420, int(self.width() * 0.95))
        max_h = max(340, int(self.height() * 0.92))
        card_w = min(860, max_w)
        card_h = min(580, max_h)
        x = (self.width() - card_w) // 2
        y = (self.height() - card_h) // 2
        self.modal_card.setGeometry(x, y, card_w, card_h)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(10, 16, 22, 140))
        p.end()
        super().paintEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_card()

    def showEvent(self, event):
        super().showEvent(event)
        if self._opening_animated:
            return
        self._opening_animated = True
        self.setWindowOpacity(0.0)
        end_rect = self.modal_card.geometry()
        start_rect = QRect(end_rect.x(), end_rect.y() + 24, end_rect.width(), end_rect.height())
        self.modal_card.setGeometry(start_rect)

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setDuration(180)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._slide_anim = QPropertyAnimation(self.modal_card, b"geometry", self)
        self._slide_anim.setDuration(220)
        self._slide_anim.setStartValue(start_rect)
        self._slide_anim.setEndValue(end_rect)
        self._slide_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._fade_anim.start()
        self._slide_anim.start()

    def mousePressEvent(self, event):
        if not self.modal_card.geometry().contains(event.pos()):
            self.reject()
            return
        super().mousePressEvent(event)

    # ── helpers de render ───────────────────────────────────────────────────
    def _clear_layout(self, layout: QVBoxLayout):
        while layout.count():
            item = layout.takeAt(0)
            child = item.widget()
            sub = item.layout()
            if child is not None:
                child.deleteLater()
            elif sub is not None:
                self._clear_layout(sub)

    def _set_tab_loading(self, key: str, text: str):
        lay = self._tab_layouts.get(key)
        if lay is None:
            return
        self._clear_layout(lay)
        msg = QLabel(str(text or "Carregando..."))
        msg.setObjectName("insightMuted")
        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        lay.addSpacing(12)
        lay.addWidget(msg)
        lay.addWidget(bar)
        lay.addStretch(1)

    def _make_stat_card(self, title: str, value: str, sub: str = "", tone: str = "") -> QFrame:
        card = QFrame()
        card.setObjectName("insightStatCard")
        if tone:
            card.setProperty("tone", tone)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setSpacing(2)
        t = QLabel(str(title or "").upper())
        t.setObjectName("insightCardTitle")
        v = QLabel(str(value or "—"))
        v.setObjectName("insightCardValue")
        s = QLabel(str(sub or ""))
        s.setObjectName("insightCardSub")
        s.setWordWrap(True)
        s.setVisible(bool(sub))
        cl.addWidget(t)
        cl.addWidget(v)
        cl.addWidget(s)
        return card

    def _month_axis_label(self, month_ref: str) -> str:
        label = _iso_to_mes_br(month_ref)
        if len(label) >= 8 and "/" in label:
            return label[:3] + "/" + label[-2:]
        return label

    # ── carregamento lazy das abas ──────────────────────────────────────────
    def _key_for_index(self, index: int) -> str:
        if 0 <= int(index) < len(self.TAB_ORDER):
            return self.TAB_ORDER[int(index)][0]
        return self.TAB_ORDER[0][0]

    def _ensure_tab_loaded(self, index: int):
        key = self._key_for_index(index)
        if self._tab_loaded.get(key):
            return
        if self._tab_loading.get(key):
            return
        compute_fn = self._compute_map.get(key)
        if compute_fn is None:
            return
        self._tab_loading[key] = True
        self._set_tab_loading(key, "Carregando dados desta aba...")
        worker = InsightsTabWorker(key, compute_fn)
        worker.signals.finished.connect(self._on_tab_data_ready)
        worker.signals.error.connect(self._on_tab_data_error)
        self._pool.start(worker)

    def _on_tab_data_ready(self, key: str, data: dict):
        k = str(key or "")
        self._tab_loading[k] = False
        self._tab_loaded[k] = True
        payload = dict(data or {})
        self._tab_data[k] = payload
        renderer = self._render_map.get(k)
        if renderer is not None:
            renderer(payload)

    def _on_tab_data_error(self, key: str, message: str):
        k = str(key or "")
        self._tab_loading[k] = False
        lay = self._tab_layouts.get(k)
        if lay is None:
            return
        self._clear_layout(lay)
        lbl = QLabel(f"Falha ao carregar os insights: {str(message or 'erro inesperado')}")
        lbl.setObjectName("insightAlertDanger")
        lay.addWidget(lbl)
        lay.addStretch(1)

    # ── cálculos de dados ───────────────────────────────────────────────────
    def _fetch_contract_snapshot(self) -> dict:
        out = {
            "clientes_ativos": [],
            "clientes_todos": [],
            "empresas_ativas": [],
            "empresas_todas": [],
            "mrr": 0.0,
            "atrasados_total": 0,
            "valor_atrasado": 0.0,
        }
        conn = db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, nome, telefone, COALESCE(valor_mensal, 0), COALESCE(vencimento_dia, 10),
                       COALESCE(status, 'ativo'), COALESCE(pagamento_status, 'em_dia'), COALESCE(data_inicio, '')
                FROM clientes
                """
            )
            for row in cur.fetchall() or []:
                try:
                    valor = float(row[3] or 0.0)
                except Exception:
                    valor = 0.0
                item = {
                    "id": int(row[0] or 0),
                    "nome": str(row[1] or ""),
                    "telefone": str(row[2] or ""),
                    "valor_mensal": max(0.0, valor),
                    "vencimento_dia": int(row[4] or 10),
                    "status": str(row[5] or "ativo").strip().lower(),
                    "pagamento_status": str(row[6] or "em_dia").strip().lower(),
                    "data_inicio": str(row[7] or ""),
                    "tipo": "cliente",
                }
                out["clientes_todos"].append(item)
                if item["status"] == "ativo":
                    out["clientes_ativos"].append(item)
                    out["mrr"] += item["valor_mensal"]
                    if item["pagamento_status"] == "atrasado":
                        out["atrasados_total"] += 1
                        out["valor_atrasado"] += item["valor_mensal"]

            cur.execute(
                """
                SELECT id, nome, telefone, COALESCE(valor_mensal, ''), COALESCE(dia_vencimento, 10),
                       COALESCE(status_pagamento, ''), COALESCE(data_cadastro, '')
                FROM empresas
                """
            )
            for row in cur.fetchall() or []:
                valor = max(0.0, _parse_any_money(row[3]))
                status_pag = str(row[5] or "").strip().lower()
                item = {
                    "id": int(row[0] or 0),
                    "nome": str(row[1] or ""),
                    "telefone": str(row[2] or ""),
                    "valor_mensal": valor,
                    "vencimento_dia": int(row[4] or 10),
                    "status_pagamento": status_pag,
                    "data_inicio": str(row[6] or ""),
                    "tipo": "empresa",
                }
                out["empresas_todas"].append(item)
                out["empresas_ativas"].append(item)
                out["mrr"] += item["valor_mensal"]
                if status_pag == "inadimplente":
                    out["atrasados_total"] += 1
                    out["valor_atrasado"] += item["valor_mensal"]
        finally:
            conn.close()

        out["ativos_total"] = len(out["clientes_ativos"]) + len(out["empresas_ativas"])
        out["inativos_total"] = len([c for c in out["clientes_todos"] if c.get("status") == "inativo"])
        return out

    def _fetch_month_receita_totals(self, months: list[str]) -> dict[str, float]:
        refs = sorted({str(m).strip() for m in (months or []) if len(str(m).strip()) == 7 and str(m).strip()[4] == "-"})
        totals = {m: 0.0 for m in refs}
        if not refs:
            return totals
        start_ref, end_ref = refs[0], refs[-1]

        conn = db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT mes_referencia, COALESCE(SUM(valor_pago), 0)
                FROM pagamentos
                WHERE mes_referencia >= ? AND mes_referencia <= ?
                GROUP BY mes_referencia
                """,
                (start_ref, end_ref),
            )
            for row in cur.fetchall() or []:
                mes = str(row[0] or "")
                if mes in totals:
                    totals[mes] += float(row[1] or 0.0)

            cur.execute(
                """
                SELECT mes_referencia, COALESCE(SUM(valor_pago), 0)
                FROM pagamentos_empresas
                WHERE mes_referencia >= ? AND mes_referencia <= ?
                GROUP BY mes_referencia
                """,
                (start_ref, end_ref),
            )
            for row in cur.fetchall() or []:
                mes = str(row[0] or "")
                if mes in totals:
                    totals[mes] += float(row[1] or 0.0)
        finally:
            conn.close()
        return totals

    def _fetch_paid_contract_counts(self, months: list[str]) -> dict[str, int]:
        refs = sorted({str(m).strip() for m in (months or []) if len(str(m).strip()) == 7 and str(m).strip()[4] == "-"})
        out = {m: 0 for m in refs}
        if not refs:
            return out
        start_ref, end_ref = refs[0], refs[-1]
        conn = db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT mes_referencia, COUNT(DISTINCT cliente_id)
                FROM pagamentos
                WHERE mes_referencia >= ? AND mes_referencia <= ?
                GROUP BY mes_referencia
                """,
                (start_ref, end_ref),
            )
            for row in cur.fetchall() or []:
                mes = str(row[0] or "")
                if mes in out:
                    out[mes] += int(row[1] or 0)

            cur.execute(
                """
                SELECT mes_referencia, COUNT(DISTINCT empresa_id)
                FROM pagamentos_empresas
                WHERE mes_referencia >= ? AND mes_referencia <= ?
                GROUP BY mes_referencia
                """,
                (start_ref, end_ref),
            )
            for row in cur.fetchall() or []:
                mes = str(row[0] or "")
                if mes in out:
                    out[mes] += int(row[1] or 0)
        finally:
            conn.close()
        return out

    def _days_overdue(self, due_day: int, today_dt: date) -> int:
        day = max(1, min(31, int(due_day or 1)))
        y = int(today_dt.year)
        m = int(today_dt.month)
        current_max = monthrange(y, m)[1]
        due_this = date(y, m, min(day, current_max))
        if due_this > today_dt:
            prev_ref = _month_shift(f"{y:04d}-{m:02d}", -1)
            py = int(prev_ref[:4])
            pm = int(prev_ref[5:7])
            prev_max = monthrange(py, pm)[1]
            due_date = date(py, pm, min(day, prev_max))
        else:
            due_date = due_this
        delta = (today_dt - due_date).days
        return max(0, int(delta))

    def _compute_resumo_data(self) -> dict:
        ref = self._mes_ref
        snap = self._fetch_contract_snapshot()
        receita_map = self._fetch_month_receita_totals([ref])
        receita = float(receita_map.get(ref, 0.0) or 0.0)

        contas = db.carregar_contas_pagar_mes(ref, detail_limit=1) or {}
        despesas_pagas = float(contas.get("valor_pago_total", 0.0) or 0.0)
        total_aberto = max(0.0, float(snap.get("mrr", 0.0) or 0.0) - receita)
        vencido = float(snap.get("valor_atrasado", 0.0) or 0.0)
        saldo = receita - despesas_pagas
        return {
            "recebido": receita,
            "aberto": total_aberto,
            "vencido": vencido,
            "despesas_pagas": despesas_pagas,
            "saldo": saldo,
            "superavit": saldo >= 0.0,
        }

    def _compute_inadimplencia_data(self) -> dict:
        ref = self._mes_ref
        snap = self._fetch_contract_snapshot()
        ativos = int(snap.get("ativos_total", 0) or 0)
        atrasados = int(snap.get("atrasados_total", 0) or 0)
        taxa = (float(atrasados) / float(ativos) * 100.0) if ativos > 0 else 0.0

        today_dt = datetime.now().date()
        devedores = []
        for row in list(snap.get("clientes_ativos", [])):
            if str(row.get("pagamento_status", "")).lower() != "atrasado":
                continue
            devedores.append({
                "nome": row.get("nome", "—"),
                "telefone": row.get("telefone", ""),
                "valor": float(row.get("valor_mensal", 0.0) or 0.0),
                "dias": self._days_overdue(int(row.get("vencimento_dia", 10) or 10), today_dt),
                "tipo": "Cliente",
            })
        for row in list(snap.get("empresas_ativas", [])):
            if str(row.get("status_pagamento", "")).lower() != "inadimplente":
                continue
            devedores.append({
                "nome": row.get("nome", "—"),
                "telefone": row.get("telefone", ""),
                "valor": float(row.get("valor_mensal", 0.0) or 0.0),
                "dias": self._days_overdue(int(row.get("vencimento_dia", 10) or 10), today_dt),
                "tipo": "Empresa",
            })
        devedores.sort(key=lambda x: (float(x.get("valor", 0.0)), int(x.get("dias", 0))), reverse=True)
        top5 = devedores[:5]

        months = _months_range(ref, 6)
        paid_counts = self._fetch_paid_contract_counts(months)
        hist = []
        for m in months:
            paid = int(paid_counts.get(m, 0) or 0)
            overdue = max(0, ativos - paid)
            pct = (float(overdue) / float(ativos) * 100.0) if ativos > 0 else 0.0
            hist.append(round(pct, 2))

        return {
            "taxa": taxa,
            "ativos": ativos,
            "atrasados": atrasados,
            "top5": top5,
            "hist_labels": [self._month_axis_label(m) for m in months],
            "hist_values": hist,
        }

    def _compute_receita_data(self) -> dict:
        ref = self._mes_ref
        months_12 = _months_range(ref, 12)
        totals_12 = self._fetch_month_receita_totals(months_12)
        values_12 = [float(totals_12.get(m, 0.0) or 0.0) for m in months_12]

        year = int(ref[:4])
        month = ref[5:7]
        yoy_ref = f"{year - 1:04d}-{month}"
        yoy_map = self._fetch_month_receita_totals([yoy_ref, ref])
        atual = float(yoy_map.get(ref, 0.0) or 0.0)
        ano_ant = float(yoy_map.get(yoy_ref, 0.0) or 0.0)
        delta = atual - ano_ant
        if ano_ant > 0:
            pct = (delta / ano_ant) * 100.0
        else:
            pct = 100.0 if atual > 0 else 0.0

        last6 = values_12[-6:] if len(values_12) >= 6 else values_12
        media_6 = (sum(last6) / len(last6)) if last6 else 0.0
        snap = self._fetch_contract_snapshot()
        proj = max(float(snap.get("mrr", 0.0) or 0.0), atual)
        restante = max(0.0, proj - atual)
        return {
            "labels_12": [self._month_axis_label(m) for m in months_12],
            "values_12": values_12,
            "atual": atual,
            "ano_anterior": ano_ant,
            "delta": delta,
            "pct": pct,
            "media_6": media_6,
            "projecao": proj,
            "restante": restante,
        }

    def _compute_despesas_data(self) -> dict:
        ref = self._mes_ref
        prev_ref = _month_shift(ref, -1)
        atual = db.carregar_contas_pagar_mes(ref, detail_limit=3000) or {}
        anterior = db.carregar_contas_pagar_mes(prev_ref, detail_limit=3000) or {}
        rows = list(atual.get("rows", []) or [])

        categorias: dict[str, float] = {}
        top_rows = []
        for r in rows:
            categoria = str(r.get("categoria", "") or "Outros").strip() or "Outros"
            status = str(r.get("status", "") or "").strip().lower()
            valor = float(r.get("valor_previsto", 0.0) or 0.0)
            if status == "paga":
                valor = float(r.get("valor_pago", valor) or valor)
            categorias[categoria] = categorias.get(categoria, 0.0) + max(0.0, valor)
            top_rows.append({
                "descricao": str(r.get("descricao", "—") or "—"),
                "categoria": categoria,
                "fornecedor": str(r.get("fornecedor", "—") or "—"),
                "valor": max(0.0, valor),
            })
        top_rows.sort(key=lambda x: float(x.get("valor", 0.0)), reverse=True)
        total_atual = float(atual.get("despesas_total", 0.0) or 0.0)
        total_prev = float(anterior.get("despesas_total", 0.0) or 0.0)
        delta = total_atual - total_prev
        pct = ((delta / total_prev) * 100.0) if total_prev > 0 else (100.0 if total_atual > 0 else 0.0)

        return {
            "categorias": categorias,
            "top5": top_rows[:5],
            "total_atual": total_atual,
            "total_prev": total_prev,
            "delta": delta,
            "pct": pct,
            "mes_anterior": prev_ref,
        }

    def _compute_fluxo_data(self) -> dict:
        snap = self._fetch_contract_snapshot()
        today = datetime.now().date()
        horizon = 30
        end = today + timedelta(days=horizon - 1)

        due_map: dict[int, float] = {}
        for r in list(snap.get("clientes_ativos", [])) + list(snap.get("empresas_ativas", [])):
            day = max(1, min(31, int(r.get("vencimento_dia", 10) or 10)))
            due_map[day] = due_map.get(day, 0.0) + float(r.get("valor_mensal", 0.0) or 0.0)

        saidas_map: dict[str, float] = {}
        conn = db.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT data_vencimento, COALESCE(valor_previsto, 0), COALESCE(status, 'Pendente')
                FROM contas_pagar
                WHERE data_vencimento >= ? AND data_vencimento <= ?
                ORDER BY data_vencimento ASC
                """,
                (today.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
            )
            for row in cur.fetchall() or []:
                iso = str(row[0] or "").strip()
                if len(iso) != 10:
                    continue
                status = str(row[2] or "Pendente").strip().lower()
                if status == "paga":
                    continue
                saidas_map[iso] = saidas_map.get(iso, 0.0) + float(row[1] or 0.0)
        finally:
            conn.close()

        month_ref = today.strftime("%Y-%m")
        receita_hoje = float(self._fetch_month_receita_totals([month_ref]).get(month_ref, 0.0) or 0.0)
        despesas_pg = float((db.carregar_contas_pagar_mes(month_ref, detail_limit=1) or {}).get("valor_pago_total", 0.0) or 0.0)
        saldo = receita_hoje - despesas_pg

        rows = []
        negativos = 0
        labels = []
        serie_saldo = []
        for i in range(horizon):
            d = today + timedelta(days=i)
            iso = d.strftime("%Y-%m-%d")
            entradas = 0.0
            days_month = monthrange(d.year, d.month)[1]
            for due_day, value in due_map.items():
                if min(days_month, due_day) == d.day:
                    entradas += float(value or 0.0)
            saidas = float(saidas_map.get(iso, 0.0) or 0.0)
            saldo += (entradas - saidas)
            if saldo < 0:
                negativos += 1
            rows.append({
                "data": iso,
                "entradas": entradas,
                "saidas": saidas,
                "saldo": saldo,
            })
            labels.append(f"{d.day:02d}/{d.month:02d}")
            serie_saldo.append(saldo)

        return {
            "rows": rows,
            "negativos": negativos,
            "labels": labels,
            "saldo_series": serie_saldo,
        }

    def _months_since(self, iso_date: str) -> float:
        s = str(iso_date or "").strip()
        if len(s) != 10 or s[4] != "-" or s[7] != "-":
            return 0.0
        try:
            start = datetime.strptime(s, "%Y-%m-%d").date()
        except Exception:
            return 0.0
        today = datetime.now().date()
        if start > today:
            return 0.0
        days = max(0, (today - start).days)
        return float(days) / 30.4375

    def _compute_kpi_data(self) -> dict:
        ref = self._mes_ref
        prev_ref = _month_shift(ref, -1)
        snap = self._fetch_contract_snapshot()
        ativos_total = int(snap.get("ativos_total", 0) or 0)
        mrr = float(snap.get("mrr", 0.0) or 0.0)
        ticket_medio = (mrr / ativos_total) if ativos_total > 0 else 0.0

        conn = db.connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM clientes WHERE substr(COALESCE(data_inicio,''), 1, 7) = ?", (ref,))
            novos_cli = int((cur.fetchone() or [0])[0] or 0)
            cur.execute("SELECT COUNT(*) FROM clientes WHERE substr(COALESCE(data_inicio,''), 1, 7) = ?", (prev_ref,))
            prev_cli = int((cur.fetchone() or [0])[0] or 0)
            cur.execute("SELECT COUNT(*) FROM empresas WHERE substr(COALESCE(data_cadastro,''), 1, 7) = ?", (ref,))
            novas_emp = int((cur.fetchone() or [0])[0] or 0)
            cur.execute("SELECT COUNT(*) FROM empresas WHERE substr(COALESCE(data_cadastro,''), 1, 7) = ?", (prev_ref,))
            prev_emp = int((cur.fetchone() or [0])[0] or 0)
        finally:
            conn.close()

        novos = novos_cli + novas_emp
        novos_prev = prev_cli + prev_emp
        if novos_prev > 0:
            crescimento = ((novos - novos_prev) / float(novos_prev)) * 100.0
        else:
            crescimento = 100.0 if novos > 0 else 0.0

        tempos: list[float] = []
        for c in list(snap.get("clientes_ativos", [])):
            meses = self._months_since(c.get("data_inicio", ""))
            if meses > 0:
                tempos.append(meses)
        for e in list(snap.get("empresas_ativas", [])):
            meses = self._months_since(e.get("data_inicio", ""))
            if meses > 0:
                tempos.append(meses)
        tempo_medio = (sum(tempos) / len(tempos)) if tempos else 0.0
        ltv = ticket_medio * tempo_medio

        inativos = int(snap.get("inativos_total", 0) or 0)
        base_churn = int(len(snap.get("clientes_ativos", [])) + inativos)
        churn = (float(inativos) / float(base_churn) * 100.0) if base_churn > 0 else 0.0

        return {
            "ticket_medio": ticket_medio,
            "crescimento": crescimento,
            "ltv": ltv,
            "churn": churn,
            "mrr": mrr,
            "ativos": ativos_total,
            "novos_mes": novos,
            "novos_mes_anterior": novos_prev,
            "tempo_medio": tempo_medio,
        }

# ── Cartão KPI melhorado ──────────────────────────────────────────────────────
class _KpiCard(QFrame):
    """Cartão de métrica individual com borda superior colorida e animação"""

    def __init__(self, title: str, accent: str = _ACCENT):
        super().__init__()
        self._accent_color = QColor(accent)
        self.setObjectName("finKpiCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(110)  # Aumentado para trend

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 16, 14, 12)
        lay.setSpacing(3)

        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("finKpiTitle")

        self.lbl_value = QLabel("—")
        self.lbl_value.setObjectName("finKpiValue")

        self.lbl_sub = QLabel("")
        self.lbl_sub.setObjectName("finKpiSub")
        self.lbl_sub.setVisible(False)
        
        # NOVO: Widget de tendência
        self.trend = TrendWidget()
        self.trend.setVisible(False)

        lay.addWidget(self.lbl_title)
        lay.addWidget(self.lbl_value)
        lay.addWidget(self.trend)
        lay.addWidget(self.lbl_sub)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self._accent_color)
        p.drawRoundedRect(0, 0, self.width(), 3, 1, 1)
        p.end()

    def set_value(self, text: str):
        self.lbl_value.setText(text)

    def set_sub(self, text: str):
        self.lbl_sub.setText(text)
        self.lbl_sub.setVisible(bool(text))
    
    def set_trend(self, current: float, previous: float):
        """Define tendência comparada ao mês anterior"""
        self.trend.set_trend(current, previous)
        self.trend.setVisible(True)


# ── View principal melhorada ──────────────────────────────────────────────────
class FinanceiroView(QWidget):
    voltar_signal  = Signal()
    refresh_signal = Signal(str)
    query_changed_signal = Signal(dict)
    export_signal  = Signal(str, list, dict)  # MODIFICADO: adiciona dict de config
    contas_refresh_signal = Signal(str)
    contas_query_changed_signal = Signal(dict)
    contas_export_signal = Signal(str, list, dict)
    contas_action_signal = Signal(dict)

    def __init__(self):
        super().__init__()
        self._rows_cache:    list[dict] = []
        self._filtered_rows: list[dict] = []
        self._contas_rows_cache: list[dict] = []
        self._contas_filtered_rows: list[dict] = []
        self._is_loading  = False
        self._contas_is_loading = False
        self._ticket_ref  = 0.0
        self._last_refresh_at = ""
        self._contas_last_refresh_at = ""
        self._previous_month_data = {}  # NOVO: para comparação
        self.nivel_usuario = "—"
        self._contas_page_size = 50
        self._contas_sort_key = "data_vencimento"
        self._contas_sort_dir = "asc"

        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.timeout.connect(self._apply_filter)
        self._contas_filter_timer = QTimer(self)
        self._contas_filter_timer.setSingleShot(True)
        self._contas_filter_timer.timeout.connect(self._apply_contas_filter)
        
        # NOVO: Thread pool para análises
        self.threadpool = QThreadPool.globalInstance()

        self._sans = _load_fonts()
        self._setup_ui()
        self._setup_shortcuts()  # NOVO
        self._apply_styles()
        self.set_month_options(
            self._default_month_options(),
            datetime.now().strftime("%Y-%m"),
        )
        self.set_payload({
            "mes_ref":          datetime.now().strftime("%Y-%m"),
            "receita_total":    0.0,
            "pagamentos":       0,
            "ticket_medio":     0.0,
            "atraso_estimado":  0.0,
            "atrasados_count":  0,
            "daily_series":     [],
            "rows":             [],
        })

    # ── NOVO: Atalhos de teclado ──────────────────────────────────────────────
    def _setup_shortcuts(self):
        """Configura atalhos de teclado"""
        # Ctrl+R - Atualizar
        shortcut_refresh = QShortcut(QKeySequence("Ctrl+R"), self)
        shortcut_refresh.activated.connect(self._emit_refresh)
        
        # Ctrl+E - Exportar
        shortcut_export = QShortcut(QKeySequence("Ctrl+E"), self)
        shortcut_export.activated.connect(self._emit_export)
        
        # Ctrl+F - Focar busca
        shortcut_search = QShortcut(QKeySequence("Ctrl+F"), self)
        shortcut_search.activated.connect(lambda: self.search.setFocus())
        
        # Ctrl+L - Limpar filtros
        shortcut_clear = QShortcut(QKeySequence("Ctrl+L"), self)
        shortcut_clear.activated.connect(self._clear_filters)
        
        # Esc - Voltar
        shortcut_back = QShortcut(QKeySequence("Esc"), self)
        shortcut_back.activated.connect(self.voltar_signal.emit)

    # ── helpers estáticos ─────────────────────────────────────────────────────
    @staticmethod
    def _default_month_options(count: int = 12) -> list[str]:
        y, m = datetime.now().year, datetime.now().month
        out: list[str] = []
        for _ in range(max(1, count)):
            out.append(f"{y:04d}-{m:02d}")
            m -= 1
            if m <= 0:
                m, y = 12, y - 1
        return out

    # ── construção da UI ──────────────────────────────────────────────────────
    def _setup_ui(self):
        self.setObjectName("FinanceiroView")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.main_scroll = QScrollArea()
        self.main_scroll.setObjectName("finScroll")
        self.main_scroll.setWidgetResizable(True)
        self.main_scroll.setFrameShape(QFrame.NoFrame)
        self.main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        page = QWidget()
        page.setObjectName("financeiroPage")
        self.main_scroll.setWidget(page)

        root = QVBoxLayout(page)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # ── cabeçalho ─────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)

        self.lbl_title = QLabel("Financeiro")
        self.lbl_title.setObjectName("pageTitle")

        self.lbl_subtitle = QLabel("Painel financeiro operacional")
        self.lbl_subtitle.setObjectName("pageSubtitle")

        title_col.addWidget(self.lbl_title)
        title_col.addWidget(self.lbl_subtitle)
        hdr.addLayout(title_col)

        self.stamp = QLabel("")
        self.stamp.setObjectName("refreshStamp")
        self.stamp.setVisible(False)
        hdr.addWidget(self.stamp)
        hdr.addStretch()

        # NOVO: Botão de análise
        self.btn_analyze = QPushButton("🔍 Insights")
        self.btn_analyze.setObjectName("btnInfo")
        self.btn_analyze.setFixedHeight(38)
        self.btn_analyze.setToolTip("Análises automáticas dos dados (Ctrl+I)")
        self.btn_analyze.clicked.connect(self._show_insights)

        self.btn_export = QPushButton("↓  Exportar")
        self.btn_export.setObjectName("btnPrimary")
        self.btn_export.setFixedHeight(38)
        self.btn_export.setToolTip("Exportar dados filtrados (Ctrl+E)")
        self.btn_export.clicked.connect(self._emit_export)

        self.btn_refresh = QPushButton("↻  Atualizar")
        self.btn_refresh.setObjectName("btnSecondary")
        self.btn_refresh.setFixedHeight(38)
        self.btn_refresh.setToolTip("Atualizar dados (Ctrl+R)")
        self.btn_refresh.clicked.connect(self._emit_refresh)

        self.btn_voltar = QPushButton("← Voltar")
        self.btn_voltar.setObjectName("btnGhost")
        self.btn_voltar.setFixedHeight(38)
        self.btn_voltar.setToolTip("Voltar ao menu (Esc)")
        self.btn_voltar.clicked.connect(self.voltar_signal.emit)

        hdr.addWidget(self.btn_analyze)
        hdr.addWidget(self.btn_export)
        hdr.addWidget(self.btn_refresh)
        hdr.addWidget(self.btn_voltar)
        root.addLayout(hdr)

        # ── barra de filtros ──────────────────────────────────────────────────
        toolbar = QFrame()
        toolbar.setObjectName("filterBar")
        tl = QVBoxLayout(toolbar)
        tl.setContentsMargins(14, 12, 14, 12)
        tl.setSpacing(10)

        row1 = QHBoxLayout()
        row1.setSpacing(8)

        self.btn_prev_month = QPushButton("‹")
        self.btn_prev_month.setObjectName("monthNav")
        self.btn_prev_month.setFixedSize(32, 36)
        self.btn_prev_month.clicked.connect(self._prev_month)

        self.month_combo = QComboBox()
        self.month_combo.setObjectName("filterCombo")
        self.month_combo.setFixedHeight(36)
        self.month_combo.setMinimumWidth(120)
        self.month_combo.currentIndexChanged.connect(self._emit_refresh)

        self.btn_next_month = QPushButton("›")
        self.btn_next_month.setObjectName("monthNav")
        self.btn_next_month.setFixedSize(32, 36)
        self.btn_next_month.clicked.connect(self._next_month)

        self.status_combo = QComboBox()
        self.status_combo.setObjectName("filterCombo")
        self.status_combo.setFixedHeight(36)
        self.status_combo.setMinimumWidth(180)
        for label, data in [
            ("Todos os status", ""),
            ("Cliente ativo",   "ativo"),
            ("Cliente inativo", "inativo"),
            ("Pagamento em dia","em_dia"),
            ("Pagamento atrasado", "atrasado"),
        ]:
            self.status_combo.addItem(label, data)
        self.status_combo.currentIndexChanged.connect(self._schedule_filter)

        self.search = QLineEdit()
        self.search.setObjectName("filterInput")
        self.search.setPlaceholderText("MAT ou CPF… (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedHeight(36)
        self.search.textChanged.connect(self._schedule_filter)

        self.name_filter = QLineEdit()
        self.name_filter.setObjectName("filterInput")
        self.name_filter.setPlaceholderText("Filtrar por nome…")
        self.name_filter.setClearButtonEnabled(True)
        self.name_filter.setFixedHeight(36)
        self.name_filter.textChanged.connect(self._schedule_filter)

        self.min_value = QLineEdit()
        self.min_value.setObjectName("filterInput")
        self.min_value.setPlaceholderText("Valor mín.")
        self.min_value.setClearButtonEnabled(True)
        self.min_value.setFixedHeight(36)
        self.min_value.setFixedWidth(110)
        self.min_value.textChanged.connect(self._schedule_filter)

        self.max_value = QLineEdit()
        self.max_value.setObjectName("filterInput")
        self.max_value.setPlaceholderText("Valor máx.")
        self.max_value.setClearButtonEnabled(True)
        self.max_value.setFixedHeight(36)
        self.max_value.setFixedWidth(110)
        self.max_value.textChanged.connect(self._schedule_filter)

        self.btn_clear = QPushButton("Limpar")
        self.btn_clear.setObjectName("btnGhost")
        self.btn_clear.setFixedHeight(36)
        self.btn_clear.setToolTip("Limpar todos os filtros (Ctrl+L)")
        self.btn_clear.clicked.connect(self._clear_filters)

        row1.addWidget(self.btn_prev_month)
        row1.addWidget(self.month_combo)
        row1.addWidget(self.btn_next_month)
        row1.addWidget(self.status_combo)
        row1.addWidget(self.search, 1)
        row1.addWidget(self.name_filter, 1)
        row1.addWidget(self.min_value)
        row1.addWidget(self.max_value)
        row1.addWidget(self.btn_clear)
        tl.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)

        self.chip_atrasados = QPushButton("Somente atrasados")
        self.chip_atrasados.setObjectName("chip")
        self.chip_atrasados.setCheckable(True)
        self.chip_atrasados.toggled.connect(self._schedule_filter)

        self.chip_ticket = QPushButton("Acima do ticket")
        self.chip_ticket.setObjectName("chip")
        self.chip_ticket.setCheckable(True)
        self.chip_ticket.toggled.connect(self._schedule_filter)

        self.chip_hoje = QPushButton("Pagamentos de hoje")
        self.chip_hoje.setObjectName("chip")
        self.chip_hoje.setCheckable(True)
        self.chip_hoje.toggled.connect(self._schedule_filter)

        self.filter_summary = QLabel("Sem filtros ativos")
        self.filter_summary.setObjectName("filterSummary")

        row2.addWidget(self.chip_atrasados)
        row2.addWidget(self.chip_ticket)
        row2.addWidget(self.chip_hoje)
        row2.addStretch()
        row2.addWidget(self.filter_summary)
        tl.addLayout(row2)

        root.addWidget(toolbar)

        # ── KPI cards (2 × 2) com gráfico de pizza ────────────────────────────
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)
        
        # Grid de KPIs
        kpi_grid = QGridLayout()
        kpi_grid.setContentsMargins(0, 0, 0, 0)
        kpi_grid.setHorizontalSpacing(12)
        kpi_grid.setVerticalSpacing(12)

        self.kpi_receita    = _KpiCard("Receita no mês",     _ACCENT)
        self.kpi_pagamentos = _KpiCard("Pagamentos",         "#2563eb")
        self.kpi_ticket     = _KpiCard("Ticket médio",       "#7c3aed")
        self.kpi_atraso     = _KpiCard("Atraso estimado",    _DANGER)

        kpi_grid.addWidget(self.kpi_receita,    0, 0)
        kpi_grid.addWidget(self.kpi_pagamentos, 0, 1)
        kpi_grid.addWidget(self.kpi_ticket,     1, 0)
        kpi_grid.addWidget(self.kpi_atraso,     1, 1)
        
        kpi_row.addLayout(kpi_grid, 3)
        
        # NOVO: Card com mini gráfico de pizza
        pie_card = QFrame()
        pie_card.setObjectName("finKpiCard")
        pie_card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        pie_card.setMinimumWidth(200)
        
        pie_layout = QVBoxLayout(pie_card)
        pie_layout.setContentsMargins(14, 16, 14, 12)
        pie_layout.setSpacing(8)
        
        pie_title = QLabel("DISTRIBUIÇÃO")
        pie_title.setObjectName("finKpiTitle")
        pie_layout.addWidget(pie_title)
        
        self.pie_chart = MiniPieChart()
        pie_layout.addWidget(self.pie_chart, 0, Qt.AlignCenter)
        
        self.pie_legend = QLabel("—")
        self.pie_legend.setObjectName("finKpiSub")
        self.pie_legend.setWordWrap(True)
        pie_layout.addWidget(self.pie_legend)
        pie_layout.addStretch()
        
        kpi_row.addWidget(pie_card, 1)
        root.addLayout(kpi_row)

        # ── NOVO: Container de insights ───────────────────────────────────────
        self.insights_container = QFrame()
        self.insights_container.setObjectName("insightsContainer")
        self.insights_container.setVisible(False)
        
        insights_layout = QVBoxLayout(self.insights_container)
        insights_layout.setContentsMargins(0, 0, 0, 0)
        insights_layout.setSpacing(8)
        
        insights_header = QHBoxLayout()
        insights_title = QLabel("💡 Insights Automáticos")
        insights_title.setFont(QFont("Segoe UI", 13, QFont.DemiBold))
        insights_header.addWidget(insights_title)
        insights_header.addStretch()
        
        self.btn_hide_insights = QPushButton("✕")
        self.btn_hide_insights.setObjectName("btnCloseInsights")
        self.btn_hide_insights.setFixedSize(24, 24)
        self.btn_hide_insights.clicked.connect(lambda: self.insights_container.setVisible(False))
        insights_header.addWidget(self.btn_hide_insights)
        
        insights_layout.addLayout(insights_header)
        
        self.insights_list = QVBoxLayout()
        self.insights_list.setSpacing(8)
        insights_layout.addLayout(self.insights_list)
        
        root.addWidget(self.insights_container)

        # ── gráfico ───────────────────────────────────────────────────────────
        self.chart = DailyRevenueChart()
        root.addWidget(self.chart)

        # ── tabela ────────────────────────────────────────────────────────────
        table_card = QFrame()
        table_card.setObjectName("tableCard")
        tw = QVBoxLayout(table_card)
        tw.setContentsMargins(14, 12, 14, 14)
        tw.setSpacing(10)

        tbl_hdr = QHBoxLayout()
        tbl_hdr.setSpacing(8)
        self.table_title = QLabel("Pagamentos do mês")
        self.table_title.setObjectName("sectionTitle")
        self.table_meta  = QLabel("0 registro(s)")
        self.table_meta.setObjectName("tableMeta")
        tbl_hdr.addWidget(self.table_title)
        tbl_hdr.addStretch()
        tbl_hdr.addWidget(self.table_meta)
        tw.addLayout(tbl_hdr)

        self.table = QTableWidget(0, 8)
        self.table.setObjectName("dataTable")
        self.table.setHorizontalHeaderLabels(
            ["Data", "MAT", "Nome", "CPF", "Status", "Pagamento", "Valor", "Mês Ref."]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        hv = self.table.horizontalHeader()
        hv.setHighlightSections(False)
        hv.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(2, QHeaderView.Stretch)
        hv.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.setSortingEnabled(True)
        self.table.setWordWrap(False)
        self.table.setMinimumHeight(170)
        tw.addWidget(self.table, 1)

        self.empty_state = QLabel("Nenhum pagamento encontrado para os filtros selecionados.")
        self.empty_state.setObjectName("emptyState")
        self.empty_state.setAlignment(Qt.AlignCenter)
        self.empty_state.setVisible(False)
        tw.addWidget(self.empty_state)

        root.addWidget(table_card, 1)

        # ── contas a pagar ───────────────────────────────────────────────────
        contas_card = QFrame()
        contas_card.setObjectName("tableCard")
        cw = QVBoxLayout(contas_card)
        cw.setContentsMargins(14, 12, 14, 14)
        cw.setSpacing(10)

        contas_hdr = QHBoxLayout()
        contas_hdr.setSpacing(8)
        self.contas_title = QLabel("Contas a pagar")
        self.contas_title.setObjectName("sectionTitle")
        self.contas_meta = QLabel("0 registro(s)")
        self.contas_meta.setObjectName("tableMeta")
        contas_hdr.addWidget(self.contas_title)
        contas_hdr.addStretch()
        contas_hdr.addWidget(self.contas_meta)
        cw.addLayout(contas_hdr)

        contas_filters = QHBoxLayout()
        contas_filters.setSpacing(8)

        self.contas_status_combo = QComboBox()
        self.contas_status_combo.setObjectName("filterCombo")
        self.contas_status_combo.setFixedHeight(34)
        self.contas_status_combo.setMinimumWidth(160)
        for label, data in [
            ("Todos os status", ""),
            ("Pendente", "pendente"),
            ("Paga", "paga"),
            ("Vencida", "vencida"),
        ]:
            self.contas_status_combo.addItem(label, data)
        self.contas_status_combo.currentIndexChanged.connect(self._schedule_contas_filter)

        self.contas_search = QLineEdit()
        self.contas_search.setObjectName("filterInput")
        self.contas_search.setPlaceholderText("Buscar descrição, fornecedor ou categoria…")
        self.contas_search.setClearButtonEnabled(True)
        self.contas_search.setFixedHeight(34)
        self.contas_search.textChanged.connect(self._schedule_contas_filter)

        self.btn_contas_refresh = QPushButton("↻ Atualizar contas")
        self.btn_contas_refresh.setObjectName("btnSecondary")
        self.btn_contas_refresh.setFixedHeight(34)
        self.btn_contas_refresh.clicked.connect(self._emit_contas_refresh)

        self.btn_contas_nova = QPushButton("+ Registrar conta")
        self.btn_contas_nova.setObjectName("btnPrimary")
        self.btn_contas_nova.setFixedHeight(34)
        self.btn_contas_nova.clicked.connect(self._open_conta_dialog)

        self.btn_contas_editar = QPushButton("✎ Editar conta")
        self.btn_contas_editar.setObjectName("btnSecondary")
        self.btn_contas_editar.setFixedHeight(34)
        self.btn_contas_editar.clicked.connect(self._edit_selected_conta)

        self.btn_contas_pagar = QPushButton("✓ Marcar paga")
        self.btn_contas_pagar.setObjectName("btnSecondary")
        self.btn_contas_pagar.setFixedHeight(34)
        self.btn_contas_pagar.clicked.connect(self._mark_selected_conta_paid)

        self.btn_contas_excluir = QPushButton("🗑 Excluir")
        self.btn_contas_excluir.setObjectName("btnGhost")
        self.btn_contas_excluir.setFixedHeight(34)
        self.btn_contas_excluir.clicked.connect(self._delete_selected_conta)

        self.btn_contas_export = QPushButton("↓ Exportar contas")
        self.btn_contas_export.setObjectName("btnPrimary")
        self.btn_contas_export.setFixedHeight(34)
        self.btn_contas_export.clicked.connect(self._emit_contas_export)

        contas_filters.addWidget(self.contas_status_combo)
        contas_filters.addWidget(self.contas_search, 1)
        contas_filters.addWidget(self.btn_contas_nova)
        contas_filters.addWidget(self.btn_contas_editar)
        contas_filters.addWidget(self.btn_contas_pagar)
        contas_filters.addWidget(self.btn_contas_excluir)
        contas_filters.addWidget(self.btn_contas_refresh)
        contas_filters.addWidget(self.btn_contas_export)
        cw.addLayout(contas_filters)

        self.contas_table = QTableWidget(0, 8)
        self.contas_table.setObjectName("dataTable")
        self.contas_table.setHorizontalHeaderLabels(
            ["Vencimento", "Descrição", "Categoria", "Fornecedor", "Status", "Valor", "Forma Pgto", "Data Pgto"]
        )
        self.contas_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.contas_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.contas_table.setSelectionMode(QTableWidget.SingleSelection)
        self.contas_table.setFocusPolicy(Qt.NoFocus)
        self.contas_table.verticalHeader().setVisible(False)
        self.contas_table.setAlternatingRowColors(True)
        self.contas_table.setShowGrid(False)
        ch = self.contas_table.horizontalHeader()
        ch.setHighlightSections(False)
        ch.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        ch.setSectionResizeMode(1, QHeaderView.Stretch)
        ch.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        ch.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        ch.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        ch.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        ch.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        ch.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.contas_table.setMinimumHeight(170)
        self.contas_table.itemSelectionChanged.connect(self._sync_contas_actions_enabled)
        self.contas_table.itemDoubleClicked.connect(lambda *_: self._edit_selected_conta())
        cw.addWidget(self.contas_table, 1)

        self.contas_empty = QLabel("Nenhuma conta encontrada para os filtros selecionados.")
        self.contas_empty.setObjectName("emptyState")
        self.contas_empty.setAlignment(Qt.AlignCenter)
        self.contas_empty.setVisible(False)
        cw.addWidget(self.contas_empty)

        self.contas_msg = QLabel("")
        self.contas_msg.setObjectName("inlineMsg")
        self.contas_msg.setVisible(False)
        self.contas_msg.setWordWrap(True)
        cw.addWidget(self.contas_msg)

        self.btn_contas_editar.setEnabled(False)
        self.btn_contas_pagar.setEnabled(False)
        self.btn_contas_excluir.setEnabled(False)

        root.addWidget(contas_card, 1)

        # ── mensagem de erro inline ───────────────────────────────────────────
        self.msg = QLabel("")
        self.msg.setObjectName("inlineMsg")
        self.msg.setVisible(False)
        self.msg.setWordWrap(True)
        root.addWidget(self.msg)
        outer.addWidget(self.main_scroll)

    # ── estilos melhorados ────────────────────────────────────────────────────
    def _apply_styles(self):
        f = self._sans
        self.setStyleSheet(f"""
        /* ── raiz ─────────────────────────────────────────────────────── */
        QWidget#FinanceiroView {{
            background: {_BG};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QScrollArea#finScroll {{
            background: {_BG};
            border: none;
        }}
        QWidget#financeiroPage {{
            background: {_BG};
        }}

        /* ── tipografia de cabeçalho ──────────────────────────────────── */
        QLabel#pageTitle {{
            font-size: 22px;
            font-weight: 700;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#pageSubtitle {{
            font-size: 12px;
            color: {_INK2};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#refreshStamp {{
            background: rgba(26,107,124,0.08);
            border: 1px solid rgba(26,107,124,0.20);
            border-radius: 20px;
            padding: 4px 12px;
            font-size: 11px;
            color: {_ACCENT};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}

        /* ── botões ───────────────────────────────────────────────────── */
        QPushButton#btnPrimary {{
            background: {_ACCENT};
            color: white;
            border: none;
            border-radius: 8px;
            padding: 0 18px;
            font-size: 13px;
            font-weight: 600;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QPushButton#btnPrimary:hover   {{ background: {_ACCENT_HOVER}; }}
        QPushButton#btnPrimary:disabled{{ background: #b0c4c8; }}

        QPushButton#btnSecondary {{
            background: {_WHITE};
            color: {_INK};
            border: 1px solid {_LINE};
            border-radius: 8px;
            padding: 0 16px;
            font-size: 13px;
            font-weight: 600;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QPushButton#btnSecondary:hover   {{ border-color: {_ACCENT}; color: {_ACCENT}; }}
        QPushButton#btnSecondary:disabled{{ color: {_INK3}; }}

        QPushButton#btnInfo {{
            background: rgba(37, 99, 235, 0.10);
            color: #2563eb;
            border: 1px solid rgba(37, 99, 235, 0.25);
            border-radius: 8px;
            padding: 0 16px;
            font-size: 13px;
            font-weight: 600;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QPushButton#btnInfo:hover {{
            background: rgba(37, 99, 235, 0.18);
            border-color: #2563eb;
        }}

        QPushButton#btnGhost {{
            background: transparent;
            color: {_INK2};
            border: 1px solid {_LINE};
            border-radius: 8px;
            padding: 0 16px;
            font-size: 13px;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QPushButton#btnGhost:hover {{ color: {_INK}; border-color: #c0c7d0; }}

        QPushButton#btnCloseInsights {{
            background: transparent;
            color: {_INK3};
            border: 1px solid {_LINE};
            border-radius: 12px;
            font-size: 14px;
        }}
        QPushButton#btnCloseInsights:hover {{
            background: rgba(192,57,43,0.1);
            color: {_DANGER};
            border-color: {_DANGER};
        }}

        /* ── barra de filtros ─────────────────────────────────────────── */
        QFrame#filterBar {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 12px;
        }}

        QPushButton#monthNav {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 7px;
            font-size: 18px;
            font-weight: 600;
            color: {_INK2};
        }}
        QPushButton#monthNav:hover    {{ border-color: {_ACCENT}; color: {_ACCENT}; }}
        QPushButton#monthNav:disabled {{ color: {_INK3}; border-color: {_LINE}; }}

        QComboBox#filterCombo {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 8px;
            padding-left: 10px;
            font-size: 13px;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QComboBox#filterCombo:hover  {{ border-color: {_ACCENT}; }}
        QComboBox#filterCombo::drop-down {{ border: none; width: 22px; }}
        QComboBox#filterCombo QAbstractItemView {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            selection-background-color: rgba(26,107,124,0.12);
            border-radius: 8px;
            padding: 4px;
        }}

        QLineEdit#filterInput {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 8px;
            padding-left: 10px;
            font-size: 13px;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLineEdit#filterInput:focus  {{ border-color: {_ACCENT}; }}
        QLineEdit#filterInput:hover  {{ border-color: #c0c7d0; }}

        /* ── chips de filtro rápido ───────────────────────────────────── */
        QPushButton#chip {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 20px;
            padding: 4px 14px;
            font-size: 11px;
            font-weight: 600;
            color: {_INK2};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QPushButton#chip:hover {{
            border-color: {_ACCENT};
            color: {_ACCENT};
        }}
        QPushButton#chip:checked {{
            background: rgba(26,107,124,0.10);
            border: 1.5px solid {_ACCENT};
            color: {_ACCENT};
        }}
        QLabel#filterSummary {{
            background: rgba(15,23,42,0.05);
            border: 1px solid rgba(15,23,42,0.09);
            border-radius: 20px;
            padding: 4px 12px;
            font-size: 11px;
            color: {_INK2};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}

        /* ── KPI cards ────────────────────────────────────────────────── */
        QFrame#finKpiCard {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 12px;
        }}
        QLabel#finKpiTitle {{
            font-size: 11px;
            font-weight: 600;
            color: {_INK2};
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#finKpiValue {{
            font-size: 22px;
            font-weight: 700;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#finKpiSub {{
            font-size: 11px;
            color: {_INK3};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}

        /* ── insights container ───────────────────────────────────────── */
        QFrame#insightsContainer {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 12px;
            padding: 14px;
        }}

        /* ── gráfico ──────────────────────────────────────────────────── */
        QFrame#finChart {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 12px;
        }}
        QLabel#finChartTitle {{
            font-size: 13px;
            font-weight: 600;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#finChartBadge {{
            background: rgba(26,107,124,0.10);
            border: 1px solid rgba(26,107,124,0.20);
            border-radius: 20px;
            padding: 2px 10px;
            font-size: 11px;
            font-weight: 600;
            color: {_ACCENT};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#finChartSub {{
            font-size: 11px;
            color: {_INK2};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}

        /* ── card da tabela ───────────────────────────────────────────── */
        QFrame#tableCard {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 12px;
        }}
        QLabel#sectionTitle {{
            font-size: 14px;
            font-weight: 600;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#tableMeta {{
            font-size: 11px;
            color: {_INK3};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}

        /* ── tabela ───────────────────────────────────────────────────── */
        QTableWidget#dataTable {{
            border: 1px solid {_LINE};
            border-radius: 8px;
            gridline-color: transparent;
            background: {_WHITE};
            alternate-background-color: {_BG};
            selection-background-color: rgba(26,107,124,0.10);
            selection-color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
            font-size: 12px;
        }}
        QTableWidget#dataTable::item {{
            padding: 6px 10px;
            border-bottom: 1px solid rgba(232,234,237,0.6);
        }}
        QTableWidget#dataTable::item:selected {{
            background: rgba(26,107,124,0.10);
        }}
        QTableWidget#dataTable::item:focus {{
            outline: none;
            border: none;
        }}
        QHeaderView::section {{
            background: {_BG};
            border: none;
            border-bottom: 1px solid {_LINE};
            padding: 8px 10px;
            font-size: 11px;
            font-weight: 600;
            color: {_INK2};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QScrollBar:vertical {{
            background: {_BG};
            width: 8px;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical {{
            background: #d0d5dd;
            border-radius: 4px;
            min-height: 24px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {_ACCENT}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

        /* ── estados vazios e mensagens ───────────────────────────────── */
        QLabel#emptyState {{
            background: {_BG};
            border: 1px dashed {_LINE};
            border-radius: 10px;
            padding: 18px;
            font-size: 12px;
            color: {_INK3};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#inlineMsg {{
            background: rgba(192,57,43,0.07);
            border: 1px solid rgba(192,57,43,0.20);
            border-radius: 8px;
            padding: 10px 14px;
            font-size: 12px;
            color: {_DANGER};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        """)

    # ── NOVO: Análises automáticas ────────────────────────────────────────────
    def _show_insights(self):
        """Executa análise e mostra insights"""
        if not self._rows_cache:
            self.show_error("Não há dados suficientes para análise.")
            return
        
        # Limpa insights anteriores
        while self.insights_list.count():
            item = self.insights_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Mostra loading
        loading = QLabel("Analisando dados...")
        loading.setFont(QFont("Segoe UI", 11))
        loading.setStyleSheet(f"color: {_INK2}; padding: 10px;")
        self.insights_list.addWidget(loading)
        self.insights_container.setVisible(True)
        
        # Executa análise em thread
        worker = DataAnalysisWorker(self._rows_cache, self._ticket_ref)
        worker.signals.finished.connect(self._on_analysis_finished)
        self.threadpool.start(worker)
    
    def _on_analysis_finished(self, result: dict):
        """Callback quando análise termina"""
        # Remove loading
        while self.insights_list.count():
            item = self.insights_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        insights = result.get("insights", [])
        
        if not insights:
            no_insights = QLabel("✓ Nenhum ponto de atenção detectado.")
            no_insights.setFont(QFont("Segoe UI", 11))
            no_insights.setStyleSheet(f"color: {_GOOD}; padding: 10px;")
            self.insights_list.addWidget(no_insights)
        else:
            for insight in insights:
                card = InsightCard(
                    insight.get("icon", "ℹ️"),
                    insight.get("title", "Insight"),
                    insight.get("message", ""),
                    insight.get("kind", "info")
                )
                self.insights_list.addWidget(card)

    # ── API pública melhorada ─────────────────────────────────────────────────
    def set_nivel_usuario(self, nivel: str):
        self.nivel_usuario = (nivel or "—").strip()
        self.lbl_subtitle.setText(f"Painel financeiro  ·  Nível: {self.nivel_usuario}")

    def set_month_options(self, months: list[str], current_month: str | None = None):
        current = (current_month or "").strip()
        opts = [m for m in (months or []) if isinstance(m, str) and len(m) == 7]
        if not opts:
            opts = self._default_month_options()

        self.month_combo.blockSignals(True)
        self.month_combo.clear()
        for m in opts:
            self.month_combo.addItem(_iso_to_mes_br(m), m)

        idx = 0
        for i, m in enumerate(opts):
            if m == current:
                idx = i
                break
        self.month_combo.setCurrentIndex(idx)
        self.month_combo.blockSignals(False)
        self._sync_nav()

    def current_month(self) -> str:
        v = self.month_combo.currentData()
        return str(v or datetime.now().strftime("%Y-%m"))

    def _sync_nav(self):
        idx   = self.month_combo.currentIndex()
        total = self.month_combo.count()
        ok    = not self._is_loading and total > 1
        self.btn_prev_month.setEnabled(ok and idx < total - 1)
        self.btn_next_month.setEnabled(ok and idx > 0)

    def current_query(self) -> dict:
        status_key = str(self.status_combo.currentData() or "").strip().lower()
        return {
            "page": 0,
            "page_size": 50,
            "search_doc": (self.search.text() or "").strip(),
            "search_name": (self.name_filter.text() or "").strip(),
            "status_key": status_key,
            "min_value": _parse_money_input(self.min_value.text()),
            "max_value": _parse_money_input(self.max_value.text()),
            "only_atrasados": bool(self.chip_atrasados.isChecked()),
            "above_ticket": bool(self.chip_ticket.isChecked()),
            "ticket_ref": float(self._ticket_ref or 0.0),
            "only_today": bool(self.chip_hoje.isChecked()),
            "sort_key": "data_pagamento",
            "sort_dir": "desc",
        }

    def current_contas_query(self) -> dict:
        status = str(self.contas_status_combo.currentData() or "").strip().lower()
        return {
            "page": 0,
            "page_size": int(self._contas_page_size or 50),
            "search": (self.contas_search.text() or "").strip(),
            "status": status,
            "categoria": "",
            "min_value": None,
            "max_value": None,
            "only_vencidas": status == "vencida",
            "vencem_hoje": False,
            "vencem_7d": False,
            "sort_key": str(self._contas_sort_key or "data_vencimento"),
            "sort_dir": str(self._contas_sort_dir or "asc"),
        }

    def _prev_month(self):
        idx = self.month_combo.currentIndex()
        if idx < self.month_combo.count() - 1:
            self.month_combo.setCurrentIndex(idx + 1)

    def _next_month(self):
        idx = self.month_combo.currentIndex()
        if idx > 0:
            self.month_combo.setCurrentIndex(idx - 1)

    def _schedule_filter(self, *_):
        self._filter_timer.start(140)

    def _schedule_contas_filter(self, *_):
        self._contas_filter_timer.start(160)

    def _clear_filters(self):
        self.status_combo.setCurrentIndex(0)
        self.search.clear()
        self.name_filter.clear()
        self.min_value.clear()
        self.max_value.clear()
        self.chip_atrasados.setChecked(False)
        self.chip_ticket.setChecked(False)
        self.chip_hoje.setChecked(False)
        self._apply_filter()

    def filtered_rows(self) -> list[dict]:
        return list(self._filtered_rows)

    def _emit_refresh(self):
        self._sync_nav()
        self.refresh_signal.emit(self.current_month())
        self.contas_refresh_signal.emit(self.current_month())

    def _emit_contas_refresh(self):
        self.contas_refresh_signal.emit(self.current_month())

    def _emit_export(self):
        """Abre diálogo de exportação avançada"""
        rows = self.filtered_rows()
        if not rows:
            self.show_error("Não há registros filtrados para exportar.")
            return
        
        dialog = ExportDialog(self)
        if dialog.exec() == QDialog.Accepted:
            config = dialog.get_config()
            self.export_signal.emit(self.current_month(), rows, config)

    def _emit_contas_export(self):
        rows = list(self._contas_filtered_rows or self._contas_rows_cache or [])
        if not rows:
            self.show_contas_error("Não há contas filtradas para exportar.")
            return
        config = {
            "source": "contas_pagar",
            "format": "xlsx",
            "columns": ["vencimento", "descricao", "categoria", "fornecedor", "forma_pagto", "status", "valor", "data_pgto"],
            "include_summary": True,
            "include_chart": False,
        }
        self.contas_export_signal.emit(self.current_month(), rows, config)

    def _selected_conta_context(self) -> dict | None:
        row = self.contas_table.currentRow()
        if row < 0:
            return None
        item = self.contas_table.item(row, 0)
        if item is None:
            return None
        data = item.data(Qt.UserRole)
        return dict(data or {}) if isinstance(data, dict) else None

    def _open_conta_dialog(self):
        dlg = ContaRegistroDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        self.contas_action_signal.emit({"action": "save", "payload": dlg.payload()})

    def _edit_selected_conta(self):
        ctx = self._selected_conta_context()
        if not ctx:
            self.show_contas_error("Selecione uma conta para editar.")
            return
        dlg = ContaRegistroDialog(self, conta=ctx)
        if dlg.exec() != QDialog.Accepted:
            return
        self.contas_action_signal.emit({"action": "save", "payload": dlg.payload()})

    def _mark_selected_conta_paid(self):
        ctx = self._selected_conta_context()
        if not ctx:
            self.show_contas_error("Selecione uma conta na tabela para marcar como paga.")
            return
        conta_id = int(ctx.get("id", 0) or 0)
        if conta_id <= 0:
            self.show_contas_error("Conta selecionada inválida.")
            return
        self.contas_action_signal.emit({"action": "pagar", "id": conta_id})

    def _delete_selected_conta(self):
        ctx = self._selected_conta_context()
        if not ctx:
            self.show_contas_error("Selecione uma conta na tabela para excluir.")
            return
        conta_id = int(ctx.get("id", 0) or 0)
        if conta_id <= 0:
            self.show_contas_error("Conta selecionada inválida.")
            return
        desc = str(ctx.get("descricao", "") or "").strip() or f"ID {conta_id}"
        confirm = QMessageBox.question(
            self,
            "Excluir conta",
            f"Deseja excluir a conta \"{desc}\"?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self.contas_action_signal.emit({"action": "delete", "id": conta_id})

    def _sync_contas_actions_enabled(self):
        has_selection = self._selected_conta_context() is not None
        can_act = has_selection and (not self._contas_is_loading)
        self.btn_contas_editar.setEnabled(can_act)
        self.btn_contas_pagar.setEnabled(can_act)
        self.btn_contas_excluir.setEnabled(can_act)

    def set_loading(self, loading: bool):
        self._is_loading = bool(loading)
        for w in [
            self.btn_refresh, self.btn_export, self.btn_voltar, self.btn_analyze,
            self.month_combo, self.btn_prev_month, self.btn_next_month,
            self.status_combo, self.search, self.name_filter,
            self.min_value, self.max_value, self.btn_clear,
            self.chip_atrasados, self.chip_ticket, self.chip_hoje,
        ]:
            w.setEnabled(not self._is_loading)
        self.btn_refresh.setText("Atualizando…" if self._is_loading else "↻  Atualizar")
        self._sync_nav()

    def set_contas_loading(self, loading: bool):
        self._contas_is_loading = bool(loading)
        for w in (
            self.contas_status_combo,
            self.contas_search,
            self.btn_contas_nova,
            self.btn_contas_editar,
            self.btn_contas_pagar,
            self.btn_contas_excluir,
            self.btn_contas_refresh,
            self.btn_contas_export,
        ):
            w.setEnabled(not self._contas_is_loading)
        if self._contas_is_loading:
            self.contas_meta.setText("Atualizando contas…")
        self._sync_contas_actions_enabled()

    def show_contas_error(self, text: str):
        msg = (text or "").strip()
        self.contas_msg.setText(msg)
        self.contas_msg.setVisible(bool(msg))

    def show_error(self, text: str):
        msg = (text or "").strip()
        self.msg.setText(msg)
        self.msg.setVisible(bool(msg))

    def set_payload(self, payload: dict):
        mes_ref       = str(payload.get("mes_ref", "") or self.current_month())
        receita       = float(payload.get("receita_total",   0.0) or 0.0)
        pagamentos    = int(payload.get("pagamentos",        0)   or 0)
        ticket        = float(payload.get("ticket_medio",    0.0) or 0.0)
        atraso        = float(payload.get("atraso_estimado", 0.0) or 0.0)
        atrasados_cnt = int(payload.get("atrasados_count",   0)   or 0)

        self._ticket_ref       = max(0.0, ticket)
        self._last_refresh_at  = datetime.now().strftime("%d/%m/%Y %H:%M")

        # NOVO: Comparação com mês anterior
        prev_data = self._previous_month_data.get(mes_ref, {})
        prev_receita = prev_data.get("receita", 0.0)
        prev_pagamentos = prev_data.get("pagamentos", 0)
        prev_ticket = prev_data.get("ticket", 0.0)

        self.kpi_receita.set_value(br_money(receita))
        self.kpi_receita.set_sub(f"{pagamentos} pagamento(s) no mês")
        self.kpi_receita.set_trend(receita, prev_receita)

        self.kpi_pagamentos.set_value(str(pagamentos))
        self.kpi_pagamentos.set_sub("Registros recebidos")
        self.kpi_pagamentos.set_trend(float(pagamentos), float(prev_pagamentos))

        self.kpi_ticket.set_value(br_money(ticket))
        self.kpi_ticket.set_sub("Referência para filtro rápido")
        self.kpi_ticket.set_trend(ticket, prev_ticket)

        self.kpi_atraso.set_value(br_money(atraso))
        self.kpi_atraso.set_sub(f"{atrasados_cnt} cliente(s) atrasado(s)")

        # NOVO: Atualiza gráfico de pizza
        em_dia = pagamentos - atrasados_cnt
        if pagamentos > 0:
            self.pie_chart.set_data([
                (em_dia, _GOOD, "Em dia"),
                (atrasados_cnt, _DANGER, "Atrasados"),
            ])
            self.pie_legend.setText(
                f"🟢 {em_dia} em dia\n🔴 {atrasados_cnt} atrasados"
            )
        else:
            self.pie_legend.setText("Sem dados")

        # gráfico
        series_raw   = list(payload.get("daily_series", []) or [])
        series_clean: list[tuple[str, float]] = []
        for row in series_raw:
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                d = str(row[0] or "")
                try:    v = float(row[1] or 0.0)
                except: v = 0.0
                series_clean.append((d, v))
            elif isinstance(row, dict):
                d = str(row.get("dia", "") or "")
                try:    v = float(row.get("valor", 0.0) or 0.0)
                except: v = 0.0
                series_clean.append((d, v))
        self.chart.set_series(series_clean, mes_ref)

        # sincroniza combo
        idx = self.month_combo.findData(mes_ref)
        if idx >= 0 and idx != self.month_combo.currentIndex():
            self.month_combo.blockSignals(True)
            self.month_combo.setCurrentIndex(idx)
            self.month_combo.blockSignals(False)
        self._sync_nav()

        mes_label = _iso_to_mes_br(mes_ref)
        self.lbl_subtitle.setText(
            f"Painel financeiro  ·  Nível: {self.nivel_usuario}  ·  {mes_label}"
        )
        self.stamp.setText(f"Atualizado às {self._last_refresh_at}")
        self.stamp.setVisible(True)
        self.chip_ticket.setText(f"Acima do ticket ({br_money(self._ticket_ref)})")

        self.table_title.setText(f"Pagamentos de {mes_label}")
        self._rows_cache = []
        for raw in list(payload.get("rows", []) or []):
            r = dict(raw or {})
            mat_txt = str(r.get("mat", "") or "")
            cpf_txt = str(r.get("cpf", "") or "")
            nome_txt = str(r.get("nome", "") or "")
            data_txt = str(r.get("data_pagamento", "") or "")
            r["__mat_n"] = _norm_text(mat_txt)
            r["__cpf_n"] = _norm_text(cpf_txt)
            r["__nome_n"] = _norm_text(nome_txt)
            r["__mat_d"] = _only_digits(mat_txt)
            r["__cpf_d"] = _only_digits(cpf_txt)
            r["__status_n"] = str(r.get("status", "") or "").strip().lower()
            r["__pag_n"] = str(r.get("pagamento_status", "") or "").strip().lower()
            r["__data_n"] = data_txt
            try:
                r["__valor_n"] = float(r.get("valor_pago", 0.0) or 0.0)
            except Exception:
                r["__valor_n"] = 0.0
            self._rows_cache.append(r)
        
        # Salva para comparação futura
        self._previous_month_data[mes_ref] = {
            "receita": receita,
            "pagamentos": pagamentos,
            "ticket": ticket,
        }
        
        self._apply_filter()
        self.show_error("")

    def set_contas_month_options(self, months: list[str], current_month: str | None = None):
        # Mesma referência mensal entre receitas e contas.
        self.set_month_options(months, current_month)

    def set_contas_payload(self, payload: dict):
        mes_ref = str(payload.get("mes_ref", "") or self.current_month())
        contas_total = int(payload.get("contas_total", 0) or 0)
        valor_total = float(payload.get("despesas_total", payload.get("total_valor", 0.0)) or 0.0)
        self._contas_last_refresh_at = datetime.now().strftime("%d/%m/%Y %H:%M")
        self.contas_title.setText(f"Contas a pagar de {_iso_to_mes_br(mes_ref)}")
        self.contas_meta.setText(f"{contas_total} registro(s)  ·  Total: {br_money(valor_total)}")

        rows = [dict(x or {}) for x in list(payload.get("rows", []) or [])]
        self._contas_rows_cache = rows
        self._apply_contas_filter(emit_remote=False)
        self.show_contas_error("")

    # ── filtro ────────────────────────────────────────────────────────────────
    def _apply_filter(self):
        term_doc_raw  = (self.search.text()      or "").strip()
        term_doc      = _norm_text(term_doc_raw)
        term_doc_dig  = _only_digits(term_doc_raw)
        term_nome_raw = (self.name_filter.text() or "").strip()
        term_nome     = _norm_text(term_nome_raw)
        status_key    = str(self.status_combo.currentData() or "").strip().lower()
        min_val       = _parse_money_input(self.min_value.text())
        max_val       = _parse_money_input(self.max_value.text())
        if min_val is not None and max_val is not None and min_val > max_val:
            min_val, max_val = max_val, min_val

        only_atrasados = self.chip_atrasados.isChecked()
        above_ticket   = self.chip_ticket.isChecked()
        only_today     = self.chip_hoje.isChecked()
        today_iso      = datetime.now().strftime("%Y-%m-%d")

        desc: list[str] = []
        if term_doc_raw:  desc.append(f"doc:{term_doc_raw}")
        if term_nome_raw: desc.append(f"nome:{term_nome_raw}")
        if status_key:    desc.append(f"status:{status_key}")
        if min_val is not None: desc.append(f"mín:{br_money(min_val)}")
        if max_val is not None: desc.append(f"máx:{br_money(max_val)}")
        if only_atrasados: desc.append("atrasados")
        if above_ticket and self._ticket_ref > 0: desc.append("acima ticket")
        if only_today: desc.append("hoje")

        out: list[dict] = []
        for r in self._rows_cache:
            mat_n = str(r.get("__mat_n", "") or "")
            cpf_n = str(r.get("__cpf_n", "") or "")
            mat_d = str(r.get("__mat_d", "") or "")
            cpf_d = str(r.get("__cpf_d", "") or "")
            nome_n = str(r.get("__nome_n", "") or "")
            status = str(r.get("__status_n", "") or "")
            pag_s = str(r.get("__pag_n", "") or "")
            data_pag = str(r.get("__data_n", "") or "").strip()
            try:
                valor = float(r.get("__valor_n", 0.0) or 0.0)
            except Exception:
                valor = 0.0

            if term_doc:
                match = (term_doc in mat_n) or (term_doc in cpf_n)
                if term_doc_dig:
                    match = match or (term_doc_dig in mat_d) or (term_doc_dig in cpf_d)
                if not match:
                    continue
            if term_nome and term_nome not in nome_n:
                continue
            if status_key in {"ativo", "inativo"}   and status != status_key: continue
            if status_key in {"em_dia", "atrasado"}  and pag_s  != status_key: continue
            if only_atrasados and pag_s  != "atrasado":  continue
            if above_ticket   and self._ticket_ref > 0 and valor < self._ticket_ref: continue
            if only_today     and data_pag != today_iso: continue
            if min_val is not None and valor < min_val:  continue
            if max_val is not None and valor > max_val:  continue

            out.append(r)

        self._filtered_rows = out
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(out))
        total_fil = 0.0
        for i, r in enumerate(out):
            status_txt = _status_text(str(r.get("status", "")))
            pag_txt    = _status_text(str(r.get("pagamento_status", "")))
            try:    vp = float(r.get("valor_pago", 0.0) or 0.0)
            except: vp = 0.0
            total_fil += vp

            self._set_cell(i, 0, _date_to_br(str(r.get("data_pagamento", ""))), center=True)
            self._set_cell(i, 1, str(r.get("mat",  "—")), center=True)
            self._set_cell(i, 2, str(r.get("nome", "—")))
            self._set_cell(i, 3, str(r.get("cpf",  "—")), center=True)
            self._set_cell(i, 4, status_txt, center=True, kind="status")
            self._set_cell(i, 5, pag_txt,    center=True, kind="pagamento")
            self._set_cell(i, 6, br_money(vp), center=True, kind="valor", raw=vp)
            self._set_cell(i, 7, _iso_to_mes_br(str(r.get("mes_referencia", ""))), center=True)
            item = self.table.item(i, 0)
            if item:
                item.setToolTip(str(r.get("data_pagamento", "")))

        self.table.setSortingEnabled(True)
        self.empty_state.setVisible(len(out) == 0)
        self.table_meta.setText(
            f"{len(out)} registro(s)  ·  Total: {br_money(total_fil)}"
        )
        self.filter_summary.setText(
            "Sem filtros ativos" if not desc else "  ·  ".join(desc)
        )
        self.btn_export.setEnabled((not self._is_loading) and len(out) > 0)
        if self.msg.isVisible():
            self.show_error("")

    def _apply_contas_filter(self, emit_remote: bool = True):
        term_raw = (self.contas_search.text() or "").strip()
        term = _norm_text(term_raw)
        status_key = str(self.contas_status_combo.currentData() or "").strip().lower()

        out: list[dict] = []
        for r in self._contas_rows_cache:
            desc = _norm_text(str(r.get("descricao", "") or ""))
            cat = _norm_text(str(r.get("categoria", "") or ""))
            forn = _norm_text(str(r.get("fornecedor", "") or ""))
            status = str(r.get("status", "") or "").strip().lower()

            if term and (term not in desc and term not in cat and term not in forn):
                continue
            if status_key and status != status_key:
                continue
            out.append(r)

        self._contas_filtered_rows = out
        self.contas_table.setRowCount(len(out))
        total_fil = 0.0
        for i, r in enumerate(out):
            status_txt = _status_text(str(r.get("status", "")))
            try:
                valor_prev = float(r.get("valor_previsto", 0.0) or 0.0)
            except Exception:
                valor_prev = 0.0
            total_fil += valor_prev

            c0 = QTableWidgetItem(_date_to_br(str(r.get("data_vencimento", ""))))
            c0.setData(Qt.UserRole, dict(r))
            self.contas_table.setItem(i, 0, c0)
            self.contas_table.setItem(i, 1, QTableWidgetItem(str(r.get("descricao", "—") or "—")))
            self.contas_table.setItem(i, 2, QTableWidgetItem(str(r.get("categoria", "—") or "—")))
            self.contas_table.setItem(i, 3, QTableWidgetItem(str(r.get("fornecedor", "—") or "—")))
            c4 = QTableWidgetItem(status_txt)
            low_status = status_txt.lower()
            if "vencida" in low_status:
                c4.setForeground(QColor(_DANGER))
            elif "paga" in low_status:
                c4.setForeground(QColor(_GOOD))
            self.contas_table.setItem(i, 4, c4)
            self.contas_table.setItem(i, 5, QTableWidgetItem(br_money(valor_prev)))
            self.contas_table.setItem(i, 6, QTableWidgetItem(str(r.get("forma_pagamento", "—") or "—")))
            data_pg = str(r.get("data_pagamento_real", "") or "")
            self.contas_table.setItem(i, 7, QTableWidgetItem(_date_to_br(data_pg) if data_pg else "—"))

        self.contas_empty.setVisible(len(out) == 0)
        self.contas_meta.setText(f"{len(out)} registro(s)  ·  Total: {br_money(total_fil)}")
        if len(out) > 0 and self.contas_table.currentRow() < 0:
            self.contas_table.selectRow(0)
        self._sync_contas_actions_enabled()

        if emit_remote:
            self.contas_query_changed_signal.emit(self.current_contas_query())

    def _set_cell(
        self, row: int, col: int, text: str,
        center: bool = False, kind: str = "", raw=None,
    ):
        item = QTableWidgetItem(text)
        if center:
            item.setTextAlignment(Qt.AlignCenter)

        if kind == "status":
            low = text.lower()
            if "ativo" in low and "in" not in low:
                item.setForeground(QColor(_GOOD))
            elif "inativo" in low:
                item.setForeground(QColor(_DANGER))

        elif kind == "pagamento":
            low = text.lower()
            if "em dia" in low:
                item.setForeground(QColor(_GOOD))
            elif "atrasado" in low:
                item.setForeground(QColor(_DANGER))

        elif kind == "valor":
            try:
                numeric = float(raw or 0.0)
            except Exception:
                numeric = 0.0
            if self._ticket_ref > 0 and numeric >= self._ticket_ref:
                item.setForeground(QColor(_ACCENT))
                f = item.font()
                f.setBold(True)
                item.setFont(f)

        self.table.setItem(row, col, item)
