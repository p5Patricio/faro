<#
.SYNOPSIS
    Weekly retraining orchestrator: fundamental_v1 + technical_alpha_v1 +
    sentiment_v1 materialization, fundamental_v1 retrain, then the existing
    technical_v2 full_retrain cycle -- sequentially, so the feature sets
    never fight for CPU/DB at once.

.DESCRIPTION
    Registered as the action for Faro\WeeklyRetrainingCycle (Sunday, after
    FaroFundamentalIngestionWeekly's 05:40 SEC ingestion has had time to
    finish). Runs five steps in order, all --scopes local so an unattended
    weekly run stays tractable across the full universe (the heavier
    asset_class/global scopes are for deliberate manual runs, not the
    routine cron -- see this week's retrain-batch history for why):

      1. ops.materialize_fundamentals_batch -- turns this week's freshly
         ingested SEC facts into fundamental_v1 feature rows. Without this,
         new filings sit in fundamental_facts and never reach a model.
      2. ops.materialize_technical_alpha_batch -- turns this week's OHLCV
         prices into technical_alpha_v1 feature rows (technical_v2 spine +
         the 19 Alpha158-inspired factors), across the full universe --
         unlike fundamental_v1, this feature set is not stock-only. Without
         this, brain.train --feature-set technical_alpha_v1 has no rows to
         train on.
      3. ops.materialize_sentiment_batch -- pulls this week's Finnhub
         company news, scores any not-yet-scored headline with FinBERT, and
         turns the result into sentiment_v1 feature rows, across the full
         universe (also not stock-only). Skips ingestion gracefully per
         ticker when FINNHUB_API_KEY is unset (see
         brain/materialize_sentiment.py), so this step is safe to leave
         enabled even before that key is provisioned -- it simply
         materializes zero new headlines until then.
      4. ops.retrain_batched --feature-set fundamental_v1 -- re-evaluates
         every stock's fundamental_v1 candidate against whichever model
         (any feature set) currently serves that ticker. Resumable via its
         own state file (logs/retrain_fundamental_v1_state.json) if this
         step gets interrupted mid-run.
      5. ops.run_local_scheduler --job full_retrain --scopes local -- the
         existing technical_v2 retraining + inference + paper-trading cycle.

    technical_alpha_v1 and sentiment_v1 are deliberately materialization-only
    here, mirroring only step 1's precedent, not step 4's -- no automatic
    ops.retrain_batched --feature-set technical_alpha_v1 (or sentiment_v1)
    step has been added yet; training on either today is a manual
    `brain.train --feature-set <name>` run. A non-zero exit from step 1, 2,
    3, or 4 does not stop the chain: a bad week for one feature set should
    not block the others from still improving.
#>

$ErrorActionPreference = 'Continue'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Log([string]$Message) {
    "[$(Get-Date -Format o)] $Message"
}

Log "Step 1/5: materialize fundamental_v1 features"
py -3.14 -m ops.materialize_fundamentals_batch --out artifacts/weekly_materialize_fundamentals.json

Log "Step 2/5: materialize technical_alpha_v1 features"
py -3.14 -m ops.materialize_technical_alpha_batch --out artifacts/weekly_materialize_technical_alpha.json

Log "Step 3/5: materialize sentiment_v1 features"
py -3.14 -m ops.materialize_sentiment_batch --out artifacts/weekly_materialize_sentiment.json

Log "Step 4/5: retrain fundamental_v1 (local scope)"
py -3.14 -m ops.retrain_batched --feature-set fundamental_v1 --targets-file config/targets.stocks.json --scopes local

Log "Step 5/5: technical_v2 full retraining cycle (local scope)"
py -3.14 -m ops.run_local_scheduler --job full_retrain --scopes local

Log "Weekly retraining chain complete"
