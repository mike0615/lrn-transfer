"""
lrn_transfer/sftp.py — SFTP operations via paramiko.

Provides upload, download, and directory listing against the
transfer PC, handling both key-based and password authentication.
"""

import logging
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import paramiko
except ImportError:
    paramiko = None  # checked at runtime

log = logging.getLogger(__name__)


def _check_paramiko():
    if paramiko is None:
        raise RuntimeError("paramiko is not installed. Run: pip3 install paramiko")


@contextmanager
def sftp_session(host: str, port: int, user: str,
                 key_path: str = '', password: str = '',
                 timeout: int = 30):
    """
    Context manager that yields an open (transport, sftp_client) pair.
    Prefers key auth; falls back to password if key_path is empty.
    """
    _check_paramiko()

    transport = None
    try:
        transport = paramiko.Transport((host, port))
        transport.connect()

        if key_path:
            expanded = os.path.expanduser(key_path)
            try:
                key = paramiko.Ed25519Key.from_private_key_file(expanded)
            except paramiko.SSHException:
                try:
                    key = paramiko.RSAKey.from_private_key_file(expanded)
                except paramiko.SSHException:
                    key = paramiko.ECDSAKey.from_private_key_file(expanded)
            transport.auth_publickey(user, key)
        elif password:
            transport.auth_password(user, password)
        else:
            # Try agent or default key
            agent = paramiko.Agent()
            agent_keys = agent.get_keys()
            if agent_keys:
                for k in agent_keys:
                    try:
                        transport.auth_publickey(user, k)
                        if transport.is_authenticated():
                            break
                    except paramiko.AuthenticationException:
                        continue
            if not transport.is_authenticated():
                raise paramiko.AuthenticationException(
                    "No key_path or password configured and no SSH agent keys available."
                )

        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.get_channel().settimeout(timeout)
        log.debug("SFTP session established: %s@%s:%d", user, host, port)
        yield sftp

    finally:
        if transport and transport.is_active():
            transport.close()
            log.debug("SFTP session closed: %s@%s:%d", user, host, port)


def list_remote_files(host: str, port: int, user: str, remote_dir: str,
                      key_path: str = '', password: str = '',
                      timeout: int = 30) -> Optional[List[str]]:
    """
    Return a list of plain filenames (not directories) in remote_dir.
    Returns None on connection failure (caller applies backoff).
    Returns [] if directory is empty or listing succeeds with no files.
    """
    try:
        with sftp_session(host, port, user, key_path, password, timeout) as sftp:
            entries = sftp.listdir_attr(remote_dir)
            files = [
                e.filename for e in entries
                if not stat.S_ISDIR(e.st_mode)
            ]
            log.debug("Remote listing %s:%s — %d file(s)", host, remote_dir, len(files))
            return files
    except Exception as exc:
        log.error("Failed to list remote dir %s:%s — %s", host, remote_dir, exc)
        return None


def upload_file(local_path: str, host: str, port: int, user: str,
                remote_dir: str, key_path: str = '', password: str = '',
                timeout: int = 30) -> Tuple[bool, str]:
    """
    Upload local_path to remote_dir/filename on the transfer PC.
    Returns (success, message).
    """
    filename = Path(local_path).name
    remote_path = f"{remote_dir.rstrip('/')}/{filename}"

    try:
        with sftp_session(host, port, user, key_path, password, timeout) as sftp:
            # Ensure remote directory exists
            try:
                sftp.stat(remote_dir)
            except FileNotFoundError:
                sftp.mkdir(remote_dir)

            log.info("Uploading %s → %s:%s", local_path, host, remote_path)
            sftp.put(local_path, remote_path)
            size = sftp.stat(remote_path).st_size
            log.info("Upload complete: %s (%d bytes)", filename, size)
            return True, f"Uploaded {filename} ({size} bytes) to {host}:{remote_path}"

    except Exception as exc:
        msg = f"Upload failed for {filename}: {exc}"
        log.error(msg)
        return False, msg


def download_file(filename: str, host: str, port: int, user: str,
                  remote_dir: str, local_dir: str,
                  key_path: str = '', password: str = '',
                  timeout: int = 30,
                  delete_after: bool = True) -> Tuple[bool, str]:
    """
    Download filename from remote_dir on the transfer PC to local_dir.
    If delete_after is True, removes the remote file on success.
    Returns (success, message).
    """
    remote_path = f"{remote_dir.rstrip('/')}/{filename}"
    local_path  = str(Path(local_dir) / filename)

    try:
        with sftp_session(host, port, user, key_path, password, timeout) as sftp:
            log.info("Downloading %s:%s → %s", host, remote_path, local_path)
            sftp.get(remote_path, local_path)
            size = Path(local_path).stat().st_size
            log.info("Download complete: %s (%d bytes)", filename, size)

            if delete_after:
                sftp.remove(remote_path)
                log.info("Deleted remote file: %s:%s", host, remote_path)

        return True, f"Downloaded {filename} ({size} bytes) from {host}"

    except Exception as exc:
        msg = f"Download failed for {filename}: {exc}"
        log.error(msg)
        # Clean up partial download
        if Path(local_path).exists():
            try:
                Path(local_path).unlink()
            except OSError:
                pass
        return False, msg
