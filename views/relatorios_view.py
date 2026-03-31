from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)


class RelatoriosView(QWidget):
    voltar_signal = Signal()

    def __init__(self):
        super().__init__()
        self._reports_root = Path(".")
        self._rows: list[dict] = []
        self._build_ui()
        self._apply_styles()

    def _build_ui(self):
        self.setObjectName("RelatoriosView")
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)

        self.btn_voltar = QPushButton("<- Voltar")
        self.btn_voltar.setObjectName("btnSecondary")
        self.btn_voltar.setFixedHeight(36)
        self.btn_voltar.clicked.connect(self.voltar_signal.emit)

        self.title = QLabel("Central de Relatórios")
        self.title.setObjectName("title")

        self.subtitle = QLabel("Acompanhe exportações, backups e saídas automáticas do sistema.")
        self.subtitle.setObjectName("subtitle")

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.addWidget(self.title)
        title_col.addWidget(self.subtitle)

        self.btn_refresh = QPushButton("Atualizar")
        self.btn_refresh.setObjectName("btnPrimary")
        self.btn_refresh.setFixedHeight(36)
        self.btn_refresh.clicked.connect(self.reload)

        self.btn_open = QPushButton("Abrir arquivo")
        self.btn_open.setObjectName("btnSecondary")
        self.btn_open.setFixedHeight(36)
        self.btn_open.clicked.connect(self._open_selected_file)

        self.btn_open_folder = QPushButton("Abrir pasta")
        self.btn_open_folder.setObjectName("btnSecondary")
        self.btn_open_folder.setFixedHeight(36)
        self.btn_open_folder.clicked.connect(self._open_selected_folder)

        top.addWidget(self.btn_voltar)
        top.addLayout(title_col, 1)
        top.addWidget(self.btn_open)
        top.addWidget(self.btn_open_folder)
        top.addWidget(self.btn_refresh)
        root.addLayout(top)

        self.root_hint = QLabel("")
        self.root_hint.setObjectName("rootHint")
        root.addWidget(self.root_hint)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        self.kpi_total = self._make_stat_card("Arquivos", "0")
        self.kpi_categorias = self._make_stat_card("Categorias", "0")
        self.kpi_atualizado = self._make_stat_card("Última leitura", "—")
        stats_row.addWidget(self.kpi_total)
        stats_row.addWidget(self.kpi_categorias)
        stats_row.addWidget(self.kpi_atualizado)
        root.addLayout(stats_row)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        self.search = QLineEdit()
        self.search.setObjectName("field")
        self.search.setPlaceholderText("Filtrar por nome, categoria ou caminho...")
        self.search.textChanged.connect(self._apply_filter)

        self.btn_clear = QPushButton("Limpar")
        self.btn_clear.setObjectName("btnSecondary")
        self.btn_clear.setFixedHeight(34)
        self.btn_clear.clicked.connect(self.search.clear)

        filter_row.addWidget(self.search, 1)
        filter_row.addWidget(self.btn_clear)
        root.addLayout(filter_row)

        self.table_title = QLabel("Arquivos e histórico")
        self.table_title.setObjectName("sectionTitle")
        root.addWidget(self.table_title)

        self.table = QTableWidget(0, 5)
        self.table.setObjectName("table")
        self.table.setHorizontalHeaderLabels(["Categoria", "Arquivo", "Modificado", "Tamanho", "Caminho"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.itemDoubleClicked.connect(lambda *_: self._open_selected_file())
        self.table.itemSelectionChanged.connect(self._update_preview)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(340)
        root.addWidget(self.table, 1)

        self.preview_title = QLabel("Pré-visualização")
        self.preview_title.setObjectName("sectionTitle")
        root.addWidget(self.preview_title)

        self.preview = QPlainTextEdit()
        self.preview.setObjectName("preview")
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("Selecione um relatorio para visualizar aqui.")
        self.preview.setMinimumHeight(220)
        root.addWidget(self.preview)

        self.summary = QLabel("Nenhum relatorio carregado.")
        self.summary.setObjectName("summary")
        root.addWidget(self.summary)

    def _make_stat_card(self, label: str, value: str) -> QLabel:
        card = QLabel(f"{label}\n{value}")
        card.setObjectName("statCard")
        card.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        card.setMinimumHeight(62)
        return card

    def _apply_styles(self):
        self.setStyleSheet(
            """
            QWidget#RelatoriosView {
                background: #f1f5f9;
                font-family: Segoe UI, Arial, sans-serif;
            }
            QLabel#title {
                font-size: 22px;
                font-weight: 800;
                color: #0f172a;
            }
            QLabel#sectionTitle {
                font-size: 13px;
                font-weight: 800;
                color: #0f172a;
            }
            QLabel#subtitle {
                font-size: 12px;
                color: #64748b;
                font-weight: 600;
            }
            QLabel#rootHint, QLabel#summary {
                font-size: 12px;
                color: #334155;
                font-weight: 600;
            }
            QLabel#statCard {
                background: white;
                border: 1px solid rgba(15, 23, 42, 0.10);
                border-radius: 12px;
                padding: 10px 12px;
                color: #0f172a;
                font-size: 12px;
                font-weight: 700;
            }
            QLineEdit#field {
                background: white;
                border: 1px solid rgba(15, 23, 42, 0.14);
                border-radius: 10px;
                padding: 7px 10px;
                min-height: 34px;
                color: #0f172a;
            }
            QLineEdit#field:focus {
                border: 1px solid rgba(43, 108, 126, 0.72);
            }
            QTableWidget#table {
                background: white;
                border: 1px solid rgba(15, 23, 42, 0.12);
                border-radius: 12px;
                gridline-color: rgba(15, 23, 42, 0.08);
                color: #0f172a;
                alternate-background-color: #f8fafc;
            }
            QTableWidget#table::item {
                padding: 5px 8px;
            }
            QTableWidget#table::item:selected {
                background: rgba(43, 108, 126, 0.18);
                color: #0f172a;
            }
            QPlainTextEdit#preview {
                background: #f8fafc;
                border: 1px solid rgba(15, 23, 42, 0.12);
                border-radius: 12px;
                padding: 8px;
                color: #0f172a;
                selection-background-color: rgba(43, 108, 126, 0.18);
                font-family: Consolas, "Courier New", monospace;
                font-size: 12px;
            }
            QHeaderView::section {
                background: rgba(43, 108, 126, 0.10);
                border: none;
                border-bottom: 1px solid rgba(15, 23, 42, 0.10);
                padding: 8px;
                color: #0f172a;
                font-weight: 800;
            }
            QPushButton#btnPrimary {
                background: #2b6c7e;
                color: white;
                border: 1px solid rgba(255,255,255,0.24);
                border-radius: 10px;
                padding: 0 12px;
                font-weight: 800;
            }
            QPushButton#btnPrimary:hover { background: #2f768a; }
            QPushButton#btnSecondary {
                background: white;
                color: #0f172a;
                border: 1px solid rgba(15, 23, 42, 0.15);
                border-radius: 10px;
                padding: 0 12px;
                font-weight: 700;
            }
            QPushButton#btnSecondary:hover {
                border-color: rgba(43, 108, 126, 0.60);
                color: #1f5f72;
            }
            """
        )

    @staticmethod
    def _fmt_size(num_bytes: int) -> str:
        size = float(num_bytes or 0)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"

    def set_reports_root(self, root_path: Path | str):
        self._reports_root = Path(root_path).expanduser()
        self.root_hint.setText(f"Pasta base: {self._reports_root}")

    def reload(self):
        root = Path(self._reports_root).expanduser()
        self.root_hint.setText(f"Pasta base: {root}")
        if not root.exists():
            self._rows = []
            self._apply_filter()
            self.summary.setText("Pasta de relatorios ainda nao existe.")
            self.kpi_total.setText("Arquivos\n0")
            self.kpi_categorias.setText("Categorias\n0")
            self.kpi_atualizado.setText("Última leitura\n—")
            return

        rows: list[dict] = []
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            try:
                stat = file_path.stat()
            except Exception:
                continue

            rel = file_path.relative_to(root)
            parts = rel.parts
            categoria = parts[0] if len(parts) > 1 else "geral"
            rows.append(
                {
                    "categoria": categoria,
                    "arquivo": file_path.name,
                    "modificado": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
                    "tamanho": self._fmt_size(int(stat.st_size or 0)),
                    "caminho_rel": str(rel),
                    "caminho_abs": str(file_path),
                    "mtime": float(stat.st_mtime),
                }
            )

        rows.sort(key=lambda r: float(r.get("mtime", 0.0)), reverse=True)
        self._rows = rows
        self._apply_filter()

    def _apply_filter(self):
        query = (self.search.text() or "").strip().lower()
        if query:
            items = [
                r for r in self._rows
                if query in str(r.get("arquivo", "")).lower()
                or query in str(r.get("categoria", "")).lower()
                or query in str(r.get("caminho_rel", "")).lower()
            ]
        else:
            items = list(self._rows)

        self.table.setRowCount(0)
        for row_idx, item in enumerate(items):
            self.table.insertRow(row_idx)

            it_cat = QTableWidgetItem(str(item.get("categoria", "-")))
            it_name = QTableWidgetItem(str(item.get("arquivo", "-")))
            it_date = QTableWidgetItem(str(item.get("modificado", "-")))
            it_size = QTableWidgetItem(str(item.get("tamanho", "-")))
            it_rel = QTableWidgetItem(str(item.get("caminho_rel", "-")))

            it_name.setData(Qt.UserRole, str(item.get("caminho_abs", "")))
            it_date.setTextAlignment(Qt.AlignCenter)
            it_size.setTextAlignment(Qt.AlignCenter)

            self.table.setItem(row_idx, 0, it_cat)
            self.table.setItem(row_idx, 1, it_name)
            self.table.setItem(row_idx, 2, it_date)
            self.table.setItem(row_idx, 3, it_size)
            self.table.setItem(row_idx, 4, it_rel)

        total = len(self._rows)
        visiveis = len(items)
        self.summary.setText(f"Relatorios: {visiveis} visiveis de {total} total.")
        categorias_total = len({str(r.get("categoria", "") or "").strip().lower() for r in self._rows if str(r.get("categoria", "") or "").strip()})
        self.kpi_total.setText(f"Arquivos\n{total}")
        self.kpi_categorias.setText(f"Categorias\n{categorias_total}")
        self.kpi_atualizado.setText(f"Última leitura\n{datetime.now().strftime('%d/%m/%Y %H:%M')}")

        if visiveis > 0:
            self.table.selectRow(0)
            self._update_preview()
        else:
            self.preview.setPlainText("Nenhum arquivo corresponde ao filtro atual.")

    def _selected_file_path(self) -> Path | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 1)
        if not item:
            return None
        path_txt = str(item.data(Qt.UserRole) or "").strip()
        if not path_txt:
            return None
        return Path(path_txt)

    def _open_selected_file(self):
        path = self._selected_file_path()
        if not path:
            QMessageBox.information(self, "Relatorios", "Selecione um relatorio para abrir.")
            return
        if not path.exists():
            QMessageBox.warning(self, "Relatorios", "O arquivo selecionado nao foi encontrado.")
            return
        ok = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        if not ok:
            QMessageBox.warning(self, "Relatorios", "Nao foi possivel abrir o arquivo no sistema.")

    def _open_selected_folder(self):
        path = self._selected_file_path()
        if not path:
            QMessageBox.information(self, "Relatorios", "Selecione um relatorio para abrir a pasta.")
            return
        folder = path.parent
        if not folder.exists():
            QMessageBox.warning(self, "Relatorios", "A pasta do relatorio nao foi encontrada.")
            return
        ok = QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        if not ok:
            QMessageBox.warning(self, "Relatorios", "Nao foi possivel abrir a pasta no sistema.")

    def _update_preview(self):
        path = self._selected_file_path()
        if not path:
            self.preview.setPlainText("Selecione um arquivo para pre-visualizar.")
            return
        if not path.exists():
            self.preview.setPlainText("Arquivo nao encontrado.")
            return

        try:
            stat = path.stat()
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M:%S")
            header = (
                f"Arquivo: {path.name}\n"
                f"Tamanho: {self._fmt_size(int(stat.st_size or 0))}\n"
                f"Modificado: {modified}\n"
                f"Caminho: {path}\n"
                "------------------------------------------------------------\n"
            )
        except Exception:
            header = f"Arquivo: {path.name}\n------------------------------------------------------------\n"

        ext = path.suffix.lower()
        binary_exts = {
            ".pdf", ".xlsx", ".xls", ".docx", ".db", ".dump", ".png",
            ".jpg", ".jpeg", ".gif", ".zip", ".rar", ".7z",
        }
        text_exts = {
            ".txt", ".json", ".jsonl", ".csv", ".md", ".log", ".sql", ".yaml", ".yml", ".ini", ".conf",
        }
        if ext in binary_exts:
            self.preview.setPlainText(
                header
                + "Preview interno indisponivel para este formato.\n"
                + "Use 'Abrir arquivo' para visualizar no app padrao."
            )
            return

        max_bytes = 240_000
        try:
            raw = path.read_bytes()
            clipped = raw[:max_bytes]
        except Exception as exc:
            self.preview.setPlainText(header + f"Nao foi possivel ler o arquivo.\n\nDetalhes: {exc}")
            return

        text = ""
        for enc in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                text = clipped.decode(enc)
                break
            except Exception:
                continue
        if not text:
            self.preview.setPlainText(
                header
                + "Nao foi possivel converter o arquivo para texto legivel.\n"
                + "Use 'Abrir arquivo' para visualizar no app externo."
            )
            return

        if ext == ".json":
            try:
                obj = json.loads(text)
                text = json.dumps(obj, ensure_ascii=False, indent=2)
            except Exception:
                pass

        if ext not in text_exts and ext:
            text = "Formato nao textual identificado. Exibindo tentativa de leitura:\n\n" + text

        if len(raw) > max_bytes:
            text += (
                "\n\n[Preview truncado]\n"
                f"Mostrando os primeiros {max_bytes} bytes de {len(raw)} bytes."
            )
        self.preview.setPlainText(header + text)
