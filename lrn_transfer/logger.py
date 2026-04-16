"""
lrn_transfer/logger.py — Logging setup.

Writes to a rotating log file and optionally to stdout.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(log_file: str, log_level: str = 'INFO', console: bool = True) -> logging.Logger:
    """
    Configure and return the root logger.

    Parameters
    ----------
    log_file  : Absolute path to the log file.
    log_level : DEBUG / INFO / WARNING / ERROR.
    console   : Also log to stdout (useful when running in foreground).
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        fmt='%(asctime)s [%(levelname)-8s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    root = logging.getLogger()
    root.setLevel(level)

    # Rotating file handler — 10 MB per file, keep 5
    fh = RotatingFileHandler(
        str(log_path),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8',
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    if console:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        root.addHandler(ch)

    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
