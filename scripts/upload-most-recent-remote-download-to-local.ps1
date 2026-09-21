# Overwrite the local agrolav database with the newest remote backup.
#
# Picks the most recent agrolav*.bak in C:\SQLBackups\remote_backups (the files
# scripts/pull-remote-backup.ps1 leaves there) and restores it over the local
# SQL Server container agrolav-sql (docker-compose.sqlserver.yml, SSMS at
# 127.0.0.1,1433). The container bind-mounts C:\SQLBackups at
# /var/opt/mssql/backup, so the restore reads the file straight from the mount.
#
#   powershell -File scripts/upload-most-recent-remote-download-to-local.ps1
#   powershell -File scripts/upload-most-recent-remote-download-to-local.ps1 -Yes
#
# -Yes skips the confirmation prompt. The sa password is read from the root
# .env (MSSQL_SA_PASSWORD) and handed to sqlcmd through the environment, never
# on a command line. This replaces every local database; stop the hub, BFF and
# balance apps first so their connections are not killed mid-request.

param(
    [switch]$Yes
)

$ErrorActionPreference = "Stop"

$Container = "agrolav-sql"
$Database = "agrolav"
$BackupDir = "C:/SQLBackups/remote_backups"
$DataDir = "/var/opt/mssql/data"

function Read-EnvValue([string]$path, [string]$key) {
    if (-not (Test-Path -LiteralPath $path)) { return "" }
    foreach ($line in Get-Content -LiteralPath $path) {
        $trimmed = $line.Trim()
        if ($trimmed -match "^\s*#") { continue }
        if ($trimmed -match "^\s*$([regex]::Escape($key))\s*=\s*(.*)$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return ""
}

# --- Newest backup -----------------------------------------------------------

if (-not (Test-Path -LiteralPath $BackupDir)) {
    throw "Backup directory not found: $BackupDir. Run scripts/pull-remote-backup.ps1 first."
}
$newest = Get-ChildItem -LiteralPath $BackupDir -File -Filter "agrolav*.bak" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $newest) {
    throw "No agrolav*.bak in $BackupDir. Run scripts/pull-remote-backup.ps1 first."
}
$containerFile = "/var/opt/mssql/backup/remote_backups/$($newest.Name)"
$sizeMb = [Math]::Round($newest.Length / 1MB, 1)
Write-Host "Newest backup: $($newest.FullName) ($sizeMb MB, $($newest.LastWriteTime))"

# --- sa password from the root .env -----------------------------------------

$root = Split-Path -Parent $PSScriptRoot
$password = Read-EnvValue (Join-Path $root ".env") "MSSQL_SA_PASSWORD"
if (-not $password) {
    throw "MSSQL_SA_PASSWORD not found in $root\.env"
}

# --- Container ---------------------------------------------------------------

$running = docker inspect -f "{{.State.Running}}" $Container 2>$null
if ($LASTEXITCODE -ne 0 -or "$running".Trim() -ne "true") {
    throw "Container $Container is not running. Start it with docker compose -f docker-compose.sqlserver.yml up -d."
}

$sqlcmd = "/opt/mssql-tools18/bin/sqlcmd"
docker exec $Container test -x $sqlcmd 2>$null
if ($LASTEXITCODE -ne 0) { $sqlcmd = "/opt/mssql-tools/bin/sqlcmd" }

function Invoke-Sql([string]$sql) {
    # SQLCMDPASSWORD is set inside the container only; -b makes sqlcmd exit
    # non-zero on any error so the script stops instead of half-restoring.
    $out = docker exec -e "SQLCMDPASSWORD=$password" $Container `
        $sqlcmd -S localhost -U sa -C -b -W -Q $sql 2>&1 | ForEach-Object { "$_" }
    $out | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) {
        throw "sqlcmd failed (exit $LASTEXITCODE)."
    }
    return $out
}

# --- Logical file names, so the restore lands in the container's data dir ---

$fileList = Invoke-Sql "RESTORE FILELISTONLY FROM DISK = N'$containerFile';"
$moves = @()
foreach ($line in $fileList) {
    $parts = @($line -split "\s+" | Where-Object { $_ -ne "" })
    if ($parts.Count -lt 3) { continue }
    $logical = $parts[0]
    $type = $parts[2]
    if ($logical -notmatch "^[A-Za-z0-9_]+$") { continue }
    if ($type -eq "D") { $moves += "MOVE N'$logical' TO N'$DataDir/$logical.mdf'" }
    elseif ($type -eq "L") { $moves += "MOVE N'$logical' TO N'$DataDir/${logical}_log.ldf'" }
}
if (-not $moves) {
    throw "RESTORE FILELISTONLY returned no data or log files for $containerFile."
}
Write-Host "Restoring with: $($moves -join ', ')"

if (-not $Yes) {
    $answer = Read-Host "This REPLACES the local database '$Database' in $Container. Type YES to continue"
    if ($answer -ne "YES") {
        Write-Host "Aborted. Nothing was changed."
        return
    }
}

# --- Restore ----------------------------------------------------------------

Invoke-Sql @"
USE master;
ALTER DATABASE [$Database] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
RESTORE DATABASE [$Database]
FROM DISK = N'$containerFile'
WITH REPLACE, RECOVERY, $($moves -join ', ');
ALTER DATABASE [$Database] SET MULTI_USER;
"@

$check = Invoke-Sql "SELECT name FROM sys.databases WHERE name = N'$Database';"
if (-not ($check -match [regex]::Escape($Database))) {
    throw "Restore finished but database '$Database' is not online."
}
Write-Host "Done. Local database '$Database' now holds $($newest.Name)."
