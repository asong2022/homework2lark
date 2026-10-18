[CmdletBinding()]
param(
    [ValidateSet("bootstrap", "api", "prepare")]
    [string]$Mode = "bootstrap",

    [ValidateRange(10, 600)]
    [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptFile = $MyInvocation.MyCommand.Path
$ScriptsRoot = Split-Path -Parent $ScriptFile
$RepositoryRoot = Split-Path -Parent $ScriptsRoot
$ApiUrl = "http://localhost:8000"
$ApiHealthUrl = "$ApiUrl/api/v1/health"

function Write-Step {
    param([Parameter(Mandatory)][string]$Message)

    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Get-RequiredCommand {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$InstallHint
    )

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "未找到 $Name。$InstallHint"
    }
    return $command.Source
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$FailureMessage
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage（退出码：$LASTEXITCODE）"
    }
}

function Test-PortInUse {
    param([Parameter(Mandatory)][int]$Port)

    $listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    return $null -ne ($listeners | Where-Object { $_.Port -eq $Port } | Select-Object -First 1)
}

function Get-LockHash {
    param([Parameter(Mandatory)][string]$Path)

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function Test-DependencyMarker {
    param(
        [Parameter(Mandatory)][string]$MarkerPath,
        [Parameter(Mandatory)][string]$ExpectedHash
    )

    if (-not (Test-Path -LiteralPath $MarkerPath -PathType Leaf)) {
        return $false
    }
    return (Get-Content -Raw -LiteralPath $MarkerPath).Trim() -eq $ExpectedHash
}

function Set-DependencyMarker {
    param(
        [Parameter(Mandatory)][string]$MarkerPath,
        [Parameter(Mandatory)][string]$Hash
    )

    $markerDirectory = Split-Path -Parent $MarkerPath
    New-Item -ItemType Directory -Path $markerDirectory -Force | Out-Null
    Set-Content -LiteralPath $MarkerPath -Value $Hash -Encoding ascii
}

function Wait-ForUrl {
    param(
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][System.Diagnostics.Process]$Process,
        [Parameter(Mandatory)][int]$Seconds
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($Process.HasExited) {
            throw "API 启动进程已退出。请查看新窗口中的错误日志。"
        }
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                Write-Host "[OK] 本地证据服务已就绪：$Url" -ForegroundColor Green
                return
            }
        }
        catch {
            # Startup can briefly refuse connections; retry until the deadline.
        }
        Start-Sleep -Milliseconds 500
    }
    throw "等待 API 启动超时（$Seconds 秒）。请查看新窗口中的日志。"
}

function Get-PowerShellExecutable {
    $pwsh = Get-Command "pwsh.exe" -ErrorAction SilentlyContinue
    if ($null -ne $pwsh) {
        return $pwsh.Source
    }
    return (Get-RequiredCommand -Name "powershell.exe" -InstallHint "请启用 Windows PowerShell 后重试。")
}

function Start-ApiWindow {
    $powerShellExecutable = Get-PowerShellExecutable
    $quotedScriptPath = '"' + $ScriptFile + '"'
    $arguments = @(
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-NoExit",
        "-File", $quotedScriptPath,
        "-Mode", "api"
    )
    return Start-Process -FilePath $powerShellExecutable -ArgumentList $arguments -WorkingDirectory $RepositoryRoot -PassThru
}

function Start-ApiService {
    try {
        $Host.UI.RawUI.WindowTitle = "homework2lark - 本地证据服务 (8000)"
    }
    catch {
        # Some hosts do not expose a writable window title.
    }
    Set-Location -LiteralPath $RepositoryRoot
    Write-Host "正在启动本地证据服务：$ApiUrl" -ForegroundColor Cyan
    $uv = Get-RequiredCommand -Name "uv" -InstallHint "请先安装 uv：https://docs.astral.sh/uv/"
    & $uv run --directory apps/api uvicorn --app-dir src mistake_notebook_api.main:app --reload --port 8000
    if ($LASTEXITCODE -ne 0) {
        Write-Host "API 已异常退出，退出码：$LASTEXITCODE" -ForegroundColor Red
    }
    else {
        Write-Host "API 已停止。" -ForegroundColor Yellow
    }
}

function Prepare-Project {
    Write-Step "检查并准备本地证据服务"
    $uv = Get-RequiredCommand -Name "uv" -InstallHint "请先安装 uv：https://docs.astral.sh/uv/"
    Write-Host "[OK] $(& $uv --version)" -ForegroundColor Green

    if ($Mode -eq "bootstrap" -and (Test-PortInUse -Port 8000)) {
        throw "API 需要的端口 8000 已被占用。请关闭先前启动的服务后重试。"
    }

    $environmentPath = Join-Path $RepositoryRoot ".env"
    if (-not (Test-Path -LiteralPath $environmentPath -PathType Leaf)) {
        Copy-Item -LiteralPath (Join-Path $RepositoryRoot ".env.example") -Destination $environmentPath
        Write-Host "[OK] 已从 .env.example 创建 .env（默认 PaddleOCR-VL-1.6）" -ForegroundColor Green
    }
    else {
        Write-Host "[OK] 保留现有 .env" -ForegroundColor Green
    }

    $uvLockPath = Join-Path $RepositoryRoot "apps/api/uv.lock"
    $uvMarkerPath = Join-Path $RepositoryRoot "apps/api/.venv/.quick-start-lock.sha256"
    $uvLockHash = Get-LockHash -Path $uvLockPath
    if (-not (Test-DependencyMarker -MarkerPath $uvMarkerPath -ExpectedHash $uvLockHash)) {
        Invoke-CheckedCommand -Executable $uv -Arguments @("sync", "--directory", "apps/api", "--all-groups", "--inexact") -FailureMessage "API 依赖安装失败"
        Set-DependencyMarker -MarkerPath $uvMarkerPath -Hash (Get-LockHash -Path $uvLockPath)
        Write-Host "[OK] API 依赖已准备" -ForegroundColor Green
    }
    else {
        Write-Host "[OK] API 依赖未变更，跳过安装" -ForegroundColor Green
    }

    Write-Step "执行数据库迁移"
    Invoke-CheckedCommand -Executable $uv -Arguments @("run", "--directory", "apps/api", "alembic", "upgrade", "head") -FailureMessage "数据库迁移失败"
    Write-Host "[OK] 数据库已就绪" -ForegroundColor Green
}

try {
    switch ($Mode) {
        "api" {
            Start-ApiService
            return
        }
        "prepare" {
            Prepare-Project
            Write-Host ""
            Write-Host "[OK] 项目准备检查完成。" -ForegroundColor Green
            return
        }
    }

    Set-Location -LiteralPath $RepositoryRoot
    Prepare-Project
    Write-Step "启动本地证据服务"
    $apiProcess = Start-ApiWindow
    Wait-ForUrl -Url $ApiHealthUrl -Process $apiProcess -Seconds $TimeoutSeconds
    Write-Host ""
    Write-Host "[OK] homework2lark 已就绪，可以回到 AI 对话发送作业。" -ForegroundColor Green
    Write-Host "停止时，在 API 窗口中按 Ctrl+C，或直接关闭该窗口。"
}
catch {
    Write-Host ""
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    if ($Mode -eq "api") {
        Write-Host "请根据上方日志处理后，关闭本窗口并重新启动。" -ForegroundColor Yellow
        return
    }
    exit 1
}
