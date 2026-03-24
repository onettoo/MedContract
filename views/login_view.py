from __future__ import annotations

import ctypes
import logging
import os
import random
import socket
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QHBoxLayout, QFrame,
    QToolButton, QGraphicsOpacityEffect, QGraphicsDropShadowEffect,
    QCheckBox, QSizePolicy, QAbstractButton, QDialog,
)
from PySide6.QtCore import (
    Qt, Signal, QPropertyAnimation, QEasingCurve, QTimer, Property,
    QSettings, QObject, QRunnable, QThreadPool, Slot, QEvent, QPoint,
    QRectF, QSize, QSequentialAnimationGroup, QParallelAnimationGroup,
    QPointF,
)
from PySide6.QtGui import (
    QPixmap, QColor, QPainter, QPen, QPainterPath,
    QFont, QFontDatabase, QKeySequence, QShortcut, QBrush,
)

from database.db import validate_user

logger = logging.getLogger(__name__)

APP_VERSION = "2.0.0"


# ══════════════════════════════════════════════
# _load_stylesheet  — lê o theme.qss global
# ══════════════════════════════════════════════
def _load_stylesheet(base_dir: str) -> str:
    """
    Lê o tema global e retorna o conteúdo como string.
    Retorna string vazia se o arquivo não existir (sem crash).
    """
    candidates = [
        os.path.join(base_dir, "styles", "theme.qss"),
        os.path.join(base_dir, "assets", "theme.qss"),
        os.path.join(base_dir, "styles", "base.qss"),
    ]
    for path in candidates:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
    logger.warning("Nenhum arquivo de tema encontrado. Caminhos testados: %s", candidates)
    return ""


# ══════════════════════════════════════════════
# _load_fonts — DM Sans + DM Serif Display
# Coloque os TTFs em: assets/fonts/
# Download: fonts.google.com/specimen/DM+Sans
#           fonts.google.com/specimen/DM+Serif+Display
# ══════════════════════════════════════════════
def _load_fonts(base_dir: str) -> tuple[str, str]:
    fonts_dir = os.path.join(base_dir, "assets", "fonts")
    sans_family = ""
    serif_family = ""

    def _pick_family(fams: list[str], preferred: str) -> str:
        if not fams:
            return ""
        if preferred in fams:
            return preferred
        for f in fams:
            if f.lower().startswith(preferred.lower()):
                return f
        return fams[0]

    for fname in [
        "DMSans-Light.ttf", "DMSans-Regular.ttf",
        "DMSans-Medium.ttf", "DMSans-SemiBold.ttf",
    ]:
        p = os.path.join(fonts_dir, fname)
        if os.path.exists(p):
            fid = QFontDatabase.addApplicationFont(p)
            if fid >= 0 and not sans_family:
                fams = QFontDatabase.applicationFontFamilies(fid)
                if fams:
                    sans_family = _pick_family(fams, "DM Sans")

    for fname in ["DMSerifDisplay-Regular.ttf", "DMSerifDisplay-Italic.ttf"]:
        p = os.path.join(fonts_dir, fname)
        if os.path.exists(p):
            fid = QFontDatabase.addApplicationFont(p)
            if fid >= 0 and not serif_family:
                fams = QFontDatabase.applicationFontFamilies(fid)
                if fams:
                    serif_family = _pick_family(fams, "DM Serif Display")

    sans = sans_family or "Segoe UI"
    serif = serif_family or sans
    return sans, serif


# ══════════════════════════════════════════════
# LoginAuditLogger
# ══════════════════════════════════════════════
class LoginAuditLogger:
    _audit = logging.getLogger("login.audit")

    @classmethod
    def success(cls, username: str) -> None:
        cls._audit.info("LOGIN_SUCCESS | user=%s | at=%s", username,
                        datetime.now().isoformat(timespec="seconds"))

    @classmethod
    def failure(cls, username: str) -> None:
        cls._audit.warning("LOGIN_FAILURE | user=%s | at=%s", username,
                           datetime.now().isoformat(timespec="seconds"))

    @classmethod
    def lockout(cls, username: str, duration_secs: int) -> None:
        cls._audit.warning("LOGIN_LOCKOUT | user=%s | duration=%ds | at=%s",
                           username, duration_secs,
                           datetime.now().isoformat(timespec="seconds"))


# ══════════════════════════════════════════════
# SecureString
# ══════════════════════════════════════════════
class SecureString:
    def __init__(self, value: str):
        self._buf = ctypes.create_unicode_buffer(value)

    @property
    def value(self) -> str:
        return self._buf.value

    def wipe(self) -> None:
        size = len(self._buf)
        ctypes.memset(self._buf, 0, size * ctypes.sizeof(ctypes.c_wchar))

    def __enter__(self): return self
    def __exit__(self, *_): self.wipe()


# ══════════════════════════════════════════════
# LoginSettings
# ══════════════════════════════════════════════
class LoginSettings:
    ORG_NAME = "MedContract"
    APP_NAME = "MedContract"

    def __init__(self):
        self._s = QSettings(self.ORG_NAME, self.APP_NAME)

    @property
    def remember(self) -> bool:
        return bool(self._s.value("login/remember", False, type=bool))

    @property
    def username(self) -> str:
        return self._s.value("login/username", "", type=str)

    def save(self, remember: bool, username: str) -> None:
        self._s.setValue("login/remember", remember)
        self._s.setValue("login/username", username if remember else "")
        self._s.sync()


# ══════════════════════════════════════════════
# PasswordFieldFilter
# ══════════════════════════════════════════════
class PasswordFieldFilter(QObject):
    caps_changed = Signal(bool)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.KeyPress:
            text = event.text()
            if text.isalpha():
                mods     = event.modifiers()
                caps_on  = text.isupper() and not bool(mods & Qt.ShiftModifier)
                caps_off = text.islower() and bool(mods & Qt.ShiftModifier)
                self.caps_changed.emit(caps_on or caps_off)
        elif event.type() == QEvent.FocusOut:
            self.caps_changed.emit(False)
        return False


# ══════════════════════════════════════════════
# _LoginWorker
# ══════════════════════════════════════════════
class _LoginWorkerSignals(QObject):
    finished = Signal(bool, object)


class _LoginWorker(QRunnable):
    def __init__(self, username: str, secure_pwd: SecureString):
        super().__init__()
        self.username = username
        self._secure  = secure_pwd
        self.signals  = _LoginWorkerSignals()

    @Slot()
    def run(self):
        try:
            with self._secure as pwd:
                valid, nivel = validate_user(self.username, pwd.value)
            self.signals.finished.emit(bool(valid), nivel)
        except Exception:
            logger.exception("Erro inesperado no worker de login")
            self.signals.finished.emit(False, None)


# ══════════════════════════════════════════════
# NOVO: SystemStatusChecker - Thread worker para checagem de status
# ══════════════════════════════════════════════
class SystemStatusSignals(QObject):
    status_updated = Signal(dict)


class SystemStatusChecker(QRunnable):
    """Worker que verifica status do sistema em background"""
    
    def __init__(self):
        super().__init__()
        self.signals = SystemStatusSignals()
        self._running = True

    @Slot()
    def run(self):
        status = {
            'database': self._check_database(),
            'network': self._check_network(),
            'timestamp': datetime.now()
        }
        self.signals.status_updated.emit(status)

    def _check_database(self) -> str:
        """Retorna: 'online', 'slow', 'offline'"""
        try:
            # Simula checagem do banco (substitua pela sua lógica real)
            from database.db import validate_user
            # Se importar sem erro, consideramos online
            return 'online'
        except Exception:
            return 'offline'

    def _check_network(self) -> str:
        """Retorna: 'online', 'slow', 'offline'"""
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=1)
            return 'online'
        except OSError:
            return 'offline'


