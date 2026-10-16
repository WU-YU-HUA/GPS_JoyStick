$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
$destination = Join-Path $PSScriptRoot 'dist\iPhoneGPSJoystick\config.json'
$savedConfig = $null
if (Test-Path -LiteralPath $destination) {
    $savedConfig = [System.IO.File]::ReadAllBytes($destination)
}
try {
    python -m PyInstaller --noconfirm iphone_joystick.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    # A rebuild must not overwrite the user's last saved coordinates.
    if ($null -eq $savedConfig -and -not (Test-Path -LiteralPath $destination)) {
        $configSource = Join-Path $PSScriptRoot 'config.json'
        if (-not (Test-Path -LiteralPath $configSource)) {
            $configSource = Join-Path $PSScriptRoot 'config.example.json'
        }
        Copy-Item -LiteralPath $configSource -Destination $destination
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'README.md') -Destination 'dist\iPhoneGPSJoystick\README.md'
    Write-Host 'Built: dist\iPhoneGPSJoystick\iPhoneGPSJoystick.exe'
} finally {
    if ($null -ne $savedConfig) {
        $configDirectory = Split-Path -Parent $destination
        if (-not (Test-Path -LiteralPath $configDirectory)) {
            New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
        }
        [System.IO.File]::WriteAllBytes($destination, $savedConfig)
    }
    Pop-Location
}
