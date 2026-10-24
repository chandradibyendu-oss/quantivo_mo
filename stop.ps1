# Stop the API and preview started for this project. Postgres stays up unless database is requested.

param(
    [switch]$Database,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "dev-services.ps1")
$includeDatabase = $Database.IsPresent -or @($Rest) -contains "database"

$state = Read-DevState
if ($state -and $state.api) {
    Stop-RecordedProcess ([int]$state.api.pid) ([string]$state.api.marker) "API"
} else {
    Write-Host "No API process was recorded for this project."
}
if ($state -and $state.expo) {
    Stop-RecordedProcess ([int]$state.expo.pid) ([string]$state.expo.marker) "Web preview"
} else {
    Write-Host "No web preview was recorded for this project."
}
if ($state -and $state.worker) {
    Stop-RecordedProcess ([int]$state.worker.pid) ([string]$state.worker.marker) "Telegram worker"
}

if ($includeDatabase) {
    Write-Host "Stopping this project's Postgres container."
    Push-Location $Root
    try {
        docker compose stop
        if ($LASTEXITCODE -ne 0) {
            throw "Docker could not stop this project's database."
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Host "Postgres was left running. Stop it with .\stop.cmd database"
}

if ($state) {
    $state.api = $null
    $state.expo = $null
    if ($state.PSObject.Properties.Name -contains "worker") {
        $state.worker = $null
    }
    Write-DevState $state
}
Write-Host "Quantivo local services are stopped. Other projects were not changed."
exit 0
