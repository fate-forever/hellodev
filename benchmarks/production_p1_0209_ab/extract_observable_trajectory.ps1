param(
    [Parameter(Mandatory = $true)]
    [string]$RolloutPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [Parameter(Mandatory = $true)]
    [string]$AgentPath,

    [Parameter(Mandatory = $true)]
    [string]$AgentNickname,

    [switch]$RedactLocalPaths
)

$ErrorActionPreference = "Stop"

function Get-Sha256([string]$Value) {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-FileSha256([string]$Path) {
    $stream = New-Object System.IO.FileStream(
        $Path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::ReadWrite
    )
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

function Unescape-JsString([string]$Value) {
    return $Value.Replace('\n', "`n").Replace('\r', "`r").Replace('\"', '"').Replace('\\', '\')
}

function ConvertTo-PublicText([string]$Value) {
    if (-not $RedactLocalPaths -or $null -eq $Value) {
        return $Value
    }
    $workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")).Path
    $codexHome = Join-Path $env:USERPROFILE ".codex"
    return $Value.Replace($workspaceRoot, "<workspace>").Replace($codexHome, "<codex-home>").Replace($env:USERPROFILE, "<user-home>")
}

$calls = New-Object System.Collections.ArrayList
$byCallId = @{}
$tokenEvents = 0

Get-Content -LiteralPath $RolloutPath | ForEach-Object {
    $rawLine = [string]$_
    try {
        $entry = $rawLine | ConvertFrom-Json
    }
    catch {
        if ($rawLine.Contains('"type":"custom_tool_call"')) {
            $timestampMatch = [regex]::Match($rawLine, '"timestamp":"([^"]+)"')
            $callIdMatch = [regex]::Match($rawLine, '"call_id":"([^"]+)"')
            $nameMatch = [regex]::Match($rawLine, '"name":"([^"]+)"')
            if ($timestampMatch.Success -and $callIdMatch.Success) {
                $affectedMatches = [regex]::Matches($rawLine, '\*\*\* (?:Add|Update|Delete) File:\s*(.+?)\\n')
                $fallbackRecord = [ordered]@{
                    ordinal = $calls.Count + 1
                    timestamp = $timestampMatch.Groups[1].Value
                    callId = $callIdMatch.Groups[1].Value
                    outerTool = $(if ($nameMatch.Success) { $nameMatch.Groups[1].Value } else { "unknown" })
                    kind = $(if ($rawLine.Contains("*** Begin Patch")) { "apply_patch" } else { "other" })
                    command = $null
                    affectedFiles = @($affectedMatches | ForEach-Object { ConvertTo-PublicText ((Unescape-JsString $_.Groups[1].Value).TrimEnd('\')) })
                    inputSha256 = Get-Sha256 $rawLine
                    outputTimestamp = $null
                    outputSha256 = $null
                    exitCode = $null
                    wallTimeSeconds = $null
                    recoveredFromMalformedJsonl = $true
                }
                [void]$calls.Add($fallbackRecord)
                $byCallId[$fallbackRecord.callId] = $fallbackRecord
            }
        }
        return
    }

    if ($entry.type -eq "event_msg" -and $entry.payload.type -eq "token_count") {
        $tokenEvents++
    }

    if ($entry.type -ne "response_item") {
        return
    }

    if ($entry.payload.type -eq "custom_tool_call") {
        $rawInput = [string]$entry.payload.input
        $kind = "other"
        $command = $null
        $affectedFiles = @()

        if ($rawInput.Contains("tools.shell_command")) {
            $kind = "shell"
            $match = [regex]::Match($rawInput, 'tools\.shell_command\(\{command:\"((?:\\.|[^\"])*)\"')
            if ($match.Success) {
                $command = ConvertTo-PublicText (Unescape-JsString $match.Groups[1].Value)
            }
        }
        elseif ($rawInput.Contains("tools.apply_patch") -or $rawInput.Contains("*** Begin Patch")) {
            $kind = "apply_patch"
            $matches = [regex]::Matches($rawInput, '\*\*\* (?:Add|Update|Delete) File:\s*(.+?)\\n')
            $affectedFiles = @($matches | ForEach-Object { ConvertTo-PublicText (Unescape-JsString $_.Groups[1].Value) })
        }

        $record = [ordered]@{
            ordinal = $calls.Count + 1
            timestamp = [string]$entry.timestamp
            callId = [string]$entry.payload.call_id
            outerTool = [string]$entry.payload.name
            kind = $kind
            command = $command
            affectedFiles = $affectedFiles
            inputSha256 = Get-Sha256 $rawInput
            outputTimestamp = $null
            outputSha256 = $null
            exitCode = $null
            wallTimeSeconds = $null
        }
        [void]$calls.Add($record)
        $byCallId[$record.callId] = $record
        return
    }

    if ($entry.payload.type -eq "custom_tool_call_output") {
        $callId = [string]$entry.payload.call_id
        if (-not $byCallId.ContainsKey($callId)) {
            return
        }
        $texts = @($entry.payload.output | Where-Object { $_.type -eq "input_text" } | ForEach-Object { [string]$_.text })
        $outputText = $texts -join "`n"
        $record = $byCallId[$callId]
        $record.outputTimestamp = [string]$entry.timestamp
        $record.outputSha256 = Get-Sha256 $outputText

        $exitMatch = [regex]::Match($outputText, 'Exit code:\s*(-?\d+)')
        if ($exitMatch.Success) {
            $record.exitCode = [int]$exitMatch.Groups[1].Value
        }
        $wallMatch = [regex]::Match($outputText, 'Wall time\s+([0-9.]+)\s+seconds')
        if ($wallMatch.Success) {
            $record.wallTimeSeconds = [double]$wallMatch.Groups[1].Value
        }
    }
}

foreach ($record in $calls) {
    $record["outputState"] = $(if ($record.outputSha256) { "recorded" } else { "missing-in-source-rollout" })
}

$rolloutHash = Get-FileSha256 $RolloutPath
$document = [ordered]@{
    schemaVersion = 1
    privacyBoundary = "Observable tool trajectory only; assistant hidden reasoning and private chain-of-thought are excluded."
    agent = [ordered]@{
        path = $AgentPath
        nickname = $AgentNickname
    }
    source = [ordered]@{
        rolloutPath = ConvertTo-PublicText $RolloutPath
        rolloutSha256 = $rolloutHash
        localPathsRedacted = [bool]$RedactLocalPaths
    }
    counts = [ordered]@{
        customToolCalls = $calls.Count
        shellCalls = @($calls | Where-Object { $_.kind -eq "shell" }).Count
        applyPatchCalls = @($calls | Where-Object { $_.kind -eq "apply_patch" }).Count
        otherCalls = @($calls | Where-Object { $_.kind -eq "other" }).Count
        tokenCountEvents = $tokenEvents
    }
    calls = $calls
}

$parent = Split-Path -Parent $OutputPath
if ($parent) {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
}
$document | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
