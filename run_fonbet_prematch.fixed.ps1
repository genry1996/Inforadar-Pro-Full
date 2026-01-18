param(
  [string]$EnvPath = ".\.env",
  [int]$Interval = 10,
  [int]$Hours = 12
)

$ErrorActionPreference = "Stop"

$ROOT = Split-Path -Parent $PSCommandPath
if (-not $ROOT) { $ROOT = (Get-Location).Path }
Set-Location $ROOT

# clear inherited proxy vars (avoid случайный системный прокси)
$proxyVars = @(
  "HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","NO_PROXY",
  "http_proxy","https_proxy","all_proxy","no_proxy"
)
foreach ($v in $proxyVars) { Remove-Item ("Env:{0}" -f $v) -ErrorAction SilentlyContinue }

# load .env
$envFile = (Resolve-Path $EnvPath).Path
Write-Host "[env] loading: $envFile" -ForegroundColor Cyan

Get-Content $envFile | ForEach-Object {
  $line = $_.Trim()
  if (-not $line) { return }
  if ($line.StartsWith("#")) { return }

  if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
    $k = $Matches[1]
    $v = $Matches[2].Trim()
    if (($v.StartsWith('"') -and $v.EndsWith('"')) -or ($v.StartsWith("'") -and $v.EndsWith("'"))) {
      $v = $v.Substring(1, $v.Length - 2)
    }
    Set-Item -Path ("Env:{0}" -f $k) -Value $v
  }
}

# force prematch proxy for this process
if ($env:FONBET_PREMATCH_PROXY) {
  $env:HTTP_PROXY  = $env:FONBET_PREMATCH_PROXY
  $env:HTTPS_PROXY = $env:FONBET_PREMATCH_PROXY
}

Write-Host "[env] FONBET_API_BASE=$env:FONBET_API_BASE" -ForegroundColor DarkGray
Write-Host "[env] FONBET_PREMATCH_PROXY=$env:FONBET_PREMATCH_PROXY" -ForegroundColor DarkGray

# quick proxy smoke test (ipify)
if ($env:FONBET_PREMATCH_PROXY) {
  Write-Host "[proxy] test ipify через прокси..." -ForegroundColor DarkGray
  & (Join-Path $ROOT ".\.venv_fonbet\Scripts\python.exe") -c "import os,requests; p=os.getenv('FONBET_PREMATCH_PROXY'); r=requests.get('https://api.ipify.org?format=json', proxies={'http':p,'https':p}, timeout=20); print(r.status_code, r.text)" | Write-Host
}

$py = Join-Path $ROOT ".\.venv_fonbet\Scripts\python.exe"
$script = Join-Path $ROOT ".\parsers\fonbet\prematch_fonbet.py"

Write-Host "`nRUN: $py $script --interval $Interval --hours $Hours`n" -ForegroundColor Green
& $py $script --interval $Interval --hours $Hours
