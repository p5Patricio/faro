<#
.SYNOPSIS
    Weekly retraining orchestrator: fundamental_v1 materialization + retrain,
    then the existing technical_v2 full_retrain cycle -- sequentially, so
    the two never fight for CPU/DB at once.

.DESCRIPTION
    Registered as the action for Faro\WeeklyRetrainingCycle (Sunday, after
    FaroFundamentalIngestionWeekly's 05:40 SEC ingestion has had time to
    finish). Runs three steps in order, all --scopes local so an unattended
    weekly run stays tractable across the full ~101-stock universe (the
    heavier asset_class/global scopes are for deliberate manual runs, not
    the routine cron -- see this week's retrain-batch history for why):

      1. ops.materialize_fundamentals_batch -- turns this week's freshly
         ingested SEC facts into fundamental_v1 feature rows. Without this,
         new filings sit in fundamental_facts and never reach a model.
      2. ops.retrain_batched --feature-set fundamental_v1 -- re-evaluates
         every stock's fundamental_v1 candidate against whichever model
         (any feature set) currently serves that ticker. Resumable via its
         own state file (logs/retrain_fundamental_v1_state.json) if this
         step gets interrupted mid-run.
      3. ops.run_local_scheduler --job full_retrain --scopes local -- the
         existing technical_v2 retraining + inference + paper-trading cycle.

    A non-zero exit from step 1 or 2 does not stop the chain: a bad week for
    one feature set should not block the other from still improving.
#>

$ErrorActionPreference = 'Continue'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Log([string]$Message) {
    "[$(Get-Date -Format o)] $Message"
}

Log "Step 1/3: materialize fundamental_v1 features"
py -3.14 -m ops.materialize_fundamentals_batch --out artifacts/weekly_materialize_fundamentals.json

Log "Step 2/3: retrain fundamental_v1 (local scope)"
py -3.14 -m ops.retrain_batched --feature-set fundamental_v1 --targets-file config/targets.stocks.json --scopes local

Log "Step 3/3: technical_v2 full retraining cycle (local scope)"
py -3.14 -m ops.run_local_scheduler --job full_retrain --scopes local

Log "Weekly retraining chain complete"
