%global debug_package %{nil}
%global app_user  lrn-transfer
%global app_home  /opt/lrn-transfer
%global app_conf  /etc/lrn-transfer
%global app_log   /var/log/lrn-transfer
%global app_lib   /var/lib/lrn-transfer

Name:           lrn-transfer
Version:        %{_version}
Release:        %{_release}%{?dist}
Summary:        Air-gap file transfer daemon with SFTP transport and XMPP/webhook notifications
License:        GPLv3
URL:            https://github.com/mike0615/lrn-transfer
Source0:        %{name}-%{version}.tar.gz
BuildArch:      x86_64

# No RPM-level Requires — Python deps are bundled in venv at install time

%description
lrn-transfer is an air-gapped file transfer daemon that exchanges files between
isolated networks via a transfer PC using SFTP. It monitors a local outbox
directory for new files, uploads them to the transfer PC, and polls for inbound
files from the other side. Notifications are sent via XMPP (ejabberd/Prosody)
and/or webhooks (Mattermost, RocketChat).

Features:
  - Outbound: outbox/ → SFTP → transfer PC incoming/
  - Inbound:  transfer PC outgoing/ → SFTP → inbox/
  - SHA256 deduplication (never re-sends the same file)
  - File stability check (waits for writes to complete)
  - SQLite audit trail with automatic old-record purge
  - Exponential backoff on SFTP failures
  - XMPP and/or webhook notifications
  - Systemd service + optional timer (run-once/cron mode)
  - Air-gap ready: all Python deps bundled in venv

Target OS: Rocky Linux 9.x

%prep
%setup -q

%build
# Nothing to compile

%install
# Application files
install -d %{buildroot}%{app_home}
install -d %{buildroot}%{app_conf}
install -d %{buildroot}%{app_conf}/keys
install -d %{buildroot}%{app_log}
install -d %{buildroot}%{app_lib}

# Copy source
cp -r lrn_transfer/              %{buildroot}%{app_home}/
install -m 755 lrn-transferd.py  %{buildroot}%{app_home}/
install -m 644 requirements.txt  %{buildroot}%{app_home}/

# Config example
install -m 640 config/lrn-transfer.conf.example \
    %{buildroot}%{app_conf}/lrn-transfer.conf.example

# Systemd units
install -d %{buildroot}%{_unitdir}
install -m 644 systemd/lrn-transfer.service \
    %{buildroot}%{_unitdir}/lrn-transfer.service
install -m 644 systemd/lrn-transfer-run-once.service \
    %{buildroot}%{_unitdir}/lrn-transfer-run-once.service
install -m 644 systemd/lrn-transfer-run-once.timer \
    %{buildroot}%{_unitdir}/lrn-transfer-run-once.timer

# Install script (air-gapped venv builder)
install -m 755 scripts/install.sh %{buildroot}%{app_home}/install.sh

# Bundle Python wheels if present (built by scripts/fetch-deps.sh)
%{?_wheels_dir:%{expand:
if [ -d "%{_wheels_dir}" ] && [ "$(ls -A '%{_wheels_dir}')" ]; then
    install -d %%{buildroot}%%{app_home}/wheels
    cp -r %{_wheels_dir}/. %%{buildroot}%%{app_home}/wheels/
fi
}}

# Generate file list
find %{buildroot}%{app_home} -not -type d \
    | sed "s|^%{buildroot}||" \
    > %{_builddir}/%{name}-%{version}/filelist
find %{buildroot}%{app_home} -mindepth 1 -type d \
    | sed "s|^%{buildroot}|%%dir |" \
    >> %{_builddir}/%{name}-%{version}/filelist

%files -f filelist
%defattr(-,root,root,-)
%dir %{app_conf}
%dir %attr(0700,root,root) %{app_conf}/keys
%config(noreplace) %{app_conf}/lrn-transfer.conf.example
%attr(0750,%{app_user},%{app_user}) %{app_log}
%attr(0750,%{app_user},%{app_user}) %{app_lib}
%{_unitdir}/lrn-transfer.service
%{_unitdir}/lrn-transfer-run-once.service
%{_unitdir}/lrn-transfer-run-once.timer

%pre
# Create service user if it doesn't exist
getent group  %{app_user} >/dev/null || groupadd -r %{app_user}
getent passwd %{app_user} >/dev/null || \
    useradd -r -g %{app_user} -d %{app_lib} -s /sbin/nologin \
        -c "lrn-transfer service account" %{app_user}
exit 0

%post
systemctl daemon-reload >/dev/null 2>&1 || :

echo ""
echo "============================================================"
echo "  lrn-transfer installed"
echo "  App:    %{app_home}"
echo "  Config: %{app_conf}"
echo "============================================================"
echo ""
echo "  Next steps:"
echo "    1. Build the Python venv (if not done by install.sh):"
echo "         sudo bash %{app_home}/install.sh"
echo ""
echo "    2. Copy and edit the config:"
echo "         sudo cp %{app_conf}/lrn-transfer.conf.example \\"
echo "                 %{app_conf}/lrn-transfer.conf"
echo "         sudo nano %{app_conf}/lrn-transfer.conf"
echo ""
echo "    3. Enable and start the service:"
echo "         sudo systemctl enable --now lrn-transfer"
echo ""
echo "    4. Check status:"
echo "         python3 %{app_home}/lrn-transferd.py --status \\"
echo "             --config %{app_conf}/lrn-transfer.conf"
echo ""

%preun
if [ $1 -eq 0 ]; then
    systemctl stop    lrn-transfer 2>/dev/null || :
    systemctl disable lrn-transfer 2>/dev/null || :
    systemctl stop    lrn-transfer-run-once.timer 2>/dev/null || :
    systemctl disable lrn-transfer-run-once.timer 2>/dev/null || :
fi

%postun
systemctl daemon-reload >/dev/null 2>&1 || :

%changelog
* Fri Apr 17 2026 LRN-MAN <lrn-man@planet-maytag.local> - 1.0-1
- Initial release: air-gapped SFTP file transfer daemon with XMPP/webhook notifications
- OutboxWorker, InboundWorker, SQLite audit trail, exponential backoff
- Systemd service + run-once timer, bundled Python venv for air-gapped install
