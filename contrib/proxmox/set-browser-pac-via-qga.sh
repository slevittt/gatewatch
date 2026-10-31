#!/usr/bin/env bash
# Set the Chrome PAC policy inside a Windows VM from the Proxmox host, through the QEMU guest agent.
#   usage: set-browser-pac-via-qga.sh <vmid> <pac-url>
# The PowerShell is passed base64-encoded (-EncodedCommand): no shell on the way can eat the JSON quotes.
set -euo pipefail
vmid="${1:?usage: $0 <vmid> <pac-url>}"
pac="${2:?usage: $0 <vmid> <pac-url>}"
case "$pac" in *"'"*|*'"'*) echo "the URL must not contain quotes" >&2; exit 2;; esac

ps=$(cat <<PS
\$j = @{ProxyMode='pac_script';ProxyPacUrl='$pac'} | ConvertTo-Json -Compress
New-Item -Path HKLM:\SOFTWARE\Policies\Google\Chrome -Force | Out-Null
Set-ItemProperty -Path HKLM:\SOFTWARE\Policies\Google\Chrome -Name ProxySettings -Value \$j -Type String
(Get-ItemProperty HKLM:\SOFTWARE\Policies\Google\Chrome).ProxySettings
PS
)
enc=$(printf '%s' "$ps" | iconv -t UTF-16LE | base64 -w0)
qm guest exec "$vmid" -- powershell -NoProfile -EncodedCommand "$enc"
echo
echo "Check that out-data above contains quotes: {\"ProxyMode\":\"pac_script\",...}"
echo "Then restart the browser:  qm guest exec $vmid -- cmd /c taskkill /F /IM chrome.exe"
