"""
lrn_transfer/notify.py — Notification dispatch.

Supports two backends (either or both can be enabled):
  1. XMPP  — sends an IM to notify_jid via a Prosody/ejabberd server
  2. Webhook — HTTP POST to a Mattermost / RocketChat / generic webhook URL

Both backends are tried independently; failure of one does not block the other.
"""

import json
import logging
import socket
import ssl
import urllib.request
import urllib.error
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# XMPP — pure stdlib implementation (no slixmpp dependency)
# Sends a plain-text message using the XMPP wire protocol directly.
# Works with Prosody, ejabberd, and any RFC-6120-compliant server.
# ---------------------------------------------------------------------------

def _send_xmpp(jid: str, password: str, server: str, port: int,
               to_jid: str, message: str, use_tls: bool = True) -> bool:
    """
    Send a single XMPP message using a raw socket + XML.
    Returns True on success.
    """
    try:
        # Build the XMPP stream frames we need
        local_part, domain = jid.split('@', 1)

        open_stream   = (f"<?xml version='1.0'?>"
                         f"<stream:stream to='{domain}' "
                         f"xmlns='jabber:client' "
                         f"xmlns:stream='http://etherx.jabber.org/streams' "
                         f"version='1.0'>").encode()
        auth_plain    = _xmpp_auth_plain(jid, password)
        msg_stanza    = (f"<message to='{to_jid}' type='chat'>"
                         f"<body>{_xml_escape(message)}</body>"
                         f"</message>").encode()
        close_stream  = b"</stream:stream>"

        # Connect
        raw = socket.create_connection((server, port), timeout=15)
        if use_tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            sock = ctx.wrap_socket(raw, server_hostname=server)
        else:
            sock = raw

        def send(data: bytes):
            sock.sendall(data)

        def recv(size=4096) -> str:
            return sock.recv(size).decode('utf-8', errors='replace')

        # Open stream
        send(open_stream)
        recv()  # server stream open + features

        # SASL PLAIN auth
        send(auth_plain)
        resp = recv()
        if 'success' not in resp.lower():
            log.error("XMPP auth failed: %s", resp[:200])
            sock.close()
            return False

        # Re-open stream after auth
        send(open_stream)
        recv()

        # Send message
        send(msg_stanza)
        send(close_stream)
        sock.close()

        log.info("XMPP notification sent to %s", to_jid)
        return True

    except Exception as exc:
        log.error("XMPP notification failed: %s", exc)
        return False


def _xmpp_auth_plain(jid: str, password: str) -> bytes:
    """Build a SASL PLAIN auth stanza (base64-encoded \0user\0password)."""
    import base64
    token = f"\x00{jid}\x00{password}"
    encoded = base64.b64encode(token.encode('utf-8')).decode()
    return (f"<auth xmlns='urn:ietf:params:xml:ns:xmpp-sasl' "
            f"mechanism='PLAIN'>{encoded}</auth>").encode()


def _xml_escape(text: str) -> str:
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&apos;'))


# ---------------------------------------------------------------------------
# Webhook — HTTP POST (Mattermost, RocketChat, generic)
# ---------------------------------------------------------------------------

def _send_webhook(url: str, message: str, token: str = '') -> bool:
    """POST a JSON payload to a webhook URL. Returns True on success."""
    payload = json.dumps({'text': message}).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 201, 204):
                log.info("Webhook notification sent to %s", url)
                return True
            log.error("Webhook returned HTTP %d", resp.status)
            return False
    except Exception as exc:
        log.error("Webhook notification failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def send_notification(message: str, xmpp_cfg=None, webhook_cfg=None) -> bool:
    """
    Dispatch a notification via enabled backends.
    Returns True if at least one backend succeeded.
    """
    sent = False

    if xmpp_cfg and xmpp_cfg.enabled:
        if all([xmpp_cfg.jid, xmpp_cfg.password, xmpp_cfg.server, xmpp_cfg.notify_jid]):
            ok = _send_xmpp(
                jid=xmpp_cfg.jid,
                password=xmpp_cfg.password,
                server=xmpp_cfg.server,
                port=xmpp_cfg.port,
                to_jid=xmpp_cfg.notify_jid,
                message=message,
                use_tls=xmpp_cfg.use_tls,
            )
            sent = sent or ok
        else:
            log.warning("XMPP enabled but missing required fields (jid/password/server/notify_jid)")

    if webhook_cfg and webhook_cfg.enabled:
        if webhook_cfg.url:
            ok = _send_webhook(webhook_cfg.url, message, webhook_cfg.token)
            sent = sent or ok
        else:
            log.warning("Webhook enabled but url is not configured")

    if not sent:
        log.debug("No notification backends succeeded (or none enabled)")

    return sent
