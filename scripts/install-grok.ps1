<#
.SYNOPSIS
Installs, checks, or uninstalls the Parrhesia Grok project adapter in an existing project.
.DESCRIPTION
Copies the bundled runtime and both skills (parrhesia-review and parrhesia-l2-reference),
merges one MCP server into .mcp.json, and maintains a managed AGENTS.md block (compact by default).
Does not call Grok, install packages, change ~/.grok, or run a model.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [string]$Python = 'python',
    [ValidateSet('compact', 'full')][string]$Policy = 'compact',
    [switch]$SkipAgents,
    [switch]$Check,
    [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'
$adapterScript = Join-Path $PSScriptRoot 'install-grok.py'
$adapterArgs = @($adapterScript, '--project', $Project)
if ($Check) {
    $adapterArgs += '--check'
} elseif ($Uninstall) {
    $adapterArgs += '--uninstall'
} else {
    $adapterArgs += @('--policy', $Policy, '--python', $Python)
    if ($SkipAgents) { $adapterArgs += '--skip-agents' }
}
& $Python @adapterArgs
if ($LASTEXITCODE -ne 0) { throw "Parrhesia Grok adapter failed (exit $LASTEXITCODE)." }
