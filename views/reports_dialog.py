from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QComboBox, QLineEdit, QDateEdit, QMessageBox
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QColor


class ReportsDialog(QDialog):
    """
    Dialog profissional para exportações.
    - Tipo:
        * Clientes (com último pagamento)
        * Inadimplentes (pagamento atrasado)
        * Pagamentos (mês) -> usa seu fluxo já existente
        * Pagamentos (período) -> só funciona se existir db.listar_pagamentos_por_periodo(...)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Relatórios & Exportação")
        self.setModal(True)
        self.setMinimumWidth(520)

        self._on_export = None  # callback(tipo, payload_dict)

        self._build()
        self._style()

    def set_export_handler(self, fn):
        self._on_export = fn

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Relatórios & Exportação")
        title.setObjectName("dlgTitle")

        subtitle = QLabel("Escolha o tipo e informe o período.")
        subtitle.setObjectName("dlgSub")

        header_left = QVBoxLayout()
        header_left.setSpacing(2)
        header_left.addWidget(title)
        header_left.addWidget(subtitle)

        header.addLayout(header_left)
        header.addStretch()

        btn_close = QPushButton("Fechar")
        btn_close.setObjectName("btnSecondary")
        btn_close.clicked.connect(self.reject)
        header.addWidget(btn_close)

        root.addLayout(header)

        line = QFrame()
        line.setObjectName("softLine")
        line.setFixedHeight(1)
        root.addWidget(line)

        # Tipo
        row1 = QHBoxLayout()
        self.cbo_tipo = QComboBox()
        self.cbo_tipo.setObjectName("field")
        self.cbo_tipo.addItems([
            "Clientes (último pagamento)",
            "Inadimplentes (atrasados)",
            "Pagamentos (mês)",
            "Pagamentos (período)"
        ])
        self.cbo_tipo.currentIndexChanged.connect(self._refresh_fields)

        row1.addWidget(QLabel("Tipo:"))
        row1.addWidget(self.cbo_tipo, 1)
        root.addLayout(row1)

        # mês
        self.row_mes = QHBoxLayout()
        self.inp_mes = QLineEdit()
        self.inp_mes.setObjectName("field")
        self.inp_mes.setPlaceholderText("AAAA-MM ou JAN/AAAA (ex: 2026-02 ou FEV/2026)")
        self.row_mes.addWidget(QLabel("Mês:"))
        self.row_mes.addWidget(self.inp_mes, 1)
        root.addLayout(self.row_mes)

        # período
        self.row_periodo = QHBoxLayout()
        self.dt_ini = QDateEdit()
        self.dt_ini.setObjectName("field")
        self.dt_ini.setCalendarPopup(True)
        self.dt_ini.setDate(QDate.currentDate().addDays(-30))

        self.dt_fim = QDateEdit()
        self.dt_fim.setObjectName("field")
        self.dt_fim.setCalendarPopup(True)
        self.dt_fim.setDate(QDate.currentDate())

        self.row_periodo.addWidget(QLabel("De:"))
        self.row_periodo.addWidget(self.dt_ini)
        self.row_periodo.addSpacing(10)
        self.row_periodo.addWidget(QLabel("Até:"))
        self.row_periodo.addWidget(self.dt_fim)
        root.addLayout(self.row_periodo)

        # ações
        actions = QHBoxLayout()
        actions.addStretch()

        self.btn_export = QPushButton("Exportar")
        self.btn_export.setObjectName("btnPrimary")
        self.btn_export.setFixedHeight(38)
        self.btn_export.clicked.connect(self._export)
        actions.addWidget(self.btn_export)

        root.addLayout(actions)

        self._refresh_fields()

    def _refresh_fields(self):
        t = self.cbo_tipo.currentText()
        is_mes = (t == "Pagamentos (mês)")
        is_periodo = (t == "Pagamentos (período)")

        self._set_layout_visible(self.row_mes, is_mes)
        self._set_layout_visible(self.row_periodo, is_periodo)

    @staticmethod
    def _set_layout_visible(layout, visible: bool):
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if w:
                w.setVisible(visible)

    def _export(self):
        if not self._on_export:
            QMessageBox.warning(self, "Sem ação", "Handler de exportação não configurado.")
            return

        tipo = self.cbo_tipo.currentText()

        payload = {}
        if tipo == "Pagamentos (mês)":
            mes = (self.inp_mes.text() or "").strip()
            if not mes:
                QMessageBox.warning(self, "Mês obrigatório", "Informe o mês (AAAA-MM ou JAN/AAAA).")
                return
            payload["mes"] = mes

        if tipo == "Pagamentos (período)":
            ini = self.dt_ini.date().toString("yyyy-MM-dd")
            fim = self.dt_fim.date().toString("yyyy-MM-dd")
            payload["ini"] = ini
            payload["fim"] = fim

        self._on_export(tipo, payload)
        self.accept()

    def _style(self):
        self.setStyleSheet("""
        QDialog { background: #f4f6f9; font-family: Segoe UI; }
        QLabel { color: #0f172a; }
        QLabel#dlgTitle { font-size: 16px; font-weight: 900; }
        QLabel#dlgSub { font-size: 12px; color: #64748b; font-weight: 800; }

        QFrame#softLine { background: rgba(15, 23, 42, 0.08); border: none; }

        QLineEdit#field, QComboBox#field, QDateEdit#field {
            background: white;
            border: 1px solid rgba(15, 23, 42, 0.14);
            border-radius: 12px;
            padding: 8px 10px;
            font-weight: 800;
        }

        QPushButton#btnSecondary {
            background: rgba(255,255,255,0.90);
            border: 1px solid rgba(15, 23, 42, 0.12);
            border-radius: 10px;
            padding: 8px 12px;
            font-weight: 900;
        }
        QPushButton#btnSecondary:hover { background: rgba(255,255,255,1.0); }

        QPushButton#btnPrimary {
            background: #2b6c7e;
            border: 1px solid rgba(255,255,255,0.22);
            border-radius: 12px;
            padding: 8px 14px;
            color: white;
            font-weight: 900;
        }
        QPushButton#btnPrimary:hover { background: #2f768a; }
        """)
