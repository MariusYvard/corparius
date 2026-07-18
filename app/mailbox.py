"""Reading the operator's mailbox over IMAP.

The mirror of the SMTP side in integrations.py, and the same bargain: stdlib
only (imaplib), one host and one app password, no third-party account and no
OAuth redirect. A homelab operator can point this at their own MTA and nothing
leaves the machine.

Everything here opens the mailbox **read-only**. corparius never marks a message
seen, never moves it and never deletes it: the operator's inbox is theirs, and
an agent that silently marked mail as read would be stealing information from
the human it reports to.
"""
from __future__ import annotations
import email
import imaplib
import re
import socket
import ssl
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.utils import parseaddr

from . import cfg, i18n

ADDR_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


@dataclass
class Message:
    uid: str = ""
    sender: str = ""          # bare address, lowercased
    sender_name: str = ""
    subject: str = ""
    body: str = ""
    date: str = ""
    message_id: str = ""
    in_reply_to: str = ""
    references: str = ""

    def label(self) -> str:
        who = self.sender_name or self.sender
        return f"{who}: {self.subject[:60]}" if self.subject else who


def configured() -> bool:
    return bool(cfg.get("CORP_IMAP_HOST", "").strip())


def _decode(value: str) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except (UnicodeDecodeError, LookupError, ValueError):
        return value


