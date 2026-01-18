param(
  [string]$EnvPath = ".\.env"
)

$ErrorActionPreference = "Stop"

function Upsert-EnvLine([string[]]$lines, [string]$key, [string]$value) {
  $pattern = "^\s*{0}\s*=" -f [regex]::Escape($key)
  $found = $false
  for ($i=0; $i -lt $lines.Count; $i++) {
    $line = $lines[$i]
    if ($line -match $pattern) {
      $lines[$i] = "$key=$value"
      $found = $true
      break
    }
  }
  if (-not $found) { $lines += "$key=$value" }
  return ,$lines
}

$full = (Resolve-Path $EnvPath).Path
Write-Host "[env] patching: $full" -ForegroundColor Cyan

if (-not (Test-Path $full)) { throw "File not found: $full" }
$lines = Get-Content $full -Encoding UTF8

$bak = "$full.bak"
Copy-Item $full $bak -Force
Write-Host "[env] backup: $bak" -ForegroundColor DarkGray

# --- only upsert these keys; everything else stays as-is ---
$lines = Upsert-EnvLine $lines "FONBET_API_BASE" "https://line01.cy8cff-resources.com"
$lines = Upsert-EnvLine $lines "FONBET_API_BASE_FALLBACKS" "https://line02.cy8cff-resources.com|https://line03.cy8cff-resources.com|https://line04.cy8cff-resources.com"
$lines = Upsert-EnvLine $lines "FONBET_PREMATCH_PROXY" "http://14af56aade08a:60ebda22ec@46.182.207.71:12323"
$lines = Upsert-EnvLine $lines "FONBET_FOOTBALL_SPORT_ID" "1"

Set-Content -Path $full -Value $lines -Encoding UTF8
Write-Host "[env] done. Nothing else was removed." -ForegroundColor Green
