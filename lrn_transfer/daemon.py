"""
lrn_transfer/daemon.py — Core transfer logic.

OutboxWorker : scans outbox, SFTPs files to transfer PC, moves to processed/
InboundWorker: polls transfer PC, downloads new files to inbox/, sends notifications
"""

import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from .config import AppConfig
from .notify import send_notification
from .sftp import download_file, list_remote_files, upload_file
from .state import Direction, StateDB, Status, sha256_file

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_dirs(*paths):
    for p in paths:
        Path(p).mkdir(parents=True, exist_ok=True)


def _is_stable(path: str, stable_secs: int) -> bool:
    """Return True if the file's mtime is older than stable_secs."""
    try:
        age = time.time() - Path(path).stat().st_mtime
        return age >= stable_secs
    except OSError:
        return False


def _timestamped_name(filename: str) -> str:
    """Return filename with a timestamp prefix: 20260416-143022_filename.txt"""
    ts = datetime.now().strftime('%Y%m%d-%H%M%S')
    return f"{ts}_{filename}"


def _move_file(src: str, dst_dir: str, rename: Optional[str] = None) -> str:
    """Move src to dst_dir/rename (or dst_dir/original_name). Returns new path."""
    dst_name = rename or Path(src).name
    dst = str(Path(dst_dir) / dst_name)
    shutil.move(src, dst)
    return dst


# ---------------------------------------------------------------------------
# Outbox Worker
# ---------------------------------------------------------------------------

def _backoff_wait(failures: int, base: float = 5.0, cap: float = 300.0) -> float:
    """Exponential backoff: base * 2^failures, capped at cap seconds."""
    return min(base * (2 ** failures), cap)


class OutboxWorker:
    """
    Scans the outbox directory for files and SFTPs them to the transfer PC.
    Successfully sent files are moved to processed/.
    Failed files are moved to failed/.
    """

    def __init__(self, cfg: AppConfig, db: StateDB):
        self.cfg              = cfg
        self.db               = db
        self._consecutive_failures = 0

    def run_once(self):
        """Process all pending files in outbox. Called on each poll cycle."""
        outbox    = self.cfg.nfs.outbox_path
        processed = self.cfg.nfs.processed_path
        failed    = self.cfg.nfs.failed_path
        g         = self.cfg.general
        so        = self.cfg.sftp_out

        if not so.host:
            log.warning("sftp_out.host not configured — outbound transfers disabled")
            return

        _ensure_dirs(outbox, processed, failed)

        try:
            entries = list(Path(outbox).iterdir())
        except OSError as exc:
            log.error("Cannot read outbox %s: %s", outbox, exc)
            return

        files = [e for e in entries if e.is_file() and not e.name.startswith('.')]

        if not files:
            return

        log.debug("Outbox scan: %d file(s) found", len(files))

        for entry in files:
            local_path = str(entry)
            filename   = entry.name

            # Wait for file to stop changing
            if not _is_stable(local_path, g.file_stable_secs):
                log.debug("Skipping %s — not yet stable", filename)
                continue

            # Duplicate check by content hash
            try:
                digest = sha256_file(local_path)
                size   = entry.stat().st_size
            except OSError as exc:
                log.error("Cannot read %s: %s", filename, exc)
                continue

            if self.db.already_sent(filename, digest):
                log.info("Skipping %s — already sent (hash match)", filename)
                _move_file(local_path, processed, _timestamped_name(filename))
                continue

            # Upload
            log.info("Sending %s (%d bytes) to %s", filename, size, so.host)
            ok, msg = upload_file(
                local_path  = local_path,
                host        = so.host,
                port        = so.port,
                user        = so.user,
                remote_dir  = so.remote_dir,
                key_path    = so.key_path,
                password    = so.password,
                timeout     = so.timeout,
            )

            if ok:
                archived = _move_file(local_path, processed, _timestamped_name(filename))
                self.db.record(
                    direction='out', filename=filename, status='ok',
                    size_bytes=size, sha256=digest,
                    message=msg, remote_host=so.host,
                )
                self._consecutive_failures = 0
                log.info("Sent and archived: %s → %s", filename, archived)
                # Notify on successful send
                size_line = f"  Size : {size:,} bytes\n" if size else ""
                notification = (
                    f"[lrn-transfer] File sent to transfer PC:\n"
                    f"  File : {filename}\n"
                    f"{size_line}"
                    f"  To   : {so.host}:{so.remote_dir}\n"
                )
                send_notification(
                    notification,
                    xmpp_cfg=self.cfg.xmpp,
                    webhook_cfg=self.cfg.webhook,
                )
            else:
                failed_path = _move_file(local_path, failed, _timestamped_name(filename))
                self.db.record(
                    direction='out', filename=filename, status='error',
                    size_bytes=size, sha256=digest,
                    message=msg, remote_host=so.host,
                )
                self._consecutive_failures += 1
                wait = _backoff_wait(self._consecutive_failures)
                log.error("Transfer failed, moved to failed/: %s — %s (backoff %.0fs)",
                          filename, msg, wait)
                time.sleep(wait)