def _body_text(msg) -> str:
    """The plain-text part, or a crude strip of the HTML one. Agents read this,
    so it must never be a MIME tree."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(
                    part.get("Content-Disposition", "")):
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8", "replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True) or b""
                html = payload.decode(part.get_content_charset() or "utf-8", "replace")
                return re.sub(r"<[^>]+>", " ", html)
    payload = msg.get_payload(decode=True)
    if payload is None:
        return str(msg.get_payload())
    return payload.decode(msg.get_content_charset() or "utf-8", "replace")


def _connect(timeout: int):
    host = cfg.get("CORP_IMAP_HOST", "").strip()
    port = cfg.get_int("CORP_IMAP_PORT", 993)
    # 993 is implicit TLS, 143 is STARTTLS. Same trap as SMTP's 465 and 587.
    if port == 993:
        conn = imaplib.IMAP4_SSL(host, port, timeout=timeout)
    else:
        conn = imaplib.IMAP4(host, port, timeout=timeout)
        try:
            conn.starttls()
        except (imaplib.IMAP4.error, ssl.SSLError):
            pass   # a plain local relay may legitimately offer no TLS
    user = cfg.get("CORP_IMAP_USER", "") or cfg.get("CORP_SMTP_USER", "")
    password = cfg.get("CORP_IMAP_PASSWORD", "") or cfg.get("CORP_SMTP_PASSWORD", "")
    if user:
        conn.login(user, password)
    return conn


def fetch(limit: int = 20, unseen_only: bool = True, timeout: int = 20) -> list[Message]:
    """Newest messages first. Returns [] when IMAP is not configured, so callers
    fall back to their mock exactly like the SMTP side does."""
    if not configured():
        return []
    folder = cfg.get("CORP_IMAP_FOLDER", "INBOX") or "INBOX"
    conn = None
    try:
        conn = _connect(timeout)
        conn.select(folder, readonly=True)      # readonly: never touch \Seen
        typ, data = conn.search(None, "UNSEEN" if unseen_only else "ALL")
        if typ != "OK":
            return []
        ids = (data[0] or b"").split()
        out: list[Message] = []
        for num in reversed(ids[-limit:]):
            typ, raw = conn.fetch(num, "(BODY.PEEK[])")   # PEEK: still no \Seen
            if typ != "OK" or not raw or not isinstance(raw[0], tuple):
                continue
            msg = email.message_from_bytes(raw[0][1])
            name, addr = parseaddr(msg.get("From", ""))
            out.append(Message(
                uid=num.decode(errors="replace"),
                sender=(addr or "").strip().lower(),
                sender_name=_decode(name),
                subject=_decode(msg.get("Subject", "")),
                body=_body_text(msg).strip(),
                date=msg.get("Date", ""),
                message_id=(msg.get("Message-ID", "") or "").strip(),
                in_reply_to=(msg.get("In-Reply-To", "") or "").strip(),
                references=(msg.get("References", "") or "").strip(),
            ))
        return out
    except (imaplib.IMAP4.error, OSError, ssl.SSLError):
        return []
    finally:
        if conn is not None:
            try:
                conn.logout()
            except (imaplib.IMAP4.error, OSError):
                pass


def diagnosis(exc: Exception, lang="en") -> str:
    """Name the fix, not the protocol."""
    p = lambda en, fr: i18n.pick(lang, en, fr)
    host = cfg.get("CORP_IMAP_HOST", "")
    port = cfg.get_int("CORP_IMAP_PORT", 993)
    text = str(exc)
    if isinstance(exc, imaplib.IMAP4.error):
        low = text.lower()
        if "auth" in low or "login" in low or "credentials" in low:
            return p("The server refused these credentials. Most providers need an "
                     "app-specific password here, not your account password.",
                     "Le serveur a refusé ces identifiants. La plupart des fournisseurs "
                     "exigent ici un mot de passe d'application, pas celui du compte.")
        if "folder" in low or "nonexistent" in low or "select" in low:
            return p(f"The folder '{cfg.get('CORP_IMAP_FOLDER', 'INBOX')}' does not exist on "
                     "this account. INBOX is the usual name.",
                     f"Le dossier « {cfg.get('CORP_IMAP_FOLDER', 'INBOX')} » n'existe pas sur "
                     "ce compte. INBOX est le nom habituel.")
        return text or p("The IMAP server refused the request.", "Le serveur IMAP a refusé la requête.")
    if isinstance(exc, socket.gaierror):
        return p(f"No such host: '{host}'. Check the server name.",
                 f"Hôte introuvable : « {host} ». Vérifiez le nom du serveur.")
    if isinstance(exc, ConnectionRefusedError):
        return p(f"{host} refused a connection on port {port}. Check the port.",
                 f"{host} a refusé la connexion sur le port {port}. Vérifiez le port.")
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return p(f"No answer from {host}:{port} before the timeout. A firewall or the wrong "
                 "port would both look like this.",
                 f"Aucune réponse de {host}:{port} avant le délai. Un pare-feu ou un mauvais "
                 "port donnent tous deux ce résultat.")
    if isinstance(exc, ssl.SSLError):
        return p(f"TLS handshake failed on port {port}. Port 993 expects implicit TLS, "
                 "143 expects STARTTLS.",
                 f"Échec du handshake TLS sur le port {port}. Le 993 attend un TLS implicite, "
                 "le 143 attend STARTTLS.")
    return text or exc.__class__.__name__


def check(timeout: int = 20, lang="en") -> dict:
    """Connect, open the folder, count what is unread. Proves a mailbox works
    before an agent is asked to depend on it."""
    p = lambda en, fr: i18n.pick(lang, en, fr)
    if not configured():
        return {"ok": False, "configured": False,
                "detail": p("No IMAP server set, so inbox triage keeps using its mock.",
                            "Aucun serveur IMAP réglé ; le triage continue avec son mock.")}
    folder = cfg.get("CORP_IMAP_FOLDER", "INBOX") or "INBOX"
    conn = None
    try:
        conn = _connect(timeout)
        typ, _ = conn.select(folder, readonly=True)
        if typ != "OK":
            return {"ok": False, "configured": True,
                    "detail": p(f"Connected, but the folder '{folder}' could not be opened.",
                                f"Connecté, mais le dossier « {folder} » n'a pas pu être ouvert.")}
        typ, data = conn.search(None, "UNSEEN")
        unread = len((data[0] or b"").split()) if typ == "OK" else 0
        host = cfg.get("CORP_IMAP_HOST", "")
        return {"ok": True, "configured": True, "unread": unread,
                "detail": p(f"Connected to {host}, folder {folder}: {unread} unread. "
                            "corparius opens it read-only and never marks anything seen.",
                            f"Connecté à {host}, dossier {folder} : {unread} non lu(s). "
                            "corparius l'ouvre en lecture seule et ne marque jamais rien comme lu.")}
    except (imaplib.IMAP4.error, OSError, ssl.SSLError) as exc:
        return {"ok": False, "configured": True, "detail": diagnosis(exc, lang)}
    finally:
        if conn is not None:
            try:
                conn.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
