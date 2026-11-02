# Run the deployment helper (ADR-0033) for the person using this Windows machine.
#   .\deploy.ps1 install|check -Config deploy.conf [-AllowElevated]
# It must run in the USER's context (Intune: "run this script using the logged on credentials";
# a login script). Started as SYSTEM it refuses: the workspace belongs to one person.
param(
  [Parameter(Mandatory = $true, Position = 0)][ValidateSet('install', 'check')][string]$Command,
  [Parameter(Mandatory = $true)][string]$Config,
  [switch]$AllowElevated,
  [switch]$PinsOnly
)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Write-Error 'Node.js 20 or newer is required (not found).'; exit 2 }
$me = [System.Security.Principal.WindowsIdentity]::GetCurrent()
if ($me.IsSystem) { Write-Error 'Running as SYSTEM: run this in the logged-on user''s context.'; exit 3 }
$args2 = @((Join-Path $PSScriptRoot 'deploy.mjs'), $Command, '--config', (Resolve-Path $Config).Path)
if ($AllowElevated) { $args2 += '--allow-elevated' }
if ($PinsOnly) { $args2 += '--pins-only' }
& node @args2
exit $LASTEXITCODE
