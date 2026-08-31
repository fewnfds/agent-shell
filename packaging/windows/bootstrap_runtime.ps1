[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Assert-ChildPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Parent
    )
    $fullPath = Get-FullPath $Path
    $fullParent = (Get-FullPath $Parent).TrimEnd("\") + "\"
    if (-not $fullPath.StartsWith($fullParent, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify a path outside the project runtime directory."
    }
    return $fullPath
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [int]$MaxAttempts = 1
    )
    Push-Location $WorkingDirectory
    try {
        for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
            & $FilePath @Arguments
            $exitCode = $LASTEXITCODE
            if ($exitCode -eq 0) {
                return
            }
            if ($attempt -eq $MaxAttempts) {
                throw "Command failed with exit code ${exitCode}: $FilePath"
            }
            Write-Warning "Command failed with exit code ${exitCode}; retrying attempt $($attempt + 1) of $MaxAttempts."
            Start-Sleep -Milliseconds 500
        }
    }
    finally {
        Pop-Location
    }
}

function Test-IsRetryableFileSystemException {
    param([Parameter(Mandatory = $true)][System.Exception]$Exception)
    $current = $Exception
    while ($null -ne $current) {
        if (
            $current -is [System.IO.IOException] -or
            $current -is [System.UnauthorizedAccessException]
        ) {
            return $true
        }
        $current = $current.InnerException
    }
    return $false
}

function Move-DirectoryWithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    $maxAttempts = 120
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        try {
            [System.IO.Directory]::Move($Source, $Destination)
            return
        }
        catch {
            if (
                -not (Test-IsRetryableFileSystemException $_.Exception) -or
                $attempt -eq $maxAttempts
            ) {
                if ($attempt -eq $maxAttempts) {
                    throw "A runtime directory remained in use for 30 seconds. Close any running Agent Shell or Python process and retry: $Source"
                }
                throw
            }
            if ($attempt -eq 1) {
                Write-Warning "A runtime directory is temporarily in use; waiting up to 30 seconds."
            }
            Start-Sleep -Milliseconds 250
        }
    }
}

function Remove-DirectoryWithRetry {
    param([Parameter(Mandatory = $true)][string]$Path)
    for ($attempt = 1; $attempt -le 80; $attempt++) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            return $true
        }
        catch {
            if (-not (Test-IsRetryableFileSystemException $_.Exception)) {
                throw
            }
            if ($attempt -eq 80) {
                return $false
            }
            Start-Sleep -Milliseconds 250
        }
    }
    return $false
}

function Wait-PortablePythonReady {
    param([Parameter(Mandatory = $true)][string]$PythonExe)
    for ($attempt = 1; $attempt -le 120; $attempt++) {
        & $PythonExe -I -B -c "import _socket, ssl" *> $null
        if ($LASTEXITCODE -eq 0) {
            return
        }
        if ($attempt -eq 120) {
            throw "The portable Python DLLs remained unavailable for 30 seconds."
        }
        Start-Sleep -Milliseconds 250
    }
}

function Copy-ReusablePythonRuntime {
    param(
        [Parameter(Mandatory = $true)][string]$ApplicationRoot,
        [Parameter(Mandatory = $true)][string]$BuildRoot,
        [Parameter(Mandatory = $true)][string]$ExpectedPython
    )
    $manifestPath = Join-Path $ApplicationRoot "runtime-manifest.json"
    $pythonHomeFile = Join-Path $ApplicationRoot "python-home.txt"
    if (
        -not (Test-Path -LiteralPath $manifestPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $pythonHomeFile -PathType Leaf)
    ) {
        return $false
    }

    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $relativePythonHome = (Get-Content -LiteralPath $pythonHomeFile -Raw).Trim()
    }
    catch {
        return $false
    }
    if (
        [string]$manifest.python -ne $ExpectedPython -or
        [string]::IsNullOrWhiteSpace($relativePythonHome)
    ) {
        return $false
    }

    $sourcePythonRoot = Assert-ChildPath (Join-Path $ApplicationRoot "python") $ApplicationRoot
    $sourcePythonHome = Assert-ChildPath (Join-Path $ApplicationRoot $relativePythonHome) $ApplicationRoot
    $sourcePythonExe = Join-Path $sourcePythonHome "python.exe"
    if (
        -not (Test-Path -LiteralPath $sourcePythonRoot -PathType Container) -or
        -not (Test-Path -LiteralPath $sourcePythonExe -PathType Leaf)
    ) {
        return $false
    }

    $destinationPythonRoot = Join-Path $BuildRoot "python"
    Copy-Item -LiteralPath $sourcePythonRoot -Destination $destinationPythonRoot -Recurse -Force
    $destinationPythonHome = Assert-ChildPath (Join-Path $BuildRoot $relativePythonHome) $BuildRoot
    if (-not (Test-Path -LiteralPath (Join-Path $destinationPythonHome "python.exe") -PathType Leaf)) {
        Remove-Item -LiteralPath $destinationPythonRoot -Recurse -Force
        return $false
    }
    Write-Host "Reusing the verified portable Python runtime."
    return $true
}

