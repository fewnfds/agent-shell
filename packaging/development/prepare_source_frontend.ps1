[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$project = [System.IO.Path]::GetFullPath($ProjectRoot)
$frontend = Join-Path $project "frontend"
$output = Join-Path $project "runtime\frontend_dist"
$runtime = Join-Path $project "runtime"
$manifestPath = Join-Path $runtime "source-frontend-manifest.json"
$projectPrefix = $project.TrimEnd("\") + "\"

function Get-RelativeProjectPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if (-not $fullPath.StartsWith($projectPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "A source frontend input is outside the project root."
    }
    return $fullPath.Substring($projectPrefix.Length).Replace("\", "/")
}

function Get-FileSetFingerprint {
    param([Parameter(Mandatory = $true)][System.IO.FileInfo[]]$Files)

    $builder = New-Object System.Text.StringBuilder
    foreach ($file in @($Files | Sort-Object FullName -Unique)) {
        $relativePath = Get-RelativeProjectPath $file.FullName
        $fileAlgorithm = [System.Security.Cryptography.SHA256]::Create()
        $stream = [System.IO.File]::OpenRead($file.FullName)
        try {
            $fileHash = -join (
                $fileAlgorithm.ComputeHash($stream) |
                    ForEach-Object { $_.ToString("x2") }
            )
        }
        finally {
            $stream.Dispose()
            $fileAlgorithm.Dispose()
        }
        [void]$builder.Append($relativePath).Append("`t").Append($fileHash).Append("`n")
    }
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($builder.ToString())
        return -join ($algorithm.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") })
    }
    finally {
        $algorithm.Dispose()
    }
}

$requiredFiles = @(
    "package.json",
    "package-lock.json",
    "index.html",
    "vite.config.ts",
    "tsconfig.json",
    "tsconfig.app.json",
    "tsconfig.node.json"
) | ForEach-Object { Get-Item -LiteralPath (Join-Path $frontend $_) -ErrorAction Stop }
$sourceFiles = @(
    Get-ChildItem -LiteralPath (Join-Path $frontend "src") -Recurse -File
    Get-ChildItem -LiteralPath (Join-Path $frontend "public") -Recurse -File
)
$allInputs = @($requiredFiles) + @($sourceFiles)
$sourceFingerprint = Get-FileSetFingerprint $allInputs
$dependencyFiles = @(
    Get-Item -LiteralPath (Join-Path $frontend "package.json")
    Get-Item -LiteralPath (Join-Path $frontend "package-lock.json")
)
$dependencyFingerprint = Get-FileSetFingerprint $dependencyFiles

$manifest = $null
if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
    try {
        $candidate = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $properties = @($candidate.PSObject.Properties.Name)
        if (
            $properties -contains "schema" -and
            $properties -contains "source_sha256" -and
            $properties -contains "dependencies_sha256"
        ) {
            $manifest = $candidate
        }
    }
    catch {
        $manifest = $null
    }
}
$frontendReady = (
    (Test-Path -LiteralPath (Join-Path $output "index.html") -PathType Leaf) -and
    (Test-Path -LiteralPath (Join-Path $output "assets") -PathType Container)
)
if (
    $frontendReady -and
    $null -ne $manifest -and
    $manifest.schema -eq 1 -and
    $manifest.source_sha256 -eq $sourceFingerprint
) {
    Write-Host "Agent Shell source frontend is already current."
    exit 0
}

$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if ($null -eq $npm) {
    throw "Running an Agent Shell source clone requires Node.js 22 with npm."
}
$vite = Join-Path $frontend "node_modules\.bin\vite.cmd"
$dependenciesCurrent = (
    (Test-Path -LiteralPath $vite -PathType Leaf) -and
    $null -ne $manifest -and
    $manifest.schema -eq 1 -and
    $manifest.dependencies_sha256 -eq $dependencyFingerprint
)
if (-not $dependenciesCurrent) {
    Write-Host "Preparing locked frontend dependencies..."
    & $npm.Source --prefix $frontend ci
    if ($LASTEXITCODE -ne 0) {
        throw "npm ci failed with exit code $LASTEXITCODE."
    }
}

Write-Host "Building the current source frontend..."
& $npm.Source --prefix $frontend run build
if ($LASTEXITCODE -ne 0) {
    throw "The source frontend production build failed with exit code $LASTEXITCODE."
}
if (
    -not (Test-Path -LiteralPath (Join-Path $output "index.html") -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $output "assets") -PathType Container)
) {
    throw "The source frontend production output is incomplete."
}

New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$temporaryManifest = "$manifestPath.$PID.tmp"
try {
    $manifestJson = [ordered]@{
        schema = 1
        source_sha256 = $sourceFingerprint
        dependencies_sha256 = $dependencyFingerprint
    } | ConvertTo-Json
    [System.IO.File]::WriteAllText(
        $temporaryManifest,
        ($manifestJson + "`n"),
        [System.Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $temporaryManifest -Destination $manifestPath -Force
}
finally {
    if (Test-Path -LiteralPath $temporaryManifest) {
        Remove-Item -LiteralPath $temporaryManifest -Force
    }
}
Write-Host "Agent Shell source frontend is ready."
