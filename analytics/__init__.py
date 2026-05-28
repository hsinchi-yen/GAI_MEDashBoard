"""Analytics: derived statistics that consume the macro data dictionary."""

from .gmi_backtest import (
    REGIME_ORDER,
    DEFAULT_HORIZONS,
    compute_forward_returns,
    summarize_by_regime,
    compute_cross_correlation,
)

__all__ = [
    "REGIME_ORDER",
    "DEFAULT_HORIZONS",
    "compute_forward_returns",
    "summarize_by_regime",
    "compute_cross_correlation",
]
