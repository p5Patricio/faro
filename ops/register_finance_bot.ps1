<#
.SYNOPSIS
    Register a Windows Task Scheduler task that repeatedly polls Telegram for
    personal-finance ledger messages.

.DESCRIPTION
    Creates:
      - "Faro\FinanceBotSync" -- trigger: every 15 minutes, indefinitely,
        action: `py -3.14 -m ops.finance_bot` from the repo root.

    This is a third, separate operational concern from the other two
    registration scripts in this folder, mirroring their existing split:
      - ops/register_local_app.ps1   -- API + frontend dev servers (ONLOGON)
      - ops/register_local_jobs.ps1  -- the ML pipeline's daily/weekly cron
      - ops/register_finance_bot.ps1 -- THIS script: the finance Telegram
        bot's own short-poll cycle (different cadence, different failure
        shape, independent of the ML scheduler).

    This script only *registers the schtask*. It sets NO secrets and
    hardcodes NO password -- TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, and
    LOCAL_DATABASE_URL etc. must already be in your environment or the root
    .env before the task runs. `schtasks /Query /V` and the Task Scheduler UI
    both show the full command line in clear text, so never add credentials
    to the /TR string.

.NOTES
    Run this yourself, once, from a normal PowerShell prompt. Nothing in the
    repo or CI invokes it. The task runs as the current user, LIMITED (no
    elevation), hidden window, repeating every 15 minutes indefinitely.
#>

$ErrorActionPreference = 'Stop'

$RepoRoot  = Split-Path -Parent $PSScriptRoot
$Script    = Join-Path $RepoRoot 'ops\run_finance_bot.ps1'
$HiddenVbs = Join-Path $RepoRoot 'ops\run_hidden.vbs'

if (-not (Test-Path $Script)) {
    throw "Cannot find $Script - run this from the repo's ops/ folder."
}

Write-Host "Registering Faro\FinanceBotSync for $env:USERNAME (repo root: $RepoRoot)"

# /SC MINUTE /MO 15: fires every 15 minutes, indefinitely, starting now.
# /RL LIMITED (no elevation at run time), /F overwrites an existing task so
# re-running this script is idempotent. schtasks is an external exe -- its
# failures do NOT throw -- so $LASTEXITCODE is checked explicitly below.
#
# Action routes through ops/run_hidden.vbs (wscript.exe) instead of a raw
# `cmd /c ...` (the original bug: no way to suppress cmd's own console,
# flashing a terminal every 15 minutes) or `powershell -WindowStyle
# Hidden -File ...` directly (tried next: still briefly flashes a console
# before hiding it, a known conhost quirk) -- see run_hidden.vbs's own
# header comment. Two separately-quoted paths, no nested quoting for
# schtasks.exe's own /TR parsing to mangle.
schtasks /Create `
    /TN "Faro\FinanceBotSync" `
    /SC MINUTE `
    /MO 15 `
    /RL LIMITED `
    /F `
    /TR "wscript.exe `"$HiddenVbs`" `"$Script`""

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "schtasks failed (exit $LASTEXITCODE) - the task was NOT registered." -ForegroundColor Red
    Write-Host "If it said 'Access is denied', re-run this script from an elevated"
    Write-Host "PowerShell (right-click -> Run as administrator), or create a"
    Write-Host "top-level task instead of one under the Faro\ folder:"
    Write-Host "  schtasks /Create /TN FaroFinanceBotSync /SC MINUTE /MO 15 /RL LIMITED /F ``"
    Write-Host "    /TR `"cmd /c cd /d \`"$RepoRoot\`" && py -3.14 -m ops.finance_bot`""
    exit 1
}

Write-Host ""
Write-Host "Registered. It starts polling within 15 minutes. Commands:"
Write-Host "  Run now     : schtasks /Run /TN `"Faro\FinanceBotSync`""
Write-Host "  Inspect     : schtasks /Query /TN `"Faro\FinanceBotSync`" /V /FO LIST"
Write-Host "  Unregister  : schtasks /Delete /TN `"Faro\FinanceBotSync`" /F"
Write-Host ""
Write-Host "Before the first run, make sure the root .env has:"
Write-Host "  TELEGRAM_BOT_TOKEN=<your bot token>"
Write-Host "  TELEGRAM_CHAT_ID=<your allowed chat id>"
Write-Host "  LOCAL_DATABASE_URL=<local Postgres DSN>"
Write-Host "  (optional) FINANCE_DEFAULT_ACCOUNT_NAME, FINANCE_DEFAULT_CURRENCY"
Write-Host ""
Write-Host "The task runs only while you are logged in (/RL LIMITED, no stored password)." `
    "To keep it running while logged off, re-create it with an added" `
    "'/RU `"%USERNAME%`" /RP *' (prompts for your Windows password; never store it here)."
