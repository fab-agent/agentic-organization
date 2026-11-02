# Thin PowerShell entry point for the Windows user installer (ADR-0032). All the logic is in
# install.mjs next to this file; this only finds Node and passes the arguments through.
#   .\install.ps1 --base-url https://... --root-pub KEY --cli .\3pa.mjs --cli-sha256 HEX ...
$ErrorActionPreference = 'Stop'
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { Write-Error 'Node.js 20 or newer is required (not found).'; exit 1 }
& node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)'
if ($LASTEXITCODE -ne 0) { Write-Error 'Node.js 20 or newer is required.'; exit 1 }
& node (Join-Path $PSScriptRoot 'install.mjs') @args
exit $LASTEXITCODE
