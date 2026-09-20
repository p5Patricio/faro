<#
.SYNOPSIS
    Hidden-window entry point for the Faro\FinanceBotSync scheduled task.

.DESCRIPTION
    Just `cd`s to the repo root and runs the bot. Exists only so the
    scheduled task's action can be a single
    `powershell -WindowStyle Hidden -File <this script>` -- unlike a raw
    `cmd /c ...` action (what FinanceBotSync used to run), that actually
    suppresses the console window instead of flashing one open every 15
    minutes. See ops/register_finance_bot.ps1. Sets no secrets:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, LOCAL_DATABASE_URL etc. must
    already be in the environment or the root .env (ops/finance_bot.py
    loads it via python-dotenv).
#>

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $RepoRoot

py -3.14 -m ops.finance_bot
