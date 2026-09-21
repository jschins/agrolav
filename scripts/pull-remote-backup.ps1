# Remote agrolav backup (DATABASE.md §1.1 + §1.2).
# From Windows:
#
#   powershell -File scripts/pull-remote-backup.ps1
#   powershell -File scripts/pull-remote-backup.ps1 -CopyOnly
#
# Remote keeps no .bak after a successful pull (Enable Banking keys).
# Local file is agrolavYYYYMMDD_HHMM.bak from the backup file time (no seconds).
# -CopyOnly skips BACKUP, pulls the file already on the droplet, then deletes it.
#
# The password is asked once. It reaches ssh/scp through an SSH_ASKPASS helper
# (OpenSSH >= 8.4; the helper reads it from the environment, nothing is written
# to disk) and reaches sudo on the droplet through stdin (`sudo -S`). Every
# ssh/scp step is retried up to $MaxAttempts times; after a "Permission denied"
# you may retype the password before the next attempt.

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
$MaxAttempts = 5
$RetryDelays = @(2, 4, 6, 8)

# Common ssh/scp options: password auth only, one password try per connection
# (a wrong password then fails fast instead of asking the helper three times).
$SshOpts = @(
    "-p", "$SshPort",
    "-o", "PreferredAuthentications=password",
    "-o", "PubkeyAuthentication=no",
    "-o", "NumberOfPasswordPrompts=1",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectTimeout=20"
)
$ScpOpts = @("-p", "-P", "$SshPort") + $SshOpts[2..($SshOpts.Length - 1)]

# --- Remote scripts -----------------------------------------------------------
# Each script reads the sudo password from its stdin (first line) and routes
# every `sudo` through `sudo -S`, so no TTY is needed and nothing is echoed.
$remoteSudoPrelude = @'
set -euo pipefail
IFS= read -r SUDO_PW
sudo() { printf '%s\n' "$SUDO_PW" | command sudo -S -p '' "$@"; }
sudo true
'@

$remoteBackup = $remoteSudoPrelude + "`n" + @'
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

$remoteRemove = $remoteSudoPrelude + "`n" + @'
DIR="/opt/sql_backups/remote_backups"
sudo find "$DIR" -type f \( -name '*.bak' -o -name '*.bak.partial' \) -delete
sudo rm -f /tmp/agrolav.bak /tmp/pull-remote-backup.sh /tmp/pull-remote-backup-rm.sh
sudo ls -la "$DIR"
left=$(sudo find "$DIR" -type f -name '*.bak' | wc -l)
if [ "$left" -ne 0 ]; then
  echo "still has .bak files in $DIR" >&2
  sudo find "$DIR" -type f -name '*.bak' -ls >&2
  exit 1
fi
'@

# --- Password, asked once -----------------------------------------------------

function Read-Password([string]$prompt) {
    $secure = Read-Host -AsSecureString $prompt
    return [System.Net.NetworkCredential]::new("", $secure).Password
}

# ssh/scp get the password from this helper; the helper prints the AGRLV_PW
# environment variable (inherited from this process), so the password itself
# is never written to a file. `cmd` echo would choke on & | < > characters, so
# the helper prints through PowerShell.
$askpass = Join-Path $env:TEMP ("agrolav-askpass-" + [guid]::NewGuid().ToString("N") + ".cmd")
Set-Content -LiteralPath $askpass -Encoding ASCII -Value @'
@echo off
powershell -NoProfile -NonInteractive -Command "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); [Console]::Out.WriteLine($env:AGRLV_PW)"
'@
$env:SSH_ASKPASS = $askpass
$env:SSH_ASKPASS_REQUIRE = "force"
$setDisplay = -not $env:DISPLAY
if ($setDisplay) { $env:DISPLAY = "agrolav:0" }

function Set-Password([string]$plain) {
    $env:AGRLV_PW = $plain
}

# --- Retry wrapper ------------------------------------------------------------

