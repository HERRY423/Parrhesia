<#
.SYNOPSIS
Installs the Parrhesia compatibility adapter only into an existing project.
.DESCRIPTION
Copies the bundled runtime and skill, merges one MCP server, and appends a managed
AGENTS.md block. Does not call Grok, install packages, change user configuration,
or run a model. Existing conflicting files stop installation before any write.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [string]$Python = 'python',
    [switch]$SkipAgents
)
$ErrorActionPreference = 'Stop'
$adapterScript = Join-Path $PSScriptRoot 'install-grok.py'
$adapterArgs = @($adapterScript, '--project', $Project)
if ($SkipAgents) { $adapterArgs += '--skip-agents' }
& $Python @adapterArgs
if ($LASTEXITCODE -ne 0) { throw "Parrhesia project installation failed (exit $LASTEXITCODE)." }
