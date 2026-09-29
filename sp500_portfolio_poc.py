#!/usr/bin/env python3
"""Build a reproducible 100-company S&P 500 portfolio using Yahoo Close prices."""

from __future__ import annotations

import argparse
import io
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import requests

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
CONSTITUENTS_CSV = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
HISTORICAL_CSV = "https://raw.githubusercontent.com/MarcosBayas95/DEBER-1-U3-all_stocks_5yr.csv/master/all_stocks_5yr.csv"
BENCHMARK = "^GSPC"
TRADING_DAYS = 252
RISK_FREE_RATE = 0.02


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    return parser.parse_args()


def constituents() -> pd.DataFrame:
    try:
        table = pd.read_html(WIKI_URL, attrs={"id": "constituents"})[0]
    except Exception:
        table = pd.read_csv(CONSTITUENTS_CSV)
    chosen = (table[["Symbol", "Security"]].drop_duplicates("Symbol")
              .sort_values("Symbol").head(100).copy())
    chosen["yahoo_symbol"] = chosen["Symbol"].str.replace(".", "-", regex=False)
    if len(chosen) != 100 or chosen["Symbol"].nunique() != 100:
        raise RuntimeError("Nije moguće odabrati 100 različitih kompanija")
    return chosen.reset_index(drop=True)


def historical_fallback() -> tuple[pd.DataFrame, pd.DataFrame, date]:
    """Load the public Kaggle S&P snapshot mirrored on GitHub when Yahoo is blocked."""
    response = requests.get(HISTORICAL_CSV, timeout=90)
    response.raise_for_status()
    data = pd.read_csv(io.BytesIO(response.content), parse_dates=["date"])
    available = set(data["Name"].unique())
    table = pd.read_csv(CONSTITUENTS_CSV)
    selected = (table.loc[table["Symbol"].isin(available), ["Symbol", "Security"]]
                .drop_duplicates("Symbol").sort_values("Symbol").head(100).copy())
    selected["yahoo_symbol"] = selected["Symbol"]
    if len(selected) != 100:
        raise RuntimeError("Rezervni izvor nema 100 aktualnih različitih kompanija")
    close = data.pivot(index="date", columns="Name", values="close").sort_index()
    # A daily equal-weight return across the complete snapshot is a transparent
    # S&P 500 proxy because the snapshot does not contain the index itself.
    proxy_return = close.pct_change(fill_method=None).mean(axis=1)
    proxy = (1 + proxy_return.fillna(0)).cumprod().rename(BENCHMARK)
    close[BENCHMARK] = proxy
    return selected.reset_index(drop=True), close, close.index.max().date()


