$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
$buildDirectory = Join-Path $PSScriptRoot ('.packaging-' + [guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $buildDirectory | Out-Null
    # Conda can contain older VC runtime DLLs than the PySide6 wheel. Place
    # PySide6's matching runtimes at the bundle root so Python loads them first.
    $pysideDirectory = python -c "import pathlib, PySide6; print(pathlib.Path(PySide6.__file__).parent)"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot locate PySide6.' }
    $runtimeArguments = @()
    foreach ($runtime in Get-ChildItem -LiteralPath $pysideDirectory -Filter '*.dll') {
        if ($runtime.Name -match '^(msvcp140.*|vcruntime140.*|concrt140)\.dll$') {
            $runtimeArguments += @('--add-binary', ($runtime.FullName + ';.'))
        }
    }
    $outputDirectory = Join-Path $buildDirectory 'output'
    python -m PyInstaller --clean --noconfirm --noconsole --onefile --collect-all pytun_pmd3 @runtimeArguments --runtime-hook (Join-Path $PSScriptRoot 'build_hooks\windows_qt_runtime.py') --name iPhoneGPSJoystick --distpath $outputDirectory --workpath (Join-Path $buildDirectory 'work') --specpath $buildDirectory pyside_gps.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    $builtExecutable = Join-Path $outputDirectory 'iPhoneGPSJoystick.exe'
    try {
        Copy-Item -LiteralPath $builtExecutable -Destination (Join-Path $PSScriptRoot 'iPhoneGPSJoystick.exe') -Force
        Write-Host 'Built: iPhoneGPSJoystick.exe (single file)'
    } catch {
        $pendingExecutable = Join-Path $PSScriptRoot 'iPhoneGPSJoystick.new.exe'
        Copy-Item -LiteralPath $builtExecutable -Destination $pendingExecutable -Force
        Write-Warning "Could not replace the current EXE: $($_.Exception.Message). New build saved as iPhoneGPSJoystick.new.exe. Close the running app before replacing the old EXE."
    }
} finally {
    $resolvedBuildDirectory = [System.IO.Path]::GetFullPath($buildDirectory)
    $workspacePrefix = [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\') + '\'
    if (-not $resolvedBuildDirectory.StartsWith($workspacePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Refusing to remove a build directory outside the project.'
    }
    if (Test-Path -LiteralPath $resolvedBuildDirectory) {
        Remove-Item -LiteralPath $resolvedBuildDirectory -Recurse -Force
    }
    Pop-Location
}
