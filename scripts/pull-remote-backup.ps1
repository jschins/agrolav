# Remote agrolav backup (DATABASE.md §1.1 + §1.2).
# From Windows:
#
#   powershell -File scripts/pull-remote-backup.ps1
#   powershell -File scripts/pull-remote-backup.ps1 -CopyOnly
#
# Remote keeps no .bak after a successful pull (Enable Banking keys).
# Local file is agrolavYYYYMMDD_HHMM.bak from the backup file time (no seconds).
# -CopyOnly skips BACKUP, pulls the file already on the droplet, then deletes it.

param(
    [switch]$CopyOnly
)

$ErrorActionPreference = "Stop"

$RemoteHost = "209.38.39.105"
$SshPort = 4523
$RemoteUser = "agrolav"
$RemoteDir = "/opt/sql_backups/remote_backups"
$LocalDir = "C:/SQLBackups/remote_backups"
$RemoteWorking = "$RemoteDir/agrolav.bak"
$Target = "${RemoteUser}@${RemoteHost}"

$remoteBash = @'
set -euo pipefail
DIR="/opt/sql_backups/remote_backups"
CONTAINER_PATH="/var/opt/mssql/backup/remote_backups"
FILE="agrolav.bak"

sudo chown 10001:10001 "$DIR"
sudo chmod 775 "$DIR"
# SQL (uid 10001) cannot overwrite a file owned by agrolav (error 5). Always
# give it the file before BACKUP; scp only needs read, not ownership.
if sudo test -f "$DIR/$FILE"; then
  sudo chown 10001:10001 "$DIR/$FILE"
  sudo chmod 660 "$DIR/$FILE"
else
  sudo install -o 10001 -g 10001 -m 660 /dev/null "$DIR/$FILE"
fi

PW=""
for f in /root/sqlserver/.env /opt/agrolav/.env; do
  if sudo test -f "$f"; then
    PW=$(sudo grep '^MSSQL_SA_PASSWORD=' "$f" | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^["'"'"']//;s/["'"'"']$//')
    if [ -n "$PW" ]; then
      break
    fi
  fi
done
if [ -z "$PW" ]; then
  echo "MSSQL_SA_PASSWORD not found in /root/sqlserver/.env or /opt/agrolav/.env" >&2
  exit 1
fi

SQLCMD=/opt/mssql-tools18/bin/sqlcmd
if ! sudo docker exec MSSQL2022 test -x "$SQLCMD"; then
  SQLCMD=/opt/mssql-tools/bin/sqlcmd
fi

sudo docker exec -e SQLCMDPASSWORD="$PW" MSSQL2022 "$SQLCMD" -S localhost -U sa -C -b -Q "
BACKUP DATABASE [agrolav]
TO DISK = N'${CONTAINER_PATH}/${FILE}'
WITH
    INIT,
    COMPRESSION,
    CHECKSUM,
    STATS = 10;
"

# Keep owner 10001 so the next BACKUP works; group-read for scp as agrolav.
sudo chown 10001:agrolav "$DIR/$FILE"
sudo chmod 640 "$DIR/$FILE"
sudo rm -f "$DIR"/agrolav[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_*.bak
sudo ls -lh "$DIR/$FILE"
'@

function Copy-RemoteBak {
    New-Item -ItemType Directory -Force -Path $LocalDir | Out-Null
    $tmp = "$LocalDir/agrolav.bak.partial"
    if (Test-Path $tmp) { Remove-Item -Force $tmp }

    $copied = $false
    foreach ($delay in @(0, 2, 5)) {
        if ($delay -gt 0) {
            Write-Host "scp retry in ${delay}s ..."
            Start-Sleep -Seconds $delay
        }
        & scp -p -P $SshPort "${Target}:${RemoteWorking}" $tmp
        if ($LASTEXITCODE -eq 0 -and (Test-Path $tmp)) {
            $copied = $true
            break
        }
    }
    if (-not $copied) {
        throw "scp failed."
    }

    $item = Get-Item $tmp
    $stamp = $item.LastWriteTime.ToString("yyyyMMdd_HHmm")
    $dest = "$LocalDir/agrolav$stamp.bak"
    Move-Item -Force $tmp $dest
    return $dest
}

function Remove-RemoteBak {
    Write-Host "Removing every .bak on the droplet under $RemoteDir (SSH, then sudo) ..."
    $remoteRm = @'
set -euo pipefail
DIR="/opt/sql_backups/remote_backups"
sudo find "$DIR" -type f \( -name '*.bak' -o -name '*.bak.partial' \) -delete
sudo rm -f /tmp/agrolav.bak /tmp/pull-remote-backup.sh
sudo ls -la "$DIR"
left=$(sudo find "$DIR" -type f -name '*.bak' | wc -l)
if [ "$left" -ne 0 ]; then
  echo "still has .bak files in $DIR" >&2
  sudo find "$DIR" -type f -name '*.bak' -ls >&2
  exit 1
fi
'@
    $b64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($remoteRm))
    & ssh -tt -p $SshPort $Target -- "echo $b64 | base64 -d > /tmp/pull-remote-backup-rm.sh && bash /tmp/pull-remote-backup-rm.sh; status=`$?; rm -f /tmp/pull-remote-backup-rm.sh; exit `$status"
    if ($LASTEXITCODE -ne 0) {
        throw "Copied locally, but a .bak is still on the droplet under $RemoteDir. Remove it with: sudo find $RemoteDir -name '*.bak' -delete"
    }
}

function Finish-Pull {
    $dest = Copy-RemoteBak
    Remove-RemoteBak
    Get-Item $dest | Format-Table Name, Length, LastWriteTime
    Write-Host "Done. Local file: $dest (nothing left on the droplet)"
}

if ($CopyOnly) {
    Write-Host "Copying existing ${RemoteHost}:$RemoteWorking (no BACKUP) ..."
    Write-Host "Enter the SSH password for scp, then SSH and sudo to delete the droplet file."
    Finish-Pull
    return
}

# Windows OpenSSH cannot multiplex (ControlMaster → "Not a socket").
# Backup and scp are separate connections, same as -CopyOnly.
$staleMux = Join-Path $env:TEMP "agrlv-ssh"
if (Test-Path $staleMux) { Remove-Item -Force $staleMux }

Write-Host "Backing up on ${RemoteHost} as agrolav.bak ..."
Write-Host "Enter SSH and sudo for the backup, SSH again for scp, then SSH and sudo to delete the droplet file."
$b64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($remoteBash))
# -tt gives sudo a TTY. Do not pipe the script on stdin (sudo would steal it).
& ssh -tt -p $SshPort $Target -- "echo $b64 | base64 -d > /tmp/pull-remote-backup.sh && bash /tmp/pull-remote-backup.sh; status=`$?; rm -f /tmp/pull-remote-backup.sh; exit `$status"
if ($LASTEXITCODE -ne 0) {
    throw "Remote backup failed (ssh/sqlcmd)."
}

Write-Host "Copying agrolav.bak (SSH password again) ..."
Start-Sleep -Seconds 2
Finish-Pull