def close_prices(tickers: list[str], start: date, end_exclusive: date) -> pd.DataFrame:
    # Fail quickly and quietly when an execution environment blocks Yahoo's host,
    # rather than letting one worker emit an error for every ticker.
    probe = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC",
                         timeout=5)
    probe.raise_for_status()
    raw = yf.download(tickers, start=start.isoformat(), end=end_exclusive.isoformat(),
                      auto_adjust=False, actions=False, progress=False,
                      group_by="column", threads=True, timeout=30)
    if raw.empty:
        raise RuntimeError("Yahoo Finance nije vratio podatke")
    close = raw["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    return close.sort_index().reindex(columns=tickers)


def sri(volatility: float) -> int | float:
    if not np.isfinite(volatility):
        return np.nan
    return int(np.searchsorted([0.05, 0.10, 0.15, 0.20, 0.30, 0.50], volatility) + 1)


def calculate(symbol: str, prices: pd.Series, market: pd.Series,
              start: date, as_of: date) -> dict[str, object]:
    prices = prices.dropna()
    returns = prices.pct_change(fill_method=None).dropna()
    first = prices.index.min() if not prices.empty else pd.NaT
    last = prices.index.max() if not prices.empty else pd.NaT
    full = (not prices.empty and first.date() <= start + timedelta(days=7)
            and last.date() >= as_of - timedelta(days=7))
    reason = ""
    if prices.empty:
        reason = "nema podataka"
    elif first.date() > start + timedelta(days=7):
        reason = "povijest počinje nakon tolerancije"
    elif last.date() < as_of - timedelta(days=7):
        reason = "povijest završava prije tolerancije"

    vol = returns.std(ddof=1) * math.sqrt(TRADING_DAYS) if len(returns) > 1 else np.nan
    years = (last - first).days / 365.25 if len(prices) > 1 else np.nan
    annual_return = ((prices.iloc[-1] / prices.iloc[0]) ** (1 / years) - 1
                     if np.isfinite(years) and years > 0 and prices.iloc[0] > 0 else np.nan)
    sharpe = (annual_return - RISK_FREE_RATE) / vol if np.isfinite(vol) and vol > 0 else np.nan
    paired = pd.concat([returns.rename("stock"), market.rename("market")], axis=1).dropna()
    beta = (paired["stock"].cov(paired["market"]) / paired["market"].var(ddof=1)
            if len(paired) > 1 and paired["market"].var(ddof=1) > 0 else np.nan)
    return {
        "symbol": symbol, "first_date": first.date().isoformat() if pd.notna(first) else "",
        "last_date": last.date().isoformat() if pd.notna(last) else "",
        "price_observations": len(prices), "return_observations": len(returns),
        "full_five_year_history": bool(full), "incomplete_reason": reason,
        "annual_return": annual_return, "annual_volatility": vol,
        "sharpe_ratio": sharpe, "beta_sp500": beta, "simulated_sri": sri(vol),
    }


def daily_close_output(prices: pd.DataFrame, selected: pd.DataFrame,
                       portfolio: pd.DataFrame) -> pd.DataFrame:
    """Return the source Close observations in tidy form, without filling gaps."""
    symbol_lookup = selected.set_index("yahoo_symbol")["Symbol"]
    sri_lookup = portfolio.set_index("yahoo_symbol")["simulated_sri"]
    daily = (prices[selected["yahoo_symbol"].tolist()]
             .rename_axis(index="date", columns="yahoo_symbol")
             .stack(future_stack=True)
             .dropna()
             .rename("close")
             .reset_index())
    daily.insert(1, "symbol", daily["yahoo_symbol"].map(symbol_lookup))
    daily["simulated_sri"] = daily["yahoo_symbol"].map(sri_lookup)
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    return daily[["date", "symbol", "yahoo_symbol", "close", "simulated_sri"]]


def main() -> None:
    args = arguments()
    selected = constituents()
    tickers = selected["yahoo_symbol"].tolist()
    try:
        start = args.as_of.replace(year=args.as_of.year - 5)
        end = args.as_of + timedelta(days=1)
        prices = close_prices(tickers + [BENCHMARK], start, end)
        if prices[tickers].notna().sum().sum() == 0:
            raise RuntimeError("Yahoo nije vratio cijene kompanija")
        source = "Yahoo Finance"
        benchmark_kind = "S&P 500 (^GSPC)"
    except Exception as exc:
        print(f"Primarni dohvat nije uspio ({exc}); koristim javni povijesni snapshot.")
        selected, prices, fallback_as_of = historical_fallback()
        args.as_of = fallback_as_of
        start = args.as_of.replace(year=args.as_of.year - 5)
        prices = prices.loc[prices.index.date >= start]
        tickers = selected["yahoo_symbol"].tolist()
        source = "Kaggle all_stocks_5yr (GitHub mirror)"
        benchmark_kind = "jednako ponderirani S&P snapshot proxy"
    market_returns = prices[BENCHMARK].pct_change(fill_method=None).dropna()
    rows = [calculate(t, prices[t], market_returns, start, args.as_of) for t in tickers]
    metrics = pd.DataFrame(rows)
    portfolio = selected.merge(metrics, left_on="yahoo_symbol", right_on="symbol").drop(columns="symbol")
    portfolio.insert(3, "data_source", source)
    portfolio.insert(4, "benchmark", benchmark_kind)
    daily = daily_close_output(prices, selected, portfolio)

    # Independent vector checks catch accidental changes to the implemented formulas.
    rets = prices[tickers].apply(lambda column: column.dropna().pct_change(fill_method=None))
    expected_vol = rets.std(ddof=1) * np.sqrt(TRADING_DAYS)
    def expected_sharpe(column: pd.Series) -> float:
        column = column.dropna()
        years = (column.index[-1] - column.index[0]).days / 365.25
        annual = (column.iloc[-1] / column.iloc[0]) ** (1 / years) - 1
        return (annual - RISK_FREE_RATE) / (column.pct_change().dropna().std(ddof=1) * np.sqrt(TRADING_DAYS))

    sharpe_check = prices[tickers].apply(expected_sharpe)
    beta_check = rets.apply(lambda x: pd.concat([x, market_returns], axis=1).dropna().cov().iloc[0, 1]
                            / pd.concat([x, market_returns], axis=1).dropna().iloc[:, 1].var(ddof=1))
    summary_symbols = set(portfolio["Symbol"])
    daily_symbols = set(daily["symbol"])
    daily_counts = daily.groupby("symbol").size()
    expected_counts = portfolio.set_index("Symbol")["price_observations"]
    source_close = (prices[tickers].rename_axis(index="date", columns="yahoo_symbol")
                    .stack(future_stack=True).dropna().sort_index())
    emitted_close = (daily.assign(date=pd.to_datetime(daily["date"]))
                     .set_index(["date", "yahoo_symbol"])["close"].sort_index())
    checks = [
        ("selected_rows_100", len(portfolio) == 100, len(portfolio)),
        ("unique_company_symbols_100", portfolio["Symbol"].nunique() == 100, portfolio["Symbol"].nunique()),
        ("daily_unique_symbols_100", daily["symbol"].nunique() == 100, daily["symbol"].nunique()),
        ("summary_daily_symbol_sets_match", summary_symbols == daily_symbols,
         f"summary={len(summary_symbols)}; daily={len(daily_symbols)}"),
        ("daily_rows", len(daily) > 0, len(daily)),
        ("daily_date_range", len(daily) > 0,
         f"{daily['date'].min()}..{daily['date'].max()}"),
        ("daily_date_symbol_duplicates_zero", not daily.duplicated(["date", "symbol"]).any(),
         int(daily.duplicated(["date", "symbol"]).sum())),
        ("daily_close_missing_zero", not daily["close"].isna().any(), int(daily["close"].isna().sum())),
        ("daily_close_nonpositive_zero", not daily["close"].le(0).any(), int(daily["close"].le(0).sum())),
        ("daily_counts_match_price_observations", daily_counts.equals(expected_counts),
         f"mismatches={(daily_counts != expected_counts).sum()}"),
        ("daily_close_matches_calculation_input", source_close.equals(emitted_close), len(daily)),
        ("daily_sri_constant_per_symbol", daily.groupby("symbol")["simulated_sri"].nunique().eq(1).all(),
         int(daily.groupby("symbol")["simulated_sri"].nunique().max())),
        ("daily_sri_matches_summary", daily.groupby("symbol")["simulated_sri"].first().equals(
            portfolio.set_index("Symbol")["simulated_sri"]), "exact"),
        ("volatility_formula_matches", np.allclose(portfolio.set_index("yahoo_symbol")["annual_volatility"], expected_vol, equal_nan=True), "rtol=1e-05"),
        ("sharpe_formula_matches", np.allclose(portfolio.set_index("yahoo_symbol")["sharpe_ratio"], sharpe_check, equal_nan=True), "rtol=1e-05"),
        ("beta_formula_matches", np.allclose(portfolio.set_index("yahoo_symbol")["beta_sp500"], beta_check, equal_nan=True), "rtol=1e-05"),
        ("sharpe_values_finite", np.isfinite(portfolio["sharpe_ratio"]).all(), int(np.isfinite(portfolio["sharpe_ratio"]).sum())),
        ("sri_between_1_and_7", portfolio["simulated_sri"].between(1, 7).all(), int(portfolio["simulated_sri"].notna().sum())),
    ]
    validation = pd.DataFrame(checks, columns=["check", "passed", "detail"])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected.to_csv(args.output_dir / "selected_companies.csv", index=False)
    portfolio.to_csv(args.output_dir / "sp500_portfolio.csv", index=False, float_format="%.10f")
    daily.to_csv(args.output_dir / "yahoo_close_prices.csv", index=False, float_format="%.10f")
    portfolio.loc[~portfolio["full_five_year_history"]].to_csv(
        args.output_dir / "incomplete_history.csv", index=False, float_format="%.10f")
    validation.to_csv(args.output_dir / "validation_summary.csv", index=False)
    print(validation.to_string(index=False))
    print(f"Dnevni CSV: {len(daily)} redaka, {daily['symbol'].nunique()} simbola, "
          f"{daily['date'].min()} do {daily['date'].max()}")
    print(f"Nepotpuna povijest: {(~portfolio['full_five_year_history']).sum()}")
    if not validation["passed"].all():
        raise RuntimeError("Jedna ili više validacija nije prošla")


if __name__ == "__main__":
    main()
