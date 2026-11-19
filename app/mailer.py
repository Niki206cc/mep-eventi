"""Email all'organizzatore quando il suo evento viene pubblicato nel calendario."""
from __future__ import annotations

import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from html import escape

log = logging.getLogger(__name__)

EMAIL_RX = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

DEFAULTS = {
    "mail_enabled": "0",
    "smtp_host": "",
    "smtp_port": "465",
    "smtp_security": "ssl",          # ssl | starttls
    "smtp_user": "comunicati@montagneepaesi.com",
    "smtp_password": "",
    "mail_from": "comunicati@montagneepaesi.com",
    "mail_from_name": "Redazione Montagne & Paesi",
    "mail_bcc": "",
    "social_facebook": "https://www.facebook.com/montagneepaesi/",
    "social_instagram": "https://www.instagram.com/montagne_e_paesi/",
    "social_whatsapp": "https://www.whatsapp.com/channel/0029Vb7fcHT8aKvFAuCIfm0c",
    "social_telegram": "https://t.me/montagnepaesinews",
    "social_site": "https://www.montagneepaesi.com/",
    "continuous_pause_min": "20",
}

SOCIALS = [("social_facebook", "Facebook"), ("social_instagram", "Instagram"),
           ("social_whatsapp", "WhatsApp"), ("social_telegram", "Telegram"), ("social_site", "Sito")]


def clean_email(v) -> str | None:
    if not v or not isinstance(v, str):
        return None
    v = v.strip().strip("<>").replace("mailto:", "").split("?")[0].strip().lower()
    return v if EMAIL_RX.match(v) else None


def conf(store) -> dict:
    c = dict(DEFAULTS)
    c.update({k: v for k, v in store.settings().items() if v is not None})
    return c


def build(c: dict, to: str, title: str, link: str) -> EmailMessage:
    socials = [(label, c.get(k)) for k, label in SOCIALS if c.get(k)]
    text = (f"Ciao,\n\nla redazione di Montagne & Paesi ha inserito il tuo evento \"{title}\" "
            f"nel calendario. Ecco il link:\n{link}\n\nSeguici sui nostri canali:\n"
            + "\n".join(f"- {label}: {url}" for label, url in socials)
            + "\n\nLa redazione di Montagne & Paesi\n")
    links_html = " · ".join(f'<a href="{escape(url)}" style="color:#2f6f4f">{escape(label)}</a>' for label, url in socials)
    html = f"""<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:1.5;color:#1d2421;max-width:560px">
<p>Ciao,</p>
<p>la redazione di <strong>Montagne &amp; Paesi</strong> ha inserito il tuo evento
<strong>{escape(title)}</strong> nel calendario. Ecco il link:</p>
<p><a href="{escape(link)}" style="display:inline-block;background:#2f6f4f;color:#fff;padding:10px 16px;border-radius:6px;text-decoration:none">Vedi l'evento nel calendario</a></p>
<p style="font-size:13px;color:#6b736f">{escape(link)}</p>
<p>Seguici sui nostri canali: {links_html}</p>
<p>La redazione di Montagne &amp; Paesi</p>
</div>"""
    msg = EmailMessage()
    msg["Subject"] = f"Il tuo evento è nel calendario di Montagne & Paesi: {title}"[:180]
    msg["From"] = formataddr((c.get("mail_from_name") or "Montagne & Paesi", c["mail_from"]))
    msg["To"] = to
    msg["Reply-To"] = c["mail_from"]
    if c.get("mail_bcc"):
        msg["Bcc"] = c["mail_bcc"]
    msg["Message-ID"] = make_msgid(domain=c["mail_from"].split("@")[-1])
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def send(c: dict, msg: EmailMessage) -> None:
    host, port = c.get("smtp_host"), int(c.get("smtp_port") or 465)
    if not host or not c.get("smtp_password"):
        raise RuntimeError("SMTP non configurato")
    ctx = ssl.create_default_context()
    if (c.get("smtp_security") or "ssl") == "ssl":
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
            s.login(c["smtp_user"], c["smtp_password"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(c["smtp_user"], c["smtp_password"])
            s.send_message(msg)


def notify_organizer(store, to: str, title: str, link: str) -> bool:
    """Invia la mail se l'invio è attivo. Ritorna True se inviata."""
    c = conf(store)
    if c.get("mail_enabled") != "1":
        return False
    send(c, build(c, to, title, link))
    log.info("email inviata all'organizzatore %s per %s", to, title)
    return True
