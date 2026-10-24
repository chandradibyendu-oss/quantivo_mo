# Restart the API and preview. Postgres stays up unless database is requested.

param(
    [switch]$Database,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"
$includeDatabase = $Database.IsPresent -or @($Rest) -contains "database"
if ($includeDatabase) {
    Write-Host "Restarting the API, the preview, and Postgres."
} else {
    Write-Host "Restarting the API and the preview. Postgres stays up."
    Write-Host "Use .\restart.cmd database when the Postgres container itself must be replaced."
}
& (Join-Path $PSScriptRoot "stop.ps1") -Database:$includeDatabase
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
& (Join-Path $PSScriptRoot "start.ps1") -Database:$includeDatabase
exit $LASTEXITCODE
