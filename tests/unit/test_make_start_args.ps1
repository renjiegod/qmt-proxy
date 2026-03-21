$ErrorActionPreference = "Stop"

$makeScript = Join-Path $PSScriptRoot "..\..\scripts\make.ps1"

function Write-Host {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [object[]]$Objects
    )
}

. $makeScript -Action help

$args = @(Get-UvRunArguments)
if ($args -contains "--no-project") {
    throw "Expected Get-UvRunArguments to use the project environment, but found --no-project."
}

if ($args -notcontains "run.py") {
    throw "Expected Get-UvRunArguments to launch run.py."
}

Write-Output "make start args test passed."
