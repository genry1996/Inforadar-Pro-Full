<# 
collect_fonbet_diag.ps1
Снимает диагностику проекта Inforadar (Fonbet prematch UI/API/DB) и собирает всё в ZIP.
Безопасность: пароль MySQL НЕ печатается. Скрипт пытается тихо взять MYSQL_ROOT_PASSWORD из env контейнера mysql_inforadar.
Если не получилось — в отчёте будет пометка, и MySQL-проверки надо выполнить вручную.

Запуск (пример):
  PowerShell (обычный):
    powershell -ExecutionPolicy Bypass -File .\collect_fonbet_diag.ps1 -ProjectRoot "D:\Inforadar_Pro"

  Можно поменять параметры:
    -ApiPort 8010 -Hours 12 -Limit 200 -SportId 1
#>

param(
  [Parameter(Mandatory=$false)][string]$ProjectRoot = "D:\Inforadar_Pro",
  [Parameter(Mandatory=$false)][string]$ApiHost = "localhost",
  [Parameter(Mandatory=$false)][int]$ApiPort = 8010,
  [Parameter(Mandatory=$false)][int]$Hours = 12,
  [Parameter(Mandatory=$false)][int]$Limit = 200,
  [Parameter(Mandatory=$false)][int]$SportId = 1,
  [Parameter(Mandatory=$false)][string[]]$ComposeFiles = @("docker-compose.yml","docker-compose.override.fonbet.yml"),
  [Parameter(Mandatory=$false)][switch]$SkipLogs
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

function New-OutDir {
  param([string]$root)
  $ts = Get-Date -Format "yyyyMMdd_HHmmss"
  $dir = Join-Path $root ("_diag_fonbet_" + $ts)
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  return $dir
}

function Save-Text {
  param([string]$path,[string]$text)
  $text | Out-File -FilePath $path -Encoding utf8
}

function Save-Cmd {
  param([string]$outDir,[string]$name,[string]$cmd)
  $file = Join-Path $outDir ($name + ".txt")
  ("`n>>> " + $cmd + "`n") | Out-File $file -Encoding utf8 -Append
  try {
    $res = (Invoke-Expression $cmd 2>&1 | Out-String)
  } catch {
    $res = ($_ | Out-String)
  }
  $res | Out-File $file -Encoding utf8 -Append
}

function Get-ComposeArgs {
  param([string[]]$files)
  $parts = @()
  foreach($f in $files){
    if([string]::IsNullOrWhiteSpace($f)){ continue }
    $parts += "-f `"$f`""
  }
  return ($parts -join " ")
}

function Try-GetMysqlRootPassword {
  # Пытаемся тихо достать MYSQL_ROOT_PASSWORD из env контейнера mysql_inforadar
  try {
    $envLines = docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' mysql_inforadar 2>$null
    if(-not $envLines){ return $null }
    $pwdLine = ($envLines | Select-String '^MYSQL_ROOT_PASSWORD=' | Select-Object -First 1)
    if(-not $pwdLine){ return $null }
    $val = ($pwdLine.ToString().Split('=',2)[1])
    if([string]::IsNullOrWhiteSpace($val)){ return $null }
    return $val
  } catch {
    return $null
  }
}

# --- Main ---
if(-not (Test-Path $ProjectRoot)){
  Write-Host "ProjectRoot not found: $ProjectRoot"
  exit 1
}

Set-Location $ProjectRoot
$outDir = New-OutDir -root $ProjectRoot

Save-Text (Join-Path $outDir "00_meta.txt") @"
Generated: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
ProjectRoot: $ProjectRoot
Api: http://$ApiHost`:$ApiPort
Params: hours=$Hours limit=$Limit sport_id=$SportId
ComposeFiles: $($ComposeFiles -join ", ")
SkipLogs: $SkipLogs
"@

# Git
Save-Cmd $outDir "01_git" "git rev-parse --abbrev-ref HEAD; git rev-parse --short HEAD; git status -sb"
Save-Cmd $outDir "02_git_last_commits" "git --no-pager log -n 20 --oneline --decorate"
Save-Cmd $outDir "03_git_diff_stat" "git diff --stat"

# Compose config (merged)
$composeArgs = Get-ComposeArgs -files $ComposeFiles
Save-Cmd $outDir "04_compose_config" "docker-compose $composeArgs config"

# Docker status
Save-Cmd $outDir "05_docker_version" "docker version"
Save-Cmd $outDir "06_docker_ps" "docker ps --format `"table {{.Names}}\t{{.Status}}\t{{.Ports}}`""
Save-Cmd $outDir "07_docker_ps_filtered" "docker ps --filter `"name=fonbet`" --filter `"name=inforadar`" --filter `"name=mysql_inforadar`" --format `"table {{.Names}}\t{{.Status}}\t{{.Ports}}`""

# Logs
if(-not $SkipLogs){
  Save-Cmd $outDir "08_logs_fonbet_api" "docker logs fonbet_api --tail 400"
  Save-Cmd $outDir "09_logs_inforadar_ui" "docker logs inforadar_ui --tail 400"
  Save-Cmd $outDir "10_logs_mysql_inforadar" "docker logs mysql_inforadar --tail 200"
}

# API checks (header + body)
$healthUrl = "http://$ApiHost`:$ApiPort/health"
$eventsUrl = "http://$ApiHost`:$ApiPort/fonbet/events?hours=$Hours&limit=$Limit&sport_id=$SportId"
Save-Cmd $outDir "11_curl_health" "curl.exe -s -D - `"$healthUrl`""
Save-Cmd $outDir "12_curl_events" "curl.exe -s -D - `"$eventsUrl`""

# Verify which code is running in container (main.py hash + pwd)
Save-Cmd $outDir "13_container_code_probe" "docker exec fonbet_api sh -lc `"pwd; ls -la; (test -f /app/main.py && echo '--- main.py ---' && ls -la /app/main.py && (sha256sum /app/main.py || sha1sum /app/main.py || md5sum /app/main.py)) || echo 'NO /app/main.py'; python --version 2>&1; pip --version 2>&1`""

# MySQL counts and time window sanity
$mysqlPwd = Try-GetMysqlRootPassword
if($null -ne $mysqlPwd){
  $sql = @"
select count(*) as c from fonbet_events;
select sport_id, count(*) as c from fonbet_events group by sport_id order by c desc limit 20;
select min(start_time) as min_start, max(start_time) as max_start, now() as now_local, utc_timestamp() as now_utc from fonbet_events;
select count(*) as c_next12h
  from fonbet_events
 where start_time between utc_timestamp() and date_add(utc_timestamp(), interval $Hours hour)
   and sport_id = $SportId;
"@
  # ВАЖНО: пароль не выводим. Передаём через MYSQL_PWD.
  $cmd = "docker exec -e MYSQL_PWD=$mysqlPwd mysql_inforadar sh -lc `"mysql -uroot -D inforadar -e `"$($sql.Replace('"','\"'))`"`""
  Save-Cmd $outDir "14_mysql_checks" $cmd
} else {
  Save-Text (Join-Path $outDir "14_mysql_checks.txt") "MYSQL_ROOT_PASSWORD not found in mysql_inforadar env. Run MySQL checks manually."
}

# UI -> API routing quick hint: print env of UI container (без секретов, но может быть много)
Save-Cmd $outDir "15_ui_env_hint" "docker exec inforadar_ui sh -lc `"printenv | sort | sed -n '1,200p'`""

# Pack zip
$zipPath = ($outDir + ".zip")
try {
  if(Test-Path $zipPath){ Remove-Item -Force $zipPath }
  Compress-Archive -Path (Join-Path $outDir "*") -DestinationPath $zipPath -Force | Out-Null
  Write-Host "OK. Diagnostic ZIP created:"
  Write-Host $zipPath
} catch {
  Write-Host "Failed to create ZIP: $($_.Exception.Message)"
  Write-Host "Folder kept: $outDir"
}
