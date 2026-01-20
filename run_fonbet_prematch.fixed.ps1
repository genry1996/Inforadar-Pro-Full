# Always bypass proxies for local services
if (-not $env:NO_PROXY -or $env:NO_PROXY -notmatch 'localhost') {
  $env:NO_PROXY = 'localhost,127.0.0.1'
}

param(
  [string]$EnvPath = ".\.env",
  [int]$Interval = 10,
  [int]$Hours = 12,
  [switch]$TestProxy,
  [string]$ScriptPath = ".\parsers\fonbet\prematch_fonbet.py"
)

function Load-DotEnv {
  param([string]$Path)

  if (-not (Test-Path -LiteralPath $Path)) {
    throw "Env file not found: $Path"
  }

  $lines = Get-Content -LiteralPath $Path
  foreach ($line in $lines) {
    $l = ""
    if ($null -ne $line) { $l = $line.Trim() }

    if ($l.Length -eq 0) { continue }
    if ($l.StartsWith("#")) { continue }

    $eq = $l.IndexOf("=")
    if ($eq -lt 1) { continue }

    $k = $l.Substring(0, $eq).Trim()
    $v = $l.Substring($eq + 1).Trim()

    if ($v.StartsWith('"') -and $v.EndsWith('"') -and $v.Length -ge 2) {
      $v = $v.Substring(1, $v.Length - 2)
    } elseif ($v.StartsWith("'") -and $v.EndsWith("'") -and $v.Length -ge 2) {
      $v = $v.Substring(1, $v.Length - 2)
    }

    [Environment]::SetEnvironmentVariable($k, $v, "Process")
  }
}

function Clear-ProxyEnv {
  Remove-Item Env:HTTP_PROXY  -ErrorAction SilentlyContinue
  Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue
  Remove-Item Env:ALL_PROXY   -ErrorAction SilentlyContinue
  Remove-Item Env:NO_PROXY    -ErrorAction SilentlyContinue
}

function Test-Proxy {
  $p = $env:HTTP_PROXY
  if ([string]::IsNullOrWhiteSpace($p)) {
    Write-Host "[proxy] HTTP_PROXY is empty, skip test"
    return
  }

  Write-Host "[proxy] testing via ipify..."
  python -c "import os,requests; p=os.getenv('HTTP_PROXY','').strip(); r=requests.get('https://api.ipify.org?format=json', proxies={'http':p,'https':p}, timeout=20); print('ipify', r.status_code, r.text)"
}

function Run-Once {
  if (-not (Test-Path -LiteralPath $ScriptPath)) {
    throw "Script not found: $ScriptPath"
  }

  $args = @()
  if ($Hours -gt 0) { $args += @("--hours", "$Hours") }

  Write-Host "[run] python $ScriptPath $($args -join ' ')"
  & python $ScriptPath @args
  if ($LASTEXITCODE -ne 0) {
    throw "prematch script failed with exit code $LASTEXITCODE"
  }
}

# ---- main ----
Load-DotEnv -Path $EnvPath

# Save old proxy env (important: might be empty)
$hadHttp  = Test-Path Env:HTTP_PROXY
$hadHttps = Test-Path Env:HTTPS_PROXY
$oldHttp  = $env:HTTP_PROXY
$oldHttps = $env:HTTPS_PROXY

# Clear proxy for clean run (avoid 407 / broken urls)
Clear-ProxyEnv

# Apply prematch proxy only for this script run
if (-not [string]::IsNullOrWhiteSpace($env:FONBET_PREMATCH_PROXY)) {
  $env:HTTP_PROXY  = $env:FONBET_PREMATCH_PROXY
  $env:HTTPS_PROXY = $env:FONBET_PREMATCH_PROXY
  Write-Host "[proxy] using FONBET_PREMATCH_PROXY"
} else {
  Write-Host "[proxy] FONBET_PREMATCH_PROXY not set"
}

if ($TestProxy) { Test-Proxy }

while ($true) {
  try { Run-Once } catch { Write-Host "[error] $($_.Exception.Message)" }
  if ($Interval -le 0) { break }
  Start-Sleep -Seconds $Interval
}

# Restore proxy env exactly as it was BEFORE запуск
Clear-ProxyEnv
if ($hadHttp)  { $env:HTTP_PROXY  = $oldHttp }
if ($hadHttps) { $env:HTTPS_PROXY = $oldHttps }
