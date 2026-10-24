# Start this project's API and web preview.
# Postgres is started only when it is not already running, unless database is requested.
# This project uses API port 8001 and preview port 8081.
# A taken port is left alone. The new process then tries the next few ports.

param(
    [switch]$Database,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Continue"
$PSNativeCommandUseErrorActionPreference = $false
. (Join-Path $PSScriptRoot "dev-services.ps1")
$includeDatabase = $Database.IsPresent -or @($Rest) -contains "database"

Initialize-DevState
$state = Read-DevState
if (-not $state) {
    $state = [pscustomobject]@{
        postgres = "quantivo-postgres"
        api      = $null
        expo     = $null
    }
}

$postgresRunning = (docker inspect --format "{{.State.Running}}" quantivo-postgres 2>$null) -eq "true"
Push-Location $Root
if ($includeDatabase -and $postgresRunning) {
    Write-Host "Restarting Postgres for this project on host port 5433."
    docker compose restart
    $composeCode = $LASTEXITCODE
} elseif ($postgresRunning) {
    Write-Host "Postgres is already running on host port 5433."
    $composeCode = 0
} else {
    Write-Host "Starting Postgres for this project on host port 5433."
    docker compose up -d
    $composeCode = $LASTEXITCODE
}
Pop-Location
if ($composeCode -ne 0) {
    throw "Docker did not start this project's database. The process using the port was left running."
}
Wait-Postgres
Write-Host "Postgres is up."

if (-not (Test-Path $Python)) {
    throw "The API environment is missing. From backend, run: python -m venv .venv; .\.venv\Scripts\python -m pip install -e `".[dev]`""
}
$envFile = Join-Path $Backend ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $Backend ".env.example") $envFile
    Write-Host "Created backend\.env from the example."
}
if (-not (Test-Path (Join-Path $Mobile "node_modules"))) {
    throw "Mobile dependencies are missing. From mobile, run: npm install"
}

Write-Host "Applying migrations and seed."
Push-Location $Backend
& $Python -m alembic upgrade head
$migrateCode = $LASTEXITCODE
if ($migrateCode -eq 0) {
    & $Python -m app.seed
    $migrateCode = $LASTEXITCODE
}
Pop-Location
if ($migrateCode -ne 0) { exit $migrateCode }

$apiPort = $null
if ($state.api -and (Test-RecordedProcess ([int]$state.api.pid) "app.main:app")) {
    $apiPort = [int]$state.api.port
    Write-Host "API is already running at http://127.0.0.1:$apiPort"
} else {
    $existingApi = Find-ProjectOnPort 8001 "app.main:app"
    if ($existingApi) {
        $apiPort = [int]$existingApi.port
        $state.api = [pscustomobject]@{ pid = [int]$existingApi.pid; port = $apiPort; marker = "app.main:app" }
        Write-Host "Using the Quantivo API already running at http://127.0.0.1:$apiPort"
    } else {
        $apiPort = Find-FreePort 8001 8010
        if ($apiPort -ne 8001) {
            Write-Host "Port 8001 is in use by another process. Starting the API on $apiPort."
        }
        $api = Start-Process -FilePath $Python `
            -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$apiPort") `
            -WorkingDirectory $Backend `
            -RedirectStandardOutput (Join-Path $LogDir "api.out.log") `
            -RedirectStandardError (Join-Path $LogDir "api.err.log") `
            -PassThru -WindowStyle Hidden
        if (-not (Wait-Port $apiPort 30)) {
            throw "The API did not start. See .quantivo\logs\api.err.log"
        }
        $state.api = [pscustomobject]@{ pid = $api.Id; port = $apiPort; marker = "app.main:app" }
        Write-Host "API started at http://127.0.0.1:$apiPort (process $($api.Id))."
    }
}

$apiUrl = "http://127.0.0.1:$apiPort"
Set-Content -Path (Join-Path $Mobile ".env.local") -Encoding utf8 -Value "EXPO_PUBLIC_API_URL=$apiUrl"
$env:EXPO_PUBLIC_API_URL = $apiUrl

$expoPort = $null
if ($state.expo -and (Test-RecordedProcess ([int]$state.expo.pid) "expo")) {
    $expoPort = [int]$state.expo.port
    Write-Host "Web preview is already running at http://localhost:$expoPort"
    Write-Host "It keeps the API address from when it started. Run .\restart.cmd if that address changed."
} else {
    $existingExpo = Find-ProjectOnPort 8081 "expo"
    if ($existingExpo) {
        $expoPort = [int]$existingExpo.port
        $state.expo = [pscustomobject]@{ pid = [int]$existingExpo.pid; port = $expoPort; marker = "expo" }
        Write-Host "Using the Quantivo preview already running at http://localhost:$expoPort"
    } else {
        $expoPort = Find-FreePort 8081 8090
        if ($expoPort -ne 8081) {
            Write-Host "Port 8081 is in use by another process. Starting the preview on $expoPort."
        }
        Write-Host "Starting the web preview on port $expoPort."
        $expoOut = Join-Path $LogDir "expo.out.log"
        $expoErr = Join-Path $LogDir "expo.err.log"
        $expo = Start-Process -FilePath "cmd.exe" `
            -ArgumentList @("/c", "npx expo start --web --port $expoPort > `"$expoOut`" 2> `"$expoErr`"") `
            -WorkingDirectory $Mobile `
            -PassThru -WindowStyle Hidden
        if (-not (Wait-Port $expoPort 90)) {
            throw "The web preview did not start. See .quantivo\logs\expo.err.log"
        }
        $state.expo = [pscustomobject]@{ pid = $expo.Id; port = $expoPort; marker = "expo" }
        Write-Host "Web preview started at http://localhost:$expoPort (process $($expo.Id))."
    }
}

$telegramReady = $false
if (Test-Path $envFile) {
    $settings = @{}
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*#' -or $line -notmatch '=') {
            continue
        }
        $pair = $line.Split("=", 2)
        $settings[$pair[0].Trim()] = $pair[1].Trim()
    }
    $sessionPath = $settings["TELEGRAM_SESSION_PATH"]
    $sessionFile = $null
    if ($sessionPath) {
        if (-not [System.IO.Path]::IsPathRooted($sessionPath)) {
            $sessionPath = Join-Path $Backend $sessionPath
        }
        $sessionFile = "$sessionPath.session"
    }
    $telegramReady = [bool]($settings["TELEGRAM_API_ID"] -and $settings["TELEGRAM_API_HASH"] -and $sessionFile -and (Test-Path $sessionFile))
}
if ($telegramReady) {
    $workerOut = Join-Path $LogDir "worker.out.log"
    $workerErr = Join-Path $LogDir "worker.err.log"
    $worker = Start-Process -FilePath $Python `
        -ArgumentList @("-m", "app.feeds.worker") `
        -WorkingDirectory $Backend `
        -RedirectStandardOutput $workerOut `
        -RedirectStandardError $workerErr `
        -PassThru -WindowStyle Hidden
    $workerState = [pscustomobject]@{ pid = $worker.Id; marker = "app.feeds.worker" }
    if ($state.PSObject.Properties.Name -contains "worker") {
        $state.worker = $workerState
    } else {
        $state | Add-Member -MemberType NoteProperty -Name worker -Value $workerState
    }
    Write-Host "Telegram worker started (process $($worker.Id)). It reads history once, then new posts."
} else {
    Write-Host "Telegram worker was not started. Sample calls stay until this machine has its own Telegram login."
}

Write-DevState $state
$previewUrl = "http://localhost:$expoPort"
Start-Process $previewUrl
Write-Host ""
Write-Host "Opened $previewUrl"
Write-Host "The app calls $apiUrl"
Write-Host "Logs are in .quantivo\logs"
