param(
    [ValidateSet("help", "bootstrap-uv", "install", "sync", "lock", "start", "start-bg", "stop", "force-stop", "restart", "status", "logs", "clean")]
    [string]$Action = "help",
    [string]$PythonExe = "python",
    [string]$PythonVersion = "3.12",
    [string]$AppMode = "dev"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Set-ConsoleUtf8 {
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [Console]::InputEncoding = $utf8NoBom
    [Console]::OutputEncoding = $utf8NoBom
    $OutputEncoding = $utf8NoBom
    try {
        & chcp 65001 *> $null
    } catch {
    }
}

Set-ConsoleUtf8

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$HelperScript = Join-Path $PSScriptRoot "make.helpers.ps1"
. $HelperScript
$RunDir = Join-Path $ProjectRoot ".run"
$PidFile = Join-Path $RunDir "service.pid"
$LogDir = Join-Path $ProjectRoot "logs"
$LogFile = Join-Path $LogDir "service.log"
$ErrLogFile = Join-Path $LogDir "service.err.log"
$RequiredPorts = @(8000, 50051)

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $FilePath $($Arguments -join ' ')"
    }
}

function Ensure-Uv {
    try {
        & $PythonExe -m uv --version *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "uv is already installed."
            return
        }
    } catch {
    }

    Write-Host "uv not found, installing via pip..."
    Invoke-CheckedCommand -FilePath $PythonExe -Arguments @("-m", "pip", "install", "uv")
}

function Use-ProjectVirtualEnv {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $ProjectRoot ".venv-windows"

    $sharedVenvPath = Join-Path $ProjectRoot ".venv"
    if (-not (Test-Path $sharedVenvPath)) {
        return
    }

    $reasons = [System.Collections.Generic.List[string]]::new()
    $windowsPython = Join-Path $sharedVenvPath "Scripts\\python.exe"
    $unixBinDir = Join-Path $sharedVenvPath "bin"
    $pyvenvCfg = Join-Path $sharedVenvPath "pyvenv.cfg"

    if (Test-Path $unixBinDir) {
        [void]$reasons.Add("contains a Unix-style 'bin' directory")
    }

    if (-not (Test-Path $windowsPython)) {
        [void]$reasons.Add("is missing 'Scripts\\python.exe'")
    }

    if (Test-Path $pyvenvCfg) {
        $pyvenvContents = Get-Content $pyvenvCfg -Raw
        if ($pyvenvContents -match "(?m)^home\s*=\s*/") {
            [void]$reasons.Add("was created from a non-Windows Python home")
        }
    }

    if ($reasons.Count -eq 0) {
        return
    }

    Write-Host "Detected an incompatible shared virtualenv at $sharedVenvPath."
    Write-Host "Reasons: $($reasons -join '; ')"
    Write-Host "Using Windows project virtualenv at $($env:UV_PROJECT_ENVIRONMENT) instead."
}

function Get-ServiceProcess {
    if (-not (Test-Path $PidFile)) {
        return $null
    }

    $servicePid = (Get-Content $PidFile | Select-Object -First 1).Trim()
    if (-not $servicePid) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        return $null
    }

    $process = Get-Process -Id $servicePid -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        return $null
    }

    return $process
}

