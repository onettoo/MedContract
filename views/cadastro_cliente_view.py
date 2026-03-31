# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer, QRegularExpression, QUrl
from PySide6.QtGui import QRegularExpressionValidator, QFontDatabase
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QComboBox, QSpinBox, QSizePolicy,
    QScrollArea, QMessageBox, QProgressBar, QDialog, QDoubleSpinBox
)
import database.db as db

# ── Paleta unificada (idêntica ao login / dashboard / financeiro) ─────────────
_ACCENT       = "#1a6b7c"
_ACCENT_HOVER = "#155e6d"
_ACCENT_LIGHT = "rgba(26,107,124,0.10)"
_INK          = "#0c0f12"
_INK2         = "#4a5260"
_INK3         = "#9199a6"
_LINE         = "#e8eaed"
_WHITE        = "#ffffff"
_BG           = "#f9fafb"
_GOOD         = "#16a34a"
_GOOD_BG      = "rgba(22,163,74,0.08)"
_GOOD_BORDER  = "rgba(22,163,74,0.22)"
_DANGER       = "#c0392b"
_DANGER_BG    = "rgba(192,57,43,0.07)"
_DANGER_BORDER= "rgba(192,57,43,0.20)"


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


# ============================================================
# Validators / Helpers
# ============================================================

def only_digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def is_valid_date_ddmmyyyy(s: str) -> tuple[bool, str]:
    s = (s or "").strip()
    if "_" in s or not s:
        return False, "Data obrigatória."
    try:
        dt = datetime.strptime(s, "%d/%m/%Y")
    except Exception:
        return False, "Data inválida. Use dd/mm/aaaa."
    if dt.date() > datetime.now().date():
        return False, "Data não pode ser futura."
    return True, ""


def is_valid_cpf(cpf: str) -> tuple[bool, str]:
    cpf_num = only_digits(cpf)
    if len(cpf_num) != 11:
        return False, "CPF obrigatório e completo."
    if cpf_num == cpf_num[0] * 11:
        return False, "CPF inválido."

    def calc_dv(nums: str) -> str:
        s = 0
        fator = len(nums) + 1
        for ch in nums:
            s += int(ch) * fator
            fator -= 1
        dv = (s * 10) % 11
        return "0" if dv == 10 else str(dv)

    dv1 = calc_dv(cpf_num[:9])
    dv2 = calc_dv(cpf_num[:9] + dv1)
    if cpf_num[-2:] != (dv1 + dv2):
        return False, "CPF inválido."
    return True, ""


# ============================================================
# ViaCEP Service
# ============================================================

def split_legacy_address(text: str) -> tuple[str, str, str]:
    text = (text or "").strip()
    if not text:
        return "", "", ""
    parts = [p.strip() for p in text.split("•") if p.strip()]
    if len(parts) >= 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return text, "", ""


@dataclass(frozen=True)
class AddressData:
    logradouro: str
    bairro: str
    cidade: str
    uf: str

    def is_empty(self) -> bool:
        return not any([self.logradouro, self.bairro, self.cidade, self.uf])


class ViaCepService:
    def __init__(self, parent: QWidget, timeout_ms: int = 4500):
        self._net = QNetworkAccessManager(parent)
        self._timeout_ms = int(timeout_ms)
        self._cache: dict[str, AddressData] = {}
        self._active_reply: QNetworkReply | None = None
        self._timeout_timer = QTimer(parent)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)
        self._last_ctx: dict | None = None

    def clear_cache(self):
        self._cache.clear()

    def abort(self):
        self._timeout_timer.stop()
        if self._active_reply is not None:
            try:
                self._active_reply.abort()
                self._active_reply.deleteLater()
            except Exception:
                pass
        self._active_reply = None
        self._last_ctx = None

    def lookup(self, cep_num: str, on_ok, on_err, on_status=None):
        cep_num = only_digits(cep_num)
        if len(cep_num) != 8:
            on_err("CEP inválido.")
            return
        if cep_num in self._cache:
            if on_status:
                on_status("Endereço carregado do cache.")
            on_ok(self._cache[cep_num])
            return
        self.abort()
        if on_status:
            on_status("Consultando CEP…")
        url = QUrl(f"https://viacep.com.br/ws/{cep_num}/json/")
        self._last_ctx = {
            "cep": cep_num, "on_ok": on_ok, "on_err": on_err,
            "on_status": on_status,
        }
        self._start(url)

    def _start(self, url: QUrl):
        if not self._last_ctx:
            return
        req = QNetworkRequest(url)
        req.setHeader(QNetworkRequest.UserAgentHeader, "MedContract/2.0 (PySide6)")
        self._active_reply = self._net.get(req)
        self._active_reply.finished.connect(self._on_finished)
        self._timeout_timer.start(self._timeout_ms)

    def _on_timeout(self):
        if not self._last_ctx:
            return
        on_err = self._last_ctx["on_err"]
        self.abort()
        on_err("Tempo esgotado ao consultar CEP. Verifique a internet.")

    def _on_finished(self):
        if not self._active_reply or not self._last_ctx:
            return
        reply = self._active_reply
        ctx = self._last_ctx
        self._timeout_timer.stop()
        try:
            if reply.error() != QNetworkReply.NoError:
                err = reply.errorString() or "Erro de rede"
                if "SSL" in err.upper() or "TLS" in err.upper():
                    ctx["on_err"]("Falha de seguranca TLS ao consultar CEP.")
                    return
                ctx["on_err"](f"Falha ao consultar CEP: {err}")
                return
            raw = bytes(reply.readAll()).decode("utf-8", errors="replace").strip()
            if not raw.startswith("{"):
                ctx["on_err"]("Resposta inesperada do ViaCEP.")
                return
            data = json.loads(raw)
            if data.get("erro"):
                ctx["on_err"]("CEP não encontrado.")
                return
            addr = AddressData(
                logradouro=(data.get("logradouro") or "").strip(),
                bairro=(data.get("bairro") or "").strip(),
                cidade=(data.get("localidade") or "").strip(),
                uf=(data.get("uf") or "").strip(),
            )
            if addr.is_empty():
                ctx["on_err"]("CEP consultado, mas endereço veio vazio.")
                return
            self._cache[ctx["cep"]] = addr
            ctx["on_ok"](addr)
        except Exception as e:
            ctx["on_err"](f"Erro ao processar retorno do ViaCEP: {e}")
        finally:
            try:
                reply.deleteLater()
            except Exception:
                pass
            self._active_reply = None
            self._last_ctx = None


# ============================================================
# UI widgets
# ============================================================

class MaskedLineEdit(QLineEdit):
    def _first_edit_pos(self) -> int:
        t = self.displayText() or ""
        i = t.find("_")
        return len(t) if i == -1 else i

    def _goto_first_edit_pos(self):
        self.deselect()
        self.setSelection(0, 0)
        self.setCursorPosition(self._first_edit_pos())
        self.deselect()
        self.setSelection(0, 0)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        QTimer.singleShot(0, self._goto_first_edit_pos)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setFocus()
            QTimer.singleShot(0, self._goto_first_edit_pos)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            QTimer.singleShot(0, self._goto_first_edit_pos)


# ============================================================
# View
# ============================================================

