<#
.SYNOPSIS
  Point Chrome (and optionally Edge) at a PAC file through machine policy.

.DESCRIPTION
  The policy value is a JSON string. Writing it with `reg add` loses the double quotes on the way
  through most shells, which leaves {ProxyMode:pac_script,...}: not valid JSON, silently ignored by the
  browser, no error anywhere. This script builds the JSON with ConvertTo-Json and verifies it.

.EXAMPLE
  .\Set-BrowserPac.ps1 -PacUrl http://192.168.1.10:8094/gatewatch.pac -Edge
#>
param(
  [Parameter(Mandatory = $true)][string]$PacUrl,
  [switch]$Edge
)
$ErrorActionPreference = 'Stop'
$keys = @('HKLM:\SOFTWARE\Policies\Google\Chrome')
if ($Edge) { $keys += 'HKLM:\SOFTWARE\Policies\Microsoft\Edge' }
$json = @{ ProxyMode = 'pac_script'; ProxyPacUrl = $PacUrl } | ConvertTo-Json -Compress
foreach ($key in $keys) {
  New-Item -Path $key -Force | Out-Null
  Set-ItemProperty -Path $key -Name ProxySettings -Value $json -Type String
  $back = (Get-ItemProperty -Path $key).ProxySettings
  try { $null = $back | ConvertFrom-Json } catch { throw "ProxySettings in $key is not valid JSON: $back" }
  Write-Host "OK  $key  ->  $back"
}
Write-Host "Now close the browser completely (also in the tray) and open chrome://policy -> Reload policies."
Write-Host "Disable proxy extensions (VPN add-ons): they take priority over the policy."
