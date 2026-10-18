"""Cash engine (WP-04): forecast, Monte Carlo bands, gaps, alerts, smoothing levers.

Pure functions over contracts: no database or network. Money is Decimal; the Monte Carlo runs
in integer paisa so every band is exact and reproducible from its seed.
"""
