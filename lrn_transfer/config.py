"""
lrn_transfer/config.py — Configuration loader.

Reads from ~/.lrn_transfer/lrn-transfer.conf by default.
All sections and keys documented in config/lrn-transfer.conf.example.
"""

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_CONFIG_PATH = Path.home() / '.lrn_transfer' / 'lrn-transfer.conf'


@dataclass
class GeneralConfig:
    log_file:              str  = '/var/log/lrn-transfer/lrn-transfer.log'
    log_level:             str  = 'INFO'
    state_db:              str  = str(Path.home() / '.lrn_transfer' / 'state.db')
    poll_interval:         int  = 60
    outbox_interval:       int  = 10
    file_stable_secs:      int  = 5
    purge_older_than_days: int  = 90


@dataclass
class NfsConfig:
    inbox_path:     str = '/mnt/transfer/inbox'
    outbox_path:    str = '/mnt/transfer/outbox'
    processed_path: str = '/mnt/transfer/processed'
    failed_path:    str = '/mnt/transfer/failed'


@dataclass
class SftpOutConfig:
    """Transfer PC connection used when SENDING files (outbox → transfer PC)."""
    host:         str = ''
    port:         int = 22
    user:         str = 'transfer'
    key_path:     str = ''
    password:     str = ''
    remote_dir:   str = '/transfer/incoming'
    timeout:      int = 30


@dataclass
class SftpInConfig:
    """Transfer PC connection used when RECEIVING files (transfer PC → inbox)."""
    host:              str  = ''
    port:              int  = 22
    user:              str  = 'transfer'
    key_path:          str  = ''
    password:          str  = ''
    remote_dir:        str  = '/transfer/outgoing'
    delete_after_get:  bool = True
    timeout:           int  = 30


@dataclass
class XmppConfig:
    enabled:     bool = False
    jid:         str  = ''
    password:    str  = ''
    server:      str  = ''
    port:        int  = 5222
    notify_jid:  str  = ''
    use_tls:     bool = True


@dataclass
class WebhookConfig:
    """Optional webhook for Mattermost/RocketChat/Slack notifications."""
    enabled: bool = False
    url:     str  = ''
    # Optional bearer token for authenticated webhooks
    token:   str  = ''


@dataclass
class AppConfig:
    general: GeneralConfig  = field(default_factory=GeneralConfig)
    nfs:     NfsConfig      = field(default_factory=NfsConfig)
    sftp_out: SftpOutConfig = field(default_factory=SftpOutConfig)
    sftp_in:  SftpInConfig  = field(default_factory=SftpInConfig)
    xmpp:    XmppConfig     = field(default_factory=XmppConfig)
    webhook: WebhookConfig  = field(default_factory=WebhookConfig)


def _getbool(cp, section, key, fallback=False) -> bool:
    try:
        return cp.getboolean(section, key, fallback=fallback)
    except (configparser.NoSectionError, configparser.NoOptionError):
        return fallback


def _getint(cp, section, key, fallback=0) -> int:
    try:
        return cp.getint(section, key, fallback=fallback)
    except (configparser.NoSectionError, configparser.NoOptionError):
        return fallback


def _get(cp, section, key, fallback='') -> str:
    try:
        return cp.get(section, key, fallback=fallback).strip()
    except (configparser.NoSectionError, configparser.NoOptionError):
        return fallback


def load_config(path: Optional[str] = None) -> AppConfig:
    """Load and return the application configuration."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH

    cp = configparser.ConfigParser(interpolation=None)

    if cfg_path.exists():
        cp.read(str(cfg_path))
    else:
        # Return defaults — caller should warn
        pass

    g = GeneralConfig(
        log_file              = _get(cp, 'general', 'log_file', '/var/log/lrn-transfer/lrn-transfer.log'),
        log_level             = _get(cp, 'general', 'log_level', 'INFO').upper(),
        state_db              = _get(cp, 'general', 'state_db', str(Path.home() / '.lrn_transfer' / 'state.db')),
        poll_interval         = _getint(cp, 'general', 'poll_interval', 60),
        outbox_interval       = _getint(cp, 'general', 'outbox_interval', 10),
        file_stable_secs      = _getint(cp, 'general', 'file_stable_secs', 5),
        purge_older_than_days = _getint(cp, 'general', 'purge_older_than_days', 90),
    )

    n = NfsConfig(
        inbox_path     = _get(cp, 'nfs', 'inbox_path',     '/mnt/transfer/inbox'),
        outbox_path    = _get(cp, 'nfs', 'outbox_path',    '/mnt/transfer/outbox'),
        processed_path = _get(cp, 'nfs', 'processed_path', '/mnt/transfer/processed'),
        failed_path    = _get(cp, 'nfs', 'failed_path',    '/mnt/transfer/failed'),
    )

    so = SftpOutConfig(
        host       = _get(cp, 'sftp_out', 'host', ''),
        port       = _getint(cp, 'sftp_out', 'port', 22),
        user       = _get(cp, 'sftp_out', 'user', 'transfer'),
        key_path   = _get(cp, 'sftp_out', 'key_path', ''),
        password   = _get(cp, 'sftp_out', 'password', ''),
        remote_dir = _get(cp, 'sftp_out', 'remote_dir', '/transfer/incoming'),
        timeout    = _getint(cp, 'sftp_out', 'timeout', 30),
    )

    si = SftpInConfig(
        host             = _get(cp, 'sftp_in', 'host', ''),
        port             = _getint(cp, 'sftp_in', 'port', 22),
        user             = _get(cp, 'sftp_in', 'user', 'transfer'),
        key_path         = _get(cp, 'sftp_in', 'key_path', ''),
        password         = _get(cp, 'sftp_in', 'password', ''),
        remote_dir       = _get(cp, 'sftp_in', 'remote_dir', '/transfer/outgoing'),
        delete_after_get = _getbool(cp, 'sftp_in', 'delete_after_get', True),
        timeout          = _getint(cp, 'sftp_in', 'timeout', 30),
    )

    x = XmppConfig(
        enabled    = _getbool(cp, 'xmpp', 'enabled', False),
        jid        = _get(cp, 'xmpp', 'jid', ''),
        password   = _get(cp, 'xmpp', 'password', ''),
        server     = _get(cp, 'xmpp', 'server', ''),
        port       = _getint(cp, 'xmpp', 'port', 5222),
        notify_jid = _get(cp, 'xmpp', 'notify_jid', ''),
        use_tls    = _getbool(cp, 'xmpp', 'use_tls', True),
    )

    w = WebhookConfig(
        enabled = _getbool(cp, 'webhook', 'enabled', False),
        url     = _get(cp, 'webhook', 'url', ''),
        token   = _get(cp, 'webhook', 'token', ''),
    )

    return AppConfig(general=g, nfs=n, sftp_out=so, sftp_in=si, xmpp=x, webhook=w)