# ══════════════════════════════════════════════
# NOVO: StatusIndicator - Bolinha de status com pulse
# ══════════════════════════════════════════════
class StatusIndicator(QWidget):
    """Bolinha colorida com animação de pulse"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self._status = 'offline'  # online, slow, offline
        self._pulse_value = 0.0
        
        self._pulse_anim = QPropertyAnimation(self, b"pulseValue", self)
        self._pulse_anim.setDuration(1500)
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.setEasingCurve(QEasingCurve.InOutSine)
        self._pulse_anim.setLoopCount(-1)

    def get_pulse_value(self) -> float:
        return self._pulse_value

    def set_pulse_value(self, value: float):
        self._pulse_value = value
        self.update()

    pulseValue = Property(float, get_pulse_value, set_pulse_value)

    def set_status(self, status: str):
        """Define status: 'online', 'slow', 'offline'"""
        self._status = status
        if status == 'online':
            self._pulse_anim.start()
        else:
            self._pulse_anim.stop()
            self._pulse_value = 0.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # Define cor baseado no status
        colors = {
            'online': QColor("#27AE60"),
            'slow': QColor("#F39C12"),
            'offline': QColor("#E74C3C")
        }
        color = colors.get(self._status, QColor("#95A5A6"))

        # Desenha halo pulsante (apenas quando online)
        if self._status == 'online' and self._pulse_value > 0:
            halo_radius = 5 + (self._pulse_value * 3)
            halo_alpha = int(80 * (1.0 - self._pulse_value))
            halo_color = QColor(color.red(), color.green(), color.blue(), halo_alpha)
            p.setPen(Qt.NoPen)
            p.setBrush(halo_color)
            p.drawEllipse(QPointF(5, 5), halo_radius, halo_radius)

        # Desenha bolinha principal
        p.setBrush(color)
        p.setPen(QPen(color.darker(120), 0.5))
        p.drawEllipse(QRectF(1, 1, 8, 8))


# ══════════════════════════════════════════════
# NOVO: ConfettiParticle - Partícula de confete
# ══════════════════════════════════════════════
class ConfettiParticle(QWidget):
    """Partícula individual de confete que cai"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        
        colors = ["#1A6B7C", "#27AE60", "#F39C12", "#E74C3C", "#9B59B6"]
        self._color = QColor(random.choice(colors))
        self._rotation = 0.0
        
        # Propriedades físicas aleatórias
        self._speed = random.uniform(2.0, 5.0)
        self._drift = random.uniform(-1.5, 1.5)
        self._rotation_speed = random.uniform(-15, 15)

    def get_rotation(self) -> float:
        return self._rotation

    def set_rotation(self, value: float):
        self._rotation = value
        self.update()

    rotation = Property(float, get_rotation, set_rotation)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        
        p.translate(5, 5)
        p.rotate(self._rotation)
        
        # Desenha retângulo rotacionado
        p.setPen(Qt.NoPen)
        p.setBrush(self._color)
        p.drawRect(QRectF(-3, -5, 6, 10))


# ══════════════════════════════════════════════
# NOVO: ConfettiOverlay - Sistema de confete
# ══════════════════════════════════════════════
class ConfettiOverlay(QWidget):
    """Overlay transparente que cria e anima partículas de confete"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.particles = []
        
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._update_particles)
        self._update_timer.setInterval(16)  # ~60 FPS

    def celebrate(self):
        """Inicia celebração com confete"""
        self.particles.clear()
        
        # Cria 30 partículas
        for _ in range(30):
            particle = ConfettiParticle(self)
            x = random.randint(0, self.width())
            y = -20
            particle.move(x, y)
            particle.show()
            
            # Animação de rotação
            rot_anim = QPropertyAnimation(particle, b"rotation", self)
            rot_anim.setDuration(2000)
            rot_anim.setStartValue(0.0)
            rot_anim.setEndValue(360.0 * random.choice([-1, 1]))
            rot_anim.setLoopCount(-1)
            rot_anim.start()
            
            self.particles.append({
                'widget': particle,
                'anim': rot_anim,
                'speed': particle._speed,
                'drift': particle._drift
            })
        
        self._update_timer.start()
        QTimer.singleShot(3000, self._cleanup)

    def _update_particles(self):
        """Atualiza posição das partículas"""
        for p in self.particles:
            widget = p['widget']
            pos = widget.pos()
            new_x = pos.x() + p['drift']
            new_y = pos.y() + p['speed']
            widget.move(int(new_x), int(new_y))
            
            # Remove se saiu da tela
            if new_y > self.height():
                widget.hide()

    def _cleanup(self):
        """Limpa partículas"""
        self._update_timer.stop()
        for p in self.particles:
            p['anim'].stop()
            p['widget'].deleteLater()
        self.particles.clear()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setGeometry(self.parentWidget().rect())


# ══════════════════════════════════════════════
# NOVO: KeyboardShortcutsDialog - Diálogo de atalhos
# ══════════════════════════════════════════════
class KeyboardShortcutsDialog(QDialog):
    """Diálogo que mostra todos os atalhos de teclado disponíveis"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Atalhos de Teclado")
        self.setModal(True)
        self.setMinimumWidth(420)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        # Título
        title = QLabel("Atalhos de Teclado")
        title.setObjectName("shortcutsTitle")
        f_title = QFont("Segoe UI", 18)
        f_title.setWeight(QFont.DemiBold)
        title.setFont(f_title)
        layout.addWidget(title)
        
        # Lista de atalhos
        shortcuts_data = [
            ("Enter", "Fazer login"),
            ("Esc", "Limpar campos e focar no usuário"),
            ("Tab", "Navegar entre campos"),
            ("Ctrl+L", "Focar no campo de usuário"),
            ("Ctrl+K", "Focar no campo de senha"),
            ("Ctrl+H", "Mostrar/ocultar senha"),
            ("?", "Mostrar esta ajuda"),
        ]
        
        for key, description in shortcuts_data:
            row = self._create_shortcut_row(key, description)
            layout.addWidget(row)
        
        layout.addStretch()
        
        # Botão fechar
        close_btn = QPushButton("Fechar")
        close_btn.setObjectName("shortcutsCloseBtn")
        close_btn.setFixedHeight(40)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        
        self._apply_styles()

    def _create_shortcut_row(self, key: str, description: str) -> QWidget:
        """Cria uma linha de atalho"""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)
        
        # Badge da tecla
        key_badge = QLabel(key)
        key_badge.setObjectName("keyBadge")
        key_badge.setFixedHeight(32)
        key_badge.setAlignment(Qt.AlignCenter)
        f_key = QFont("Segoe UI", 11)
        f_key.setWeight(QFont.Medium)
        key_badge.setFont(f_key)
        
        # Descrição
        desc_label = QLabel(description)
        desc_label.setObjectName("keyDescription")
        desc_label.setFont(QFont("Segoe UI", 13))
        
        row_layout.addWidget(key_badge)
        row_layout.addWidget(desc_label, 1)
        
        return row

    def _apply_styles(self):
        """Aplica estilos ao diálogo"""
        self.setStyleSheet("""
            QDialog {
                background: #FFFFFF;
            }
            QLabel#shortcutsTitle {
                color: #0c0f12;
                background: transparent;
            }
            QLabel#keyBadge {
                background: #F0F4F8;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                color: #1A6B7C;
                padding: 0px 12px;
                min-width: 60px;
            }
            QLabel#keyDescription {
                color: #4a5260;
                background: transparent;
            }
            QPushButton#shortcutsCloseBtn {
                background: #1A6B7C;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton#shortcutsCloseBtn:hover {
                background: #155E6D;
            }
            QPushButton#shortcutsCloseBtn:pressed {
                background: #114F5E;
            }
        """)


