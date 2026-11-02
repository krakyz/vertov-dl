param([string]$Destination = (Join-Path $PSScriptRoot '..\.tools\downloads'))
$ErrorActionPreference = 'Stop'
$Destination = [IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
$log = Join-Path $Destination 'download.log'
$manifest = Join-Path $Destination 'manifest.json'
$records = [System.Collections.Generic.List[object]]::new()
$headers = @{ 'User-Agent' = 'vertov-dl-bootstrap'; 'Accept' = 'application/vnd.github+json' }
function Write-Status([string]$Message) {
    Add-Content -LiteralPath $log -Value "[$([DateTime]::UtcNow.ToString('o'))] $Message" -Encoding utf8
}
function Save-Download([string]$Name, [string]$Uri, [string]$Version) {
    $target = Join-Path $Destination $Name
    $partial = "$target.partial"
    Write-Status "Downloading $Name ($Version)"
    Invoke-WebRequest -Uri $Uri -OutFile $partial -TimeoutSec 1800 -MaximumRetryCount 2
    Move-Item -LiteralPath $partial -Destination $target -Force
    $hash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
    $records.Add([pscustomobject]@{ file = $Name; url = $Uri; version = $Version; sha256 = $hash; verifiedAgainstPublisher = $false })
    $records | ConvertTo-Json -Depth 4 -AsArray | Set-Content -LiteralPath $manifest -Encoding utf8
    Write-Status "Saved $Name SHA256=$hash (local fingerprint; publisher verification pending)"
}
$failed = 0
$tasks = @(
    @{ repo = 'yt-dlp/yt-dlp'; pattern = '^yt-dlp\.exe$'; name = 'yt-dlp.exe' },
    @{ repo = 'denoland/deno'; pattern = '^deno-x86_64-pc-windows-msvc\.zip$'; name = 'deno-windows-x64.zip' },
    @{ repo = 'BtbN/FFmpeg-Builds'; pattern = '^ffmpeg-master-latest-win64-gpl\.zip$'; name = 'ffmpeg-windows-x64.zip' }
)
foreach ($task in $tasks) {
    try {
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$($task.repo)/releases/latest" -Headers $headers
        $asset = @($release.assets | Where-Object { $_.name -match $task.pattern })
        if ($asset.Count -ne 1) { throw "Expected one asset matching $($task.pattern), found $($asset.Count)" }
        Save-Download $task.name $asset[0].browser_download_url $release.tag_name
    } catch { $failed++; Write-Status "FAILED $($task.repo): $($_.Exception.Message)" }
}
foreach ($installer in @(
    @{ name = 'rustup-init.exe'; url = 'https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe' },
    @{ name = 'vs_BuildTools.exe'; url = 'https://aka.ms/vs/17/release/vs_BuildTools.exe' }
)) {
    try { Save-Download $installer.name $installer.url 'bootstrapper' }
    catch { $failed++; Write-Status "FAILED $($installer.name): $($_.Exception.Message)" }
}
Write-Status "Finished. Failures=$failed. Installers were NOT executed. Archives were NOT extracted."
if ($failed -gt 0) { exit 1 }
