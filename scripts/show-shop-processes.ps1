# Show the running deboog services (shop / admin / remind) as a process tree.
#
#   powershell -File scripts/show-shop-processes.ps1
#   powershell -File scripts/show-shop-processes.ps1 -Service shop
#
# A console script such as shop.exe is only a launcher: it spawns the venv's
# python.exe, which in turn spawns the base interpreter. All three show up as
# "python.exe", so a process is attributed to a service by walking up to the
# nearest ancestor whose executable is shop.exe / admin.exe / remind.exe.
# Listening ports come from Get-NetTCPConnection.

param(
    [string[]]$Service = @("shop", "admin", "remind")
)

$ErrorActionPreference = "Stop"

$procs = Get-CimInstance Win32_Process |
    Select-Object ProcessId, ParentProcessId, Name, ExecutablePath, CommandLine

$byId = @{}
foreach ($p in $procs) { $byId[[int]$p.ProcessId] = $p }

$children = @{}
foreach ($p in $procs) {
    $parent = [int]$p.ParentProcessId
    if (-not $children.ContainsKey($parent)) {
        $children[$parent] = New-Object System.Collections.ArrayList
    }
    [void]$children[$parent].Add([int]$p.ProcessId)
}

$listening = @{}
foreach ($conn in (Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue)) {
    $owner = [int]$conn.OwningProcess
    if (-not $listening.ContainsKey($owner)) {
        $listening[$owner] = New-Object System.Collections.ArrayList
    }
    $port = [int]$conn.LocalPort
    if (-not $listening[$owner].Contains($port)) { [void]$listening[$owner].Add($port) }
}

# A launcher is recognised by the executable it was started from, never by text
# in a command line (a shell that merely mentions shop.exe must not qualify).
$anchor = @{}
foreach ($p in $procs) {
    $leaf = if ($p.ExecutablePath) { Split-Path $p.ExecutablePath -Leaf } else { "" }
    foreach ($name in $Service) {
        if ($leaf -ieq "$name.exe") { $anchor[[int]$p.ProcessId] = $name; break }
    }
}

function Write-Node {
    param([int]$ProcId, [int]$Depth)
    $p = $byId[$ProcId]
    $exe = if ($p.ExecutablePath) { $p.ExecutablePath } else { $p.Name }
    $leaf = Split-Path $exe -Leaf
    $role = if ($anchor.ContainsKey($ProcId)) { "launcher" }
            elseif ($leaf -match "(?i)^pythonw?\.exe$") {
                if ($exe -match "(?i)\\\.venv\\Scripts\\") { "venv python" } else { "base python" }
            }
            else { "" }
    $ports = if ($listening.ContainsKey($ProcId)) { "  listening :" + ($listening[$ProcId] -join ", :") } else { "" }
    $role = if ($role) { "  [$role]" } else { "" }
    $pad = "  " * $Depth
    Write-Host ("{0}- {1}  pid {2}{3}{4}" -f $pad, $leaf, $ProcId, $role, $ports)
    foreach ($child in $children[$ProcId]) { Write-Node -ProcId $child -Depth ($Depth + 1) }
}

$roots = foreach ($p in $procs) {
    $procId = [int]$p.ProcessId
    if (-not $anchor.ContainsKey($procId)) { continue }
    if ($anchor.ContainsKey([int]$p.ParentProcessId)) { continue }  # nested in another service
    [pscustomobject]@{ Service = $anchor[$procId]; ProcId = $procId }
}

if (-not $roots) {
    Write-Host "No running shop/admin/remind process found."
    return
}

foreach ($root in ($roots | Sort-Object Service, ProcId)) {
    Write-Host ""
    Write-Host "$($root.Service)" -ForegroundColor Cyan
    Write-Node -ProcId $root.ProcId -Depth 1
}