# ---------------------------------------------------------------------------
# Inbound Worker
# ---------------------------------------------------------------------------

class InboundWorker:
    """
    Polls the transfer PC for new files and downloads them to inbox/.
    Sends an XMPP/webhook notification for each new file received.
    """

    def __init__(self, cfg: AppConfig, db: StateDB):
        self.cfg                   = cfg
        self.db                    = db
        self._consecutive_failures = 0

    def run_once(self):
        """Poll transfer PC once. Called on each inbound poll cycle."""
        inbox = self.cfg.nfs.inbox_path
        si    = self.cfg.sftp_in

        if not si.host:
            log.warning("sftp_in.host not configured — inbound transfers disabled")
            return

        _ensure_dirs(inbox)

        # List what's available on the transfer PC
        remote_files = list_remote_files(
            host       = si.host,
            port       = si.port,
            user       = si.user,
            remote_dir = si.remote_dir,
            key_path   = si.key_path,
            password   = si.password,
            timeout    = si.timeout,
        )

        if remote_files is None:
            # Connection failure
            self._consecutive_failures += 1
            wait = _backoff_wait(self._consecutive_failures)
            log.error("Inbound poll: connection to %s failed (backoff %.0fs)", si.host, wait)
            time.sleep(wait)
            return

        self._consecutive_failures = 0

        if not remote_files:
            log.debug("Inbound poll: nothing available on %s:%s", si.host, si.remote_dir)
            return

        log.info("Inbound poll: %d file(s) available on %s", len(remote_files), si.host)

        for filename in remote_files:
            # Skip already-received filenames
            if self.db.already_received(filename):
                log.info("Skipping %s — already received", filename)
                continue

            ok, msg = download_file(
                filename     = filename,
                host         = si.host,
                port         = si.port,
                user         = si.user,
                remote_dir   = si.remote_dir,
                local_dir    = inbox,
                key_path     = si.key_path,
                password     = si.password,
                timeout      = si.timeout,
                delete_after = si.delete_after_get,
            )

            if ok:
                local_path = str(Path(inbox) / filename)
                try:
                    size   = Path(local_path).stat().st_size
                    digest = sha256_file(local_path)
                except OSError:
                    size, digest = None, None

                self.db.record(
                    direction='in', filename=filename, status='ok',
                    size_bytes=size, sha256=digest,
                    message=msg, remote_host=si.host,
                )

                # Notify
                size_line = f"  Size : {size:,} bytes\n" if size else ""
                notification = (
                    f"[lrn-transfer] New file received in inbox:\n"
                    f"  File : {filename}\n"
                    f"{size_line}"
                    f"  From : {si.host}:{si.remote_dir}\n"
                    f"  Path : {inbox}/{filename}"
                )
                send_notification(
                    notification,
                    xmpp_cfg=self.cfg.xmpp,
                    webhook_cfg=self.cfg.webhook,
                )
                log.info("File received and notification sent: %s", filename)

            else:
                self.db.record(
                    direction='in', filename=filename, status='error',
                    message=msg, remote_host=si.host,
                )
                log.error("Failed to download %s: %s", filename, msg)