function Quote-Single {
    param([string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Get-UvRunArguments {
    return @("-m", "uv", "run", "--python", $PythonVersion, "python", "run.py")
}

function Get-RequiredPortListeners {
    return @(
        Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $RequiredPorts -contains $_.LocalPort } |
            Sort-Object LocalPort, OwningProcess
    )
}

function Show-CleanupResults {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Results
    )

    foreach ($result in $Results) {
        if ($result.ExitCode -eq 0) {
            Write-Host "Stopped stale project process tree rooted at PID $($result.ProcessId)."
        } else {
            Write-Host "Failed to stop stale project process tree rooted at PID $($result.ProcessId): $($result.Output)"
        }
    }
}

function Assert-NoExternalPortConflicts {
    for ($attempt = 0; $attempt -lt 2; $attempt++) {
        $listeners = @(Get-RequiredPortListeners)
        $projectProcessIds = @(
            Get-ProjectServiceProcesses -ProjectRoot $ProjectRoot |
                ForEach-Object { [int]$_.ProcessId }
        )

        if ($projectProcessIds.Count -eq 0) {
            $conflicts = $listeners
        } else {
            $conflicts = @(
                $listeners |
                    Where-Object { $projectProcessIds -notcontains [int]$_.OwningProcess }
            )
        }

        if ($conflicts.Count -eq 0) {
            return
        }

        if ($attempt -eq 0) {
            Start-Sleep -Seconds 2
            continue
        }

        $details = @(
            $conflicts |
                ForEach-Object { "$($_.LocalAddress):$($_.LocalPort) [PID=$($_.OwningProcess)]" }
        ) -join ", "
        throw "Required ports are already in use by another process: $details"
    }
}

function Prepare-ServiceStart {
    $staleProcesses = @(Get-ProjectServiceProcesses -ProjectRoot $ProjectRoot)
    if ($staleProcesses.Count -gt 0) {
        Write-Host "Found stale project service processes: $(@($staleProcesses | ForEach-Object { $_.ProcessId }) -join ', ')"
        $cleanupResults = @(Stop-ProjectServiceProcesses -ProjectRoot $ProjectRoot -Force)
        Show-CleanupResults -Results $cleanupResults
        Start-Sleep -Seconds 2
    }

    $remainingProjectListeners = @(Get-ProjectPortListeners -ProjectRoot $ProjectRoot -Ports $RequiredPorts)
    if ($remainingProjectListeners.Count -gt 0) {
        Write-Host "Project listeners remain after cleanup, waiting briefly before retrying port checks..."
        Start-Sleep -Seconds 2
    }

    Assert-NoExternalPortConflicts
}

function Start-ForegroundProcess {
    $backgroundProcess = Get-ServiceProcess
    if ($null -ne $backgroundProcess) {
        Write-Host "A background service is already running with PID $($backgroundProcess.Id)."
        Write-Host "Run 'make stop' first, or use 'make start-bg' only when you want background mode."
        return
    }

    Use-ProjectVirtualEnv
    Prepare-ServiceStart

    $env:APP_MODE = $AppMode
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    Write-Host "Starting service in foreground with APP_MODE=$AppMode"
    & $PythonExe @(Get-UvRunArguments)
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $PythonExe $((Get-UvRunArguments) -join ' ')"
    }
}

function Start-BackgroundServiceProcess {
    $existingProcess = Get-ServiceProcess
    if ($null -ne $existingProcess) {
        Write-Host "Service is already running with PID $($existingProcess.Id)."
        return
    }

    Use-ProjectVirtualEnv
    Prepare-ServiceStart

    New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    Remove-Item $LogFile -Force -ErrorAction SilentlyContinue
    Remove-Item $ErrLogFile -Force -ErrorAction SilentlyContinue

    $cmdPython = $PythonExe.Replace('"', '\"')
    $cmdCommand = 'set "APP_MODE=' + $AppMode + '" && set "PYTHONUTF8=1" && set "PYTHONIOENCODING=utf-8" && "' + $cmdPython + '" -m uv run --python ' + $PythonVersion + ' python run.py'

    $process = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList @("/c", $cmdCommand) `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError $ErrLogFile `
        -PassThru

    Set-Content -Path $PidFile -Value $process.Id

    Write-Host "Service started in background."
    Write-Host "PID: $($process.Id)"
    Write-Host "STDOUT: $LogFile"
    Write-Host "STDERR: $ErrLogFile"
}

function Stop-ServiceProcess {
    param([switch]$Force)

    $process = Get-ServiceProcess
    if ($null -eq $process) {
        $cleanupResults = @(Stop-ProjectServiceProcesses -ProjectRoot $ProjectRoot -Force:$Force)
        if ($cleanupResults.Count -eq 0) {
            Write-Host "Service is not running."
            return
        }

        Show-CleanupResults -Results $cleanupResults
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        Write-Host "Removed stale project service processes."
        return
    }

    $taskkillArgs = @("/PID", "$($process.Id)", "/T")
    if ($Force) {
        $taskkillArgs = @("/F") + $taskkillArgs
    }

    $taskkillOutput = & taskkill @taskkillArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to stop service: $taskkillOutput"
    }

    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue

    if ($Force) {
        Write-Host "Service force-stopped."
    } else {
        Write-Host "Service stopped."
    }
}

