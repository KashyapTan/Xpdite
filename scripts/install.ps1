[CmdletBinding()]
param(
    [string]$Channel = $(if ($env:XPDITE_CHANNEL) { $env:XPDITE_CHANNEL } else { 'latest' }),
    [string]$Version = $env:XPDITE_VERSION,
    [string]$InstallDir = $env:XPDITE_INSTALL_DIR,
    [switch]$Silent,
    [switch]$DryRun,
    [switch]$KeepInstaller
)

$ErrorActionPreference = 'Stop'

$repoOwner = if ($env:XPDITE_REPO_OWNER) { $env:XPDITE_REPO_OWNER } else { 'KashyapTan' }
$repoName = if ($env:XPDITE_REPO_NAME) { $env:XPDITE_REPO_NAME } else { 'Xpdite' }
$userAgent = 'xpdite-install-script'
$releasesUri = if ($env:XPDITE_RELEASES_API) { $env:XPDITE_RELEASES_API } else { "https://api.github.com/repos/$repoOwner/$repoName/releases?per_page=20" }
$effectiveDryRun = $DryRun.IsPresent -or ($env:XPDITE_DRY_RUN -eq '1')
$effectiveKeepInstaller = $KeepInstaller.IsPresent -or ($env:XPDITE_KEEP_DOWNLOAD -eq '1')
$effectiveSilent = $Silent.IsPresent -or ($env:XPDITE_SILENT -eq '1')

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message"
}

function Normalize-RequestedTag {
    param([string]$RequestedVersion)

    if ([string]::IsNullOrWhiteSpace($RequestedVersion)) {
        return $null
    }

    if ($RequestedVersion.StartsWith('v')) {
        return $RequestedVersion
    }

    return "v$RequestedVersion"
}

function Resolve-Release {
    param(
        [string]$RequestedChannel,
        [string]$RequestedVersionTag
    )

    $headers = @{
        Accept = 'application/vnd.github+json'
        'User-Agent' = $userAgent
    }

    if ($env:XPDITE_RELEASES_JSON) {
        $releases = $env:XPDITE_RELEASES_JSON | ConvertFrom-Json
    }
    else {
        $releases = Invoke-RestMethod -Headers $headers -Uri $releasesUri
    }

    foreach ($release in $releases) {
        if ($release.draft) {
            continue
        }

        if ($RequestedVersionTag -and $release.tag_name -ne $RequestedVersionTag) {
            continue
        }

        switch ($RequestedChannel.ToLowerInvariant()) {
            'beta' {
                if (-not $release.prerelease) { continue }
            }
            'stable' {
                if ($release.prerelease) { continue }
            }
            'latest' { }
            'any' { }
            default {
                throw "Unsupported XPDITE_CHANNEL value: $RequestedChannel"
            }
        }

        $asset = $release.assets | Where-Object { $_.name -match '^Xpdite-.*-win-x64\.exe$' } | Select-Object -First 1
        if (-not $asset) {
            continue
        }

        $checksum = $release.assets | Where-Object { $_.name -eq 'SHA256SUMS.txt' } | Select-Object -First 1

        return [pscustomobject]@{
            TagName = $release.tag_name
            AssetName = $asset.name
            AssetUrl = $asset.browser_download_url
            ChecksumUrl = if ($checksum) { $checksum.browser_download_url } else { $null }
        }
    }

    throw "Could not find a matching Xpdite release for channel '$RequestedChannel'."
}

function Get-ExpectedChecksum {
    param(
        [string]$ChecksumsPath,
        [string]$AssetName
    )

    foreach ($line in Get-Content -Path $ChecksumsPath) {
        $parts = $line -split '\s+'
        if ($parts.Count -ge 2 -and $parts[-1] -eq $AssetName) {
            return $parts[0].ToLowerInvariant()
        }
    }

    throw "Could not find checksum entry for $AssetName in SHA256SUMS.txt"
}

function Verify-Checksum {
    param(
        [string]$AssetPath,
        [string]$ChecksumsPath,
        [string]$AssetName
    )

    $expected = Get-ExpectedChecksum -ChecksumsPath $ChecksumsPath -AssetName $AssetName
    $actual = (Get-FileHash -Path $AssetPath -Algorithm SHA256).Hash.ToLowerInvariant()

    if ($actual -ne $expected) {
        throw "Checksum verification failed for $AssetName"
    }
}

$requestedTag = Normalize-RequestedTag -RequestedVersion $Version
$release = Resolve-Release -RequestedChannel $Channel -RequestedVersionTag $requestedTag

Write-Step "Selected release $($release.TagName)"
Write-Step "Installer asset $($release.AssetName)"

if ($effectiveDryRun) {
    Write-Output "tag=$($release.TagName)"
    Write-Output "asset=$($release.AssetName)"
    Write-Output "url=$($release.AssetUrl)"
    Write-Output "checksum=$(if ($release.ChecksumUrl) { $release.ChecksumUrl } else { 'none' })"
    exit 0
}

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("xpdite-install-" + [System.Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $tempRoot -Force
$installerPath = Join-Path $tempRoot $release.AssetName
$checksumsPath = Join-Path $tempRoot 'SHA256SUMS.txt'

try {
    Write-Step 'Downloading installer'
    Invoke-WebRequest -Headers @{ 'User-Agent' = $userAgent } -Uri $release.AssetUrl -OutFile $installerPath

    if ($release.ChecksumUrl) {
        Write-Step 'Downloading release checksums'
        Invoke-WebRequest -Headers @{ 'User-Agent' = $userAgent } -Uri $release.ChecksumUrl -OutFile $checksumsPath
        Write-Step 'Verifying checksum'
        Verify-Checksum -AssetPath $installerPath -ChecksumsPath $checksumsPath -AssetName $release.AssetName
    } else {
        Write-Warning "Release checksums were not published for $($release.TagName); skipping verification."
    }

    $arguments = @()
    if ($effectiveSilent) {
        $arguments += '/S'
    }
    if ($InstallDir) {
        $arguments += "/D=$InstallDir"
    }

    Write-Step 'Launching Windows installer'
    $process = Start-Process -FilePath $installerPath -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "Installer exited with code $($process.ExitCode)"
    }

    if ($effectiveSilent) {
        if ($InstallDir) {
            Write-Step "Installed Xpdite to $InstallDir"
        } else {
            Write-Step 'Installed Xpdite using the default installer location'
        }
    } else {
        Write-Step 'Installer completed'
    }
}
finally {
    if (-not $effectiveKeepInstaller -and (Test-Path -LiteralPath $tempRoot)) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
