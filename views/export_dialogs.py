from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFrame, QProgressBar
)
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from datetime import datetime
import os


class ExportPagamentosDialog(QDialog):
    PRIMARY = "#2b6c7e"
    SECONDARY = "#939598"

    def __init__(self, parent=None, *, default_mes: str = "", count_callback=None):
        super().__init__(parent)

        self._count_callback = count_callback
        self._msg_timer = QTimer(self)
        self._msg_timer.setSingleShot(True)
        self._msg_timer.timeout.connect(self._hide_message)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._refresh_preview)

        self.setWindowTitle("Exportar pagamentos do mês")
        self.setModal(True)
        self.setObjectName("ExportPagamentosDialog")
        self.setFixedSize(460, 270)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title = QLabel("Exportar pagamentos do mês")
        title.setObjectName("dlgTitle")

        sub = QLabel("Informe o mês para exportar. Aceita AAAA-MM ou JAN/AAAA.")
        sub.setObjectName("dlgSub")
        sub.setWordWrap(True)

        root.addWidget(title)
        root.addWidget(sub)

        line = QFrame()
        line.setObjectName("softLine")
        line.setFixedHeight(1)
        root.addWidget(line)

        chips = QHBoxLayout()
        chips.setSpacing(10)

        self.btn_mes_atual = QPushButton("Mês atual")
        self.btn_mes_atual.setObjectName("chipBtn")
        self.btn_mes_atual.setCursor(Qt.PointingHandCursor)
        self.btn_mes_atual.setFixedHeight(34)
        self.btn_mes_atual.clicked.connect(self._set_mes_atual)

        self.btn_mes_anterior = QPushButton("Mês anterior")
        self.btn_mes_anterior.setObjectName("chipBtn")
        self.btn_mes_anterior.setCursor(Qt.PointingHandCursor)
        self.btn_mes_anterior.setFixedHeight(34)
        self.btn_mes_anterior.clicked.connect(self._set_mes_anterior)

        chips.addWidget(self.btn_mes_atual)
        chips.addWidget(self.btn_mes_anterior)
        chips.addStretch(1)
        root.addLayout(chips)

        self.month = QLineEdit()
        self.month.setObjectName("dlgInput")
        self.month.setFixedHeight(40)
        self.month.setPlaceholderText("Ex: 2026-02  ou  FEV/2026")
        self.month.setText(default_mes or "")
        self.month.textChanged.connect(self._on_text_changed)
        root.addWidget(self.month)

        self.preview = QLabel("Encontrados: —")
        self.preview.setObjectName("dlgPreview")
        root.addWidget(self.preview)

        self.inline_msg = QLabel("")
        self.inline_msg.setObjectName("dlgMsg")
        self.inline_msg.setVisible(False)
        root.addWidget(self.inline_msg)

        root.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setObjectName("btnSecondary")
        self.btn_cancel.setFixedHeight(38)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_ok = QPushButton("Exportar")
        self.btn_ok.setObjectName("btnPrimary")
        self.btn_ok.setFixedHeight(38)
        self.btn_ok.clicked.connect(self._on_ok)

        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_ok)
        root.addLayout(btn_row)

        self.apply_styles()
        QTimer.singleShot(0, self._refresh_preview)

    def apply_styles(self):
        self.setStyleSheet(f"""
        QDialog#ExportPagamentosDialog {{
            background: white;
            border-radius: 14px;
            font-family: Segoe UI;
        }}

        QLabel#dlgTitle {{
            font-size: 16px;
            font-weight: 900;
            color: #0f172a;
        }}
        QLabel#dlgSub {{
            font-size: 12px;
            color: {self.SECONDARY};
            font-weight: 700;
        }}

        QFrame#softLine {{
            background: rgba(15, 23, 42, 0.08);
            border: none;
        }}

        QPushButton#chipBtn {{
            background: rgba(43,108,126,0.10);
            border: 1px solid rgba(43,108,126,0.22);
            border-radius: 12px;
            padding: 6px 12px;
            font-weight: 900;
            color: #0f172a;
        }}
        QPushButton#chipBtn:hover {{ background: rgba(43,108,126,0.16); }}
        QPushButton#chipBtn:pressed {{ background: rgba(43,108,126,0.22); }}

        QLineEdit#dlgInput {{
            border: 1px solid rgba(15, 23, 42, 0.14);
            border-radius: 12px;
            padding-left: 12px;
            font-size: 13px;
            background: white;
            color: #0f172a;
        }}
        QLineEdit#dlgInput:focus {{
            border: 1px solid rgba(43,108,126,0.72);
        }}

        QLabel#dlgPreview {{
            font-size: 12px;
            font-weight: 900;
            color: #0f172a;
            padding: 8px 10px;
            border-radius: 12px;
            background: rgba(15, 23, 42, 0.03);
            border: 1px solid rgba(15, 23, 42, 0.08);
        }}

        QLabel#dlgMsg {{
            border-radius: 12px;
            padding: 10px 10px;
            font-size: 12px;
            font-weight: 800;
        }}
        QLabel#dlgMsg[ok="false"] {{
            background: rgba(231, 76, 60, 0.10);
            border: 1px solid rgba(231, 76, 60, 0.25);
            color: #c0392b;
        }}
        QLabel#dlgMsg[ok="true"] {{
            background: rgba(46, 204, 113, 0.10);
            border: 1px solid rgba(46, 204, 113, 0.25);
            color: #166534;
        }}

        QPushButton#btnPrimary {{
            background: {self.PRIMARY};
            color: white;
            border: none;
            border-radius: 12px;
            padding: 6px 14px;
            font-weight: 900;
        }}
        QPushButton#btnPrimary:hover {{ background: #245b6a; }}
        QPushButton#btnPrimary:pressed {{ background: #1f4f5c; }}
        QPushButton#btnPrimary:disabled {{
            background: rgba(147,149,152,0.85);
            color: #ffffff;
        }}

        QPushButton#btnSecondary {{
            background: rgba(255,255,255,0.92);
            border: 1px solid rgba(15, 23, 42, 0.12);
            border-radius: 12px;
            padding: 6px 14px;
            font-weight: 900;
            color: #0f172a;
        }}
        QPushButton#btnSecondary:hover {{ background: rgba(255,255,255,1.0); }}
        """)

    def _show_message(self, text: str, ok: bool = False, ms: int = 2600):
        self.inline_msg.setText(text)
        self.inline_msg.setProperty("ok", ok)
        self.inline_msg.style().unpolish(self.inline_msg)
        self.inline_msg.style().polish(self.inline_msg)
        self.inline_msg.setVisible(True)
        self._msg_timer.start(ms)

    def _hide_message(self):
        self._msg_timer.stop()
        self.inline_msg.setVisible(False)
        self.inline_msg.setText("")
        self.inline_msg.setProperty("ok", False)

    def _on_text_changed(self):
        self._hide_message()
        self._debounce.start(180)

    def _set_mes_atual(self):
        self.month.setText(datetime.now().strftime("%Y-%m"))

    def _set_mes_anterior(self):
        now = datetime.now()
        y = now.year
        m = now.month - 1
        if m == 0:
            m = 12
            y -= 1
        self.month.setText(f"{y}-{m:02d}")

    def _refresh_preview(self):
        mes_raw = (self.month.text() or "").strip()
        try:
            mes_iso = self._normalize_mes(mes_raw)
        except Exception:
            self.preview.setText("Encontrados: —")
            self.btn_ok.setEnabled(False)
            return

        self.btn_ok.setEnabled(True)

        if callable(self._count_callback):
            try:
                n = int(self._count_callback(mes_iso))
                self.preview.setText(f"Encontrados: {n} pagamento(s) em {mes_iso}")
            except Exception:
                self.preview.setText("Encontrados: — (erro ao consultar)")

    def _normalize_mes(self, mes_ref: str) -> str:
        s = (mes_ref or "").strip().upper()

        if len(s) == 7 and s[4] == "-":
            y, m = s.split("-")
            if len(y) == 4 and y.isdigit() and m.isdigit() and 1 <= int(m) <= 12:
                return f"{y}-{int(m):02d}"
            raise ValueError("Mês ISO inválido")

        pt = {
            "JAN": "01", "FEV": "02", "MAR": "03", "ABR": "04", "MAI": "05", "JUN": "06",
            "JUL": "07", "AGO": "08", "SET": "09", "OUT": "10", "NOV": "11", "DEZ": "12",
        }
        if "/" in s:
            mm, yy = s.split("/", 1)
            mm = mm.strip().upper()
            yy = yy.strip()
            if mm in pt and yy.isdigit() and len(yy) == 4:
                return f"{yy}-{pt[mm]}"
            raise ValueError("Mês BR inválido")

        raise ValueError("Formato inválido")

    def _on_ok(self):
        raw = (self.month.text() or "").strip()
        if not raw:
            self._show_message("Informe o mês para exportar.", ok=False)
            self.month.setFocus()
            return

        try:
            _ = self._normalize_mes(raw)
        except Exception:
            self._show_message("Mês inválido. Use AAAA-MM ou JAN/AAAA (ex: FEV/2026).", ok=False)
            self.month.setFocus()
            self.month.selectAll()
            return

        self.accept()

    def get_mes_iso(self) -> str:
        return self._normalize_mes((self.month.text() or "").strip())