class CadastroClienteView(QWidget):
    voltar_signal = Signal()
    salvar_signal = Signal(dict)
    baixar_contrato_signal = Signal(int)

    DEFAULT_PLANOS = {
        "Classic": {"base": 80.0, "dep": 20.0},
        "Master":  {"base": 100.0, "dep": 40.0},
    }
    PLANOS = {
        "Classic": {"base": 80.0, "dep": 20.0},
        "Master":  {"base": 100.0, "dep": 40.0},
    }
    FORMAS_PAG = ["Boleto", "Pix", "Recepção"]

    def __init__(self):
        super().__init__()

        self.matricula = None
        self.nome = None
        self.cpf = None
        self.telefone = None
        self.email = None
        self.data_nascimento = None
        self.cep = None
        self.logradouro = None
        self.bairro = None
        self.cidade = None
        self.numero = None
        self.uf = None
        self.plano = None
        self.vencimento_dia = None
        self.forma_pagamento = None
        self.valor_mensal = None
        self.resumo_contrato = None
        self.valor_card = None
        self.inline_msg = None
        self.endereco_status = None
        self.dep_pricing_hint = None
        self.form_progress = None
        self.progress_count = None
        self.step_chips: dict[str, QPushButton] = {}
        self.step_meta: dict[str, QLabel] = {}
        self.sidebar_value = None
        self.sidebar_plan = None
        self.sidebar_due = None
        self.sidebar_pay = None
        self.sidebar_status = None
        self.sidebar_deps = None
        self.sidebar_address = None

        self._deps: list[dict] = []
        self.dep_nome = None
        self.dep_cpf = None
        self.dep_data_nascimento = None
        self.dep_list_wrap = None
        self.btn_rascunho = None
        self.btn_carregar_rascunho = None
        self.btn_editar_planos = None
        self.btn_baixar_contrato = None
        self._valor_mensal_manual: float | None = None
        self._last_saved_cliente_id: int | None = None

        self._modo = "create"
        self._edit_id = None
        self._endereco_manual = False
        self._last_cep_filled = ""
        self._address_autofill = False
        self._suspend_dirty = False
        self._dirty = False

        self.on_check_matricula_exists = None
        self.on_find_cliente_por_cpf = None

        self._msg_timer = QTimer(self)
        self._msg_timer.setSingleShot(True)
        self._msg_timer.timeout.connect(self._hide_message)

        self._save_state_timer = QTimer(self)
        self._save_state_timer.setSingleShot(True)
        self._save_state_timer.timeout.connect(self._set_save_ready)

        self._cep_debounce = QTimer(self)
        self._cep_debounce.setSingleShot(True)
        self._cep_debounce.timeout.connect(self._busca_cep)

        self._viacep = ViaCepService(self, timeout_ms=4500)
        self._sans = _load_fonts()
        self.PLANOS = self._load_planos_config()

        self.setup_ui()
        self.apply_styles()
        self._wire_behaviors()
        self._recalc_valor_and_resumo()
        self._refresh_form_progress()
        self._refresh_draft_buttons()
        self._set_clean()

    def _default_planos_copy(self) -> dict:
        return {
            nome: {
                "base": float(cfg.get("base", 0.0) or 0.0),
                "dep": float(cfg.get("dep", 0.0) or 0.0),
            }
            for nome, cfg in self.DEFAULT_PLANOS.items()
        }

    def _load_planos_config(self) -> dict:
        cfg = self._default_planos_copy()
        try:
            db_cfg = db.obter_planos_config() or {}
        except Exception:
            return cfg

        if not isinstance(db_cfg, dict):
            return cfg

        for nome in cfg.keys():
            item = db_cfg.get(nome)
            if not isinstance(item, dict):
                item = db_cfg.get(nome.lower())
            if not isinstance(item, dict):
                continue
            try:
                base = max(0.0, float(item.get("base", cfg[nome]["base"])))
            except Exception:
                base = cfg[nome]["base"]
            try:
                dep = max(0.0, float(item.get("dep", cfg[nome]["dep"])))
            except Exception:
                dep = cfg[nome]["dep"]
            cfg[nome] = {"base": base, "dep": dep}
        return cfg

    def reload_planos_config(self):
        self.PLANOS = self._load_planos_config()
        self._recalc_valor_and_resumo()

    # =========================
    # MODOS
    # =========================
    def set_create_mode(self):
        self._suspend_dirty = True
        try:
            self.PLANOS = self._load_planos_config()
            self._modo = "create"
            self._edit_id = None
            self.title.setText("Novo Contrato")
            self.subtitle.setText("Preencha os dados do cliente e finalize o contrato ao fim.")
            self.btn_salvar.setText("Salvar contrato")
            if self.cpf and "input" in self.cpf:
                self.cpf["input"].setEnabled(True)
            if self.matricula and "input" in self.matricula:
                self.matricula["input"].setEnabled(True)
            self._last_saved_cliente_id = None
            if self.btn_baixar_contrato:
                self.btn_baixar_contrato.setVisible(False)
            self.limpar_campos()
            self._scroll_top()
        finally:
            self._suspend_dirty = False
        self._set_save_ready()
        self._refresh_form_progress()
        self._refresh_draft_buttons()
        self._set_clean()

    def set_edit_mode(self, cliente: dict):
        self._suspend_dirty = True
        try:
            self.PLANOS = self._load_planos_config()
            self._modo = "edit"
            self._edit_id = int(cliente.get("id"))
            self.title.setText("Editar Cliente")
            self.subtitle.setText(f"Editando MAT {self._edit_id}  ·  Revise o contrato antes de salvar.")
            self.btn_salvar.setText("Salvar alterações")

            self.matricula["input"].setText(str(cliente.get("id", "") or ""))
            self.matricula["input"].setEnabled(False)
            self.nome["input"].setText((cliente.get("nome", "") or "").upper())
            self.cpf["input"].setText(cliente.get("cpf", "") or "")
            self.telefone["input"].setText(cliente.get("telefone", "") or "")
            self.email["input"].setText(cliente.get("email", "") or "")

            dn = (cliente.get("data_nascimento") or "").strip()
            if dn and "-" in dn:
                try:
                    y, m, d = dn.split("-")
                    dn = f"{d}/{m}/{y}"
                except Exception:
                    pass
            self.data_nascimento["input"].setText(dn)

            self.cep["input"].setText(cliente.get("cep", "") or "")
            logradouro = (cliente.get("endereco_logradouro", "") or "").strip()
            bairro     = (cliente.get("endereco_bairro", "") or "").strip()
            cidade     = (cliente.get("endereco_cidade", "") or "").strip()

            if not any([logradouro, bairro, cidade]):
                legacy_lbc = (cliente.get("endereco_lbc", "") or "").strip()
                if legacy_lbc:
                    logradouro, bairro, cidade = split_legacy_address(legacy_lbc)
                else:
                    legacy_end = (cliente.get("endereco", "") or "").strip()
                    if "N" in legacy_end:
                        legacy_end = re.split(r"\s+[••].*N.*$", legacy_end, maxsplit=1)[0].strip()
                    logradouro, bairro, cidade = split_legacy_address(legacy_end)

            self.logradouro["input"].setText(logradouro)
            self.bairro["input"].setText(bairro)
            self.cidade["input"].setText(cidade)
            self.numero["input"].setText(cliente.get("endereco_numero", "") or "")
            self.uf["input"].setText(cliente.get("endereco_uf", "") or "")

            self._endereco_manual = True
            self._address_autofill = False
            self._last_cep_filled = only_digits(self.cep["input"].text())

            pl = cliente.get("plano") or "Classic"
            if pl not in self.PLANOS:
                pl = "Classic"
            self.plano["combo"].setCurrentText(pl)

            try:
                vdia = int(cliente.get("vencimento_dia", 10) or 10)
            except Exception:
                vdia = 10
            if str(vdia) not in ("5", "10", "15", "20"):
                vdia = 10
            self.vencimento_dia["combo"].setCurrentText(str(vdia))

            fp = cliente.get("forma_pagamento") or "Boleto"
            if fp not in self.FORMAS_PAG:
                fp = "Boleto"
            self.forma_pagamento["combo"].setCurrentText(fp)

            self.cpf["input"].setEnabled(False)
            self._last_saved_cliente_id = None
            if self.btn_baixar_contrato:
                self.btn_baixar_contrato.setVisible(False)
            self._valor_mensal_manual = None
            self._deps = []
            self._render_dependentes()
            self._hide_message()
            self._set_address_status("")
            self._clear_errors()
            self._recalc_valor_and_resumo()
            self.nome["input"].setFocus()
            self._scroll_top()
        finally:
            self._suspend_dirty = False
        self._set_save_ready()
        self._refresh_form_progress()
        self._refresh_draft_buttons()
        self._set_clean()

    def _sanitize_dependentes(self, deps: list[dict]) -> list[dict]:
        sanitizados = []
        for d in deps or []:
            try:
                nome = (d.get("nome") or "").strip()
                cpf  = (d.get("cpf") or "").strip()
                data_nascimento = self._dep_birth_to_br((d.get("data_nascimento") or "").strip())
                idade = int(d.get("idade") or 0)
                if data_nascimento and "_" not in data_nascimento:
                    ok_dn, _ = is_valid_date_ddmmyyyy(data_nascimento)
                    if ok_dn:
                        idade = self._dep_age_from_br(data_nascimento)
                sanitizados.append({"nome": nome, "cpf": cpf, "data_nascimento": data_nascimento, "idade": idade})
            except Exception:
                continue
        return sanitizados

    def set_dependentes_lista(self, deps: list[dict]):
        self._suspend_dirty = True
        try:
            self._deps = self._sanitize_dependentes(deps or [])
            self._render_dependentes()
            self._recalc_valor_and_resumo()
            self._refresh_form_progress()
        finally:
            self._suspend_dirty = False

    # =========================
    # UI
    # =========================
    def setup_ui(self):
        self.setObjectName("CadastroCliente")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # ── cabeçalho ────────────────────────────────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(12)

        title_wrap = QVBoxLayout()
        title_wrap.setSpacing(2)

        self.title = QLabel("Novo Contrato")
        self.title.setObjectName("pageTitle")

        self.subtitle = QLabel("Preencha os dados do cliente e finalize o contrato ao fim.")
        self.subtitle.setObjectName("pageSubtitle")

        title_wrap.addWidget(self.title)
        title_wrap.addWidget(self.subtitle)
        top.addLayout(title_wrap)
        top.addStretch()

        self.btn_voltar = QPushButton("← Voltar")
        self.btn_voltar.setObjectName("btnGhost")
        self.btn_voltar.setFixedHeight(36)
        self.btn_voltar.setCursor(Qt.PointingHandCursor)
        self.btn_voltar.clicked.connect(self._on_voltar_clicked)
        top.addWidget(self.btn_voltar)
        root.addLayout(top)

        # ── separador ────────────────────────────────────────────────────────
        line = QFrame()
        line.setObjectName("softLine")
        line.setFixedHeight(1)
        root.addWidget(line)

        # ── barra de progresso ───────────────────────────────────────────────
        progress_block = QFrame()
        progress_block.setObjectName("progressBlock")
        pl = QVBoxLayout(progress_block)
        pl.setContentsMargins(16, 14, 16, 14)
        pl.setSpacing(10)

        ptop = QHBoxLayout()
        ptop.setSpacing(10)
        progress_title = QLabel("Etapa do contrato")
        progress_title.setObjectName("progressTitle")
        self.progress_count = QLabel("0/4 etapas")
        self.progress_count.setObjectName("progressCount")
        self.progress_label = QLabel("0% completo")
        self.progress_label.setObjectName("progressValue")
        ptop.addWidget(progress_title)
        ptop.addStretch()
        ptop.addWidget(self.progress_count)
        ptop.addWidget(self.progress_label)
        pl.addLayout(ptop)

        self.form_progress = QProgressBar()
        self.form_progress.setObjectName("formProgress")
        self.form_progress.setRange(0, 100)
        self.form_progress.setTextVisible(False)
        self.form_progress.setFixedHeight(8)
        pl.addWidget(self.form_progress)

        self.step_row = QHBoxLayout()
        self.step_row.setSpacing(8)
        pl.addLayout(self.step_row)
        root.addWidget(progress_block)

        # ── área de conteúdo (scroll + sidebar) ─────────────────────────────
        content_row = QHBoxLayout()
        content_row.setSpacing(14)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("formScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget()
        self.scroll.setWidget(scroll_content)
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 6, 0)
        scroll_layout.setSpacing(14)

        # ── Card: Dados pessoais ─────────────────────────────────────────────
        self.card_pessoais = self._make_card("👤  Dados pessoais")
        c1 = self.card_pessoais["layout"]

        row_mat_nome = QHBoxLayout()
        row_mat_nome.setSpacing(10)
        self.matricula = self._labeled_input("Matrícula", "Ex: 1001")
        self.matricula["input"].setMaxLength(10)
        self.matricula["input"].setValidator(
            QRegularExpressionValidator(QRegularExpression(r"^[0-9]+$"), self)
        )
        self.nome = self._labeled_input("Nome completo", "Ex: João da Silva")
        row_mat_nome.addLayout(self.matricula["layout"], 1)
        row_mat_nome.addLayout(self.nome["layout"], 3)
        c1.addLayout(row_mat_nome)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        self.cpf = self._labeled_input("CPF", "000.000.000-00", use_masked=True)
        self.cpf["input"].setInputMask("000.000.000-00;_")
        self.data_nascimento = self._labeled_input("Data de nascimento", "dd/mm/aaaa", use_masked=True)
        self.data_nascimento["input"].setInputMask("00/00/0000;_")
        row1.addLayout(self.cpf["layout"])
        row1.addLayout(self.data_nascimento["layout"])
        c1.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        self.telefone = self._labeled_input("Telefone", "(00) 00000-0000", use_masked=True)
        self.telefone["input"].setInputMask("(00) 00000-0000;_")
        self.email = self._labeled_input("E-mail (opcional)", "nome@dominio.com")
        self.email["input"].setValidator(
            QRegularExpressionValidator(QRegularExpression(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"), self)
        )
        row2.addLayout(self.telefone["layout"])
        row2.addLayout(self.email["layout"])
        c1.addLayout(row2)

        # ── Card: Endereço ───────────────────────────────────────────────────
        self.card_endereco = self._make_card("📍  Endereço")
        cE = self.card_endereco["layout"]

        row3 = QHBoxLayout()
        row3.setSpacing(10)
        self.cep = self._labeled_input("CEP", "00000-000", use_masked=True)
        self.cep["input"].setInputMask("00000-000;_")
        self.uf = self._labeled_input("UF", "SP")
        self.uf["input"].setMaxLength(2)
        self.uf["input"].setMaximumWidth(90)
        self.uf["input"].setInputMask(">AA;_")
        self.numero = self._labeled_input("Número", "123")
        row3.addLayout(self.cep["layout"])
        row3.addLayout(self.uf["layout"])
        row3.addLayout(self.numero["layout"])
        cE.addLayout(row3)

        self.endereco_status = QLabel("")
        self.endereco_status.setObjectName("addressStatus")
        self.endereco_status.setVisible(False)
        cE.addWidget(self.endereco_status)

        self.logradouro = self._labeled_input("Logradouro", "Ex: Av. Paulista")
        cE.addLayout(self.logradouro["layout"])

        row_end = QHBoxLayout()
        row_end.setSpacing(10)
        self.bairro = self._labeled_input("Bairro", "Ex: Bela Vista")
        self.cidade = self._labeled_input("Cidade", "Ex: São Paulo")
        row_end.addLayout(self.bairro["layout"])
        row_end.addLayout(self.cidade["layout"])
        cE.addLayout(row_end)

        self.cep["input"].textChanged.connect(self._on_cep_changed)
        self.cep["input"].editingFinished.connect(self._busca_cep)
        self.logradouro["input"].textEdited.connect(self._on_endereco_edited)
        self.bairro["input"].textEdited.connect(self._on_endereco_edited)
        self.cidade["input"].textEdited.connect(self._on_endereco_edited)
        self.numero["input"].textEdited.connect(self._on_endereco_edited)
        self.uf["input"].textEdited.connect(self._on_endereco_edited)

        # ── Card: Contrato ───────────────────────────────────────────────────
        self.card_contrato = self._make_card("📄  Contrato")
        c2 = self.card_contrato["layout"]

        contract_hero = QFrame()
        contract_hero.setObjectName("contractHero")
        ch_lay = QVBoxLayout(contract_hero)
        ch_lay.setContentsMargins(16, 14, 16, 14)
        ch_lay.setSpacing(6)

        eyebrow = QLabel("Resumo do contrato")
        eyebrow.setObjectName("contractEyebrow")
        ch_lay.addWidget(eyebrow)

        self.valor_card = QLabel("R$ 0,00")
        self.valor_card.setObjectName("contractValue")
        ch_lay.addWidget(self.valor_card)

        self.resumo_contrato = QLabel("—")
        self.resumo_contrato.setObjectName("contractSummary")
        self.resumo_contrato.setWordWrap(True)
        ch_lay.addWidget(self.resumo_contrato)
        c2.addWidget(contract_hero)

        row4 = QHBoxLayout()
        row4.setSpacing(10)
        self.plano = self._labeled_combo_values("Plano", ["Classic", "Master"])
        self.forma_pagamento = self._labeled_combo_values("Forma de pagamento", self.FORMAS_PAG)
        row4.addLayout(self.plano["layout"])
        row4.addLayout(self.forma_pagamento["layout"])
        c2.addLayout(row4)

        row5 = QHBoxLayout()
        row5.setSpacing(10)
        self.vencimento_dia = self._labeled_combo_values("Dia de vencimento", ["5", "10", "15", "20"])
        row5.addLayout(self.vencimento_dia["layout"])
        row5.addStretch()
        c2.addLayout(row5)

        self.valor_mensal = self._labeled_input("Valor mensal total", "—")
        self.valor_mensal["input"].setReadOnly(True)
        self.valor_mensal["input"].setObjectName("fieldInputReadOnly")
        c2.addLayout(self.valor_mensal["layout"])

        valores_actions = QHBoxLayout()
        valores_actions.setSpacing(8)
        valores_actions.addStretch()
        self.btn_editar_planos = QPushButton("Editar valor total")
        self.btn_editar_planos.setObjectName("btnGhost")
        self.btn_editar_planos.setFixedHeight(34)
        self.btn_editar_planos.setCursor(Qt.PointingHandCursor)
        self.btn_editar_planos.clicked.connect(self._open_valor_total_dialog)
        valores_actions.addWidget(self.btn_editar_planos)
        c2.addLayout(valores_actions)

        # ── Card: Dependentes ────────────────────────────────────────────────
        self.card_dependentes = self._make_card("👥  Dependentes (opcional)")
        c3 = self.card_dependentes["layout"]

        self.dep_pricing_hint = QLabel("")
        self.dep_pricing_hint.setObjectName("depPricingHint")
        self.dep_pricing_hint.setWordWrap(True)
        c3.addWidget(self.dep_pricing_hint)

        dep_row = QHBoxLayout()
        dep_row.setSpacing(10)
        self.dep_nome = self._labeled_input("Nome do dependente", "Ex: Maria da Silva")
        self.dep_cpf = self._labeled_input("CPF do dependente", "000.000.000-00", use_masked=True)
        self.dep_cpf["input"].setInputMask("000.000.000-00;_")
        self.dep_data_nascimento = self._labeled_input("Nascimento do dependente", "dd/mm/aaaa", use_masked=True)
        self.dep_data_nascimento["input"].setInputMask("00/00/0000;_")
        dep_row.addLayout(self.dep_nome["layout"])
        dep_row.addLayout(self.dep_cpf["layout"])
        dep_row.addLayout(self.dep_data_nascimento["layout"])
        c3.addLayout(dep_row)

        dep_actions = QHBoxLayout()
        self.dep_total_hint = QLabel("")
        self.dep_total_hint.setObjectName("depTotalHint")
        dep_actions.addWidget(self.dep_total_hint)
        dep_actions.addStretch()
        self.btn_add_dep = QPushButton("+ Adicionar dependente")
        self.btn_add_dep.setObjectName("btnSecondary")
        self.btn_add_dep.setFixedHeight(36)
        self.btn_add_dep.setCursor(Qt.PointingHandCursor)
        self.btn_add_dep.clicked.connect(self._add_dependente)
        self.dep_nome["input"].returnPressed.connect(self._add_dependente)
        self.dep_cpf["input"].returnPressed.connect(self._add_dependente)
        self.dep_data_nascimento["input"].returnPressed.connect(self._add_dependente)
        dep_actions.addWidget(self.btn_add_dep)
        c3.addLayout(dep_actions)

        self.dep_list_wrap = QVBoxLayout()
        self.dep_list_wrap.setSpacing(8)
        c3.addLayout(self.dep_list_wrap)
        self._render_dependentes()

        # ── Mensagem inline + ações ──────────────────────────────────────────
        self.inline_msg = QLabel("")
        self.inline_msg.setObjectName("inlineMessage")
        self.inline_msg.setVisible(False)
        self.inline_msg.setWordWrap(True)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        self.btn_carregar_rascunho = QPushButton("Carregar rascunho")
        self.btn_carregar_rascunho.setObjectName("btnGhost")
        self.btn_carregar_rascunho.setFixedHeight(40)
        self.btn_carregar_rascunho.setCursor(Qt.PointingHandCursor)
        self.btn_carregar_rascunho.clicked.connect(self._load_draft_if_available)

        self.btn_rascunho = QPushButton("Salvar rascunho")
        self.btn_rascunho.setObjectName("btnGhost")
        self.btn_rascunho.setFixedHeight(40)
        self.btn_rascunho.setCursor(Qt.PointingHandCursor)
        self.btn_rascunho.clicked.connect(self._save_draft)

        self.btn_limpar = QPushButton("Limpar tudo")
        self.btn_limpar.setObjectName("btnDangerSoft")
        self.btn_limpar.setFixedHeight(40)
        self.btn_limpar.setCursor(Qt.PointingHandCursor)
        self.btn_limpar.clicked.connect(self._on_limpar_clicked)

        self.btn_salvar = QPushButton("Salvar contrato")
        self.btn_salvar.setObjectName("btnPrimary")
        self.btn_salvar.setFixedHeight(40)
        self.btn_salvar.setCursor(Qt.PointingHandCursor)
        self.btn_salvar.clicked.connect(self._on_salvar)

        self.btn_baixar_contrato = QPushButton("Gerar e baixar PDF")
        self.btn_baixar_contrato.setObjectName("btnSecondary")
        self.btn_baixar_contrato.setFixedHeight(40)
        self.btn_baixar_contrato.setCursor(Qt.PointingHandCursor)
        self.btn_baixar_contrato.setVisible(False)
        self.btn_baixar_contrato.clicked.connect(self._on_baixar_contrato_clicked)

        actions.addWidget(self.btn_carregar_rascunho)
        actions.addWidget(self.btn_rascunho)
        actions.addStretch()
        actions.addWidget(self.btn_limpar)
        actions.addWidget(self.btn_baixar_contrato)
        actions.addWidget(self.btn_salvar)

        scroll_layout.addWidget(self.card_pessoais["frame"])
        scroll_layout.addWidget(self.card_endereco["frame"])
        scroll_layout.addWidget(self.card_contrato["frame"])
        scroll_layout.addWidget(self.card_dependentes["frame"])
        scroll_layout.addWidget(self.inline_msg)
        scroll_layout.addLayout(actions)
        scroll_layout.addStretch()

        # ── Step chips ───────────────────────────────────────────────────────
        self.step_chips = {
            "pessoais":    self._make_step_chip("1 · 👤 Cliente",      self.card_pessoais["frame"]),
            "endereco":    self._make_step_chip("2 · 📍 Endereço",    self.card_endereco["frame"]),
            "contrato":    self._make_step_chip("3 · 📄 Contrato",    self.card_contrato["frame"]),
            "dependentes": self._make_step_chip("4 · 👥 Dependentes", self.card_dependentes["frame"]),
        }
        for chip in self.step_chips.values():
            self.step_row.addWidget(chip)
        self.step_row.addStretch()

        content_row.addWidget(self.scroll, 1)

        # ── Sidebar ──────────────────────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setObjectName("stickySummary")
        sidebar.setFixedWidth(288)
        sidebar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 18, 18, 18)
        side.setSpacing(10)

        sidebar_eyebrow = QLabel("RESUMO DO CONTRATO")
        sidebar_eyebrow.setObjectName("summaryEyebrow")
        side.addWidget(sidebar_eyebrow)

        self.sidebar_value = QLabel("R$ 0,00")
        self.sidebar_value.setObjectName("summaryValue")
        side.addWidget(self.sidebar_value)

        sep = QFrame()
        sep.setObjectName("softLine")
        sep.setFixedHeight(1)
        side.addWidget(sep)

        for attr, text in [
            ("sidebar_plan",    "Plano: —"),
            ("sidebar_due",     "Vencimento: —"),
            ("sidebar_pay",     "Pagamento: —"),
            ("sidebar_status",  "Status: cálculo automático"),
            ("sidebar_deps",    "Dependentes: 0"),
            ("sidebar_address", "Endereço: —"),
        ]:
            lbl = QLabel(text)
            lbl.setObjectName("summaryLine")
            lbl.setWordWrap(True)
            setattr(self, attr, lbl)
            side.addWidget(lbl)

        side.addStretch()
        content_row.addWidget(sidebar)
        root.addLayout(content_row, 1)

        # ── wiring combos ────────────────────────────────────────────────────
        for combo_dict in (self.plano, self.vencimento_dia, self.forma_pagamento):
            combo_dict["combo"].currentTextChanged.connect(self._recalc_valor_and_resumo)
            combo_dict["combo"].currentIndexChanged.connect(self._mark_dirty)
            combo_dict["combo"].currentIndexChanged.connect(self._refresh_form_progress)

    # ── helpers de UI ─────────────────────────────────────────────────────────
    def _scroll_top(self):
        try:
            self.scroll.verticalScrollBar().setValue(0)
        except Exception:
            pass

    def _address_parts(self) -> tuple[str, str, str]:
        return (
            (self.logradouro["input"].text() or "").strip() if self.logradouro else "",
            (self.bairro["input"].text() or "").strip() if self.bairro else "",
            (self.cidade["input"].text() or "").strip() if self.cidade else "",
        )

    def _compose_lbc(self) -> str:
        return " • ".join(p for p in self._address_parts() if p)

    def _set_address_status(self, text: str, ok: bool = True):
        if not self.endereco_status:
            return
        self.endereco_status.setText(text)
        self.endereco_status.setProperty("ok", ok)
        self.endereco_status.style().unpolish(self.endereco_status)
        self.endereco_status.style().polish(self.endereco_status)
        self.endereco_status.setVisible(bool((text or "").strip()))

    def _set_busy_cep(self, busy: bool, msg: str | None = None):
        for field in (self.logradouro, self.bairro, self.cidade, self.uf):
            if field and "input" in field:
                field["input"].setEnabled(not busy)
        if msg:
            self._set_address_status(msg, ok=True)

    def _set_field_error(self, field: dict | None, text: str):
        if not isinstance(field, dict):
            return
        err = field.get("error_label")
        if err is None:
            return
        err.setText(text)
        err.setVisible(bool((text or "").strip()))

    def _make_card(self, title: str) -> dict:
        frame = QFrame()
        frame.setObjectName("cardBlock")
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)
        t = QLabel(title)
        t.setObjectName("sectionTitle")
        lay.addWidget(t)
        return {"frame": frame, "layout": lay, "title": t}

    def _make_step_chip(self, text: str, target_widget: QWidget) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("stepChip")
        btn.setProperty("baseText", text)
        btn.setProperty("active", False)
        btn.setProperty("done", False)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(32)
        btn.setMinimumWidth(150)
        btn.clicked.connect(lambda: self._scroll_to_widget(target_widget))
        return btn

    def _scroll_to_widget(self, widget: QWidget | None):
        if not widget or not self.scroll:
            return
        try:
            self.scroll.ensureWidgetVisible(widget, 20, 40)
        except Exception:
            pass

    def _mark_dirty(self, *_):
        if self._suspend_dirty:
            return
        self._dirty = True

    def _set_clean(self):
        self._dirty = False

    def has_unsaved_changes(self) -> bool:
        return bool(self._dirty)

    def _on_voltar_clicked(self):
        # UX direto: voltar sem confirmação de rascunho, conforme fluxo solicitado.
        self.voltar_signal.emit()

    def _on_limpar_clicked(self):
        self.set_create_mode()
        self._show_message("Formulário limpo. Pronto para um novo contrato.", ok=True, ms=2200)

    def _draft_path(self) -> Path:
        base = Path(__file__).resolve().parents[1] / "backup"
        return base / "cadastro_cliente_draft.json"

    def _on_endereco_edited(self, _=None):
        self._endereco_manual = True
        self._address_autofill = False
        self._set_address_status("Endereço editado manualmente.", ok=True)
        self._mark_dirty()
        self._refresh_form_progress()

    def _on_cep_changed(self, _=None):
        if not self.cep:
            return
        txt = (self.cep["input"].text() or "").strip()
        if "_" in txt:
            self._set_address_status("")
            return
        cep_num = only_digits(txt)
        if len(cep_num) != 8:
            self._set_address_status("")
            return
        if cep_num != self._last_cep_filled:
            self._endereco_manual = False
            self._set_address_status("Consultando CEP…", ok=True)
        self._cep_debounce.start(350)
        self._refresh_form_progress()

    def _busca_cep(self):
        if not self.cep:
            return
        cep_num = only_digits(self.cep["input"].text() or "")
        if len(cep_num) != 8:
            return
        if self._endereco_manual and cep_num == self._last_cep_filled:
            return

        def on_status(text: str):
            self._set_busy_cep(True, msg=text)

        def on_err(msg: str):
            self._set_busy_cep(False)
            self._set_address_status(msg, ok=False)

        def on_ok(addr: AddressData):
            self._set_busy_cep(False)
            if not self._endereco_manual:
                for field_attr, val in [
                    ("logradouro", addr.logradouro),
                    ("bairro",     addr.bairro),
                    ("cidade",     addr.cidade),
                    ("uf",         addr.uf.upper()),
                ]:
                    f = getattr(self, field_attr, None)
                    if f and "input" in f:
                        f["input"].setText(val.strip())
                self._address_autofill = True
                self._last_cep_filled = cep_num
                self._set_address_status("✓  Endereço preenchido automaticamente pelo CEP.", ok=True)
                if self.numero and "input" in self.numero:
                    self.numero["input"].setFocus()
            self._refresh_form_progress()

        self._viacep.lookup(cep_num=cep_num, on_ok=on_ok, on_err=on_err, on_status=on_status)

    def _refresh_form_progress(self, *_):
        checks = {
            "pessoais":    self._is_step_pessoais_ok(),
            "endereco":    self._is_step_endereco_ok(),
            "contrato":    self._is_step_contrato_ok(),
            "dependentes": self._is_step_dependentes_ok(),
        }
        done = 0
        active_key = next((key for key, ok in checks.items() if not ok), None)
        for key, ok in checks.items():
            chip = self.step_chips.get(key)
            if chip:
                chip.setProperty("done", bool(ok))
                is_active = bool((not ok) and active_key == key)
                chip.setProperty("active", is_active)
                base = str(chip.property("baseText") or chip.text()).replace("✓  ", "")
                chip.setText(f"✓  {base}" if ok else (f"→  {base}" if is_active else base))
                chip.style().unpolish(chip)
                chip.style().polish(chip)
            if ok:
                done += 1
        pct = int(round(done / 4 * 100))
        if self.form_progress:
            self.form_progress.setValue(pct)
        if hasattr(self, "progress_label") and self.progress_label:
            self.progress_label.setText(f"{pct}% completo")
        if self.progress_count:
            self.progress_count.setText(f"{done}/4 etapas")

    def _is_step_pessoais_ok(self) -> bool:
        if self._modo == "create":
            try:
                mat_ok = int((self.matricula["input"].text() or "0").strip()) > 0
            except Exception:
                mat_ok = False
        else:
            mat_ok = True
        nome_ok  = bool((self.nome["input"].text() or "").strip())
        cpf_ok, _ = is_valid_cpf((self.cpf["input"].text() or "").strip())
        dt_ok,  _ = is_valid_date_ddmmyyyy((self.data_nascimento["input"].text() or "").strip())
        tel      = (self.telefone["input"].text() or "").strip()
        tel_ok   = bool(tel) and "_" not in tel
        email    = (self.email["input"].text() or "").strip()
        email_ok = (not email) or bool(self.email["input"].hasAcceptableInput())
        return all([mat_ok, nome_ok, cpf_ok, dt_ok, tel_ok, email_ok])

    def _is_step_endereco_ok(self) -> bool:
        cep_num  = only_digits((self.cep["input"].text() or "").strip())
        log      = (self.logradouro["input"].text() or "").strip()
        bairro   = (self.bairro["input"].text() or "").strip()
        cidade   = (self.cidade["input"].text() or "").strip()
        uf       = (self.uf["input"].text() or "").strip().upper()
        numero   = (self.numero["input"].text() or "").strip()
        num_ok   = bool(numero) and bool(re.match(r"^[0-9A-Za-z\-\/\. ]+$", numero))
        uf_ok    = bool(uf) and "_" not in uf and len(uf) == 2
        return len(cep_num) == 8 and bool(log) and bool(bairro) and bool(cidade) and uf_ok and num_ok

    def _is_step_contrato_ok(self) -> bool:
        return (
            bool((self.plano["combo"].currentText()           or "").strip()) and
            bool((self.forma_pagamento["combo"].currentText() or "").strip()) and
            bool((self.vencimento_dia["combo"].currentText()  or "").strip())
        )

    @staticmethod
    def _dep_birth_to_br(value: str) -> str:
        txt = (value or "").strip()
        if not txt:
            return ""
        if "-" in txt and "/" not in txt:
            try:
                y, m, d = txt.split("-")
                return f"{d}/{m}/{y}"
            except Exception:
                return txt
        return txt

    @staticmethod
    def _dep_birth_to_iso(value: str) -> str:
        txt = (value or "").strip()
        if not txt or "_" in txt:
            return ""
        if "-" in txt and "/" not in txt:
            try:
                datetime.strptime(txt, "%Y-%m-%d")
                return txt
            except Exception:
                return ""
        try:
            return datetime.strptime(txt, "%d/%m/%Y").strftime("%Y-%m-%d")
        except Exception:
            return ""

    @staticmethod
    def _dep_age_from_br(value: str) -> int:
        txt = (value or "").strip()
        if not txt or "_" in txt:
            return 0
        try:
            born  = datetime.strptime(txt, "%d/%m/%Y").date()
            today = datetime.now().date()
            return max(today.year - born.year - ((today.month, today.day) < (born.month, born.day)), 0)
        except Exception:
            return 0

    def _dep_birth_is_valid_or_legacy(self, dep: dict) -> bool:
        dep_dn = self._dep_birth_to_br((dep.get("data_nascimento") or "").strip())
        if dep_dn:
            ok_dn, _ = is_valid_date_ddmmyyyy(dep_dn)
            return ok_dn
        try:
            return int(dep.get("idade") or -1) > 0
        except Exception:
            return False

    def _is_step_dependentes_ok(self) -> bool:
        titular_cpf = only_digits((self.cpf["input"].text() or "").strip())
        seen: set[str] = set()
        for d in self._deps:
            nome     = (d.get("nome") or "").strip()
            cpf_num  = only_digits((d.get("cpf") or "").strip())
            ok_cpf, _ = is_valid_cpf(d.get("cpf", ""))
            if not nome or not ok_cpf or not self._dep_birth_is_valid_or_legacy(d):
                return False
            if cpf_num in seen or (titular_cpf and cpf_num == titular_cpf):
                return False
            seen.add(cpf_num)
        draft_nome    = (self.dep_nome["input"].text() or "").strip()
        draft_cpf_raw = (self.dep_cpf["input"].text() or "").strip()
        draft_cpf_num = only_digits(draft_cpf_raw)
        draft_dn      = self._dep_birth_to_br((self.dep_data_nascimento["input"].text() or "").strip())
        tem_draft     = bool(draft_nome or draft_cpf_num or only_digits(draft_dn))
        if not tem_draft:
            return True
        ok_cpf_d = (False if "_" in draft_cpf_raw else is_valid_cpf(draft_cpf_raw)[0])
        ok_dn_d  = (False if not draft_dn or "_" in draft_dn else is_valid_date_ddmmyyyy(draft_dn)[0])
        return (
            bool(draft_nome) and ok_cpf_d and ok_dn_d
            and draft_cpf_num not in seen
            and (not titular_cpf or draft_cpf_num != titular_cpf)
        )

    def _add_dependente(self):
        self._hide_message()
        self._clear_errors()
        nome           = (self.dep_nome["input"].text() or "").strip()
        cpf            = (self.dep_cpf["input"].text() or "").strip()
        data_nascimento = self._dep_birth_to_br((self.dep_data_nascimento["input"].text() or "").strip())
        titular_cpf    = only_digits((self.cpf["input"].text() or "").strip())

        if not nome:
            self._mark_error(self.dep_nome["input"], self.dep_nome, "Informe o nome do dependente.")
            self.dep_nome["input"].setFocus()
            return
        ok_cpf, msg_cpf = is_valid_cpf(cpf) if "_" not in cpf else (False, "CPF do dependente incompleto.")
        if not ok_cpf:
            self._mark_error(self.dep_cpf["input"], self.dep_cpf, msg_cpf)
            self.dep_cpf["input"].setFocus()
            return
        ok_dn, msg_dn = is_valid_date_ddmmyyyy(data_nascimento)
        if not ok_dn:
            self._mark_error(self.dep_data_nascimento["input"], self.dep_data_nascimento, msg_dn)
            self.dep_data_nascimento["input"].setFocus()
            return
        if titular_cpf and titular_cpf == only_digits(cpf):
            self._mark_error(self.dep_cpf["input"], self.dep_cpf, "CPF do dependente não pode ser igual ao titular.")
            self.dep_cpf["input"].setFocus()
            return
        for d in self._deps:
            if only_digits(d.get("cpf", "")) == only_digits(cpf):
                self._mark_error(self.dep_cpf["input"], self.dep_cpf, "Já existe dependente com esse CPF.")
                self.dep_cpf["input"].setFocus()
                return

        self._deps.append({
            "nome": nome, "cpf": cpf, "data_nascimento": data_nascimento,
            "idade": self._dep_age_from_br(data_nascimento),
        })
        self.dep_nome["input"].clear()
        self.dep_cpf["input"].clear()
        self.dep_data_nascimento["input"].clear()
        self._render_dependentes()
        self._recalc_valor_and_resumo()
        self._mark_dirty()
        self._refresh_form_progress()
        self._show_message("Dependente adicionado.", ok=True)
        try:
            QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(
                self.scroll.verticalScrollBar().maximum()))
        except Exception:
            pass

    def _remove_dependente(self, idx: int):
        try:
            self._deps.pop(idx)
        except Exception:
            return
        self._render_dependentes()
        self._recalc_valor_and_resumo()
        self._mark_dirty()
        self._refresh_form_progress()

    def _clear_layout(self, layout: QVBoxLayout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            else:
                child = item.layout()
                if child is not None:
                    self._clear_layout(child)

    def _render_dependentes(self):
        if not self.dep_list_wrap:
            return
        self._clear_layout(self.dep_list_wrap)
        if not self._deps:
            hint = QLabel("Nenhum dependente adicionado.")
            hint.setObjectName("depHint")
            self.dep_list_wrap.addWidget(hint)
            return

        for i, d in enumerate(self._deps):
            box = QFrame()
            box.setObjectName("depCard")
            outer = QVBoxLayout(box)
            outer.setContentsMargins(12, 10, 12, 10)
            outer.setSpacing(8)

            top_row = QHBoxLayout()
            dep_label = QLabel(f"Dependente {i + 1}")
            dep_label.setObjectName("depText")
            btn_rem = QPushButton("✕  Remover")
            btn_rem.setObjectName("depRemove")
            btn_rem.setCursor(Qt.PointingHandCursor)
            btn_rem.clicked.connect(lambda _=False, ii=i: self._remove_dependente(ii))
            top_row.addWidget(dep_label)
            top_row.addStretch()
            top_row.addWidget(btn_rem)
            outer.addLayout(top_row)

            fields = QHBoxLayout()
            fields.setSpacing(8)

            nome_inp = QLineEdit()
            nome_inp.setObjectName("depInlineInput")
            nome_inp.setPlaceholderText("Nome")
            nome_inp.setFixedHeight(34)
            nome_inp.setText((d.get("nome") or "").strip())
            nome_inp.textEdited.connect(lambda txt, ii=i: self._on_dep_nome_changed(ii, txt))

            cpf_inp = MaskedLineEdit()
            cpf_inp.setObjectName("depInlineInput")
            cpf_inp.setInputMask("000.000.000-00;_")
            cpf_inp.setPlaceholderText("CPF")
            cpf_inp.setFixedHeight(34)
            cpf_inp.setText((d.get("cpf") or "").strip())
            cpf_inp.textEdited.connect(lambda txt, ii=i: self._on_dep_cpf_changed(ii, txt))

            nasc_inp = MaskedLineEdit()
            nasc_inp.setObjectName("depInlineInput")
            nasc_inp.setInputMask("00/00/0000;_")
            nasc_inp.setPlaceholderText("Nascimento")
            nasc_inp.setFixedHeight(34)
            nasc_txt = self._dep_birth_to_br((d.get("data_nascimento") or "").strip())
            if not nasc_txt:
                try:
                    idade_leg = int(d.get("idade") or 0)
                    if idade_leg > 0:
                        nasc_inp.setPlaceholderText(f"Nasc. (idade: {idade_leg})")
                except Exception:
                    pass
            nasc_inp.setText(nasc_txt)
            nasc_inp.textEdited.connect(lambda txt, ii=i: self._on_dep_data_nascimento_changed(ii, txt))

            widgets = {"nome": nome_inp, "cpf": cpf_inp, "data_nascimento": nasc_inp}
            for w_key, w_obj in widgets.items():
                w_obj.editingFinished.connect(
                    lambda ii=i, ws=widgets: self._validate_dependente_idx(ii, show_message=False, widgets=ws)
                )

            fields.addWidget(nome_inp, 2)
            fields.addWidget(cpf_inp, 2)
            fields.addWidget(nasc_inp, 1)
            outer.addLayout(fields)
            self._validate_dependente_idx(i, show_message=False, widgets=widgets)
            self.dep_list_wrap.addWidget(box)

    def _set_dep_inline_error(self, widget: QWidget, has_error: bool):
        widget.setProperty("error", bool(has_error))
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _on_dep_nome_changed(self, idx: int, text: str):
        if idx < len(self._deps):
            self._deps[idx]["nome"] = (text or "").strip()
            self._mark_dirty()
            self._refresh_form_progress()

    def _on_dep_cpf_changed(self, idx: int, text: str):
        if idx < len(self._deps):
            self._deps[idx]["cpf"] = (text or "").strip()
            self._mark_dirty()
            self._refresh_form_progress()

    def _on_dep_data_nascimento_changed(self, idx: int, text: str):
        if idx >= len(self._deps):
            return
        dn = self._dep_birth_to_br(text)
        self._deps[idx]["data_nascimento"] = dn
        if not dn or "_" in dn:
            self._deps[idx]["idade"] = 0
        else:
            ok_dn, _ = is_valid_date_ddmmyyyy(dn)
            self._deps[idx]["idade"] = self._dep_age_from_br(dn) if ok_dn else 0
        self._mark_dirty()
        self._recalc_valor_and_resumo()
        self._refresh_form_progress()

    def _validate_dependente_idx(self, idx: int, show_message: bool = False, widgets: dict | None = None) -> bool:
        if idx >= len(self._deps):
            return False
        d = self._deps[idx]
        nome   = (d.get("nome") or "").strip()
        cpf    = (d.get("cpf") or "").strip()
        dn     = self._dep_birth_to_br((d.get("data_nascimento") or "").strip())
        d["data_nascimento"] = dn
        try:
            idade_leg = int(d.get("idade") or 0)
        except Exception:
            idade_leg = 0
        titular_cpf = only_digits((self.cpf["input"].text() or "").strip())
        cpf_num = only_digits(cpf)
        ok_cpf, msg_cpf = is_valid_cpf(cpf) if "_" not in cpf else (False, "CPF incompleto.")

        msg = campo = ""
        if not nome:
            msg, campo = "Nome do dependente é obrigatório.", "nome"
        elif not ok_cpf:
            msg, campo = msg_cpf, "cpf"
        elif dn:
            ok_dn, msg_dn = is_valid_date_ddmmyyyy(dn)
            if not ok_dn:
                msg, campo = msg_dn, "data_nascimento"
            else:
                d["idade"] = self._dep_age_from_br(dn)
        elif idade_leg <= 0:
            msg, campo = "Data de nascimento obrigatória.", "data_nascimento"
        elif titular_cpf and cpf_num == titular_cpf:
            msg, campo = "CPF não pode ser igual ao titular.", "cpf"
        else:
            for j, dep in enumerate(self._deps):
                if j != idx and only_digits(dep.get("cpf", "")) == cpf_num and cpf_num:
                    msg, campo = "CPF duplicado.", "cpf"
                    break

        if widgets:
            for key in ("nome", "cpf", "data_nascimento"):
                w = widgets.get(key)
                if w:
                    self._set_dep_inline_error(w, key == campo and bool(msg))
        if msg and show_message:
            self._show_message(msg, ok=False)
        return not bool(msg)

    def _labeled_input(self, label: str, placeholder: str, use_masked: bool = False):
        wrapper = QVBoxLayout()
        wrapper.setSpacing(5)
        lab = QLabel(label)
        lab.setObjectName("fieldLabel")
        inp = MaskedLineEdit() if use_masked else QLineEdit()
        inp.setObjectName("fieldInput")
        inp.setPlaceholderText(placeholder)
        inp.setFixedHeight(40)
        inp.textChanged.connect(self._clear_errors)
        inp.textEdited.connect(self._mark_dirty)
        inp.textEdited.connect(self._refresh_form_progress)
        err = QLabel("")
        err.setObjectName("fieldError")
        err.setVisible(False)
        wrapper.addWidget(lab)
        wrapper.addWidget(inp)
        wrapper.addWidget(err)
        return {"layout": wrapper, "label": lab, "input": inp, "error_label": err}

    def _labeled_combo_values(self, label: str, items: list[str]):
        wrapper = QVBoxLayout()
        wrapper.setSpacing(5)
        lab = QLabel(label)
        lab.setObjectName("fieldLabel")
        cb = QComboBox()
        cb.setObjectName("saasCombo")
        cb.setFixedHeight(40)
        cb.addItems(items)
        cb.currentIndexChanged.connect(self._clear_errors)
        cb.currentIndexChanged.connect(self._mark_dirty)
        cb.currentIndexChanged.connect(self._refresh_form_progress)
        err = QLabel("")
        err.setObjectName("fieldError")
        err.setVisible(False)
        wrapper.addWidget(lab)
        wrapper.addWidget(cb)
        wrapper.addWidget(err)
        return {"layout": wrapper, "label": lab, "combo": cb, "error_label": err}

    def _labeled_spin(self, label: str, mn: int, mx: int, default: int):
        wrapper = QVBoxLayout()
        wrapper.setSpacing(5)
        lab = QLabel(label)
        lab.setObjectName("fieldLabel")
        sp = QSpinBox()
        sp.setObjectName("pillSpin")
        sp.setFixedHeight(40)
        sp.setRange(mn, mx)
        sp.setValue(default)
        sp.valueChanged.connect(self._clear_errors)
        sp.valueChanged.connect(self._mark_dirty)
        sp.valueChanged.connect(self._refresh_form_progress)
        err = QLabel("")
        err.setObjectName("fieldError")
        err.setVisible(False)
        wrapper.addWidget(lab)
        wrapper.addWidget(sp)
        wrapper.addWidget(err)
        return {"layout": wrapper, "label": lab, "spin": sp, "error_label": err}

    def _inputs_existentes(self):
        out = []
        for attr in ("matricula","nome","cpf","data_nascimento","telefone",
                     "email","cep","logradouro","bairro","cidade","numero","uf"):
            obj = getattr(self, attr, None)
            if isinstance(obj, dict) and "input" in obj:
                out.append(obj["input"])
        return out

    def _wire_behaviors(self):
        ordem = [
            self.matricula["input"], self.nome["input"], self.cpf["input"],
            self.data_nascimento["input"], self.telefone["input"], self.email["input"],
            self.cep["input"], self.uf["input"], self.logradouro["input"],
            self.bairro["input"], self.cidade["input"], self.numero["input"],
        ]
        for i, w in enumerate(ordem):
            w.returnPressed.connect(lambda i=i: self._focus_next(ordem, i))

        self.matricula["input"].editingFinished.connect(lambda: self._validate_matricula_field(show_message=False, check_duplicate=True))
        self.nome["input"].textEdited.connect(self._force_nome_uppercase)
        self.nome["input"].editingFinished.connect(lambda: self._validate_text_required(self.nome, "Nome é obrigatório.", show_message=False))
        self.cpf["input"].editingFinished.connect(lambda: self._validate_cpf_field(show_message=False, check_duplicate=True))
        self.data_nascimento["input"].editingFinished.connect(lambda: self._validate_data_field(show_message=False))
        self.telefone["input"].editingFinished.connect(lambda: self._validate_telefone_field(show_message=False))
        self.email["input"].editingFinished.connect(lambda: self._validate_email_field(show_message=False))
        self.cep["input"].editingFinished.connect(lambda: self._validate_cep_field(show_message=False))
        self.logradouro["input"].editingFinished.connect(lambda: self._validate_text_required(self.logradouro, "Logradouro obrigatório.", show_message=False))
        self.bairro["input"].editingFinished.connect(lambda: self._validate_text_required(self.bairro, "Bairro obrigatório.", show_message=False))
        self.cidade["input"].editingFinished.connect(lambda: self._validate_text_required(self.cidade, "Cidade obrigatória.", show_message=False))
        self.uf["input"].editingFinished.connect(lambda: self._validate_uf_field(show_message=False))
        self.numero["input"].editingFinished.connect(lambda: self._validate_numero_field(show_message=False))

    def _force_nome_uppercase(self, text: str):
        if not self.nome or "input" not in self.nome:
            return
        field = self.nome["input"]
        original = str(text or "")
        upper = original.upper()
        if original == upper:
            return
        pos = int(field.cursorPosition() or 0)
        field.blockSignals(True)
        try:
            field.setText(upper)
            field.setCursorPosition(min(pos, len(upper)))
        finally:
            field.blockSignals(False)
        self._mark_dirty()
        self._refresh_form_progress()

    def _focus_next(self, ordem, idx):
        if idx + 1 < len(ordem):
            ordem[idx + 1].setFocus()
        else:
            self._on_salvar()

    def _clear_widget_error(self, widget: QWidget | None):
        if widget and widget.property("error"):
            widget.setProperty("error", False)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _set_field_valid(self, field: dict | None):
        if not isinstance(field, dict):
            return
        widget = field.get("input") or field.get("combo") or field.get("spin")
        self._clear_widget_error(widget)
        self._set_field_error(field, "")

    def _invalidate_field(self, field: dict | None, msg: str, show_message: bool = False, focus: bool = False) -> bool:
        if not isinstance(field, dict):
            return False
        widget = field.get("input") or field.get("combo") or field.get("spin")
        if widget:
            self._mark_error(widget, field, msg, show_message=show_message)
            if focus:
                widget.setFocus()
        return False

    def _validate_text_required(self, field: dict, msg: str, show_message: bool = False) -> bool:
        if not (field["input"].text() or "").strip():
            return self._invalidate_field(field, msg, show_message=show_message)
        self._set_field_valid(field)
        return True

    def _validate_matricula_field(self, show_message: bool = False, check_duplicate: bool = False) -> bool:
        if self._modo != "create":
            self._set_field_valid(self.matricula)
            return True
        txt = (self.matricula["input"].text() or "").strip()
        if not txt:
            return self._invalidate_field(self.matricula, "Matrícula é obrigatória.", show_message=show_message)
        try:
            mat = int(txt)
            if mat <= 0: raise ValueError
        except Exception:
            return self._invalidate_field(self.matricula, "Matrícula inválida. Use apenas números.", show_message=show_message)
        if check_duplicate and callable(self.on_check_matricula_exists):
            try:
                if bool(self.on_check_matricula_exists(mat)):
                    return self._invalidate_field(self.matricula, "Matrícula já cadastrada.", show_message=show_message)
            except Exception:
                pass
        self._set_field_valid(self.matricula)
        return True

    def _validate_cpf_field(self, show_message: bool = False, check_duplicate: bool = False) -> bool:
        cpf = (self.cpf["input"].text() or "").strip()
        ok, msg = is_valid_cpf(cpf)
        if not ok:
            return self._invalidate_field(self.cpf, msg, show_message=show_message)
        if check_duplicate and callable(self.on_find_cliente_por_cpf):
            try:
                row = self.on_find_cliente_por_cpf(cpf)
            except Exception:
                row = None
            if row:
                try:
                    cid = int(row[0])
                except Exception:
                    cid = None
                if self._modo == "create" or (cid is not None and cid != int(self._edit_id or 0)):
                    return self._invalidate_field(self.cpf, "CPF já cadastrado.", show_message=show_message)
        self._set_field_valid(self.cpf)
        return True

    def _validate_data_field(self, show_message: bool = False) -> bool:
        ok, msg = is_valid_date_ddmmyyyy((self.data_nascimento["input"].text() or "").strip())
        if not ok:
            return self._invalidate_field(self.data_nascimento, msg, show_message=show_message)
        self._set_field_valid(self.data_nascimento)
        return True

    def _validate_telefone_field(self, show_message: bool = False) -> bool:
        tel = (self.telefone["input"].text() or "").strip()
        if "_" in tel or not tel:
            return self._invalidate_field(self.telefone, "Telefone obrigatório e completo.", show_message=show_message)
        self._set_field_valid(self.telefone)
        return True

    def _validate_email_field(self, show_message: bool = False) -> bool:
        email = (self.email["input"].text() or "").strip()
        if email and not bool(self.email["input"].hasAcceptableInput()):
            return self._invalidate_field(self.email, "E-mail inválido.", show_message=show_message)
        self._set_field_valid(self.email)
        return True

    def _validate_cep_field(self, show_message: bool = False) -> bool:
        if len(only_digits((self.cep["input"].text() or "").strip())) != 8:
            return self._invalidate_field(self.cep, "CEP obrigatório (00000-000).", show_message=show_message)
        self._set_field_valid(self.cep)
        return True

    def _validate_uf_field(self, show_message: bool = False) -> bool:
        uf = (self.uf["input"].text() or "").strip().upper()
        if not uf or "_" in uf or len(uf) != 2:
            return self._invalidate_field(self.uf, "UF obrigatória (ex: SP).", show_message=show_message)
        self._set_field_valid(self.uf)
        return True

    def _validate_numero_field(self, show_message: bool = False) -> bool:
        numero = (self.numero["input"].text() or "").strip()
        if not numero or not re.match(r"^[0-9A-Za-z\-\/\. ]+$", numero):
            return self._invalidate_field(self.numero, "Número inválido.", show_message=show_message)
        self._set_field_valid(self.numero)
        return True

    def _validate_dependentes_lista(self, show_message: bool = False) -> bool:
        for i in range(len(self._deps)):
            if not self._validate_dependente_idx(i, show_message=show_message, widgets=None):
                return False
        return True

    # =========================
    # Valor / Resumo
    # =========================
    @staticmethod
    def _br_money(v: float) -> str:
        try:
            s = f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return f"R$ {s}"
        except Exception:
            return "R$ 0,00"

    def _open_valor_total_dialog(self):
        dlg = QDialog(self)
        dlg.setObjectName("valorTotalDialog")
        dlg.setWindowTitle("Editar valor total")
        dlg.setModal(True)
        dlg.setMinimumWidth(420)

        f = self._sans
        dlg.setStyleSheet(f"""
        QDialog#valorTotalDialog {{
            background: {_WHITE};
        }}
        QLabel#dialogTitle {{
            font-size: 17px;
            font-weight: 700;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#dialogSubtitle {{
            font-size: 12px;
            color: {_INK2};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#dialogLabel {{
            font-size: 12px;
            font-weight: 600;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QDoubleSpinBox#dialogValueSpin {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 8px;
            padding: 0 10px;
            font-size: 13px;
            color: {_INK};
            min-height: 38px;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QDoubleSpinBox#dialogValueSpin:hover {{ border-color: #c0c7d0; }}
        QDoubleSpinBox#dialogValueSpin:focus {{ border-color: {_ACCENT}; }}
        QDoubleSpinBox#dialogValueSpin::up-button, QDoubleSpinBox#dialogValueSpin::down-button {{
            width: 20px;
            border: none;
            background: transparent;
        }}
        QPushButton#dlgPrimary {{
            background: {_ACCENT};
            color: white;
            border: none;
            border-radius: 8px;
            padding: 0 16px;
            min-height: 36px;
            font-size: 13px;
            font-weight: 600;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QPushButton#dlgPrimary:hover {{ background: {_ACCENT_HOVER}; }}
        QPushButton#dlgPrimary:pressed {{ background: #114f5e; }}
        QPushButton#dlgSecondary {{
            background: {_WHITE};
            color: {_INK};
            border: 1px solid {_LINE};
            border-radius: 8px;
            padding: 0 14px;
            min-height: 36px;
            font-size: 13px;
            font-weight: 600;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QPushButton#dlgSecondary:hover {{
            border-color: {_ACCENT};
            color: {_ACCENT};
        }}
        """)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)

        title = QLabel("Editar valor total mensal")
        title.setObjectName("dialogTitle")
        lay.addWidget(title)

        subtitle = QLabel(
            "Esse ajuste altera apenas o valor total deste cadastro. "
            "Os valores de plano e de dependente não serão modificados."
        )
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)
        lay.addWidget(subtitle)

        value_wrap = QVBoxLayout()
        value_wrap.setSpacing(4)
        value_label = QLabel("Valor total")
        value_label.setObjectName("dialogLabel")
        value_wrap.addWidget(value_label)

        spin = QDoubleSpinBox(dlg)
        spin.setObjectName("dialogValueSpin")
        spin.setDecimals(2)
        spin.setRange(0.0, 1000000.0)
        spin.setSingleStep(5.0)
        spin.setPrefix("R$ ")
        spin.setValue(float(self._calc_valor()))
        value_wrap.addWidget(spin)
        lay.addLayout(value_wrap)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addStretch()

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setObjectName("dlgSecondary")
        btn_cancel.clicked.connect(dlg.reject)

        btn_save = QPushButton("Salvar valor")
        btn_save.setObjectName("dlgPrimary")
        btn_save.setDefault(True)
        btn_save.clicked.connect(dlg.accept)

        btns.addWidget(btn_cancel)
        btns.addWidget(btn_save)
        lay.addLayout(btns)

        if dlg.exec() != QDialog.Accepted:
            return

        self._valor_mensal_manual = float(spin.value())
        self._mark_dirty()
        self._recalc_valor_and_resumo()
        self._show_message("Valor total atualizado.", ok=True)

    def _calc_valor(self) -> float:
        if self._valor_mensal_manual is not None:
            return float(self._valor_mensal_manual)
        plano = self.plano["combo"].currentText() if self.plano else "Classic"
        conf  = self.PLANOS.get(plano, self.PLANOS["Classic"])
        return float(conf["base"] + len(self._deps) * conf["dep"])

    def _recalc_valor_and_resumo(self):
        valor     = self._calc_valor()
        valor_fmt = self._br_money(valor)

        if self.valor_mensal and "input" in self.valor_mensal:
            self.valor_mensal["input"].setText(valor_fmt)
        if self.valor_card:
            self.valor_card.setText(valor_fmt)
        if self.sidebar_value:
            self.sidebar_value.setText(valor_fmt)

        plano     = self.plano["combo"].currentText() if self.plano else "—"
        deps      = len(self._deps)
        valor_manual = self._valor_mensal_manual is not None
        dep_unit  = float(self.PLANOS.get(plano, self.PLANOS["Classic"])["dep"])
        try:
            vdia = int(self.vencimento_dia["combo"].currentText()) if self.vencimento_dia else 10
        except Exception:
            vdia = 10
        fp        = self.forma_pagamento["combo"].currentText() if self.forma_pagamento else "—"
        extra     = f"{deps} dependente(s)" if deps > 0 else "sem dependentes"

        if self.resumo_contrato:
            extra_valor = "  ·  valor manual" if valor_manual else ""
            self.resumo_contrato.setText(
                f"Plano {plano}  ·  vencimento dia {vdia:02d}  ·  {fp}  ·  {extra}{extra_valor}"
            )
        if self.dep_pricing_hint:
            self.dep_pricing_hint.setText(
                f"Cada dependente adiciona {self._br_money(dep_unit)} ao valor do plano selecionado."
            )
        if getattr(self, "dep_total_hint", None):
            self.dep_total_hint.setText(
                f"Total manual: {valor_fmt}" if valor_manual else f"Total com dependentes: {valor_fmt}"
            )
        if self.sidebar_plan:    self.sidebar_plan.setText(f"Plano: {plano}")
        if self.sidebar_due:     self.sidebar_due.setText(f"Vencimento: dia {vdia:02d}")
        if self.sidebar_pay:     self.sidebar_pay.setText(f"Pagamento: {fp}")
        if self.sidebar_status:  self.sidebar_status.setText("Status: cálculo automático pelo mês vigente")
        if self.sidebar_deps:    self.sidebar_deps.setText(f"Dependentes: {deps}")
        if self.sidebar_address:
            parts = [p for p in self._address_parts() if p]
            self.sidebar_address.setText(f"Endereço: {' · '.join(parts)}" if parts else "Endereço: —")
        self._refresh_form_progress()

    def limpar_campos(self):
        self._suspend_dirty = True
        try:
            for w in self._inputs_existentes():
                w.clear()
            for dep_field in (self.dep_nome, self.dep_cpf, self.dep_data_nascimento):
                if isinstance(dep_field, dict) and "input" in dep_field:
                    dep_field["input"].clear()
            self._last_saved_cliente_id = None
            if self.btn_baixar_contrato:
                self.btn_baixar_contrato.setVisible(False)
            self._valor_mensal_manual = None
            self._deps = []
            self._render_dependentes()
            for attr, val in [("plano", "Classic"), ("forma_pagamento", "Boleto"), ("vencimento_dia", "10")]:
                combo_dict = getattr(self, attr, None)
                if combo_dict:
                    combo_dict["combo"].setCurrentText(val)
            self._viacep.abort()
            self._endereco_manual = False
            self._address_autofill = False
            self._last_cep_filled = ""
            self._hide_message()
            self._set_address_status("")
            self._clear_errors()
            self._recalc_valor_and_resumo()
            if self._modo == "create" and self.matricula and "input" in self.matricula:
                self.matricula["input"].setEnabled(True)
            if self._modo == "create" and self.cpf and "input" in self.cpf:
                self.cpf["input"].setEnabled(True)
            if self.nome and "input" in self.nome:
                self.nome["input"].setFocus()
            self._scroll_top()
            self._refresh_form_progress()
            self._refresh_draft_buttons()
            self._set_save_ready()
        finally:
            self._suspend_dirty = False
        self._set_clean()

    def _snapshot_form(self) -> dict:
        return {
            "modo": self._modo, "edit_id": self._edit_id,
            "matricula": (self.matricula["input"].text() or "").strip(),
            "nome": (self.nome["input"].text() or "").strip(),
            "cpf": (self.cpf["input"].text() or "").strip(),
            "data_nascimento": (self.data_nascimento["input"].text() or "").strip(),
            "telefone": (self.telefone["input"].text() or "").strip(),
            "email": (self.email["input"].text() or "").strip(),
            "cep": (self.cep["input"].text() or "").strip(),
            "logradouro": (self.logradouro["input"].text() or "").strip(),
            "bairro": (self.bairro["input"].text() or "").strip(),
            "cidade": (self.cidade["input"].text() or "").strip(),
            "numero": (self.numero["input"].text() or "").strip(),
            "uf": (self.uf["input"].text() or "").strip(),
            "plano": (self.plano["combo"].currentText() or "").strip(),
            "forma_pagamento": (self.forma_pagamento["combo"].currentText() or "").strip(),
            "vencimento_dia": (self.vencimento_dia["combo"].currentText() or "").strip(),
            "valor_mensal_manual": self._valor_mensal_manual,
            "dependentes": list(self._deps),
        }

    def _apply_snapshot_form(self, data: dict):
        self._suspend_dirty = True
        try:
            self.matricula["input"].setText(str(data.get("matricula", "") or ""))
            self.nome["input"].setText((data.get("nome", "") or "").upper())
            self.cpf["input"].setText(data.get("cpf", "") or "")
            self.data_nascimento["input"].setText(data.get("data_nascimento", "") or "")
            self.telefone["input"].setText(data.get("telefone", "") or "")
            self.email["input"].setText(data.get("email", "") or "")
            self.cep["input"].setText(data.get("cep", "") or "")
            self.logradouro["input"].setText(data.get("logradouro", "") or "")
            self.bairro["input"].setText(data.get("bairro", "") or "")
            self.cidade["input"].setText(data.get("cidade", "") or "")
            self.numero["input"].setText(data.get("numero", "") or "")
            self.uf["input"].setText((data.get("uf", "") or "").upper())
            for attr, key in [("plano","plano"),("forma_pagamento","forma_pagamento"),("vencimento_dia","vencimento_dia")]:
                v = (data.get(key, "") or "").strip()
                getattr(self, attr)["combo"].setCurrentText(v)
            vm_manual = data.get("valor_mensal_manual", None)
            if vm_manual in ("", None):
                self._valor_mensal_manual = None
            else:
                try:
                    self._valor_mensal_manual = float(vm_manual)
                except Exception:
                    self._valor_mensal_manual = None
            self._deps = self._sanitize_dependentes(data.get("dependentes") or [])
            self._render_dependentes()
            self._clear_errors()
            self._recalc_valor_and_resumo()
            self._refresh_form_progress()
        finally:
            self._suspend_dirty = False

    def _save_draft(self):
        try:
            path = self._draft_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "payload": self._snapshot_form()}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._show_message("Rascunho salvo com sucesso.", ok=True)
            self._refresh_draft_buttons()
        except Exception as e:
            self._show_message(f"Não foi possível salvar rascunho: {e}", ok=False)

    def _load_draft_if_available(self, ask_restore: bool = True) -> bool:
        path = self._draft_path()
        if not path.exists():
            self._refresh_draft_buttons()
            if ask_restore:
                self._show_message("Nenhum rascunho encontrado.", ok=False)
            return False
        if self._modo != "create":
            if ask_restore:
                self._show_message("Abra o cadastro em modo novo para carregar rascunho.", ok=False)
            return False
        try:
            raw  = path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
            payload = data.get("payload") if isinstance(data, dict) else {}
            if not isinstance(payload, dict):
                payload = {}
        except Exception as e:
            self._show_message(f"Não foi possível carregar rascunho: {e}", ok=False)
            return False
        if ask_restore:
            stamp = (data.get("saved_at") or "").strip() if isinstance(data, dict) else ""
            msg = f"Deseja carregar o rascunho salvo em {stamp}?" if stamp else "Deseja carregar o rascunho salvo?"
            if QMessageBox.question(self, "Carregar rascunho", msg,
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
                return False
        self._apply_snapshot_form(payload)
        self._show_message("Rascunho carregado.", ok=True)
        self._dirty = True
        self._refresh_draft_buttons()
        return True

    def _refresh_draft_buttons(self):
        exists = self._draft_path().exists()
        if self.btn_carregar_rascunho:
            self.btn_carregar_rascunho.setEnabled(exists and self._modo == "create")
            self.btn_carregar_rascunho.setToolTip(
                "Carregar o último rascunho salvo" if exists else "Nenhum rascunho salvo"
            )

    def _on_salvar(self):
        self._hide_message()
        self._clear_errors()

        checks = [
            (self._validate_matricula_field,   [True, True],  self.matricula),
            (self._validate_text_required,     [self.nome, "Nome é obrigatório.", True], self.nome),
            (self._validate_cpf_field,         [True, True],  self.cpf),
            (self._validate_data_field,        [True],        self.data_nascimento),
            (self._validate_telefone_field,    [True],        self.telefone),
            (self._validate_email_field,       [True],        self.email),
            (self._validate_cep_field,         [True],        self.cep),
            (self._validate_text_required,     [self.logradouro, "Logradouro obrigatório.", True], self.logradouro),
            (self._validate_text_required,     [self.bairro, "Bairro obrigatório.", True], self.bairro),
            (self._validate_text_required,     [self.cidade, "Cidade obrigatória.", True], self.cidade),
            (self._validate_uf_field,          [True],        self.uf),
            (self._validate_numero_field,      [True],        self.numero),
        ]
        for fn, args, focus_field in checks:
            if not fn(*args):
                inp = focus_field.get("input") or focus_field.get("combo") if isinstance(focus_field, dict) else None
                if inp:
                    inp.setFocus()
                return

        if not self._validate_dependentes_lista(show_message=True):
            self._show_message("Revise os dados dos dependentes.", ok=False)
            return
        if not self._is_step_dependentes_ok():
            self._show_message("Finalize os dados do dependente antes de salvar.", ok=False)
            return

        matricula_txt = (self.matricula["input"].text() or "").strip()
        matricula     = int(matricula_txt) if self._modo == "create" else int(self._edit_id)
        nome          = (self.nome["input"].text() or "").strip().upper()
        self.nome["input"].setText(nome)
        cpf           = (self.cpf["input"].text() or "").strip()
        data_nasc     = (self.data_nascimento["input"].text() or "").strip()
        dt_nasc       = datetime.strptime(data_nasc, "%d/%m/%Y")
        telefone      = (self.telefone["input"].text() or "").strip()
        email         = (self.email["input"].text() or "").strip()
        cep           = (self.cep["input"].text() or "").strip()
        logradouro, bairro, cidade = self._address_parts()
        lbc           = self._compose_lbc()
        numero        = (self.numero["input"].text() or "").strip()
        uf            = (self.uf["input"].text() or "").strip().upper()
        plano         = self.plano["combo"].currentText()
        forma_pag     = self.forma_pagamento["combo"].currentText()
        try:
            venc_dia = int(self.vencimento_dia["combo"].currentText())
        except Exception:
            venc_dia = 10
        valor_mensal  = self._calc_valor()
        pag_value     = "em_dia"

        deps_payload = []
        for d in self._deps:
            dep_dn_br  = self._dep_birth_to_br((d.get("data_nascimento") or "").strip())
            dep_dn_iso = self._dep_birth_to_iso(dep_dn_br)
            try:
                dep_idade = int(d.get("idade") or 0)
            except Exception:
                dep_idade = 0
            if dep_dn_br and "_" not in dep_dn_br:
                ok_dep, _ = is_valid_date_ddmmyyyy(dep_dn_br)
                if ok_dep:
                    dep_idade = self._dep_age_from_br(dep_dn_br)
            deps_payload.append({
                "nome": (d.get("nome") or "").strip(),
                "cpf":  (d.get("cpf") or "").strip(),
                "data_nascimento": dep_dn_iso,
                "idade": dep_idade,
            })

        dados = {
            "modo": self._modo, "id": matricula, "matricula": matricula,
            "nome": nome, "cpf": cpf, "data_nascimento": dt_nasc.strftime("%Y-%m-%d"),
            "telefone": telefone, "email": email or "", "cep": cep,
            "endereco": f"{lbc} • Nº {numero} • {uf}",
            "endereco_lbc": lbc, "endereco_logradouro": logradouro,
            "endereco_bairro": bairro, "endereco_cidade": cidade,
            "endereco_numero": numero, "endereco_uf": uf,
            "plano": plano, "dependentes": len(self._deps),
            "dependentes_lista": deps_payload, "vencimento_dia": venc_dia,
            "forma_pagamento": forma_pag, "valor_mensal": valor_mensal,
            "data_inicio": datetime.now().strftime("%Y-%m-%d"),
            "status": "ativo", "pagamento_status": pag_value, "observacoes": "",
        }
        if self._modo == "create" and not self._confirm_create_review(dados):
            self._show_message("Revise os dados do contrato e confirme para continuar.", ok=False, ms=2200)
            return
        self._set_save_saving()
        self.salvar_signal.emit(dados)

    def _confirm_create_review(self, dados: dict) -> bool:
        nome = str(dados.get("nome") or "").strip() or "-"
        cpf = str(dados.get("cpf") or "").strip() or "-"
        plano = str(dados.get("plano") or "").strip() or "-"
        forma = str(dados.get("forma_pagamento") or "").strip() or "-"
        dependentes = int(dados.get("dependentes") or 0)
        vencimento = int(dados.get("vencimento_dia") or 0)
        valor = float(dados.get("valor_mensal") or 0.0)
        resumo = (
            "Confira os dados antes de salvar:\n\n"
            f"• Cliente: {nome}\n"
            f"• CPF: {cpf}\n"
            f"• Plano: {plano}\n"
            f"• Forma de pagamento: {forma}\n"
            f"• Vencimento: dia {vencimento}\n"
            f"• Dependentes: {dependentes}\n"
            f"• Valor mensal: {self._br_money(valor)}"
        )
        dlg = QDialog(self)
        dlg.setWindowTitle("Revisar novo contrato")
        dlg.setModal(True)
        dlg.setObjectName("ReviewContratoDialog")
        dlg.setMinimumWidth(560)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)

        title = QLabel("Revisar novo contrato")
        title.setObjectName("dlgTitle")
        sub = QLabel("Etapa final antes do salvamento")
        sub.setObjectName("dlgSub")
        body = QLabel(resumo)
        body.setObjectName("dlgBody")
        body.setWordWrap(True)

        actions = QHBoxLayout()
        actions.addStretch()
        btn_back = QPushButton("Voltar e revisar")
        btn_back.setObjectName("dlgBtnSecondary")
        btn_back.setFixedHeight(36)
        btn_ok = QPushButton("Confirmar e salvar")
        btn_ok.setObjectName("dlgBtnPrimary")
        btn_ok.setFixedHeight(36)
        actions.addWidget(btn_back)
        actions.addWidget(btn_ok)

        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addWidget(body)
        lay.addLayout(actions)

        dlg.setStyleSheet(f"""
            QDialog#ReviewContratoDialog {{
                background: {_WHITE};
                border: 1px solid rgba(15, 23, 42, 0.12);
                border-radius: 14px;
                font-family: '{self._sans}', 'Segoe UI', sans-serif;
            }}
            QLabel#dlgTitle {{
                font-size: 18px;
                font-weight: 800;
                color: {_INK};
            }}
            QLabel#dlgSub {{
                font-size: 12px;
                font-weight: 600;
                color: {_INK2};
            }}
            QLabel#dlgBody {{
                background: {_BG};
                border: 1px solid {_LINE};
                border-radius: 10px;
                padding: 12px 14px;
                color: {_INK};
                font-size: 12px;
                line-height: 1.35;
            }}
            QPushButton#dlgBtnPrimary {{
                background: {_ACCENT};
                color: white;
                border: none;
                border-radius: 8px;
                padding: 0 16px;
                font-weight: 700;
                min-width: 160px;
            }}
            QPushButton#dlgBtnPrimary:hover {{ background: {_ACCENT_HOVER}; }}
            QPushButton#dlgBtnSecondary {{
                background: {_WHITE};
                color: {_INK};
                border: 1px solid {_LINE};
                border-radius: 8px;
                padding: 0 14px;
                font-weight: 700;
            }}
            QPushButton#dlgBtnSecondary:hover {{
                border-color: {_ACCENT};
                color: {_ACCENT};
            }}
        """)

        btn_ok.clicked.connect(dlg.accept)
        btn_back.clicked.connect(dlg.reject)
        return dlg.exec() == QDialog.Accepted

    def _on_baixar_contrato_clicked(self):
        if not self._last_saved_cliente_id:
            self._show_message("Salve o cadastro antes de baixar o contrato.", ok=False)
            return
        self._show_message(
            "Gerando contrato em PDF. Aguarde a confirmação do download.",
            ok=True,
            ms=2200,
        )
        self.baixar_contrato_signal.emit(int(self._last_saved_cliente_id))

    def sucesso_salvo(self, cliente_id: int | None = None):
        self._set_save_saved()
        self._set_clean()
        if cliente_id:
            try:
                self._last_saved_cliente_id = int(cliente_id)
            except Exception:
                self._last_saved_cliente_id = None
        if self.btn_baixar_contrato:
            self.btn_baixar_contrato.setVisible(bool(self._last_saved_cliente_id))
            self.btn_baixar_contrato.setEnabled(bool(self._last_saved_cliente_id))
        try:
            if self._modo == "create":
                self._draft_path().unlink(missing_ok=True)
        except Exception:
            pass
        self._refresh_draft_buttons()
        self._show_message("✓  Contrato salvo com sucesso!", ok=True)

    def erro_salvo(self, msg="Não foi possível salvar."):
        self._set_save_ready()
        self._apply_backend_error(msg)

    @staticmethod
    def _normalize_error_text(msg: str) -> str:
        txt = unicodedata.normalize("NFKD", str(msg or ""))
        txt = "".join(ch for ch in txt if not unicodedata.combining(ch))
        txt = txt.lower()
        txt = re.sub(r"[^a-z0-9\s]+", " ", txt)
        return " ".join(txt.split())

    def _focus_field_widget(self, field: dict | None, msg: str):
        if not isinstance(field, dict):
            return
        widget = field.get("input") or field.get("combo") or field.get("spin")
        if widget is None:
            return
        self._mark_error(widget, field, str(msg or ""), show_message=False)
        try:
            widget.setFocus()
        except Exception:
            pass

    def _apply_backend_error(self, msg: str):
        message = str(msg or "Não foi possível salvar.")
        norm = self._normalize_error_text(message)
        self._clear_errors()

        target = None
        if "dependente" in norm:
            if "cpf" in norm:
                target = self.dep_cpf
            elif "data de nascimento" in norm:
                target = self.dep_data_nascimento
            else:
                target = self.dep_nome
        elif "matricula" in norm or "id do cliente" in norm:
            target = self.matricula
        elif "cpf" in norm:
            target = self.cpf
        elif "nome" in norm:
            target = self.nome
        elif "telefone" in norm:
            target = self.telefone
        elif "e mail" in norm or "email" in norm:
            target = self.email
        elif "data de nascimento" in norm:
            target = self.data_nascimento
        elif "cep" in norm:
            target = self.cep
        elif "logradouro" in norm or "endereco" in norm:
            target = self.logradouro
        elif "bairro" in norm:
            target = self.bairro
        elif "cidade" in norm:
            target = self.cidade
        elif "uf" in norm:
            target = self.uf
        elif "dia de vencimento" in norm:
            target = self.vencimento_dia
        elif "forma de pagamento" in norm:
            target = self.forma_pagamento
        elif "valor mensal" in norm:
            target = self.valor_mensal
        elif "plano" in norm:
            target = self.plano

        self._focus_field_widget(target, message)
        self._show_message(message, ok=False)

    def _set_save_ready(self):
        self._save_state_timer.stop()
        if not self.btn_salvar:
            return
        self.btn_salvar.setEnabled(True)
        self.btn_limpar.setEnabled(True)
        if self.btn_rascunho:
            self.btn_rascunho.setEnabled(True)
        if self.btn_baixar_contrato:
            self.btn_baixar_contrato.setEnabled(bool(self._last_saved_cliente_id))
        self.btn_salvar.setText("Salvar alterações" if self._modo == "edit" else "Salvar contrato")
        self.btn_salvar.setProperty("saved", False)
        self.btn_salvar.style().unpolish(self.btn_salvar)
        self.btn_salvar.style().polish(self.btn_salvar)

    def _set_save_saving(self):
        self._save_state_timer.stop()
        if not self.btn_salvar:
            return
        self.btn_salvar.setEnabled(False)
        self.btn_limpar.setEnabled(False)
        if self.btn_rascunho:
            self.btn_rascunho.setEnabled(False)
        if self.btn_baixar_contrato:
            self.btn_baixar_contrato.setEnabled(False)
        self.btn_salvar.setText("Salvando…")
        self.btn_salvar.setProperty("saved", False)
        self.btn_salvar.style().unpolish(self.btn_salvar)
        self.btn_salvar.style().polish(self.btn_salvar)

    def _set_save_saved(self):
        if not self.btn_salvar:
            return
        self.btn_salvar.setEnabled(False)
        self.btn_limpar.setEnabled(True)
        if self.btn_rascunho:
            self.btn_rascunho.setEnabled(True)
        if self.btn_baixar_contrato:
            self.btn_baixar_contrato.setEnabled(bool(self._last_saved_cliente_id))
        self.btn_salvar.setText("✓  Salvo")
        self.btn_salvar.setProperty("saved", True)
        self.btn_salvar.style().unpolish(self.btn_salvar)
        self.btn_salvar.style().polish(self.btn_salvar)
        self._save_state_timer.start(1400)

    def _show_message(self, text: str, ok: bool = False, ms: int = 3200):
        if not self.inline_msg:
            return
        self.inline_msg.setText(text)
        self.inline_msg.setProperty("ok", ok)
        self.inline_msg.style().unpolish(self.inline_msg)
        self.inline_msg.style().polish(self.inline_msg)
        self.inline_msg.setVisible(True)
        self._msg_timer.start(ms)

    def _hide_message(self):
        self._msg_timer.stop()
        if not self.inline_msg:
            return
        self.inline_msg.setVisible(False)
        self.inline_msg.setText("")
        self.inline_msg.setProperty("ok", False)

    def _mark_error(self, widget: QWidget, field: dict | None = None, text: str = "", show_message: bool = True):
        widget.setProperty("error", True)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        self._set_field_error(field, text)
        if text and show_message:
            self._show_message(text, ok=False)
        try:
            self.scroll.ensureWidgetVisible(widget, 20, 40)
        except Exception:
            pass

    def _clear_errors(self):
        for w in self._inputs_existentes():
            if w.property("error"):
                w.setProperty("error", False)
                w.style().unpolish(w)
                w.style().polish(w)
        for w in self.findChildren(QLineEdit):
            if w.objectName() == "depInlineInput" and w.property("error"):
                w.setProperty("error", False)
                w.style().unpolish(w)
                w.style().polish(w)
        for attr in ("matricula","nome","cpf","data_nascimento","telefone","email",
                     "cep","logradouro","bairro","cidade","numero","uf",
                     "dep_nome","dep_cpf","dep_data_nascimento","plano",
                     "forma_pagamento","vencimento_dia"):
            self._set_field_error(getattr(self, attr, None), "")

    # =========================
    # Estilos
    # =========================
    def apply_styles(self):
        f = self._sans
        base_qss = f"""
        /* ── raiz ────────────────────────────────────────────────────────── */
        QWidget#CadastroCliente {{
            background: {_BG};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}

        /* ── cabeçalho ───────────────────────────────────────────────────── */
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

        /* ── separador ───────────────────────────────────────────────────── */
        QFrame#softLine {{
            background: {_LINE};
            border: none;
        }}

        /* ── barra de progresso ──────────────────────────────────────────── */
        QFrame#progressBlock {{
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:0,
                stop:0 {_WHITE},
                stop:1 rgba(26,107,124,0.05)
            );
            border: 1px solid rgba(26,107,124,0.18);
            border-radius: 14px;
        }}
        QLabel#progressTitle {{
            font-size: 12px;
            font-weight: 700;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#progressCount {{
            font-size: 11px;
            font-weight: 700;
            color: {_INK2};
            background: rgba(145,153,166,0.14);
            border: 1px solid rgba(145,153,166,0.24);
            border-radius: 11px;
            padding: 2px 9px;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#progressValue {{
            font-size: 11px;
            font-weight: 700;
            color: {_ACCENT};
            background: rgba(26,107,124,0.10);
            border: 1px solid rgba(26,107,124,0.24);
            border-radius: 11px;
            padding: 2px 10px;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QProgressBar#formProgress {{
            background: rgba(26,107,124,0.12);
            border: 1px solid rgba(26,107,124,0.18);
            border-radius: 4px;
        }}
        QProgressBar#formProgress::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {_ACCENT}, stop:1 #34b7aa);
            border-radius: 4px;
        }}

        /* ── step chips ──────────────────────────────────────────────────── */
        QPushButton#stepChip {{
            background: #fbfcfc;
            border: 1px solid rgba(145,153,166,0.24);
            border-radius: 16px;
            padding: 4px 12px;
            font-size: 11px;
            font-weight: 600;
            color: {_INK2};
            text-align: left;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QPushButton#stepChip:hover {{
            border-color: {_ACCENT};
            background: rgba(26,107,124,0.05);
            color: {_ACCENT};
        }}
        QPushButton#stepChip[active="true"] {{
            background: {_ACCENT_LIGHT};
            border: 1px solid rgba(26,107,124,0.32);
            color: {_ACCENT};
            font-weight: 700;
        }}
        QPushButton#stepChip[done="true"] {{
            background: {_GOOD_BG};
            border: 1px solid {_GOOD_BORDER};
            color: {_GOOD};
            font-weight: 700;
        }}

        /* ── cards de seção ──────────────────────────────────────────────── */
        QFrame#cardBlock {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 12px;
        }}
        QLabel#sectionTitle {{
            font-size: 13px;
            font-weight: 600;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}

        /* ── hero do contrato ────────────────────────────────────────────── */
        QFrame#contractHero {{
            background: rgba(26,107,124,0.06);
            border: 1px solid rgba(26,107,124,0.16);
            border-left: 4px solid {_ACCENT};
            border-radius: 10px;
        }}
        QLabel#contractEyebrow {{
            font-size: 10px;
            font-weight: 600;
            color: {_ACCENT};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#contractValue {{
            font-size: 28px;
            font-weight: 700;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#contractSummary {{
            font-size: 12px;
            color: {_INK2};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}

        /* ── sidebar ─────────────────────────────────────────────────────── */
        QFrame#stickySummary {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 12px;
        }}
        QLabel#summaryEyebrow {{
            font-size: 10px;
            font-weight: 600;
            color: {_INK3};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#summaryValue {{
            font-size: 30px;
            font-weight: 700;
            color: {_ACCENT};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#summaryLine {{
            font-size: 12px;
            color: {_INK2};
            padding: 2px 0;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}

        /* ── labels de campo ─────────────────────────────────────────────── */
        QLabel#fieldLabel {{
            font-size: 12px;
            font-weight: 600;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#fieldError {{
            font-size: 11px;
            color: {_DANGER};
            font-family: '{f}', 'Segoe UI', sans-serif;
            margin-top: -2px;
        }}

        /* ── inputs ──────────────────────────────────────────────────────── */
        QLineEdit#fieldInput {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 8px;
            padding: 0 12px;
            font-size: 13px;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
            selection-background-color: rgba(26,107,124,0.15);
        }}
        QLineEdit#fieldInput:focus  {{ border-color: {_ACCENT}; }}
        QLineEdit#fieldInput:hover  {{ border-color: #c0c7d0; }}
        QLineEdit#fieldInput[error="true"] {{
            border-color: {_DANGER};
            background: {_DANGER_BG};
        }}
        QLineEdit#fieldInput:disabled {{
            background: {_BG};
            color: {_INK3};
            border-color: {_LINE};
        }}
        QLineEdit#fieldInputReadOnly {{
            background: {_BG};
            border: 1px solid {_LINE};
            border-radius: 8px;
            padding: 0 12px;
            font-size: 15px;
            font-weight: 700;
            color: {_ACCENT};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}

        /* ── combos ──────────────────────────────────────────────────────── */
        QComboBox#saasCombo {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 8px;
            padding: 0 32px 0 12px;
            font-size: 13px;
            font-weight: 500;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QComboBox#saasCombo:hover  {{ border-color: #c0c7d0; }}
        QComboBox#saasCombo:focus  {{ border-color: {_ACCENT}; }}
        QComboBox#saasCombo[error="true"] {{
            border-color: {_DANGER};
            background: {_DANGER_BG};
        }}
        QComboBox#saasCombo::drop-down {{ border: none; width: 28px; }}
        QComboBox#saasCombo::down-arrow {{
            width: 0; height: 0;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid {_INK3};
            margin-right: 6px;
        }}
        QComboBox QAbstractItemView {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 8px;
            padding: 4px;
            selection-background-color: rgba(26,107,124,0.10);
            selection-color: {_INK};
            font-size: 13px;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QComboBox QAbstractItemView::item {{
            min-height: 34px;
            padding: 4px 10px;
            border-radius: 6px;
        }}
        QComboBox QAbstractItemView::item:hover {{
            background: rgba(26,107,124,0.06);
        }}

        /* ── status do CEP ───────────────────────────────────────────────── */
        QLabel#addressStatus {{
            background: rgba(26,107,124,0.07);
            border: 1px solid rgba(26,107,124,0.18);
            border-left: 3px solid {_ACCENT};
            border-radius: 8px;
            padding: 7px 12px;
            font-size: 12px;
            color: {_ACCENT};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#addressStatus[ok="false"] {{
            background: {_DANGER_BG};
            border: 1px solid {_DANGER_BORDER};
            border-left: 3px solid {_DANGER};
            color: {_DANGER};
        }}

        /* ── hints de dependentes ────────────────────────────────────────── */
        QLabel#depPricingHint, QLabel#depTotalHint {{
            font-size: 12px;
            color: {_INK2};
            background: {_BG};
            border-radius: 8px;
            padding: 6px 10px;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#depHint {{
            font-size: 12px;
            color: {_INK3};
            padding: 6px 0;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QFrame#depCard {{
            background: {_BG};
            border: 1px solid {_LINE};
            border-radius: 10px;
        }}
        QLabel#depText {{
            font-size: 12px;
            font-weight: 600;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QPushButton#depRemove {{
            background: {_DANGER_BG};
            border: 1px solid {_DANGER_BORDER};
            border-radius: 6px;
            padding: 4px 10px;
            font-size: 11px;
            font-weight: 600;
            color: {_DANGER};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QPushButton#depRemove:hover {{
            background: rgba(192,57,43,0.14);
        }}
        QLineEdit#depInlineInput {{
            background: {_WHITE};
            border: 1px solid {_LINE};
            border-radius: 7px;
            padding: 0 10px;
            font-size: 12px;
            color: {_INK};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLineEdit#depInlineInput:focus  {{ border-color: {_ACCENT}; }}
        QLineEdit#depInlineInput[error="true"] {{
            border-color: {_DANGER};
            background: {_DANGER_BG};
        }}

        /* ── mensagem inline ─────────────────────────────────────────────── */
        QLabel#inlineMessage {{
            background: {_DANGER_BG};
            border: 1px solid {_DANGER_BORDER};
            border-left: 4px solid {_DANGER};
            border-radius: 8px;
            padding: 10px 14px;
            font-size: 13px;
            font-weight: 600;
            color: {_DANGER};
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QLabel#inlineMessage[ok="true"] {{
            background: {_GOOD_BG};
            border: 1px solid {_GOOD_BORDER};
            border-left: 4px solid {_GOOD};
            color: {_GOOD};
        }}

        /* ── botões ──────────────────────────────────────────────────────── */
        QPushButton#btnPrimary {{
            background: {_ACCENT};
            color: white;
            border: none;
            border-radius: 8px;
            padding: 0 22px;
            font-size: 13px;
            font-weight: 600;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QPushButton#btnPrimary:hover   {{ background: {_ACCENT_HOVER}; }}
        QPushButton#btnPrimary:pressed {{ background: #114f5e; }}
        QPushButton#btnPrimary[saved="true"] {{ background: {_GOOD}; }}
        QPushButton#btnPrimary:disabled {{
            background: rgba(26,107,124,0.30);
            color: rgba(255,255,255,0.65);
        }}

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
        QPushButton#btnSecondary:hover {{
            border-color: {_ACCENT};
            color: {_ACCENT};
        }}
        QPushButton#btnSecondary:disabled {{
            color: {_INK3};
            border-color: {_LINE};
        }}

        QPushButton#btnDangerSoft {{
            background: {_DANGER_BG};
            color: {_DANGER};
            border: 1px solid {_DANGER_BORDER};
            border-radius: 8px;
            padding: 0 16px;
            font-size: 13px;
            font-weight: 600;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QPushButton#btnDangerSoft:hover {{
            background: rgba(192,57,43,0.13);
            border-color: {_DANGER};
            color: {_DANGER};
        }}
        QPushButton#btnDangerSoft:disabled {{
            background: {_WHITE};
            color: {_INK3};
            border-color: {_LINE};
        }}

        QPushButton#btnGhost {{
            background: transparent;
            color: {_INK2};
            border: 1px solid {_LINE};
            border-radius: 8px;
            padding: 0 14px;
            font-size: 13px;
            font-family: '{f}', 'Segoe UI', sans-serif;
        }}
        QPushButton#btnGhost:hover   {{ color: {_INK}; border-color: #c0c7d0; }}
        QPushButton#btnGhost:disabled{{ color: {_INK3}; }}

        /* ── scrollbar ───────────────────────────────────────────────────── */
        QScrollArea#formScroll {{ background: transparent; border: none; }}
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
        """
        self._base_qss = base_qss
        self.setStyleSheet(base_qss)

