"""Static catalog of the Mexico/US macro series Faro tracks.

Single source of truth for three consumers: ``collector/run_macro_job.py``
(which provider id to fetch and whether to transform it, and the rows that seed
``macro_series``), ``api/routers/macro.py`` (labels, units, frequencies, section
membership and order) and the tests.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MacroSeries:
    id: str
    country: str
    label: str  # es-MX
    frequency: str  # 'monthly' | 'weekly' | 'daily'
    source: str
    provider: str  # 'fred' | 'banxico'
    provider_id: str
    transform: str | None = None  # 'yoy': the provider serves an index level; store its 12-month % change
    unit: str = "percent"


MACRO_SERIES: tuple[MacroSeries, ...] = (
    MacroSeries("mx_inflation_yoy", "MX", "Inflación general (anual)", "monthly", "INEGI vía Banxico", "banxico", "SP30578"),
    MacroSeries("mx_core_inflation_yoy", "MX", "Inflación subyacente (anual)", "monthly", "INEGI vía Banxico", "banxico", "SP74662"),
    MacroSeries("us_cpi_yoy", "US", "Inflación general (anual)", "monthly", "BLS vía FRED", "fred", "CPIAUCNS", "yoy"),
    MacroSeries("us_core_cpi_yoy", "US", "Inflación subyacente (anual)", "monthly", "BLS vía FRED", "fred", "CPILFENS", "yoy"),
    MacroSeries("mx_policy_rate", "MX", "Tasa objetivo de Banxico", "daily", "Banxico", "banxico", "SF61745"),
    MacroSeries("mx_tiie28", "MX", "TIIE a 28 días", "daily", "Banxico", "banxico", "SF43783"),
    MacroSeries("mx_cetes_28d", "MX", "Cetes a 28 días", "weekly", "Banxico", "banxico", "SF43936"),
    MacroSeries("mx_cetes_91d", "MX", "Cetes a 91 días", "weekly", "Banxico", "banxico", "SF43939"),
    MacroSeries("mx_cetes_182d", "MX", "Cetes a 182 días", "weekly", "Banxico", "banxico", "SF43942"),
    MacroSeries("mx_cetes_364d", "MX", "Cetes a 364 días", "weekly", "Banxico", "banxico", "SF43945"),
    MacroSeries("us_fed_funds", "US", "Tasa de fondos federales", "daily", "Reserva Federal vía FRED", "fred", "DFF"),
    MacroSeries("us_breakeven_10y", "US", "Inflación implícita a 10 años", "daily", "Reserva Federal vía FRED", "fred", "T10YIE"),
)

SERIES_BY_ID: dict[str, MacroSeries] = {series.id: series for series in MACRO_SERIES}

# (key, label, series ids) in display order.
SECTIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("inflation", "Inflación", ("mx_inflation_yoy", "mx_core_inflation_yoy", "us_cpi_yoy", "us_core_cpi_yoy")),
    (
        "rates",
        "Tasas",
        (
            "mx_policy_rate",
            "mx_tiie28",
            "mx_cetes_28d",
            "mx_cetes_91d",
            "mx_cetes_182d",
            "mx_cetes_364d",
            "us_fed_funds",
            "us_breakeven_10y",
        ),
    ),
)


def catalog_rows() -> list[dict[str, str]]:
    """The ``macro_series`` rows the job upserts before writing observations."""
    return [
        {
            "id": series.id,
            "country": series.country,
            "label": series.label,
            "unit": series.unit,
            "frequency": series.frequency,
            "source": series.source,
        }
        for series in MACRO_SERIES
    ]
