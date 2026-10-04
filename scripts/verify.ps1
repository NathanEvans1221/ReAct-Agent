[CmdletBinding()]
param(
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$oldPythonUtf8 = $env:PYTHONUTF8
$hadPythonUtf8 = Test-Path Env:PYTHONUTF8
$locationPushed = $false
$exitCode = 0

function Invoke-PythonCheck {
    param(
        [string]$Name,
        [string[]]$Arguments
    )

    & $script:PythonExecutable @Arguments
    $commandExitCode = $LASTEXITCODE
    if ($commandExitCode -ne 0) {
        throw "$Name 失敗（退出碼 $commandExitCode）。"
    }
    Write-Host "✓ $Name"
}

function Invoke-GitCheck {
    param([string[]]$Arguments)

    & $script:GitExecutable @Arguments
    $commandExitCode = $LASTEXITCODE
    if ($commandExitCode -ne 0) {
        throw "Git diff check 失敗（退出碼 $commandExitCode）。"
    }
    Write-Host "✓ git diff --check"
}

try {
    Push-Location $repoRoot
    $locationPushed = $true
    $env:PYTHONUTF8 = "1"

    if (-not $Python) {
        if ($env:PYTHON) {
            $Python = $env:PYTHON
        } elseif (Test-Path ".venv-win\Scripts\python.exe") {
            $Python = (Resolve-Path ".venv-win\Scripts\python.exe").Path
        } elseif (Test-Path ".venv\Scripts\python.exe") {
            $Python = (Resolve-Path ".venv\Scripts\python.exe").Path
        } else {
            $Python = "python"
        }
    }

    $pythonCommand = Get-Command -Name $Python -ErrorAction Stop
    $script:PythonExecutable = if ($pythonCommand.Source) { $pythonCommand.Source } else { $pythonCommand.Path }
    $gitCommand = Get-Command -Name "git" -ErrorAction Stop
    $script:GitExecutable = if ($gitCommand.Source) { $gitCommand.Source } else { $gitCommand.Path }

    Invoke-PythonCheck "Python 3.10+ 版本檢查" @(
        "-c", "import sys; print(sys.version.split()[0]); sys.exit(0 if sys.version_info >= (3, 10) else 1)"
    )
    Invoke-PythonCheck "離線單元與整合測試" @("-m", "unittest", "discover", "-s", "tests", "-v")
    Invoke-PythonCheck "依賴一致性檢查" @("-m", "pip", "check")
    Invoke-PythonCheck "Python 編譯檢查" @("-m", "compileall", "-q", "main.py", "tests")
    Invoke-GitCheck @("-c", "core.autocrlf=true", "diff", "--check")
    Write-Host "所有離線驗證均通過。"
} catch {
    Write-Host "驗證失敗：$($_.Exception.Message)" -ForegroundColor Red
    $exitCode = 1
} finally {
    if ($locationPushed) {
        Pop-Location
    }
    if ($hadPythonUtf8) {
        $env:PYTHONUTF8 = $oldPythonUtf8
    } else {
        Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue
    }
}

if ($exitCode -ne 0) {
    exit $exitCode
}