function Invoke-Remote {
    # $step: label; $run: script block that runs one ssh/scp attempt and
    # returns $true on success. Output of the attempt is shown live; the caller
    # passes the text in $script:LastRemoteOutput for the denied check.
    param([string]$step, [scriptblock]$run)
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        $script:LastRemoteOutput = ""
        $ok = & $run
        if ($ok -is [array]) { $ok = $ok[-1] }
        if ($ok -eq $true) { return }
        $denied = $script:LastRemoteOutput -match "Permission denied|incorrect password|Sorry, try again"
        if ($attempt -eq $MaxAttempts) {
            throw "$step failed after $MaxAttempts attempts."
        }
        $delay = $RetryDelays[[Math]::Min($attempt - 1, $RetryDelays.Length - 1)]
        if ($denied) {
            Write-Host "$step : permission denied (attempt $attempt of $MaxAttempts)."
            $again = Read-Password "Retype the password, or press Enter to retry with the same one"
            if ($again) { Set-Password $again }
        } else {
            Write-Host "$step : failed (attempt $attempt of $MaxAttempts), retry in ${delay}s ..."
        }
        Start-Sleep -Seconds $delay
    }
}

function Invoke-SshScript {
    # Runs $bash on the droplet; the password goes in on stdin for sudo -S.
    param([string]$step, [string]$bash, [string]$remoteFile)
    $b64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($bash))
    $cmd = "echo $b64 | base64 -d > $remoteFile && bash $remoteFile; status=`$?; rm -f $remoteFile; exit `$status"
    Invoke-Remote $step {
        $prev = $OutputEncoding
        try {
            $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
            $out = $env:AGRLV_PW | & ssh @SshOpts $Target -- $cmd 2>&1 | ForEach-Object { "$_" }
        } finally {
            $OutputEncoding = $prev
        }
        $out | ForEach-Object { Write-Host $_ }
        $script:LastRemoteOutput = ($out -join "`n")
        return ($LASTEXITCODE -eq 0)
    }
}

# --- Steps --------------------------------------------------------------------

function Copy-RemoteBak {
    New-Item -ItemType Directory -Force -Path $LocalDir | Out-Null
    $tmp = "$LocalDir/agrolav.bak.partial"
    Invoke-Remote "scp" {
        if (Test-Path $tmp) { Remove-Item -Force $tmp }
        $out = & scp @ScpOpts "${Target}:${RemoteWorking}" $tmp 2>&1 | ForEach-Object { "$_" }
        $out | ForEach-Object { Write-Host $_ }
        $script:LastRemoteOutput = ($out -join "`n")
        return ($LASTEXITCODE -eq 0 -and (Test-Path $tmp))
    }
    $item = Get-Item $tmp
    $stamp = $item.LastWriteTime.ToString("yyyyMMdd_HHmm")
    $dest = "$LocalDir/agrolav$stamp.bak"
    Move-Item -Force $tmp $dest
    return $dest
}

function Remove-RemoteBak {
    Write-Host "Removing every .bak on the droplet under $RemoteDir ..."
    try {
        Invoke-SshScript "remote cleanup" $remoteRemove "/tmp/pull-remote-backup-rm.sh"
    } catch {
        throw "Copied locally, but a .bak is still on the droplet under $RemoteDir. Remove it with: sudo find $RemoteDir -name '*.bak' -delete"
    }
}

function Finish-Pull {
    $dest = Copy-RemoteBak
    Remove-RemoteBak
    Get-Item $dest | Format-Table Name, Length, LastWriteTime
    Write-Host "Done. Local file: $dest (nothing left on the droplet)"
}

try {
    Set-Password (Read-Password "Password for $Target (SSH and sudo, asked once)")

    if ($CopyOnly) {
        Write-Host "Copying existing ${RemoteHost}:$RemoteWorking (no BACKUP) ..."
        Finish-Pull
    } else {
        # Windows OpenSSH cannot multiplex (ControlMaster -> "Not a socket").
        $staleMux = Join-Path $env:TEMP "agrlv-ssh"
        if (Test-Path $staleMux) { Remove-Item -Force $staleMux }

        Write-Host "Backing up on ${RemoteHost} as agrolav.bak ..."
        Invoke-SshScript "remote backup" $remoteBackup "/tmp/pull-remote-backup.sh"

        Write-Host "Copying agrolav.bak ..."
        Start-Sleep -Seconds 2
        Finish-Pull
    }
} finally {
    Remove-Item Env:AGRLV_PW -ErrorAction SilentlyContinue
    Remove-Item Env:SSH_ASKPASS, Env:SSH_ASKPASS_REQUIRE -ErrorAction SilentlyContinue
    if ($setDisplay) { Remove-Item Env:DISPLAY -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $askpass -Force -ErrorAction SilentlyContinue
}
