# lrn-transfer

Air-gap file transfer daemon for Rocky Linux 9. Exchanges files between isolated networks via a transfer PC using SFTP. Built for the LRN (Local Restricted Network) architecture.

## Overview

```
[Isolated Network A]                [Transfer PC]              [Isolated Network B]
   outbox/  ──────── SFTP upload ──► incoming/                     (same pattern)
   inbox/   ◄─────── SFTP poll  ──── outgoing/
```

- **Outbound**: scans `outbox/`, SFTPs new files to transfer PC `incoming/`
- **Inbound**: polls transfer PC `outgoing/`, downloads to `inbox/`
- SHA256 deduplication — never re-sends the same file
- File stability check — waits for writes to finish before sending
- SQLite audit trail with automatic old-record purge
- Exponential backoff on SFTP failures
- XMPP and/or webhook (Mattermost/RocketChat) notifications
- systemd service + optional run-once timer
- Air-gap ready: all Python deps bundled in venv

## Requirements

- Rocky Linux 9.x (or RHEL 9.x compatible)
- Python 3.9+
- SFTP access to a transfer PC
- `rpmbuild` + `python3` on build host (for building the RPM)

## Quick Start

### Build

```bash
# On an internet-connected machine:
make fetch-deps       # downloads paramiko wheels to SOURCES/wheels/
make rpm              # builds the RPM
```

The RPM is at `RPMS/x86_64/lrn-transfer-1.0-1.el9.x86_64.rpm`.

### Install (air-gapped target)

```bash
# Copy RPM to target, then:
sudo dnf install -y lrn-transfer-1.0-1.el9.x86_64.rpm

# Build the Python venv (installs paramiko from bundled wheels):
sudo bash /opt/lrn-transfer/install.sh
```

### Configure

```bash
sudo cp /etc/lrn-transfer/lrn-transfer.conf.example /etc/lrn-transfer/lrn-transfer.conf
sudo nano /etc/lrn-transfer/lrn-transfer.conf
```

Minimum required settings:

```ini
[sftp_out]
host     = 192.168.100.10
username = transfer
key_file = /etc/lrn-transfer/keys/id_ed25519_transfer

[sftp_in]
host     = 192.168.100.10    ; same host, different remote dirs
username = transfer
key_file = /etc/lrn-transfer/keys/id_ed25519_transfer
```

### SSH Key Setup

```bash
# Generate key for SFTP auth
sudo ssh-keygen -t ed25519 -f /etc/lrn-transfer/keys/id_ed25519_transfer -N ""

# Copy public key to transfer PC's authorized_keys
cat /etc/lrn-transfer/keys/id_ed25519_transfer.pub
```

### Enable and Start

```bash
sudo systemctl enable --now lrn-transfer

# Check status
systemctl status lrn-transfer
journalctl -u lrn-transfer -f

# View transfer history
sudo /opt/lrn-transfer/venv/bin/python3 /opt/lrn-transfer/lrn-transferd.py \
    --config /etc/lrn-transfer/lrn-transfer.conf --status
```

## Directory Layout

| Path | Purpose |
|---|---|
| `/opt/lrn-transfer/` | Application home (binary, venv, wheels) |
| `/etc/lrn-transfer/` | Config file, SSH keys |
| `/var/log/lrn-transfer/` | Log files |
| `/var/lib/lrn-transfer/` | SQLite state DB |

## Configuration Reference

See `/etc/lrn-transfer/lrn-transfer.conf.example` for full documentation. Key sections:

### `[general]`
| Key | Default | Description |
|---|---|---|
| `log_file` | `/var/log/lrn-transfer/lrn-transfer.log` | Log path |
| `log_level` | `INFO` | DEBUG / INFO / WARNING / ERROR |
| `state_db` | `/var/lib/lrn-transfer/state.db` | SQLite path |
| `outbox_interval` | `30` | Seconds between outbox scans |
| `poll_interval` | `60` | Seconds between inbound polls |
| `purge_older_than_days` | `90` | Auto-purge DB records older than N days |

### `[nfs]`
| Key | Description |
|---|---|
| `outbox_path` | Local directory to watch for outbound files |
| `inbox_path` | Local directory to place inbound files |

### `[sftp_out]` / `[sftp_in]`
| Key | Default | Description |
|---|---|---|
| `host` | | Transfer PC hostname/IP |
| `port` | `22` | SSH port |
| `username` | | SFTP username |
| `key_file` | | Path to Ed25519/RSA private key |
| `password` | | Password (fallback if no key) |
| `remote_dir` | | Remote directory on transfer PC |
| `connect_timeout` | `15` | TCP connect timeout (seconds) |

### `[xmpp]`
| Key | Default | Description |
|---|---|---|
| `enabled` | `false` | Enable XMPP notifications |
| `host` | | XMPP server hostname |
| `port` | `5222` | XMPP port |
| `jid` | | Sender JID (user@domain) |
| `password` | | XMPP account password |
| `to_jid` | | Recipient JID |
| `use_tls` | `true` | Enable STARTTLS |

### `[webhook]`
| Key | Default | Description |
|---|---|---|
| `enabled` | `false` | Enable webhook notifications |
| `url` | | Webhook URL (Mattermost/RocketChat) |
| `channel` | | Target channel (optional) |
| `timeout` | `10` | HTTP timeout (seconds) |

## CLI Usage

```
usage: lrn-transferd.py [-h] [--config CONFIG] [--foreground] [--status] [--run-once]

  --config, -c     Config file path
  --foreground, -f Log to stdout in addition to log file
  --status, -s     Print recent transfer history and exit
  --run-once       Run one outbox + inbound cycle then exit (cron-friendly)
```

## Run-Once / Cron Mode

The optional systemd timer runs lrn-transfer every 5 minutes as a one-shot:

```bash
sudo systemctl enable --now lrn-transfer-run-once.timer
systemctl list-timers lrn-transfer-run-once.timer
```

## Notifications

### XMPP
Configure an ejabberd or Prosody account. lrn-transfer uses a pure-Python XMPP implementation (no external XMPP library required beyond paramiko).

### Webhook
Compatible with Mattermost and RocketChat incoming webhooks. Posts a JSON payload:
```json
{"text": "[lrn-transfer] New file received in inbox:\n  File: example.pdf\n  ..."}
```

## Security Notes

- The `lrn-transfer` service user has no shell and no login capability
- SSH keys stored in `/etc/lrn-transfer/keys/` (mode 700)
- Config file mode 640 (root:lrn-transfer)
- systemd unit uses `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`
- Log and lib directories mode 750 (lrn-transfer:lrn-transfer)

## Build Details

```
make fetch-deps    # Download Python wheels (needs internet)
make rpm           # Build RPM (run fetch-deps first)
make tarball       # Build source tarball only
make clean         # Remove build artifacts (keep wheels)
make distclean     # Remove everything including SOURCES/wheels/
```

Versioning: `make rpm VERSION=1.1 RELEASE=2`

## License

GPLv3
