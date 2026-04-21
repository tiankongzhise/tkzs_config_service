param(
    [string]$GoOS = "linux",
    [string]$GoArch = "amd64",
    [string]$Output = "tkzs-config-service"
)

$ErrorActionPreference = "Stop"

Push-Location "service"
try {
    $env:GOOS = $GoOS
    $env:GOARCH = $GoArch
    go build -ldflags="-s -w" -o "..\$Output" .
}
finally {
    Pop-Location
}
