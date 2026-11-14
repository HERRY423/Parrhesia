<#
.SYNOPSIS
Installs, checks, or uninstalls the Parrhesia Antigravity plugin adapter.
.DESCRIPTION
Creates a self-contained Antigravity plugin bundle (.agents/plugins/parrhesia/) with
strict plugin.json, mcp_config.json, compact rules/parrhesia.md (< 24,000 B),
both skills (parrhesia-review and parrhesia-l2-reference), and a read-only SessionStart hook.
Never modifies ~/.gemini/config/config.json or calls any model.
#>
[CmdletBinding()]
param(
    [ValidateSet('project', 'user')][string]$Scope = 'project',
    [string]$Project,
    [string]$Target,
    [string]$Workspace,
    [ValidateSet('plugin', 'root', 'both', 'none')][string]$RulesTarget = 'plugin',
    [string]$Python = 'python',
    [switch]$NoHooks,
    [switch]$Check,
    [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'
$adapterScript = Join-Path $PSScriptRoot 'install-antigravity.py'
$adapterArgs = @($adapterScript, '--scope', $Scope)
if ($Project) { $adapterArgs += @('--project', $Project) }
if ($Target) { $adapterArgs += @('--target', $Target) }
if ($Check) {
    $adapterArgs += '--check'
} elseif ($Uninstall) {
    $adapterArgs += '--uninstall'
} else {
    $adapterArgs += @('--rules-target', $RulesTarget, '--python', $Python)
    if ($Workspace) { $adapterArgs += @('--workspace', $Workspace) }
    if ($NoHooks) { $adapterArgs += '--no-hooks' }
}
& $Python @adapterArgs
if ($LASTEXITCODE -ne 0) { throw "Parrhesia Antigravity adapter failed (exit $LASTEXITCODE)." }
