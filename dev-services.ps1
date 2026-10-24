# Shared by start.ps1, stop.ps1, and restart.ps1.
# Tracks only the servers those scripts start. A busy port is skipped, never cleared.

$script:Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:StateDir = Join-Path $Root ".quantivo"
$script:StateFile = Join-Path $StateDir "services.json"
$script:LogDir = Join-Path $StateDir "logs"
$script:Backend = Join-Path $Root "backend"
$script:Mobile = Join-Path $Root "mobile"
$script:Python = Join-Path $Backend ".venv\Scripts\python.exe"

function Initialize-DevState {
    New-Item -ItemType Directory -Force -Path $StateDir, $LogDir | Out-Null
}

function Read-DevState {
    if (-not (Test-Path $StateFile)) {
        return $null
    }
    return Get-Content -Raw -Path $StateFile | ConvertFrom-Json
}

function Write-DevState($State) {
    Initialize-DevState
    $State | ConvertTo-Json -Depth 5 | Set-Content -Path $StateFile -Encoding utf8
}

function Get-ProcessCommandLine([int]$ProcessId) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if ($process) {
        return [string]$process.CommandLine
    }
    return $null
}

function Test-RecordedProcess([int]$ProcessId, [string]$Marker) {
    if ($ProcessId -le 0) {
        return $false
    }
    $command = Get-ProcessCommandLine $ProcessId
    return ($null -ne $command -and $command -like "*$Marker*")
}

function Test-PortOpen([int]$Port) {
    $client = $null
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $client.Connect("127.0.0.1", $Port)
        return $true
    } catch {
        return $false
    } finally {
        if ($client) {
            $client.Dispose()
        }
    }
}

function Test-PortTaken([int]$Port) {
    if (Test-PortOpen $Port) {
        return $true
    }
    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        return $false
    } catch {
        return $true
    } finally {
        if ($listener) {
            $listener.Stop()
        }
    }
}

function Get-ListeningProcessId([int]$Port) {
    $pattern = "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
    foreach ($line in (netstat -ano -p TCP)) {
        if ($line -match $pattern) {
            return [int]$Matches[1]
        }
    }
    return $null
}

function Find-ProjectOnPort([int]$Port, [string]$Marker) {
    if (-not (Test-PortTaken $Port)) {
        return $null
    }
    $owner = Get-ListeningProcessId $Port
    if (-not $owner) {
        return $null
    }
    $command = Get-ProcessCommandLine $owner
    if ($command -like "*$Marker*" -and $command -like "*quantivo-mobile*") {
        return [pscustomobject]@{ pid = $owner; port = $Port }
    }
    return $null
}

function Find-FreePort([int]$Preferred, [int]$Last) {
    for ($port = $Preferred; $port -le $Last; $port++) {
        if (-not (Test-PortTaken $port)) {
            return $port
        }
    }
    throw "No free port from $Preferred through $Last."
}

function Stop-RecordedProcess([int]$ProcessId, [string]$Marker, [string]$Name) {
    if ($ProcessId -le 0) {
        Write-Host "$Name was not started by these scripts."
        return
    }
    $command = Get-ProcessCommandLine $ProcessId
    if (-not $command) {
        Write-Host "$Name process $ProcessId is already gone."
        return
    }
    if ($command -notlike "*$Marker*") {
        Write-Host "$Name process $ProcessId does not belong to this project. Left it running."
        return
    }
    & taskkill.exe /PID $ProcessId /T /F | Out-Host
    Write-Host "Stopped $Name (process $ProcessId)."
}

function Wait-Port([int]$Port, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortTaken $Port) {
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Wait-Postgres {
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        $status = docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" quantivo-postgres 2>$null
        if ($status -eq "healthy" -or $status -eq "running") {
            if ($status -eq "healthy") {
                return
            }
        }
        Start-Sleep -Seconds 2
    }
    throw "Postgres did not become healthy. The database container was not replaced."
}