# ══════════════════════════════════════════════
# NOVO: RippleButton - Botão com efeito ripple
# ══════════════════════════════════════════════
class RippleButton(QPushButton):
    """QPushButton com efeito ripple ao clicar"""
    
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._ripples = []

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self._create_ripple(event.pos())

    def _create_ripple(self, pos: QPoint):
        """Cria efeito ripple na posição do clique"""
        ripple = QWidget(self)
        ripple.setFixedSize(0, 0)
        ripple.move(pos.x(), pos.y())
        ripple.setStyleSheet(
            "background: rgba(255, 255, 255, 0.5); border-radius: 50%;"
        )
        ripple.show()
        
        # Animação de expansão
        anim = QPropertyAnimation(ripple, b"geometry", self)
        anim.setDuration(600)
        final_size = max(self.width(), self.height()) * 2
        anim.setStartValue(QRectF(pos.x(), pos.y(), 0, 0))
        anim.setEndValue(QRectF(
            pos.x() - final_size/2,
            pos.y() - final_size/2,
            final_size,
            final_size
        ))
        anim.setEasingCurve(QEasingCurve.OutCubic)
        
        # Animação de fade out
        fade = QPropertyAnimation(ripple, b"windowOpacity", self)
        fade.setDuration(600)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        
        # Grupo de animações
        group = QParallelAnimationGroup(self)
        group.addAnimation(anim)
        group.addAnimation(fade)
        group.finished.connect(ripple.deleteLater)
        group.start()
        
        self._ripples.append((ripple, group))