class ExportProgressDialog(QDialog):
    PRIMARY = "#2b6c7e"
    SECONDARY = "#939598"

    def __init__(self, parent=None, *, title="Exportando", subtitle="Preparando exportação...", folder_to_open: str | None = None):
        super().__init__(parent)
        self.setModal(True)
        self.setObjectName("ExportProgressDialog")
        self.setFixedSize(520, 250)
        self._cancelled = False
        self._folder = folder_to_open

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("pTitle")

        self.lbl_sub = QLabel(subtitle)
        self.lbl_sub.setObjectName("pSub")
        self.lbl_sub.setWordWrap(True)

        root.addWidget(self.lbl_title)
        root.addWidget(self.lbl_sub)

        line = QFrame()
        line.setObjectName("softLine")
        line.setFixedHeight(1)
        root.addWidget(line)

        self.progress = QProgressBar()
        self.progress.setObjectName("pBar")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(18)
        root.addWidget(self.progress)

        self.lbl_status = QLabel("0%")
        self.lbl_status.setObjectName("pStatus")
        root.addWidget(self.lbl_status)

        self.inline = QLabel("")
        self.inline.setObjectName("pMsg")
        self.inline.setVisible(False)
        root.addWidget(self.inline)

        root.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self.btn_open = QPushButton("Abrir pasta")
        self.btn_open.setObjectName("btnSecondary")
        self.btn_open.setFixedHeight(38)
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self._open_folder)

        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setObjectName("btnDanger")
        self.btn_cancel.setFixedHeight(38)
        self.btn_cancel.clicked.connect(self._on_cancel)

        self.btn_close = QPushButton("Fechar")
        self.btn_close.setObjectName("btnPrimary")
        self.btn_close.setFixedHeight(38)
        self.btn_close.setEnabled(False)
        self.btn_close.clicked.connect(self.accept)

        btn_row.addWidget(self.btn_open)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_close)

        root.addLayout(btn_row)

        self.apply_styles()

    def apply_styles(self):
        self.setStyleSheet(f"""
        QDialog#ExportProgressDialog {{
            background: white;
            border-radius: 14px;
            font-family: Segoe UI;
        }}

        QLabel#pTitle {{
            font-size: 16px;
            font-weight: 900;
            color: #0f172a;
        }}
        QLabel#pSub {{
            font-size: 12px;
            color: {self.SECONDARY};
            font-weight: 700;
        }}

        QFrame#softLine {{
            background: rgba(15, 23, 42, 0.08);
            border: none;
        }}

        QProgressBar#pBar {{
            background: rgba(15, 23, 42, 0.06);
            border: 1px solid rgba(15, 23, 42, 0.10);
            border-radius: 9px;
            text-align: center;
            font-weight: 900;
            color: transparent; /* escondemos o texto padrão */
        }}
        QProgressBar#pBar::chunk {{
            background: {self.PRIMARY};
            border-radius: 9px;
        }}

        QLabel#pStatus {{
            font-size: 12px;
            font-weight: 900;
            color: #0f172a;
        }}

        QLabel#pMsg {{
            border-radius: 12px;
            padding: 10px 10px;
            font-size: 12px;
            font-weight: 800;
        }}
        QLabel#pMsg[ok="true"] {{
            background: rgba(46, 204, 113, 0.10);
            border: 1px solid rgba(46, 204, 113, 0.25);
            color: #166534;
        }}
        QLabel#pMsg[ok="false"] {{
            background: rgba(231, 76, 60, 0.10);
            border: 1px solid rgba(231, 76, 60, 0.25);
            color: #c0392b;
        }}

        QPushButton#btnPrimary {{
            background: {self.PRIMARY};
            color: white;
            border: none;
            border-radius: 12px;
            padding: 6px 14px;
            font-weight: 900;
        }}
        QPushButton#btnPrimary:hover {{ background: #245b6a; }}
        QPushButton#btnPrimary:pressed {{ background: #1f4f5c; }}
        QPushButton#btnPrimary:disabled {{
            background: rgba(147,149,152,0.85);
            color: #ffffff;
        }}

        QPushButton#btnSecondary {{
            background: rgba(255,255,255,0.92);
            border: 1px solid rgba(15, 23, 42, 0.12);
            border-radius: 12px;
            padding: 6px 14px;
            font-weight: 900;
            color: #0f172a;
        }}
        QPushButton#btnSecondary:hover {{ background: rgba(255,255,255,1.0); }}
        QPushButton#btnSecondary:disabled {{
            background: rgba(255,255,255,0.70);
            color: rgba(15,23,42,0.35);
        }}

        QPushButton#btnDanger {{
            background: rgba(231, 76, 60, 0.10);
            border: 1px solid rgba(231, 76, 60, 0.25);
            border-radius: 12px;
            padding: 6px 14px;
            font-weight: 900;
            color: #b91c1c;
        }}
        QPushButton#btnDanger:hover {{ background: rgba(231, 76, 60, 0.16); }}
        """)

    def _on_cancel(self):
        self._cancelled = True
        self.btn_cancel.setEnabled(False)
        self.lbl_sub.setText("Cancelando…")

    def is_cancelled(self) -> bool:
        return self._cancelled

    def set_progress(self, value: int, text: str | None = None):
        value = max(0, min(100, int(value)))
        self.progress.setValue(value)
        self.lbl_status.setText(f"{value}%")
        if text:
            self.lbl_sub.setText(text)

    def finish_success(self, msg: str, folder: str | None = None):
        self._folder = folder or self._folder
        self.inline.setText(msg)
        self.inline.setProperty("ok", True)
        self.inline.style().unpolish(self.inline)
        self.inline.style().polish(self.inline)
        self.inline.setVisible(True)

        self.btn_open.setEnabled(bool(self._folder))
        self.btn_cancel.setEnabled(False)
        self.btn_close.setEnabled(True)

        self.lbl_sub.setText("Concluído ✅")

    def finish_error(self, msg: str):
        self.inline.setText(msg)
        self.inline.setProperty("ok", False)
        self.inline.style().unpolish(self.inline)
        self.inline.style().polish(self.inline)
        self.inline.setVisible(True)

        self.btn_open.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.btn_close.setEnabled(True)

        self.lbl_sub.setText("Falha ❌")

    def _open_folder(self):
        if not self._folder:
            return
        folder = self._folder
        if os.path.isfile(folder):
            folder = os.path.dirname(folder)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))