function Show-Status {
    $process = Get-ServiceProcess
    $projectProcesses = @(Get-ProjectServiceProcesses -ProjectRoot $ProjectRoot)
    $listeners = @(Get-RequiredPortListeners)

    if ($null -eq $process -and $projectProcesses.Count -eq 0 -and $listeners.Count -eq 0) {
        Write-Host "Service is not running."
        return
    }

    if ($null -ne $process) {
        Write-Host "Managed background service is running."
        Write-Host "PID: $($process.Id)"
        Write-Host "STDOUT: $LogFile"
        Write-Host "STDERR: $ErrLogFile"
    } else {
        Write-Host "No managed background PID file is active."
    }

    if ($projectProcesses.Count -gt 0) {
        Write-Host "Detected project service processes: $(@($projectProcesses | ForEach-Object { $_.ProcessId }) -join ', ')"
    }

    if ($listeners.Count -gt 0) {
        $listenerSummary = @(
            $listeners |
                ForEach-Object { "$($_.LocalAddress):$($_.LocalPort) [PID=$($_.OwningProcess)]" }
        ) -join ", "
        Write-Host "Listening ports: $listenerSummary"
    }
}

function Show-Logs {
    Write-Host $LogFile
    Write-Host $ErrLogFile
}

function Clean-State {
    if (Test-Path $PidFile) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }

    if ((Test-Path $RunDir) -and -not (Get-ChildItem $RunDir -Force | Select-Object -First 1)) {
        Remove-Item $RunDir -Force -ErrorAction SilentlyContinue
    }

    Write-Host "Runtime state cleaned."
}

function Show-Help {
    Write-Host "Available targets:"
    Write-Host "  make install      Install uv, Python $PythonVersion, and project dependencies"
    Write-Host "  make sync         Sync project dependencies with uv"
    Write-Host "  make lock         Refresh uv.lock using Python $PythonVersion"
    Write-Host "  make start        Start the service in foreground with APP_MODE=$AppMode"
    Write-Host "  make start-bg     Start the service in background with APP_MODE=$AppMode"
    Write-Host "  make stop         Stop the background service"
    Write-Host "  make force-stop   Force stop the background service"
    Write-Host "  make restart      Restart the background service"
    Write-Host "  make status       Show background service status"
    Write-Host "  make logs         Print the background service log paths"
    Write-Host "  make clean        Remove runtime state"
}

Push-Location $ProjectRoot
try {
    switch ($Action) {
        "help" { Show-Help }
        "bootstrap-uv" { Ensure-Uv }
        "install" {
            Ensure-Uv
            Invoke-CheckedCommand -FilePath $PythonExe -Arguments @("-m", "uv", "python", "install", $PythonVersion)
            Use-ProjectVirtualEnv
            Invoke-CheckedCommand -FilePath $PythonExe -Arguments @("-m", "uv", "sync", "--no-install-project", "--python", $PythonVersion)
        }
        "sync" {
            Ensure-Uv
            Use-ProjectVirtualEnv
            Invoke-CheckedCommand -FilePath $PythonExe -Arguments @("-m", "uv", "sync", "--no-install-project", "--python", $PythonVersion)
        }
        "lock" {
            Ensure-Uv
            Invoke-CheckedCommand -FilePath $PythonExe -Arguments @("-m", "uv", "lock", "--python", $PythonVersion)
        }
        "start" {
            Ensure-Uv
            Start-ForegroundProcess
        }
        "start-bg" {
            Ensure-Uv
            Start-BackgroundServiceProcess
        }
        "stop" { Stop-ServiceProcess }
        "force-stop" { Stop-ServiceProcess -Force }
        "restart" {
            Stop-ServiceProcess
            Ensure-Uv
            Start-BackgroundServiceProcess
        }
        "status" { Show-Status }
        "logs" { Show-Logs }
        "clean" { Clean-State }
        default { throw "Unsupported action: $Action" }
    }
} finally {
    Pop-Location
}
