param([switch]$ReplaceExisting, [switch]$WithPythonFallback, [switch]$Extras)
$ErrorActionPreference = 'Stop'
function Get-PayloadDigest([string]$LiteralPath) {
    $stream = [IO.File]::OpenRead($LiteralPath)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
    finally { $algorithm.Dispose(); $stream.Dispose() }
}
$name = 'image-proxy-first'
$payload = Join-Path $PSScriptRoot $name
$architecture = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
$platform = switch ($architecture.ToUpperInvariant()) { 'AMD64' { 'windows-x64' } 'ARM64' { 'windows-arm64' } default { throw 'Unsupported Windows processor architecture.' } }
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'payload-sha256.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($entry in $manifest.PSObject.Properties) {
    if ($entry.Name -match '(^/|\.\.|:|\\)') { throw 'Unsafe manifest path.' }
    $file = Join-Path $payload $entry.Name
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing payload: $($entry.Name)" }
    if ((Get-Item -LiteralPath $file).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Payload reparse point rejected.' }
    if ((Get-PayloadDigest $file) -ne $entry.Value) { throw "Payload integrity mismatch: $($entry.Name)" }
}
$actualCount = @(Get-ChildItem -LiteralPath $payload -Recurse -File).Count
if ($actualCount -ne @($manifest.PSObject.Properties).Count) { throw 'Unexpected payload file.' }
$codexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$parent = Join-Path $codexRoot 'skills'
$target = Join-Path $parent $name
$backup = $null
New-Item -ItemType Directory -Path $parent -Force | Out-Null
if (Test-Path -LiteralPath $target) {
    if (-not $ReplaceExisting) { throw 'Skill exists. Use -ReplaceExisting to keep a backup and replace.' }
    if ((Get-Item -LiteralPath $target).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Installed skill reparse point rejected.' }
}
$stage = Join-Path $parent ('.image-proxy-stage-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
Copy-Item -LiteralPath (Join-Path $payload 'SKILL.md') -Destination $stage
foreach ($directory in @('agents','references','scripts','native','bin')) { Copy-Item -LiteralPath (Join-Path $payload $directory) -Destination $stage -Recurse }
foreach ($entry in $manifest.PSObject.Properties) { if ((Get-PayloadDigest (Join-Path $stage $entry.Name)) -ne $entry.Value) { throw 'Staging copy verification failed.' } }
$encoding = New-Object System.Text.UTF8Encoding($false)
$launcher = Join-Path $stage 'scripts\proxy.cmd'
$text = [IO.File]::ReadAllText($launcher).Replace('windows-x64',$platform)
[IO.File]::WriteAllText($launcher,$text,$encoding)
if (Test-Path -LiteralPath $target) {
    $backupRoot = Join-Path $codexRoot 'skill-backups'
    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    $backup = Join-Path $backupRoot ($name + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fffffff'))
    Move-Item -LiteralPath $target -Destination $backup
}
Move-Item -LiteralPath $stage -Destination $target
$binary = Join-Path $target "bin\$platform\image-proxy.exe"
& $binary --version
if ($LASTEXITCODE -ne 0) { throw 'Selected native executable failed its smoke test. Previous skill, if any, remains in the backup directory.' }
if ($WithPythonFallback -or $Extras) {
    $python = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } elseif (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { throw 'Python is needed only for the requested optional fallback.' }
    & $python -m venv (Join-Path $target '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create optional fallback environment.' }
    $privatePython = Join-Path $target '.venv\Scripts\python.exe'
    $packages = @('Pillow>=11,<13')
    if ($Extras) { $packages += @('pillow-heif>=0.20,<2','rawpy>=0.23,<1') }
    & $privatePython -m pip install --disable-pip-version-check @packages
    if ($LASTEXITCODE -ne 0) { throw 'Optional fallback dependencies were not installed.' }
}
$runtime = @{ platform=$platform; native_executable=$binary; entry_point=(Join-Path $target 'scripts\proxy.cmd'); python_default=$false; compile_at_runtime=$false; backup=$backup }
[IO.File]::WriteAllText((Join-Path $target 'runtime.json'),($runtime | ConvertTo-Json),$encoding)
$runtime | ConvertTo-Json -Compress
