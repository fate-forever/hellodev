param(
    [string]$Project = (Join-Path ([IO.Path]::GetTempPath()) "hellodev-minimal-demo-$PID")
)

$ErrorActionPreference = "Stop"
$command = Get-Command hellodev -ErrorAction Stop
New-Item -ItemType Directory -Force -Path $Project | Out-Null

& $command.Source --root $Project open
& $command.Source --root $Project next
& $command.Source --root $Project do task create --title "Document the minimal HelloDev flow"
& $command.Source --root $Project do plan
& $command.Source --root $Project do work
& $command.Source --root $Project do check
& $command.Source --root $Project do finish
& $command.Source --root $Project resume --context --token-budget 256
& $command.Source --root $Project policy checkpoint export

Write-Output "HELLODEV_DEMO_PROJECT=$Project"
