$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
$buildDirectory = Join-Path $PSScriptRoot ('.packaging-' + [guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $buildDirectory | Out-Null
    python -m PyInstaller --clean --noconfirm --noconsole --onefile --collect-all pytun_pmd3 --name iPhoneGPSJoystick --distpath $PSScriptRoot --workpath (Join-Path $buildDirectory 'work') --specpath $buildDirectory iphone_joystick.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    Write-Host 'Built: iPhoneGPSJoystick.exe (single file)'
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