function Remove-UvPythonInstallArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$InstallRoot,
        [Parameter(Mandatory = $true)][string]$PythonDirectory
    )
    foreach ($entry in Get-ChildItem -LiteralPath $InstallRoot -Force) {
        if ($entry.FullName -eq $PythonDirectory) {
            continue
        }
        if (($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            if ($entry.PSIsContainer) {
                [System.IO.Directory]::Delete($entry.FullName)
            }
            else {
                [System.IO.File]::Delete($entry.FullName)
            }
        }
        elseif ($entry.PSIsContainer) {
            Remove-Item -LiteralPath $entry.FullName -Recurse -Force
        }
        else {
            Remove-Item -LiteralPath $entry.FullName -Force
        }
    }
}

function Get-RuntimeBuildFingerprint {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    $inputPaths = @(
        "server\pyproject.toml",
        "server\uv.lock",
        "packaging\windows\runtime-lock.json",
        "packaging\windows\bootstrap_runtime.ps1"
    )
    $files = foreach ($relativePath in $inputPaths) {
        $fullPath = Join-Path $ProjectRoot $relativePath
        if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
            throw "A portable runtime build input is missing: $relativePath"
        }
        Get-Item -LiteralPath $fullPath
    }
    $entries = foreach ($file in $files) {
        $relativePath = $file.FullName.Substring($ProjectRoot.TrimEnd("\").Length + 1).Replace("\", "/")
        [PSCustomObject]@{
            Path = $relativePath
            Hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    $fingerprintInput = [System.Text.StringBuilder]::new()
    foreach ($entry in ($entries | Sort-Object -Property Path)) {
        [void]$fingerprintInput.Append($entry.Path)
        [void]$fingerprintInput.Append([char]0)
        [void]$fingerprintInput.Append($entry.Hash)
        [void]$fingerprintInput.Append("`n")
    }
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($fingerprintInput.ToString())
        return ([System.BitConverter]::ToString($sha256.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
    }
}

$project = Get-FullPath $ProjectRoot
$serverRoot = Join-Path $project "server"
$lockPath = Join-Path $project "packaging\windows\runtime-lock.json"
if (-not (Test-Path -LiteralPath (Join-Path $serverRoot "pyproject.toml") -PathType Leaf)) {
    throw "ProjectRoot does not contain server\pyproject.toml."
}
if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
    throw "The Windows runtime lock file is missing."
}

$runtimeRoot = Join-Path $project "runtime"
$bootstrapRoot = Assert-ChildPath (Join-Path $runtimeRoot "bootstrap") $runtimeRoot
$cacheRoot = Assert-ChildPath (Join-Path $runtimeRoot "cache\uv") $runtimeRoot
$temporaryRoot = Assert-ChildPath (Join-Path $runtimeRoot "tmp") $runtimeRoot
$applicationRoot = Assert-ChildPath (Join-Path $runtimeRoot "app") $runtimeRoot
$pythonHomeFile = Join-Path $applicationRoot "python-home.txt"
$lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
if ($lock.schema -ne 1 -or $lock.platform -ne "windows-x64") {
    throw "Unsupported Windows runtime lock schema or platform."
}
$buildFingerprint = Get-RuntimeBuildFingerprint $project

if (-not $Force -and (Test-Path -LiteralPath $pythonHomeFile -PathType Leaf)) {
    $relativePythonHome = (Get-Content -LiteralPath $pythonHomeFile -Raw).Trim()
    $existingPython = Join-Path (Join-Path $applicationRoot $relativePythonHome) "python.exe"
    $runtimeManifestPath = Join-Path $applicationRoot "runtime-manifest.json"
    if (
        (Test-Path -LiteralPath $existingPython -PathType Leaf) -and
        (Test-Path -LiteralPath $runtimeManifestPath -PathType Leaf)
    ) {
        $installedRuntime = Get-Content -LiteralPath $runtimeManifestPath -Raw | ConvertFrom-Json
        $installedFingerprint = $installedRuntime.PSObject.Properties["build_fingerprint"]
        if (
            $installedRuntime.schema -eq 1 -and
            $installedRuntime.platform -eq $lock.platform -and
            $installedRuntime.python -eq $lock.python -and
            $installedRuntime.uv -eq $lock.uv.version -and
            $null -ne $installedFingerprint -and
            $installedFingerprint.Value -eq $buildFingerprint
        ) {
            Write-Host "Agent Shell portable runtime is already prepared."
            exit 0
        }
    }
}

New-Item -ItemType Directory -Force -Path $bootstrapRoot, $cacheRoot, $temporaryRoot | Out-Null

$uvExe = Join-Path $bootstrapRoot "uv.exe"
$uvVersionFile = Join-Path $bootstrapRoot "uv-version.txt"
$expectedUvVersion = [string]$lock.uv.version
$installedUvVersion = if (Test-Path -LiteralPath $uvVersionFile) {
    (Get-Content -LiteralPath $uvVersionFile -Raw).Trim()
} else {
    ""
}
if (-not (Test-Path -LiteralPath $uvExe -PathType Leaf) -or $installedUvVersion -ne $expectedUvVersion) {
    $uvArchive = Assert-ChildPath (Join-Path $temporaryRoot "uv-$expectedUvVersion.zip") $runtimeRoot
    $uvExtract = Assert-ChildPath (Join-Path $temporaryRoot "uv-$expectedUvVersion") $runtimeRoot
    if (Test-Path -LiteralPath $uvArchive) {
        Remove-Item -LiteralPath $uvArchive -Force
    }
    if (Test-Path -LiteralPath $uvExtract) {
        Remove-Item -LiteralPath $uvExtract -Recurse -Force
    }
    Write-Host "Downloading the pinned Agent Shell bootstrap runtime..."
    Invoke-WebRequest -UseBasicParsing -Uri ([string]$lock.uv.url) -OutFile $uvArchive
    $actualHash = (Get-FileHash -LiteralPath $uvArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne ([string]$lock.uv.sha256).ToLowerInvariant()) {
        Remove-Item -LiteralPath $uvArchive -Force
        throw "The downloaded uv archive failed SHA-256 verification."
    }
    Expand-Archive -LiteralPath $uvArchive -DestinationPath $uvExtract -Force
    $downloadedUv = Get-ChildItem -LiteralPath $uvExtract -Filter "uv.exe" -File -Recurse |
        Select-Object -First 1
    if ($null -eq $downloadedUv) {
        throw "The verified uv archive did not contain uv.exe."
    }
    Copy-Item -LiteralPath $downloadedUv.FullName -Destination $uvExe -Force
    Set-Content -LiteralPath $uvVersionFile -Value $expectedUvVersion -Encoding ascii
    Remove-Item -LiteralPath $uvArchive -Force
    Remove-Item -LiteralPath $uvExtract -Recurse -Force
}

$buildRoot = Assert-ChildPath (Join-Path $temporaryRoot "app-build-$PID") $runtimeRoot
$installTarget = Assert-ChildPath (Join-Path $temporaryRoot "site-packages-$PID") $runtimeRoot
if (Test-Path -LiteralPath $buildRoot) {
    Remove-Item -LiteralPath $buildRoot -Recurse -Force
}
if (Test-Path -LiteralPath $installTarget) {
    Remove-Item -LiteralPath $installTarget -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null
New-Item -ItemType Directory -Force -Path $installTarget | Out-Null

$previousEnvironment = @{}
$runtimeEnvironment = @{
    "PYTHONHOME" = $null
    "PYTHONPATH" = $null
    "PYTHONNOUSERSITE" = "1"
    "UV_CACHE_DIR" = $cacheRoot
    "UV_MANAGED_PYTHON" = "1"
    "UV_PYTHON_INSTALL_BIN" = "0"
    "UV_PYTHON_INSTALL_DIR" = (Join-Path $buildRoot "python")
    "UV_PYTHON_INSTALL_REGISTRY" = "0"
}
foreach ($name in $runtimeEnvironment.Keys) {
    $previousEnvironment[$name] = [System.Environment]::GetEnvironmentVariable($name, "Process")
    [System.Environment]::SetEnvironmentVariable($name, $runtimeEnvironment[$name], "Process")
}

$completed = $false
try {
    $pythonInstallRoot = Join-Path $buildRoot "python"
    $reusedPython = Copy-ReusablePythonRuntime `
        -ApplicationRoot $applicationRoot `
        -BuildRoot $buildRoot `
        -ExpectedPython ([string]$lock.python)
    if (-not $reusedPython) {
        Invoke-Native $uvExe @(
            "python", "install", ([string]$lock.python),
            "--install-dir", $pythonInstallRoot,
            "--no-bin", "--no-registry", "--managed-python"
        ) $project
    }

    $pythonInstallFullPath = Get-FullPath $pythonInstallRoot
    $pythonCandidates = @(
        Get-ChildItem -LiteralPath $pythonInstallRoot -Filter "python.exe" -File -Recurse |
            Where-Object { $_.Directory.Parent.FullName -eq $pythonInstallFullPath }
    )
    if ($pythonCandidates.Count -ne 1) {
        throw "Expected exactly one portable python.exe, found $($pythonCandidates.Count)."
    }
    $pythonExe = $pythonCandidates[0]
    if ($pythonExe.Directory.Parent.FullName -ne $pythonInstallFullPath) {
        throw "The portable Python layout is not supported by this builder."
    }
    Remove-UvPythonInstallArtifacts $pythonInstallRoot $pythonExe.Directory.FullName
    Wait-PortablePythonReady $pythonExe.FullName

    $buildMetadata = Join-Path $buildRoot ".build"
    $requirementsPath = Join-Path $buildMetadata "requirements.txt"
    New-Item -ItemType Directory -Force -Path $buildMetadata | Out-Null

    Invoke-Native $uvExe @(
        "export", "--project", $serverRoot, "--locked", "--no-dev",
        "--no-emit-project", "--format", "requirements.txt",
        "--output-file", $requirementsPath, "--quiet"
    ) $project
    $sitePackages = Join-Path $pythonExe.Directory.FullName "Lib\site-packages"
    New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null
    Invoke-Native $uvExe @(
        "pip", "install", "--target", $installTarget,
        "--python-version", ([string]$lock.python),
        "--python-platform", "x86_64-pc-windows-msvc",
        "--only-binary", ":all:",
        "--no-deps", "--require-hashes", "--requirements", $requirementsPath
    ) $project
    # uv may recreate version aliases while discovering an interpreter for pip.
    # Keep only the fully-versioned physical runtime selected above.
    Remove-UvPythonInstallArtifacts $pythonInstallRoot $pythonExe.Directory.FullName
    Get-ChildItem -LiteralPath $installTarget -Filter "direct_url.json" -File -Recurse |
        Remove-Item -Force

    # Legacy namespace packages and pywin32 may ship wheel-owned .pth files.
    # They are part of locked distributions and do not link the runtime to a
    # source checkout. All other .pth files remain forbidden because uv
    # editable installs and arbitrary path injection use that surface.
    $editableLinks = @(
        Get-ChildItem -LiteralPath $installTarget -Filter "*.pth" -File -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -notlike "*-nspkg.pth" -and $_.Name -ne "pywin32.pth"
            }
    )
    $directUrls = @(Get-ChildItem -LiteralPath $installTarget -Filter "direct_url.json" -File -Recurse -ErrorAction SilentlyContinue)
    if ($editableLinks.Count -gt 0 -or $directUrls.Count -gt 0) {
        throw "The dependency installation contains editable or checkout-linked package metadata."
    }
    Get-ChildItem -LiteralPath $installTarget -Force |
        Where-Object { $_.Name -ne "bin" } |
        Copy-Item -Destination $sitePackages -Recurse -Force
    Get-ChildItem -LiteralPath $sitePackages -Directory -Filter ".agents" -Recurse |
        Remove-Item -Recurse -Force

    & $pythonExe.FullName -I -B -c "import deepagents, fastapi, langchain, uvicorn"
    if ($LASTEXITCODE -ne 0) {
        throw "The portable Python cannot import the locked third-party runtime."
    }

    Get-ChildItem -LiteralPath $sitePackages -Directory -Filter "__pycache__" -Recurse |
        Remove-Item -Recurse -Force
    Get-ChildItem -LiteralPath $sitePackages -File -Recurse |
        Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
        Remove-Item -Force
    $thirdPartyCaches = @(
        Get-ChildItem -LiteralPath $sitePackages -Directory -Filter "__pycache__" -Recurse
    )
    $thirdPartyBytecode = @(
        Get-ChildItem -LiteralPath $sitePackages -File -Recurse |
            Where-Object { $_.Extension -in @(".pyc", ".pyo") }
    )
    if ($thirdPartyCaches.Count -gt 0 -or $thirdPartyBytecode.Count -gt 0) {
        throw "The portable runtime contains generated third-party bytecode."
    }

    Get-ChildItem -LiteralPath $sitePackages -Filter "direct_url.json" -File -Recurse |
        Remove-Item -Force
    $editableLinks = @(
        Get-ChildItem -LiteralPath $sitePackages -Filter "*.pth" -File -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -notlike "*-nspkg.pth" -and $_.Name -ne "pywin32.pth"
            }
    )
    $directUrls = @(Get-ChildItem -LiteralPath $sitePackages -Filter "direct_url.json" -File -Recurse -ErrorAction SilentlyContinue)
    if ($editableLinks.Count -gt 0 -or $directUrls.Count -gt 0) {
        throw "The portable runtime contains editable or checkout-linked package metadata."
    }
    $reparsePoints = @(
        Get-ChildItem -LiteralPath $buildRoot -Force -Recurse |
            Where-Object {
                ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
            }
    )
    if ($reparsePoints.Count -gt 0) {
        $reparsePointDetails = $reparsePoints | ForEach-Object {
            $relativePath = $_.FullName.Substring($buildRoot.TrimEnd("\").Length + 1)
            "$relativePath ($($_.LinkType))"
        }
        throw "The portable runtime contains path-linked reparse points: $($reparsePointDetails -join ', ')"
    }

    $relativePythonHome = "python\$($pythonExe.Directory.Name)"
    Set-Content -LiteralPath (Join-Path $buildRoot "python-home.txt") -Value $relativePythonHome -Encoding ascii
    $runtimeManifest = [ordered]@{
        schema = 1
        application = "agent-shell"
        platform = "windows-x64"
        python = [string]$lock.python
        python_home = $relativePythonHome.Replace("\", "/")
        uv = $expectedUvVersion
        uv_url = [string]$lock.uv.url
        uv_sha256 = ([string]$lock.uv.sha256).ToLowerInvariant()
        build_fingerprint = $buildFingerprint
    }
    $runtimeManifestPath = Join-Path $buildRoot "runtime-manifest.json"
    $runtimeManifestJson = ($runtimeManifest | ConvertTo-Json) + "`n"
    [System.IO.File]::WriteAllText(
        $runtimeManifestPath,
        $runtimeManifestJson,
        [System.Text.UTF8Encoding]::new($false)
    )
    Remove-Item -LiteralPath $buildMetadata -Recurse -Force

    $previousApplicationRoot = Assert-ChildPath (Join-Path $temporaryRoot "app-previous-$PID") $runtimeRoot
    $hasPreviousApplication = Test-Path -LiteralPath $applicationRoot -PathType Container
    if ($hasPreviousApplication) {
        if (Test-Path -LiteralPath $previousApplicationRoot) {
            throw "The temporary previous-runtime path already exists."
        }
        Move-DirectoryWithRetry $applicationRoot $previousApplicationRoot
    }
    try {
        Move-DirectoryWithRetry $buildRoot $applicationRoot
    }
    catch {
        if ($hasPreviousApplication -and -not (Test-Path -LiteralPath $applicationRoot)) {
            Move-DirectoryWithRetry $previousApplicationRoot $applicationRoot
        }
        throw
    }
    if ($hasPreviousApplication -and (Test-Path -LiteralPath $previousApplicationRoot)) {
        if (-not (Remove-DirectoryWithRetry $previousApplicationRoot)) {
            Write-Warning "Could not remove the previous portable runtime at ${previousApplicationRoot}."
        }
    }
    $completed = $true
    Write-Host "Agent Shell portable runtime is ready: $applicationRoot"
}
finally {
    foreach ($name in $runtimeEnvironment.Keys) {
        [System.Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
    }
    if (Test-Path -LiteralPath $installTarget) {
        if (-not (Remove-DirectoryWithRetry $installTarget)) {
            Write-Warning "Could not remove the temporary dependency installation at ${installTarget}."
        }
    }
    if (-not $completed -and (Test-Path -LiteralPath $buildRoot)) {
        Assert-ChildPath $buildRoot $runtimeRoot | Out-Null
        if (-not (Remove-DirectoryWithRetry $buildRoot)) {
            Write-Warning "Could not remove the failed temporary runtime at ${buildRoot}."
        }
    }
}
