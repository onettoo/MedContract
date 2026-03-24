# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import smtplib
import ssl
import base64
import unicodedata
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, parseaddr


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _is_ascii(value: str) -> bool:
    try:
        str(value or "").encode("ascii")
        return True
    except Exception:
        return False


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_login(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    _, parsed_addr = parseaddr(raw)
    return (parsed_addr or raw).strip()


def _ascii_fold(value: str) -> str:
    txt = str(value or "")
    norm = unicodedata.normalize("NFKD", txt)
    return "".join(ch for ch in norm if ord(ch) < 128)


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    username: str
    password: str
    from_email: str
    from_name: str
    use_tls: bool
    use_ssl: bool
    timeout_seconds: int

    @property
    def from_header(self) -> str:
        if self.from_name:
            return formataddr((self.from_name, self.from_email), charset="utf-8")
        return self.from_email


def load_smtp_config() -> SmtpConfig:
    host = str(os.getenv("MEDCONTRACT_SMTP_HOST", "") or "").strip()
    try:
        port = int(str(os.getenv("MEDCONTRACT_SMTP_PORT", "587") or "587").strip())
    except Exception:
        port = 587

    username = _normalize_login(os.getenv("MEDCONTRACT_SMTP_USER", "") or "")
    password = str(os.getenv("MEDCONTRACT_SMTP_PASSWORD", "") or "")

    raw_from = str(os.getenv("MEDCONTRACT_SMTP_FROM", "") or "").strip()
    parsed_name, parsed_addr = parseaddr(raw_from)
    from_email = (parsed_addr or raw_from or "").strip()
    if not from_email:
        from_email = username

    raw_from_name = os.getenv("MEDCONTRACT_SMTP_FROM_NAME")
    if raw_from_name is None:
        from_name = (parsed_name or "MedContract").strip() or "MedContract"
    else:
        from_name = str(raw_from_name or "").strip() or "MedContract"

    use_ssl = _env_flag("MEDCONTRACT_SMTP_USE_SSL", default=False)
    use_tls = _env_flag("MEDCONTRACT_SMTP_USE_TLS", default=not use_ssl)
    if use_ssl:
        use_tls = False

    try:
        timeout_seconds = int(str(os.getenv("MEDCONTRACT_SMTP_TIMEOUT", "20") or "20").strip())
    except Exception:
        timeout_seconds = 20
    timeout_seconds = max(5, timeout_seconds)

    return SmtpConfig(
        host=host,
        port=port,
        username=username,
        password=password,
        from_email=from_email,
        from_name=from_name,
        use_tls=use_tls,
        use_ssl=use_ssl,
        timeout_seconds=timeout_seconds,
    )


def smtp_config_help_text() -> str:
    return (
        "Configure estas variaveis no .env: "
        "MEDCONTRACT_SMTP_HOST, MEDCONTRACT_SMTP_PORT, MEDCONTRACT_SMTP_USER, "
        "MEDCONTRACT_SMTP_PASSWORD, MEDCONTRACT_SMTP_FROM."
    )


def _validate_recipient(email: str) -> str:
    to_email = str(email or "").strip()
    _, parsed_addr = parseaddr(to_email)
    to_email = (parsed_addr or to_email).strip()
    if not to_email:
        raise ValueError("E-mail do cliente nao informado.")
    if not _EMAIL_RE.match(to_email):
        raise ValueError("E-mail do cliente invalido.")
    if not _is_ascii(to_email):
        raise ValueError("E-mail do cliente invalido (use apenas endereco sem nome/acentos).")
    return to_email


def _validate_content(subject: str, body_text: str):
    subj = str(subject or "").strip()
    body = str(body_text or "").strip()
    if not subj:
        raise ValueError("Assunto do e-mail nao informado.")
    if not body:
        raise ValueError("Corpo do e-mail nao informado.")
    return subj, body


def _validate_smtp_config(cfg: SmtpConfig):
    if not cfg.host:
        raise RuntimeError("Servidor SMTP nao configurado. " + smtp_config_help_text())
    if not cfg.from_email:
        raise RuntimeError("E-mail remetente nao configurado. " + smtp_config_help_text())
    if not _EMAIL_RE.match(cfg.from_email) or not _is_ascii(cfg.from_email):
        raise RuntimeError(
            "MEDCONTRACT_SMTP_FROM invalido. Use apenas o e-mail remetente "
            "(sem nome), por exemplo: contato@empresa.com."
        )
    if cfg.username and not cfg.password:
        raise RuntimeError("Senha SMTP nao configurada. " + smtp_config_help_text())


def _smtp_login(smtp, username: str, password: str) -> None:
    """
    Login SMTP com fallback UTF-8 para evitar UnicodeEncodeError de alguns backends.
    """
    if not username:
        return
    try:
        smtp.login(username, password)
        return
    except UnicodeEncodeError:
        user_b64 = base64.b64encode(str(username).encode("utf-8")).decode("ascii")
        pass_b64 = base64.b64encode(str(password).encode("utf-8")).decode("ascii")

        code, resp = smtp.docmd("AUTH", "LOGIN " + user_b64)
        if code != 334:
            raise smtplib.SMTPAuthenticationError(code, resp)

        code, resp = smtp.docmd(pass_b64)
        if code not in (235, 503):
            raise smtplib.SMTPAuthenticationError(code, resp)


def _send_message_safe(
    smtp,
    cfg: SmtpConfig,
    to_addr: str,
    subj: str,
    body: str,
    body_html: str | None,
):
    msg = EmailMessage()
    msg["Subject"] = subj
    msg["From"] = cfg.from_header
    msg["To"] = to_addr
    msg.set_content(body)

    html = (body_html or "").strip()
    if html:
        msg.add_alternative(html, subtype="html")

    try:
        smtp.send_message(msg, from_addr=cfg.from_email, to_addrs=[to_addr])
        return
    except UnicodeEncodeError:
        # Fallback para servidores/clientes SMTP com restrições estritas de ASCII.
        fallback = EmailMessage()
        fallback["Subject"] = _ascii_fold(subj) or "Mensagem"
        fallback["From"] = cfg.from_email
        fallback["To"] = to_addr
        fallback.set_content(body)
        if html:
            fallback.add_alternative(html, subtype="html")
        smtp.send_message(fallback, from_addr=cfg.from_email, to_addrs=[to_addr])


def send_email(
    to_email: str,
    subject: str,
    body_text: str,
    *,
    body_html: str | None = None,
) -> dict:
    """
    Envia um e-mail simples usando SMTP configurado por variaveis de ambiente.
    Lanca excecao com mensagem amigavel em caso de falha.
    """
    cfg = load_smtp_config()
    _validate_smtp_config(cfg)
    to_addr = _validate_recipient(to_email)
    subj, body = _validate_content(subject, body_text)
    html = (body_html or "").strip()

    context = ssl.create_default_context()
    local_hostname = str(os.getenv("MEDCONTRACT_SMTP_LOCAL_HOSTNAME", "localhost") or "localhost").strip()
    if not local_hostname or not _is_ascii(local_hostname):
        local_hostname = "localhost"

    try:
        if cfg.use_ssl:
            with smtplib.SMTP_SSL(
                cfg.host,
                cfg.port,
                timeout=cfg.timeout_seconds,
                context=context,
                local_hostname=local_hostname,
            ) as smtp:
                smtp.ehlo()
                _smtp_login(smtp, cfg.username, cfg.password)
                _send_message_safe(smtp, cfg, to_addr, subj, body, html)
        else:
            with smtplib.SMTP(
                cfg.host,
                cfg.port,
                timeout=cfg.timeout_seconds,
                local_hostname=local_hostname,
            ) as smtp:
                smtp.ehlo()
                if cfg.use_tls:
                    smtp.starttls(context=context)
                    smtp.ehlo()
                _smtp_login(smtp, cfg.username, cfg.password)
                _send_message_safe(smtp, cfg, to_addr, subj, body, html)
    except UnicodeEncodeError as exc:
        raise RuntimeError(
            "Falha de codificacao no SMTP mesmo apos fallback. "
            f"Detalhe tecnico: {exc}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Falha ao enviar e-mail: {exc}") from exc

    return {
        "ok": True,
        "to": to_addr,
        "subject": subj,
    }
