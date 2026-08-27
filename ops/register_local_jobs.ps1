<#
.SYNOPSIS
    Register the two Windows Task Scheduler tasks that replace the retired
    ".github/workflows/operational-jobs.yml" GitHub Actions cron.

.DESCRIPTION
    Creates:
      - "IAInversiones\DailyOperationalCycle"  -- daily at 06:20, `--job full`
        (mirrors the retired workflow's `cron: "20 6 * * *"`)
      - "IAInversiones\WeeklyRetrainingCycle"  -- weekly Sunday at 06:40,
        `--job full_retrain` (mirrors `cron: "40 6 * * 0"`)

    This script only *registers the schtasks*. It does NOT set
    LOCAL_DATABASE_URL, TEST_DATABASE_URL, or TELEGRAM_BOT_TOKEN/CHAT_ID --
    those must already be present in your own user/machine environment (or
    a `.env` file `python-dotenv` will load) before either task runs.
    NEVER hardcode a database password or bot token into this script or
    into the registered task's command line: `schtasks /Query ... /V` and
    the Task Scheduler UI both show the full command line in plain text.

.NOTES
    Run this script yourself, interactively, from an elevated or normal
    PowerShell prompt. It is not invoked automatically by anything in this
    repository or by CI.
#>

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Registering IAInversiones Task Scheduler jobs (repo root: $RepoRoot)"

# Daily operational cycle: market data -> inference -> paper trading, 06:20.
schtasks /Create `
    /TN "IAInversiones\DailyOperationalCycle" `
    /SC DAILY `
    /ST 06:20 `
    /RL LIMITED `
    /F `
    /TR "cmd /c cd /d `"$RepoRoot`" && py -3.14 -m ops.run_local_scheduler --job full"

# Weekly retraining cycle: adds brain.run_retraining_job, Sunday 06:40.
schtasks /Create `
    /TN "IAInversiones\WeeklyRetrainingCycle" `
    /SC WEEKLY `
    /D SUN `
    /ST 06:40 `
    /RL LIMITED `
    /F `
    /TR "cmd /c cd /d `"$RepoRoot`" && py -3.14 -m ops.run_local_scheduler --job full_retrain"

Write-Host ""
Write-Host "Registered. Verify with:"
Write-Host "  schtasks /Query /TN `"IAInversiones\DailyOperationalCycle`" /V /FO LIST"
Write-Host "  schtasks /Query /TN `"IAInversiones\WeeklyRetrainingCycle`" /V /FO LIST"
Write-Host ""
Write-Host "Smoke-test a run on demand with:"
Write-Host "  schtasks /Run /TN `"IAInversiones\DailyOperationalCycle`""
Write-Host ""
Write-Host "Remove either task with:"
Write-Host "  schtasks /Delete /TN `"IAInversiones\DailyOperationalCycle`" /F"
Write-Host "  schtasks /Delete /TN `"IAInversiones\WeeklyRetrainingCycle`" /F"
Write-Host ""
Write-Host "Both tasks run as the current user (/RL LIMITED, no elevation)." `
    "If they must run while you are logged off, re-run schtasks /Create with" `
    "an added '/RU `"%USERNAME%`" /RP *' (interactively prompts for your" `
    "Windows password -- never store it in this script)."
