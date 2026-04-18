#!/usr/bin/env python3
"""
lrn-transferd.py — Air-gap file transfer daemon.

Runs two concurrent workers in a single process:
  OutboxWorker  — scans outbox/, SFTPs new files to the transfer PC
  InboundWorker — polls transfer PC, downloads to inbox/, sends notifications

Usage:
    python3 lrn-transferd.py [--config /path/to/lrn-transfer.conf] [--foreground]
    systemctl start lrn-transfer

See README.md and config/lrn-transfer.conf.example for full documentation.
"""

import argparse
import logging
import os
import signal
import sys
import time
import threading
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lrn_transfer.config import load_config, DEFAULT_CONFIG_PATH
from lrn_transfer.daemon import InboundWorker, OutboxWorker
from lrn_transfer.logger import setup_logging
from lrn_transfer.state import StateDB
from lrn_transfer import __version__

log = logging.getLogger('lrn-transferd')

# ---------------------------------------------------------------------------
# Globals for signal handling
# ---------------------------------------------------------------------------
_running = threading.Event()
_running.set()


def _handle_signal(signum, frame):
    log.info("Signal %d received — shutting down gracefully", signum)
    _running.clear()


# ---------------------------------------------------------------------------
# Worker threads
# ---------------------------------------------------------------------------

def _outbox_loop(worker: OutboxWorker, interval: int):
    """Thread: run outbox scan every interval seconds."""
    log.info("OutboxWorker started (interval: %ds)", interval)
    while _running.is_set():
        try:
            worker.run_once()
        except Exception as exc:
            log.exception("Unhandled error in OutboxWorker: %s", exc)
        _running.wait(timeout=interval)
    log.info("OutboxWorker stopped")


def _inbound_loop(worker: InboundWorker, interval: int):
    """Thread: run inbound poll every interval seconds."""
    log.info("InboundWorker started (interval: %ds)", interval)
    while _running.is_set():
        try:
            worker.run_once()
        except Exception as exc:
            log.exception("Unhandled error in InboundWorker: %s", exc)
        _running.wait(timeout=interval)
    log.info("InboundWorker stopped")


# ---------------------------------------------------------------------------
# Status CLI sub-command
# ---------------------------------------------------------------------------

def _cmd_status(cfg, db):
    """Print recent transfer history and stats."""
    from datetime import datetime

    stats = db.stats()
    print(f"\nlrn-transfer {__version__} — Transfer Status")
    print("=" * 50)
    print(f"  Sent OK    : {stats.get('sent_ok', 0)}")
    print(f"  Sent ERR   : {stats.get('sent_err', 0)}")
    print(f"  Recv OK    : {stats.get('recv_ok', 0)}")
    print(f"  Recv ERR   : {stats.get('recv_err', 0)}")
    print()

    rows = db.recent(20)
    if not rows:
        print("  No transfers recorded yet.")
        return

    print(f"  {'Time':<20} {'Dir':<5} {'Status':<8} {'Filename'}")
    print("  " + "-" * 60)
    for r in rows:
        ts  = datetime.fromtimestamp(r['ts']).strftime('%Y-%m-%d %H:%M:%S')
        print(f"  {ts:<20} {r['direction']:<5} {r['status']:<8} {r['filename']}")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=f'lrn-transfer {__version__} — Air-gap file transfer daemon',
    )
    parser.add_argument('--config', '-c',
                        default=str(DEFAULT_CONFIG_PATH),
                        help='Config file path (default: ~/.lrn_transfer/lrn-transfer.conf)')
    parser.add_argument('--foreground', '-f', action='store_true',
                        help='Log to stdout in addition to the log file')
    parser.add_argument('--status', '-s', action='store_true',
                        help='Print recent transfer history and exit')
    parser.add_argument('--run-once', action='store_true',
                        help='Run outbox and inbound scans once then exit (useful for cron)')
    args = parser.parse_args()

    # Load config
    if not Path(args.config).exists():
        print(f"WARNING: Config file not found: {args.config}", file=sys.stderr)
        print(f"         Copy config/lrn-transfer.conf.example to {args.config} and edit it.",
              file=sys.stderr)

    cfg = load_config(args.config)

    # Set up logging
    setup_logging(
        log_file=cfg.general.log_file,
        log_level=cfg.general.log_level,
        console=args.foreground or args.status or args.run_once,
    )

    log.info("lrn-transfer %s starting — config: %s", __version__, args.config)

    # State DB
    db = StateDB(cfg.general.state_db)

    # Status sub-command
    if args.status:
        _cmd_status(cfg, db)
        return 0

    # Validate config
    errors = []
    if not cfg.sftp_out.host and not cfg.sftp_in.host:
        errors.append("Neither sftp_out.host nor sftp_in.host is configured.")
    if errors:
        for e in errors:
            log.error("Config error: %s", e)
        return 1

    outbox_worker  = OutboxWorker(cfg, db)
    inbound_worker = InboundWorker(cfg, db)

    # Run-once mode (cron-friendly)
    if args.run_once:
        log.info("Run-once mode")
        outbox_worker.run_once()
        inbound_worker.run_once()
        log.info("Run-once complete")
        return 0

    # Daemon mode — install signal handlers
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    log.info("Starting workers...")
    log.info("  Outbox path    : %s", cfg.nfs.outbox_path)
    log.info("  Inbox path     : %s", cfg.nfs.inbox_path)
    log.info("  SFTP out host  : %s", cfg.sftp_out.host or '(not configured)')
    log.info("  SFTP in host   : %s", cfg.sftp_in.host or '(not configured)')
    log.info("  XMPP enabled   : %s", cfg.xmpp.enabled)
    log.info("  Webhook enabled: %s", cfg.webhook.enabled)

    def _maintenance_loop():
        """Daily: purge old state DB records."""
        while _running.is_set():
            _running.wait(timeout=86400)
            if not _running.is_set():
                break
            days = cfg.general.purge_older_than_days
            if days > 0:
                n = db.purge_old(days)
                if n:
                    log.info("Maintenance: purged %d records older than %d days", n, days)

    threads = [
        threading.Thread(
            target=_outbox_loop,
            args=(outbox_worker, cfg.general.outbox_interval),
            name='outbox',
            daemon=True,
        ),
        threading.Thread(
            target=_inbound_loop,
            args=(inbound_worker, cfg.general.poll_interval),
            name='inbound',
            daemon=True,
        ),
        threading.Thread(
            target=_maintenance_loop,
            name='maintenance',
            daemon=True,
        ),
    ]

    for t in threads:
        t.start()

    log.info("lrn-transfer running. PID %d. Send SIGTERM or Ctrl-C to stop.", os.getpid())

    # Main thread — wait for shutdown signal
    while _running.is_set():
        time.sleep(1)

    log.info("Waiting for workers to finish current cycle...")
    for t in threads:
        t.join(timeout=60)

    log.info("lrn-transfer stopped cleanly")
    return 0


if __name__ == '__main__':
    sys.exit(main())
