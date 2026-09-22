from __future__ import annotations

import pandas as pd
import yfinance as yf

from collector.providers.base import (
    AnalystConsensus,
    HistoricalPriceRequest,
    ensure_non_empty,
    normalize_price_frame,
)


class YFinanceProvider:
    name = "yfinance"

    def fetch_prices(self, request: HistoricalPriceRequest) -> pd.DataFrame:
        kwargs: dict[str, str | bool] = {
            "interval": request.interval,
            "auto_adjust": False,
            "progress": False,
        }
        if request.start:
            kwargs["start"] = request.start
        if request.end:
            kwargs["end"] = request.end
        if not request.start and not request.end:
            kwargs["period"] = "max"

        data = yf.download(request.ticker, **kwargs)
        data = ensure_non_empty(data, self.name, request.ticker)

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        data = data.reset_index().rename(
            columns={
                "Date": "timestamp",
                "Datetime": "timestamp",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )

        return normalize_price_frame(data, request.ticker, self.name)

    def fetch_analyst_consensus(self, ticker: str) -> AnalystConsensus:
        ticker_obj = yf.Ticker(ticker)

        info = ticker_obj.info
        if not info:
            raise ValueError(f"{self.name} returned no info for {ticker}")

        summary = ticker_obj.recommendations_summary
        if summary.empty:
            raise ValueError(f"{self.name} returned no analyst recommendations for {ticker}")

        current_period = summary.loc[summary["period"] == "0m"]
        if current_period.empty:
            raise ValueError(f"{self.name} returned no current-period recommendations for {ticker}")
        current = current_period.iloc[0]

        strong_buy = int(current["strongBuy"])
        buy = int(current["buy"])
        hold = int(current["hold"])
        sell = int(current["sell"])
        strong_sell = int(current["strongSell"])

        # Yahoo scores price-target coverage and rating coverage with different
        # analyst panels, so info["numberOfAnalystOpinions"] can diverge from the
        # rating buckets (e.g. 50 vs 55 for AMD); use the bucket sum since that's
        # what public finance widgets display as the analyst count.
        analyst_count = strong_buy + buy + hold + sell + strong_sell

        targets = ticker_obj.analyst_price_targets

        return AnalystConsensus(
            ticker=ticker.upper(),
            source=self.name,
            recommendation_key=info["recommendationKey"],
            recommendation_mean=float(info["recommendationMean"]),
            analyst_count=analyst_count,
            strong_buy=strong_buy,
            buy=buy,
            hold=hold,
            sell=sell,
            strong_sell=strong_sell,
            target_mean=float(targets["mean"]),
            target_median=float(targets["median"]),
            target_high=float(targets["high"]),
            target_low=float(targets["low"]),
        )