# ══════════════════════════════════════════════
# EyeButton — ícone animado desenhado via QPainter
# ══════════════════════════════════════════════
class EyeButton(QAbstractButton):
    """
    Botão ver/ocultar senha.
    _t = 0.0 → olho fechado (senha oculta)
    _t = 1.0 → olho aberto  (senha visível)
    A "pálpebra" superior anima de linha reta → curva ao abrir.
    A pupila cresce junto.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 44)
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.NoFocus)

        self._t     = 0.0
        self._hover = False

        self._anim = QPropertyAnimation(self, b"eyeT", self)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        self.clicked.connect(self._on_clicked)

    # ── Property animável ──────────────────────
    def getEyeT(self) -> float: return self._t

    def setEyeT(self, v: float):
        self._t = max(0.0, min(1.0, v))
        self.update()

    eyeT = Property(float, getEyeT, setEyeT)

    def _on_clicked(self):
        target = 1.0 if self.isChecked() else 0.0
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(target)
        self._anim.start()

    def isOpen(self) -> bool:
        return self.isChecked()

    def enterEvent(self, e): self._hover = True;  self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # ── Fundo do botão ────────────────────
        r = self.rect().adjusted(1, 1, -1, -1)
        border = QColor("#1a6b7c") if self._hover else QColor("#e8eaed")
        p.setPen(QPen(border, 1.0))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(r, 10, 10)

        # ── Cor do ícone ──────────────────────
        icon_col = QColor("#1a6b7c") if self._hover else QColor("#9199a6")

        cx = self.width()  / 2.0
        cy = self.height() / 2.0
        ew = 9.5    # metade largura olho
        eh = 5.0    # metade altura

        pen = QPen(icon_col, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)

        # ── Curva inferior (sempre visível) ───
        bot = QPainterPath()
        bot.moveTo(cx - ew, cy)
        bot.cubicTo(cx - ew, cy + eh,  cx + ew, cy + eh,  cx + ew, cy)
        p.drawPath(bot)

        # ── Curva superior (pálpebra animada) ─
        # t=0 → linha reta; t=1 → curva aberta
        lift = eh * self._t
        top = QPainterPath()
        top.moveTo(cx - ew, cy)
        top.cubicTo(cx - ew, cy - lift, cx + ew, cy - lift, cx + ew, cy)
        p.drawPath(top)

        # ── Pupila ────────────────────────────
        pr = 2.0 + 1.2 * self._t      # raio cresce ao abrir
        p.setPen(Qt.NoPen)
        p.setBrush(icon_col)
        p.drawEllipse(QRectF(cx - pr, cy - pr, pr * 2, pr * 2))

        # ── Slash diagonal quando fechado ─────
        if self._t < 0.45:
            alpha = int(210 * (1.0 - self._t / 0.45))
            slash_col = QColor(
                icon_col.red(), icon_col.green(), icon_col.blue(), alpha
            )
            p.setPen(QPen(slash_col, 1.5, Qt.SolidLine, Qt.RoundCap))
            off = 6.0
            p.drawLine(
                QRectF(cx - off, cy - off, 1, 1).topLeft(),
                QRectF(cx + off, cy + off, 1, 1).topLeft(),
            )

        p.end()

    def sizeHint(self) -> QSize:
        return QSize(44, 44)


class WavingHand(QWidget):
    """
    Mão animada para saudação do login.
    Rotaciona o emoji para simular aceno.
    """

    def __init__(self, font_family: str = "Segoe UI", parent=None):
        super().__init__(parent)
        self.setObjectName("fmGreetingHand")
        # Área maior para evitar corte do emoji durante a rotação.
        self.setFixedSize(42, 42)
        self._angle = 0.0
        self._font = QFont(font_family, 22)

        self._anim = QPropertyAnimation(self, b"angle", self)
        self._anim.setDuration(3600)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)

        # Aceno mais lento e suave com pequena pausa no fim
        self._anim.setKeyValueAt(0.00, 0.0)
        self._anim.setKeyValueAt(0.18, 7.0)
        self._anim.setKeyValueAt(0.36, -4.0)
        self._anim.setKeyValueAt(0.54, 6.0)
        self._anim.setKeyValueAt(0.72, -3.0)
        self._anim.setKeyValueAt(0.86, 1.5)
        self._anim.setKeyValueAt(1.00, 0.0)

    def set_font_family(self, family: str):
        self._font.setFamily(family or "Segoe UI")
        self.update()

    def get_angle(self) -> float:
        return self._angle

    def set_angle(self, value: float):
        self._angle = float(value)
        self.update()

    angle = Property(float, get_angle, set_angle)

    def start(self):
        if self._anim.state() != QPropertyAnimation.Running:
            self._anim.start()

    def stop(self):
        self._anim.stop()
        self.set_angle(0.0)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        r = self.rect()
        cx = r.center().x()
        cy = r.center().y()

        p.translate(cx, cy)
        p.rotate(self._angle)
        p.setFont(self._font)
        p.drawText(QRectF(-20, -20, 40, 40), Qt.AlignCenter, "👋")
        p.end()


# ══════════════════════════════════════════════
# LockoutBar — barra de progresso regressiva
# ══════════════════════════════════════════════
class LockoutBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(3)
        self._progress = 1.0

    def setProgress(self, v: float):
        self._progress = max(0.0, min(1.0, v))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#e8eaed"))
        w = int(self.width() * self._progress)
        if w > 0:
            p.fillRect(0, 0, w, self.height(), QColor("#c0392b"))


# ══════════════════════════════════════════════
# LeftPanel — branding + marca d'água da logo
# MODIFICADO: Adiciona dashboard de status
# ══════════════════════════════════════════════
class LeftPanel(QWidget):
    WM_OPACITY = 0.09

    def __init__(self, logo_path: str, serif_family: str, parent=None):
        super().__init__(parent)
        self._logo_path    = logo_path
        self._serif_family = serif_family
        self._wm_pm: QPixmap | None = None
        self.setMinimumWidth(320)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(52, 44, 52, 36)
        root.setSpacing(0)

        # Marca
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        brand_row.setContentsMargins(0, 0, 0, 0)
        icon_frame = QFrame()
        icon_frame.setFixedSize(32, 32)
        icon_frame.setObjectName("brandIcon")
        brand_lbl = QLabel("MedContract")
        brand_lbl.setObjectName("brandName")
        brand_row.addWidget(icon_frame)
        brand_row.addWidget(brand_lbl)
        brand_row.addStretch()

        eyebrow = QLabel("Pronto Clínica Arnaldo Quintela")
        eyebrow.setObjectName("lpEyebrow")

        headline = QLabel("Gestão de\ncontratos e\npagamentos")
        headline.setObjectName("lpHeadline")
        headline.setWordWrap(True)
        f_h = QFont(self._serif_family, 33)
        f_h.setWeight(QFont.Light)
        headline.setFont(f_h)

        tagline = QLabel(
            "Acesso interno restrito à equipe autorizada.\n"
            "Todas as ações são registradas com hora e usuário."
        )
        tagline.setObjectName("lpTagline")
        tagline.setWordWrap(True)

        bullets_data = [
            "Controle de contratos médicos em tempo real",
            "Auditoria completa de acessos e alterações",
            "Relatórios de pagamentos e repasses",
            "Perfis de acesso por nível hierárquico",
        ]
        bullets_w = QWidget()
        bullets_w.setAttribute(Qt.WA_TranslucentBackground, True)
        bl = QVBoxLayout(bullets_w)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(11)
        for txt in bullets_data:
            row = QHBoxLayout()
            row.setSpacing(12)
            dot = QLabel()
            dot.setFixedSize(6, 6)
            dot.setObjectName("lpBulletDot")
            lbl = QLabel(txt)
            lbl.setObjectName("lpBulletText")
            row.addWidget(dot, 0, Qt.AlignVCenter)
            row.addWidget(lbl, 1)
            bl.addLayout(row)

        # ── NOVO: Dashboard de Status do Sistema ──
        status_container = QFrame()
        status_container.setObjectName("statusContainer")
        status_layout = QVBoxLayout(status_container)
        status_layout.setContentsMargins(16, 12, 16, 12)
        status_layout.setSpacing(10)
        
        status_title = QLabel("Status do Sistema")
        status_title.setObjectName("statusTitle")
        status_title.setFont(QFont("Segoe UI", 11, QFont.DemiBold))
        status_layout.addWidget(status_title)
        
        # Indicador de Banco de Dados
        self.db_status_row = self._create_status_row("Banco de dados")
        self.db_indicator = StatusIndicator()
        self.db_status_row.layout().insertWidget(1, self.db_indicator)
        status_layout.addWidget(self.db_status_row)
        
        # Indicador de Rede
        self.net_status_row = self._create_status_row("Conexão de rede")
        self.net_indicator = StatusIndicator()
        self.net_status_row.layout().insertWidget(1, self.net_indicator)
        status_layout.addWidget(self.net_status_row)
        
        # Última verificação
        self.last_check_label = QLabel("Verificando...")
        self.last_check_label.setObjectName("lastCheckLabel")
        self.last_check_label.setFont(QFont("Segoe UI", 9))
        status_layout.addWidget(self.last_check_label)

        footer = QLabel(f"Uso interno · Confidencial · v{APP_VERSION}")
        footer.setObjectName("lpFooter")

        root.addLayout(brand_row)
        root.addSpacing(52)
        root.addWidget(eyebrow)
        root.addSpacing(14)
        root.addWidget(headline)
        root.addSpacing(20)
        root.addWidget(tagline)
        root.addSpacing(26)
        root.addWidget(bullets_w)
        root.addStretch(1)
        root.addWidget(status_container)
        root.addSpacing(10)
        root.addWidget(footer)

    def _create_status_row(self, label_text: str) -> QWidget:
        """Cria uma linha de status com label e indicador"""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        
        label = QLabel(label_text)
        label.setObjectName("statusLabel")
        label.setFont(QFont("Segoe UI", 10))
        row_layout.addWidget(label, 1)
        
        # Espaço para indicador (será inserido externamente)
        row_layout.addStretch(0)
        
        return row

    def update_status(self, status_dict: dict):
        """Atualiza indicadores de status"""
        db_status = status_dict.get('database', 'offline')
        net_status = status_dict.get('network', 'offline')
        timestamp = status_dict.get('timestamp')
        
        self.db_indicator.set_status(db_status)
        self.net_indicator.set_status(net_status)
        
        if timestamp:
            time_str = timestamp.strftime("%H:%M:%S")
            self.last_check_label.setText(f"Última verificação: {time_str}")

    def _reload_watermark(self):
        pm = QPixmap(self._logo_path)
        if pm.isNull():
            self._wm_pm = None
            self.update()
            return
        target_w = int(self.width() * 0.68)
        self._wm_pm = pm.scaledToWidth(max(80, target_w), Qt.SmoothTransformation)
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._reload_watermark()

    def showEvent(self, e):
        super().showEvent(e)
        self._reload_watermark()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # Fundo branco
        p.fillRect(self.rect(), QColor("#ffffff"))

        # Borda direita
        p.setPen(QPen(QColor("#e8eaed"), 1))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())

        # Marca d'água centralizada
        if self._wm_pm and not self._wm_pm.isNull():
            p.setOpacity(self.WM_OPACITY)
            x = (self.width()  - self._wm_pm.width())  // 2
            y = (self.height() - self._wm_pm.height()) // 2
            p.drawPixmap(x, y, self._wm_pm)
            p.setOpacity(1.0)

        super().paintEvent(e)


# ══════════════════════════════════════════════
# RightPanel — fundo #f9fafb
# ══════════════════════════════════════════════
class RightPanel(QWidget):
    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#f9fafb"))
        super().paintEvent(e)


# ══════════════════════════════════════════════
# LoginView - MODIFICADO com todas as melhorias
# ══════════════════════════════════════════════
class LoginView(QWidget):
    login_success = Signal(str)

    _ACCENT       = "#1a6b7c"
    _ACCENT_HOVER = "#155e6d"
    _INK          = "#0c0f12"
    _INK2         = "#4a5260"
    _INK3         = "#9199a6"
    _LINE         = "#e8eaed"
    _WHITE        = "#ffffff"
    _BG           = "#f9fafb"
    _DANGER       = "#c0392b"

    _MAX_ATTEMPTS    = 3
    _LOCKOUT_SECS    = 60
    _IDLE_TIMEOUT_MS = 3 * 60 * 1000

    def __init__(self):
        super().__init__()

        self._loading       = False
        self._did_fade      = False
        self._login_worker  = None
        self._attempt_count = 0
        self._countdown_rem = 0
        self._loading_dots  = 0

        self._base_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        self._sans, self._serif = _load_fonts(self._base_dir)

        # ── Timers ──────────────────────────────
        self._loading_timer = QTimer(self)
        self._loading_timer.setInterval(90)
        self._loading_timer.timeout.connect(self._tick_loading)

        self._msg_timer = QTimer(self)
        self._msg_timer.setSingleShot(True)
        self._msg_timer.timeout.connect(self._hide_message)

        self._guard_timer = QTimer(self)
        self._guard_timer.setSingleShot(True)
        self._guard_timer.timeout.connect(self._on_login_timeout)

        self._lockout_timer = QTimer(self)
        self._lockout_timer.setSingleShot(True)
        self._lockout_timer.timeout.connect(self._reset_lockout)

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._tick_countdown)

        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._on_idle_timeout)
        if self._IDLE_TIMEOUT_MS > 0:
            self._idle_timer.start(self._IDLE_TIMEOUT_MS)

        # NOVO: Timer para checagem de status
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(10000)  # Verifica a cada 10s
        self._status_timer.timeout.connect(self._check_system_status)

        self._greeting_text = ""
        self._greeting_idx = 0
        self._greeting_timer = QTimer(self)
        self._greeting_timer.setInterval(34)
        self._greeting_timer.timeout.connect(self._tick_greeting)

        self.login_settings = LoginSettings()
        self.threadpool     = QThreadPool.globalInstance()

        self._setup_ui()
        self._setup_keyboard_shortcuts()  # NOVO
        self._apply_styles()
        self._load_remembered_user()
        self._setup_tab_order()

        self._pw_filter = PasswordFieldFilter(self)
        self._pw_filter.caps_changed.connect(self._show_caps_warning)
        self.password_input.installEventFilter(self._pw_filter)

        for w in (self.username_input, self.password_input):
            w.textChanged.connect(self._reset_idle_timer)

        # NOVO: Inicia checagem de status do sistema
        self._check_system_status()
        self._status_timer.start()

    @staticmethod
    def _build_greeting_text() -> str:
        hour = datetime.now().hour
        greeting = "Bom dia" if hour < 12 else ("Boa tarde" if hour < 18 else "Boa noite")
        return greeting

    def _refresh_greeting_text(self):
        self._greeting_text = self._build_greeting_text()
        if hasattr(self, "greeting_lbl"):
            self.greeting_lbl.setText(self._greeting_text)

    def _start_greeting_animation(self):
        self._refresh_greeting_text()
        if hasattr(self, "greeting_hand"):
            self.greeting_hand.start()
        self._greeting_timer.stop()
        self._greeting_idx = 0
        self.greeting_lbl.setText("")
        self._greeting_timer.start()

    def _tick_greeting(self):
        if not self._greeting_text:
            self._greeting_timer.stop()
            return
        self._greeting_idx += 1
        self.greeting_lbl.setText(self._greeting_text[: self._greeting_idx])
        if self._greeting_idx >= len(self._greeting_text):
            self._greeting_timer.stop()

    # ─────────────────────────────────────────
    # NOVO: Configurar atalhos de teclado
    # ─────────────────────────────────────────
    def _setup_keyboard_shortcuts(self):
        """Configura atalhos de teclado globais"""
        # Ctrl+L - Focar no campo usuário
        shortcut_user = QShortcut(QKeySequence("Ctrl+L"), self)
        shortcut_user.activated.connect(lambda: self.username_input.setFocus())
        
        # Ctrl+K - Focar no campo senha
        shortcut_pass = QShortcut(QKeySequence("Ctrl+K"), self)
        shortcut_pass.activated.connect(lambda: self.password_input.setFocus())
        
        # Ctrl+H - Toggle visibilidade senha
        shortcut_toggle = QShortcut(QKeySequence("Ctrl+H"), self)
        shortcut_toggle.activated.connect(self.btn_eye.click)
        
        # ? - Mostrar ajuda de atalhos
        shortcut_help = QShortcut(QKeySequence("?"), self)
        shortcut_help.activated.connect(self._show_keyboard_shortcuts)

    def _show_keyboard_shortcuts(self):
        """Mostra diálogo com atalhos de teclado"""
        dialog = KeyboardShortcutsDialog(self)
        dialog.exec()

    # ─────────────────────────────────────────
    # NOVO: Checagem de status do sistema
    # ─────────────────────────────────────────
    def _check_system_status(self):
        """Inicia worker para verificar status do sistema"""
        worker = SystemStatusChecker()
        worker.signals.status_updated.connect(self._on_status_updated)
        self.threadpool.start(worker)

    def _on_status_updated(self, status: dict):
        """Callback quando status é atualizado"""
        if hasattr(self, 'left_panel'):
            self.left_panel.update_status(status)

    # ─────────────────────────────────────────
    # Setup UI - MODIFICADO
    # ─────────────────────────────────────────
    def _setup_ui(self):
        self.setObjectName("LoginView")
        self.setMinimumSize(820, 540)

        logo_path = os.path.join(self._base_dir, "assets", "logo.png")

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Painel esquerdo ───────────────────
        self.left_panel = LeftPanel(logo_path, self._serif)
        self.left_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # ── Painel direito ────────────────────
        right = RightPanel()
        right.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right.setMinimumWidth(380)

        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addStretch(1)

        # Form box
        self.form_box = QFrame()
        self.form_box.setObjectName("formBox")
        self.form_box.setFixedWidth(348)
        self.form_box.setAttribute(Qt.WA_TranslucentBackground, True)

        fb = QVBoxLayout(self.form_box)
        fb.setContentsMargins(24, 22, 24, 20)
        fb.setSpacing(0)

        # Saudação dinâmica
        self._greeting_text = self._build_greeting_text()
        self.greeting_lbl = QLabel(self._greeting_text)
        self.greeting_lbl.setObjectName("fmGreeting")
        f_gr = QFont(self._sans, 22)
        f_gr.setWeight(QFont.DemiBold)
        self.greeting_lbl.setFont(f_gr)
        self.greeting_hand = WavingHand(self._sans)

        self.form_sub = QLabel("Entre com suas credenciais para continuar.")
        self.form_sub.setObjectName("fmSub")
        self.form_sub.setFont(QFont(self._sans, 13))

        greeting_row = QHBoxLayout()
        greeting_row.setContentsMargins(0, 0, 0, 0)
        greeting_row.setSpacing(8)
        greeting_row.addWidget(self.greeting_lbl)
        greeting_row.addWidget(self.greeting_hand, 0, Qt.AlignBottom)
        greeting_row.addStretch(1)

        fb.addLayout(greeting_row)
        fb.addSpacing(6)
        fb.addWidget(self.form_sub)
        fb.addSpacing(24)

        # Campo Usuário
        fb.addWidget(self._field_label("Usuário"))
        fb.addSpacing(7)
        self.username_input = QLineEdit()
        self.username_input.setObjectName("fmInput")
        self.username_input.setPlaceholderText("Digite seu usuário")
        self.username_input.setMaxLength(50)
        self.username_input.setFixedHeight(44)
        self.username_input.setClearButtonEnabled(True)
        self.username_input.setAccessibleName("Usuário")
        self.username_input.setFont(QFont(self._sans, 13))
        self.username_input.textChanged.connect(self._on_username_changed)
        self.username_input.returnPressed.connect(
            lambda: self.password_input.setFocus()
        )
        # NOVO: Adiciona efeito de focus
        self.username_input.installEventFilter(self)
        fb.addWidget(self.username_input)
        fb.addSpacing(18)

        # Campo Senha
        fb.addWidget(self._field_label("Senha"))
        fb.addSpacing(7)

        pw_row = QHBoxLayout()
        pw_row.setSpacing(8)
        pw_row.setContentsMargins(0, 0, 0, 0)

        self.password_input = QLineEdit()
        self.password_input.setObjectName("fmInput")
        self.password_input.setPlaceholderText("Digite sua senha")
        self.password_input.setMaxLength(128)
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setFixedHeight(44)
        self.password_input.setAccessibleName("Senha")
        self.password_input.setFont(QFont(self._sans, 13))
        self.password_input.textChanged.connect(self._hide_message)
        self.password_input.returnPressed.connect(self._on_login_clicked)
        # NOVO: Adiciona efeito de focus
        self.password_input.installEventFilter(self)

        self.btn_eye = EyeButton()
        self.btn_eye.setToolTip("Mostrar senha (Ctrl+H)")
        self.btn_eye.clicked.connect(self._toggle_password_visibility)

        pw_row.addWidget(self.password_input, 1)
        pw_row.addWidget(self.btn_eye)
        fb.addLayout(pw_row)
        fb.addSpacing(6)

        # Caps Lock
        self.caps_warn = QLabel("⚠  Caps Lock ativado")
        self.caps_warn.setObjectName("fmCapsWarn")
        self.caps_warn.setFont(QFont(self._sans, 11))
        self.caps_warn.setVisible(False)
        fb.addWidget(self.caps_warn)
        fb.addSpacing(16)

        # Lembrar + Esqueci
        opts_row = QHBoxLayout()
        opts_row.setContentsMargins(0, 0, 0, 0)
        opts_row.setSpacing(8)

        self.remember_cb = QCheckBox("Lembrar usuário")
        self.remember_cb.setObjectName("fmRemember")
        self.remember_cb.setCursor(Qt.PointingHandCursor)
        self.remember_cb.setFont(QFont(self._sans, 12))
        self.remember_cb.toggled.connect(self._on_remember_toggled)

        forgot_btn = QToolButton()
        forgot_btn.setObjectName("fmForgot")
        forgot_btn.setText("Esqueci a senha")
        forgot_btn.setCursor(Qt.PointingHandCursor)
        forgot_btn.setFont(QFont(self._sans, 12))
        forgot_btn.setAutoRaise(True)
        forgot_btn.clicked.connect(self._on_forgot_password)

        opts_row.addWidget(self.remember_cb, 1)
        opts_row.addWidget(forgot_btn)
        fb.addLayout(opts_row)
        fb.addSpacing(24)

        # MODIFICADO: Botão Entrar com RippleButton
        self.login_button = RippleButton("Entrar")
        self.login_button.setObjectName("fmLoginBtn")
        self.login_button.setFixedHeight(46)
        self.login_button.setCursor(Qt.PointingHandCursor)
        self.login_button.setDefault(True)
        f_btn = QFont(self._sans, 14)
        f_btn.setWeight(QFont.Medium)
        self.login_button.setFont(f_btn)
        self.login_button.clicked.connect(self._on_login_clicked)
        fb.addWidget(self.login_button)
        fb.addSpacing(10)

        # Lockout bar
        self.lockout_bar = LockoutBar()
        self.lockout_bar.setVisible(False)
        self.lockout_lbl = QLabel()
        self.lockout_lbl.setObjectName("fmLockout")
        self.lockout_lbl.setAlignment(Qt.AlignCenter)
        self.lockout_lbl.setFont(QFont(self._sans, 11))
        self.lockout_lbl.setVisible(False)
        fb.addWidget(self.lockout_bar)
        fb.addSpacing(4)
        fb.addWidget(self.lockout_lbl)

        # Mensagem inline
        self.inline_msg = QLabel("")
        self.inline_msg.setObjectName("fmInlineMsg")
        self.inline_msg.setAlignment(Qt.AlignCenter)
        self.inline_msg.setWordWrap(True)
        self.inline_msg.setFont(QFont(self._sans, 12))
        self.inline_msg.setVisible(False)
        self._msg_opacity = QGraphicsOpacityEffect(self.inline_msg)
        self._msg_opacity.setOpacity(0.0)
        self.inline_msg.setGraphicsEffect(self._msg_opacity)
        fb.addSpacing(10)
        fb.addWidget(self.inline_msg)

        # Separador + rodapé
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("fmSep")

        form_footer = QLabel(
            "Pronto Clínica Arnaldo Quintela · Sistema de Gestão Interna\n"
            "Todos os acessos são registrados e auditados."
        )
        form_footer.setObjectName("fmFooter")
        form_footer.setAlignment(Qt.AlignCenter)
        form_footer.setWordWrap(True)
        form_footer.setFont(QFont(self._sans, 11))

        fb.addSpacing(24)
        fb.addWidget(sep)
        fb.addSpacing(14)
        fb.addWidget(form_footer)

        # Centraliza o form_box no painel direito
        center = QHBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.addStretch(1)
        center.addWidget(self.form_box)
        center.addStretch(1)

        right_layout.addLayout(center)
        right_layout.addStretch(1)

        hint_row = QHBoxLayout()
        hint_row.setContentsMargins(0, 0, 18, 12)
        hint_row.setSpacing(0)
        hint_row.addStretch(1)
        self.shortcut_hint = QLabel("Pressione ? para ver atalhos")
        self.shortcut_hint.setObjectName("shortcutHint")
        self.shortcut_hint.setFont(QFont(self._sans, 10))
        self.shortcut_hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hint_row.addWidget(self.shortcut_hint, 0, Qt.AlignRight | Qt.AlignBottom)
        right_layout.addLayout(hint_row)

        root.addWidget(self.left_panel, 48)
        root.addWidget(right, 52)

        # NOVO: Overlay de confete (invisível inicialmente)
        self.confetti = ConfettiOverlay(self)
        self.confetti.hide()

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("fmFieldLabel")
        lbl.setFont(QFont(self._sans, 12))
        return lbl

    # ─────────────────────────────────────────
    # NOVO: Event filter para efeito de focus elevado
    # ─────────────────────────────────────────
    def eventFilter(self, obj, event):
        """Adiciona elevação suave aos inputs quando ganham foco"""
        username_input = getattr(self, "username_input", None)
        password_input = getattr(self, "password_input", None)
        if obj in (username_input, password_input):
            if event.type() == QEvent.FocusIn:
                self._add_input_elevation(obj)
            elif event.type() == QEvent.FocusOut:
                self._remove_input_elevation(obj)
        return super().eventFilter(obj, event)

    def _add_input_elevation(self, widget):
        """Adiciona sombra elevada ao input"""
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(12)
        shadow.setXOffset(0)
        shadow.setYOffset(2)
        shadow.setColor(QColor(26, 107, 124, 40))
        widget.setGraphicsEffect(shadow)

    def _remove_input_elevation(self, widget):
        """Remove sombra do input"""
        widget.setGraphicsEffect(None)

    # ─────────────────────────────────────────
    # Estilos — theme.qss global + overrides da LoginView
    # MODIFICADO: Adiciona estilos para novos componentes
    # ─────────────────────────────────────────
    def _apply_styles(self):
        global_qss = _load_stylesheet(self._base_dir)

        a   = self._ACCENT
        ah  = self._ACCENT_HOVER
        ink = self._INK
        i2  = self._INK2
        i3  = self._INK3
        ln  = self._LINE
        wh  = self._WHITE
        dng = self._DANGER
        sf  = self._sans
        ser = self._serif

        login_qss = f"""

        /* ══ BASE ══════════════════════════════════════════════════════ */
        QWidget#LoginView {{
            background: #F0F4F8;
            font-family: '{sf}', 'Segoe UI', sans-serif;
        }}
        QWidget#LoginView * {{
            font-family: '{sf}', 'Segoe UI', sans-serif;
        }}

        /* ══ PAINEL ESQUERDO ════════════════════════════════════════════ */

        /* Ícone da marca — quadrado teal arredondado */
        QFrame#brandIcon {{
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:1,
                stop:0 #1A6B7C, stop:1 #2B938F
            );
            border-radius: 10px;
        }}

        /* Nome da marca */
        QLabel#brandName {{
            font-size: 14px;
            font-weight: 700;
            color: {ink};
            background: transparent;
            letter-spacing: -0.2px;
        }}

        /* Eyebrow — "Pronto Clínica Arnaldo Quintela" */
        QLabel#lpEyebrow {{
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.12em;
            color: #1A6B7C;
            background: transparent;
            text-transform: uppercase;
        }}

        /* Headline serif — "Gestão de contratos..." */
        QLabel#lpHeadline {{
            font-family: '{ser}', '{sf}', serif;
            color: {ink};
            background: transparent;
            line-height: 1.15;
        }}

        /* Tagline */
        QLabel#lpTagline {{
            font-size: 13px;
            color: {i2};
            background: transparent;
            line-height: 1.6;
        }}

        /* Bullets */
        QLabel#lpBulletText {{
            font-size: 13px;
            color: {i2};
            background: transparent;
        }}
        QLabel#lpBulletDot {{
            background: #1A6B7C;
            border-radius: 3px;
            min-width: 6px; max-width: 6px;
            min-height: 6px; max-height: 6px;
        }}

        /* NOVO: Status Container */
        QFrame#statusContainer {{
            background: rgba(26, 107, 124, 0.045);
            border: 1px solid rgba(26, 107, 124, 0.14);
            border-radius: 14px;
        }}
        QLabel#statusTitle {{
            color: #164A58;
            background: transparent;
            font-size: 11px;
            font-weight: 700;
        }}
        QLabel#statusLabel {{
            color: #3C4E63;
            background: transparent;
            font-size: 10px;
        }}
        QLabel#lastCheckLabel {{
            color: #7C8DA1;
            background: transparent;
            font-size: 9px;
        }}

        /* Rodapé esquerdo */
        QLabel#lpFooter {{
            font-size: 11px;
            color: {i3};
            background: transparent;
            letter-spacing: 0.02em;
        }}

        /* ══ FORMULÁRIO ═════════════════════════════════════════════════ */
        QFrame#formBox {{
            background: rgba(255, 255, 255, 0.94);
            border: 1px solid rgba(15, 23, 42, 0.08);
            border-radius: 16px;
        }}

        /* Saudação "Boa noite 👋" */
        QLabel#fmGreeting {{
            color: {ink};
            background: transparent;
            letter-spacing: -0.5px;
        }}

        /* Subtítulo do form */
        QLabel#fmSub {{
            color: {i3};
            background: transparent;
            font-size: 13px;
        }}

        /* NOVO: Hint de atalho */
        QLabel#shortcutHint {{
            color: rgba(74, 82, 96, 0.65);
            background: transparent;
            font-style: normal;
            font-size: 10px;
            letter-spacing: 0.01em;
            padding-right: 2px;
        }}

        /* Labels dos campos — "Usuário" / "Senha" */
        QLabel#fmFieldLabel {{
            font-size: 11px;
            font-weight: 600;
            color: {i2};
            background: transparent;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }}

        /* ── Inputs ── */
        QLineEdit#fmInput {{
            border: 1.5px solid #E2E8F0;
            border-radius: 10px;
            padding: 0px 14px;
            min-height: 46px;
            background: {wh};
            color: {ink};
            font-size: 14px;
            font-weight: 500;
            selection-background-color: rgba(26,107,124,0.15);
        }}
        QLineEdit#fmInput:hover {{
            border-color: #CBD5E1;
        }}
        QLineEdit#fmInput:focus {{
            border: 1.5px solid #1A6B7C;
            background: {wh};
            outline: none;
        }}
        QLineEdit#fmInput:disabled {{
            background: #F8FAFC;
            color: {i3};
            border-color: #F1F5F9;
        }}

        /* ── Caps Lock ── */
        QLabel#fmCapsWarn {{
            font-size: 11px;
            font-weight: 600;
            color: #92400E;
            background: #FEF3C7;
            border: 1px solid #FDE68A;
            border-radius: 8px;
            padding: 5px 12px;
        }}

        /* ── Lembrar usuário ── */
        QCheckBox#fmRemember {{
            color: {i2};
            font-size: 13px;
            font-weight: 500;
            spacing: 8px;
            background: transparent;
        }}
        QCheckBox#fmRemember::indicator {{
            width: 18px;
            height: 18px;
            border: 1.5px solid #CBD5E1;
            border-radius: 5px;
            background: {wh};
        }}
        QCheckBox#fmRemember::indicator:hover {{
            border-color: #1A6B7C;
        }}
        QCheckBox#fmRemember::indicator:checked {{
            background: #1A6B7C;
            border-color: #1A6B7C;
            image: none;
        }}

        /* ── Esqueci a senha ── */
        QToolButton#fmForgot {{
            color: #1A6B7C;
            font-size: 13px;
            font-weight: 500;
            background: transparent;
            border: none;
            padding: 0;
        }}
        QToolButton#fmForgot:hover {{
            color: {ah};
            text-decoration: underline;
        }}

        /* ── Botão Entrar ── */
        QPushButton#fmLoginBtn {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 #1E7A8C, stop:1 #1A6B7C
            );
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 14px;
            font-weight: 600;
            letter-spacing: 0.02em;
            min-height: 46px;
        }}
        QPushButton#fmLoginBtn:hover {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 #1D7285, stop:1 #155E6E
            );
        }}
        QPushButton#fmLoginBtn:pressed {{
            background: #114F5E;
        }}
        QPushButton#fmLoginBtn:disabled {{
            background: #94B4BB;
            color: rgba(255,255,255,0.65);
        }}

        /* ── Lockout ── */
        QLabel#fmLockout {{
            color: {dng};
            font-size: 12px;
            font-weight: 600;
            background: transparent;
        }}

        /* ── Mensagem inline ── */
        QLabel#fmInlineMsg {{
            background: rgba(192,57,43,0.07);
            border: 1px solid rgba(192,57,43,0.18);
            border-left: 4px solid {dng};
            color: {dng};
            font-size: 12px;
            font-weight: 600;
            border-radius: 8px;
            padding: 10px 14px;
        }}

        /* ── Separador ── */
        QFrame#fmSep {{
            border: none;
            border-top: 1px solid #EEF2F7;
            background: transparent;
        }}

        /* ── Rodapé do form ── */
        QLabel#fmFooter {{
            color: {i3};
            font-size: 11px;
            background: transparent;
            line-height: 1.5;
        }}
        """

        self.setStyleSheet(global_qss + login_qss)

    # ─────────────────────────────────────────
    # Tab order
    # ─────────────────────────────────────────
    def _setup_tab_order(self):
        QWidget.setTabOrder(self.username_input, self.password_input)
        QWidget.setTabOrder(self.password_input, self.login_button)
        QWidget.setTabOrder(self.login_button, self.remember_cb)

    # ─────────────────────────────────────────
    # Fade de entrada
    # ─────────────────────────────────────────
    def showEvent(self, event):
        super().showEvent(event)
        if not self._did_fade:
            self._did_fade = True
            self._start_greeting_animation()
            eff = QGraphicsOpacityEffect(self.form_box)
            self.form_box.setGraphicsEffect(eff)
            anim = QPropertyAnimation(eff, b"opacity", self)
            anim.setDuration(380)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.finished.connect(lambda: self.form_box.setGraphicsEffect(None))
            anim.start(QPropertyAnimation.DeleteWhenStopped)

    # ─────────────────────────────────────────
    # Responsividade
    # ─────────────────────────────────────────
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.left_panel.setVisible(self.width() >= 760)
        # NOVO: Atualiza posição do confetti
        if hasattr(self, 'confetti'):
            self.confetti.setGeometry(self.rect())

    # ─────────────────────────────────────────
    # Persistência
    # ─────────────────────────────────────────
    def _load_remembered_user(self):
        remember = self.login_settings.remember
        user     = self.login_settings.username
        self.remember_cb.setChecked(remember)
        if remember and user:
            self.username_input.setText(user)
            self.password_input.setFocus()
        else:
            self.username_input.setFocus()

    def _save_remembered_user(self):
        self.login_settings.save(
            remember=self.remember_cb.isChecked(),
            username=self.username_input.text().strip(),
        )

    def _on_remember_toggled(self, _: bool):
        self._save_remembered_user()

    def _on_username_changed(self):
        self._hide_message()
        if self.remember_cb.isChecked():
            self._save_remembered_user()

    # ─────────────────────────────────────────
    # Caps Lock
    # ─────────────────────────────────────────
    def _show_caps_warning(self, visible: bool):
        self.caps_warn.setVisible(visible)

    # ─────────────────────────────────────────
    # Idle timeout
    # ─────────────────────────────────────────
    def _reset_idle_timer(self):
        if self._IDLE_TIMEOUT_MS > 0:
            self._idle_timer.start(self._IDLE_TIMEOUT_MS)

    def _on_idle_timeout(self):
        logger.info("Sessão de login expirou por inatividade.")
        self.password_input.clear()
        self._hide_message()
        self._show_message("Sessão expirada por inatividade. Digite novamente.", 5000)
        self.password_input.setFocus()

    # ─────────────────────────────────────────
    # Teclas
    # ─────────────────────────────────────────
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._on_login_clicked(); event.accept(); return
        if event.key() == Qt.Key_Escape:
            self._hide_message()
            self.password_input.clear()
            self.username_input.setFocus()
            event.accept(); return
        super().keyPressEvent(event)

    # ─────────────────────────────────────────
    # Toggle senha
    # ─────────────────────────────────────────
    def _toggle_password_visibility(self):
        open_ = self.btn_eye.isOpen()
        self.password_input.setEchoMode(
            QLineEdit.Normal if open_ else QLineEdit.Password
        )
        self.btn_eye.setToolTip(
            "Ocultar senha (Ctrl+H)" if open_ else "Mostrar senha (Ctrl+H)"
        )
        self.password_input.setFocus()

    # ─────────────────────────────────────────
    # Shake
    # ─────────────────────────────────────────
    def _shake_card(self):
        origin = self.form_box.pos()
        dx = 10
        anim = QPropertyAnimation(self.form_box, b"pos", self)
        anim.setDuration(380)
        for t, pt in [
            (0.00, QPoint(origin.x(),         origin.y())),
            (0.12, QPoint(origin.x() - dx,    origin.y())),
            (0.28, QPoint(origin.x() + dx,    origin.y())),
            (0.44, QPoint(origin.x() - dx,    origin.y())),
            (0.60, QPoint(origin.x() + dx,    origin.y())),
            (0.76, QPoint(origin.x() - dx//2, origin.y())),
            (0.88, QPoint(origin.x() + dx//2, origin.y())),
            (1.00, QPoint(origin.x(),         origin.y())),
        ]:
            anim.setKeyValueAt(t, pt)
        anim.finished.connect(lambda: self.form_box.move(origin))
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    # ─────────────────────────────────────────
    # Mensagens
    # ─────────────────────────────────────────
    def _show_message(self, text: str, ms: int = 0):
        self.inline_msg.setText(text)
        self.inline_msg.setVisible(True)
        self._msg_timer.stop()
        anim = QPropertyAnimation(self._msg_opacity, b"opacity", self)
        anim.setDuration(180)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        if ms > 0:
            self._msg_timer.start(ms)

    def _hide_message(self):
        self._msg_timer.stop()
        self.inline_msg.setVisible(False)
        self._msg_opacity.setOpacity(0.0)

    # ─────────────────────────────────────────
    # Rate limiting
    # ─────────────────────────────────────────
    def _is_locked_out(self) -> bool:
        return self._lockout_timer.isActive()

    def _register_failed_attempt(self, username: str):
        LoginAuditLogger.failure(username)
        self._attempt_count += 1
        if self._attempt_count >= self._MAX_ATTEMPTS:
            self.username_input.setEnabled(False)
            self.password_input.setEnabled(False)
            self.login_button.setEnabled(False)
            self._countdown_rem = self._LOCKOUT_SECS
            self._lockout_timer.start(self._LOCKOUT_SECS * 1000)
            self._countdown_timer.start()
            LoginAuditLogger.lockout(username, self._LOCKOUT_SECS)
            self.lockout_bar.setVisible(True)
            self.lockout_lbl.setVisible(True)
            self._update_lockout_ui()

    def _tick_countdown(self):
        self._countdown_rem -= 1
        self.lockout_bar.setProgress(self._countdown_rem / self._LOCKOUT_SECS)
        if self._countdown_rem <= 0:
            self._countdown_timer.stop()
        else:
            self._update_lockout_ui()

    def _update_lockout_ui(self):
        self.lockout_lbl.setText(
            f"Aguarde {self._countdown_rem}s para tentar novamente"
        )
        self._show_message(
            f"Muitas tentativas. Aguarde {self._countdown_rem}s."
        )

    def _reset_lockout(self):
        self._attempt_count = 0
        self._countdown_rem = 0
        self._countdown_timer.stop()
        self.username_input.setEnabled(True)
        self.password_input.setEnabled(True)
        self.login_button.setEnabled(True)
        self.login_button.setText("Entrar")
        self.lockout_bar.setVisible(False)
        self.lockout_lbl.setVisible(False)
        self._hide_message()
        self.password_input.setFocus()

    # ─────────────────────────────────────────
    # Loading - MODIFICADO: Loading spinner customizado
    # ─────────────────────────────────────────
    def _set_loading(self, loading: bool):
        self._loading = loading
        for w in (self.username_input, self.password_input,
                  self.btn_eye, self.remember_cb):
            w.setEnabled(not loading)
        if loading:
            self._loading_dots = 0
            self.login_button.setEnabled(False)
            self.login_button.setText("⟳  Entrando")
            self._loading_timer.start()
            self._guard_timer.start(15000)
        else:
            self._loading_timer.stop()
            self._guard_timer.stop()
            if not self._is_locked_out():
                self.login_button.setEnabled(True)
                self.login_button.setText("Entrar")

    def _tick_loading(self):
        spinners = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._loading_dots = (self._loading_dots + 1) % len(spinners)
        self.login_button.setText(f"{spinners[self._loading_dots]}  Entrando")

    def _on_login_timeout(self):
        if not self._loading:
            return
        self._set_loading(False)
        self._login_worker = None
        self._show_message(
            "Não foi possível concluir o login. Tente novamente."
        )

    # ─────────────────────────────────────────
    # Animação de saída - MODIFICADO: Adiciona confete
    # ─────────────────────────────────────────
    def _animate_exit(self, on_done):
        # NOVO: Celebração com confete
        self.confetti.show()
        self.confetti.celebrate()
        
        eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(400)  # Aumentado para dar tempo do confete
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InCubic)
        anim.finished.connect(on_done)
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    # ─────────────────────────────────────────
    # prepare_for_show
    # ─────────────────────────────────────────
    def prepare_for_show(self):
        self.setGraphicsEffect(None)
        self._set_loading(False)
        self._hide_message()
        self._did_fade = False
        self._greeting_timer.stop()
        self._refresh_greeting_text()
        if hasattr(self, "greeting_hand"):
            self.greeting_hand.stop()
        self.caps_warn.setVisible(False)
        if self.btn_eye.isChecked():
            self.btn_eye.setChecked(False)
            self.btn_eye._t = 0.0
            self.btn_eye.update()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.btn_eye.setToolTip("Mostrar senha (Ctrl+H)")
        self.confetti.hide()

    # ─────────────────────────────────────────
    # Login (thread)
    # ─────────────────────────────────────────
    def _on_login_clicked(self):
        if self._loading or self._is_locked_out():
            return

        self._reset_idle_timer()
        self._hide_message()

        username = self.username_input.text().strip()
        raw_pwd  = self.password_input.text()

        if not username:
            self._show_message("Digite seu usuário para continuar.", 3000)
            self.username_input.setFocus()
            return
        
        if not raw_pwd:
            self._show_message("Digite sua senha para continuar.", 3000)
            self.password_input.setFocus()
            return
        
        if len(raw_pwd) < 4:
            self._show_message("Senha muito curta.", 3000)
            self.password_input.setFocus()
            return

        self._set_loading(True)

        secure = SecureString(raw_pwd)
        del raw_pwd

        worker = _LoginWorker(username, secure)
        self._login_worker = worker
        worker.signals.finished.connect(
            lambda valid, nivel, w=worker:
                self._on_login_result(valid, nivel, username, w)
        )
        self.threadpool.start(worker)

    def _on_login_result(self, valid: bool, nivel, username: str, worker=None):
        if worker is self._login_worker:
            self._login_worker = None
        self._set_loading(False)

        if valid:
            LoginAuditLogger.success(username)
            self._save_remembered_user()
            self.login_button.setText("✓  Acesso liberado")
            self.login_button.setStyleSheet(
                "QPushButton#fmLoginBtn { background: #1a7a47; color: white; "
                "border-radius: 10px; }"
            )
            QTimer.singleShot(
                400,
                lambda: self._animate_exit(
                    lambda: self.login_success.emit(str(nivel or ""))
                ),
            )
            return

        self._shake_card()
        self.password_input.clear()
        self._register_failed_attempt(username)

        if not self._is_locked_out():
            rem = self._MAX_ATTEMPTS - self._attempt_count
            self._show_message(
                f"Credenciais inválidas. "
                f"{rem} tentativa{'s' if rem != 1 else ''} "
                f"restante{'s' if rem != 1 else ''}."
            )

        self.password_input.setFocus()

    def _on_forgot_password(self):
        """Handler para recuperação de senha."""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            self,
            "Recuperação de Senha",
            "Entre em contato com o administrador do sistema para redefinir sua senha.\n\n"
            "Telefone: (21) 96599-3667\n"
            "Email: suporte@medcontract.com.br"
        )
