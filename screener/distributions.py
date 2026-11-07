"""
distributions.py -- shared loader for data/distributions.csv.

One loader for every module that reads the hand-logged distribution
history, so the CSV's shape is handled in exactly one place:

- ex_date is parsed per row; an unparseable date (or amount) drops
  that row with a named warning instead of killing the run with a
  pandas traceback.
- Rows collapse to one row per (symbol, ex-date) before any test or
  average: the CSV logs one row per account, so a fund held in two
  accounts has two rows for the same payout. A disagreement on a
  logged value for one date is reported as a CONFLICT and the first
  logged value is used.
- total_received is SUMMED across the rows for one payout event (it
  is per-account cash; Roth + Traditional both arrived).
- Per-share values are validated before they feed any projection:
  non-positive values are excluded with a warning, and a value more
  than 3x the median of the symbol's other logged payouts is flagged
  as a likely logging slip and excluded, with a warning. Only the
  HIGH side is flagged: a low value is usually a real payout cut, but
  a 10x jump is the decimal-slip signature (0.5087 typed as 5.087).
  Flagging both sides would be self-defeating -- with two logged
  payouts and one slip, the good value looks 0.1x the bad one, and
  excluding both leaves no data at all. A decimal slip (0.5087 typed
  as 5.087) moves a monthly fund's headline 10x; this module is the
  only thing standing between the keystroke and the quote. Weekly
  payouts swing hard legitimately (AMDY's last-4 spans 0.3361-0.6677,
  a 2x range), so the bar is 3x, not a tight band.

Usage:
    log = DistributionLog(DISTRIBUTIONS_PATH)
    info = log.series("YMAX")   # deduped, validated per-share series
"""

from pathlib import Path

import pandas as pd

OUTLIER_FACTOR = 3.0


class DistributionLog:
    """The hand-logged distribution history, cleaned once for all readers."""

    def __init__(self, path):
        self.path = Path(path)
        self.issues = []  # warnings collected while loading (strings)
        self.df = pd.DataFrame()
        if not self.path.exists():
            self.issues.append(
                "No data/distributions.csv found -- copy "
                "data/distributions_template.csv and start logging."
            )
            return
        raw = pd.read_csv(self.path)
        if raw.empty:
            return
        if "ex_date" not in raw.columns:
            self.issues.append("distributions.csv has no ex_date column.")
            return
        # Parse dates per row so one bad row is named, not fatal.
        parsed = pd.to_datetime(raw["ex_date"], errors="coerce")
        bad = parsed.isna() & raw["ex_date"].notna()
        for idx in raw[bad].index:
            self.issues.append(
                "Skipping row {} ({} ex_date '{}'): unparseable date.".format(
                    int(idx) + 2, raw.at[idx, "symbol"], raw.at[idx, "ex_date"]
                )
            )
        raw = raw[~bad].copy()
        raw["ex_date"] = parsed[~bad]
        # Non-numeric per-share amounts are data errors, not crashes.
        if "distribution_per_share" in raw.columns:
            numeric = pd.to_numeric(raw["distribution_per_share"], errors="coerce")
            bad_amt = numeric.isna() & raw["distribution_per_share"].notna()
            for idx in raw[bad_amt].index:
                self.issues.append(
                    "Skipping per-share value on row {} ({} ex_date {}): "
                    "unparseable amount '{}'.".format(
                        int(idx) + 2,
                        raw.at[idx, "symbol"],
                        pd.Timestamp(raw.at[idx, "ex_date"]).strftime("%Y-%m-%d"),
                        raw.at[idx, "distribution_per_share"],
                    )
                )
            raw["distribution_per_share"] = numeric
        self.df = raw.sort_values(["symbol", "ex_date"], kind="mergesort").reset_index(drop=True)

    def _collapse(self, df_symbol):
        """One row per ex-date. Returns (deduped_df, conflicts)."""
        rows = []
        conflicts = []
        for ex_date, group in df_symbol.groupby("ex_date", sort=True):
            row = {"ex_date": ex_date}
            for col in ("distribution_per_share", "roc_pct", "market_price"):
                if col not in group.columns:
                    row[col] = float("nan")
                    continue
                logged = group[col].dropna().unique()
                if len(logged) > 1:
                    conflicts.append(
                        {
                            "ex_date": pd.Timestamp(ex_date).strftime("%Y-%m-%d"),
                            "column": col,
                            "values": [float(v) for v in sorted(logged)],
                            "used": float(logged[0]),
                        }
                    )
                row[col] = float(logged[0]) if len(logged) else float("nan")
            # total_received is per-account cash: Roth + Traditional both
            # arrived, so a payout event's cash is the SUM of its rows.
            if "total_received" in group.columns:
                row["total_received"] = group["total_received"].sum(min_count=1)
            else:
                row["total_received"] = float("nan")
            rows.append(row)
        deduped = pd.DataFrame(
            rows,
            columns=["ex_date", "distribution_per_share", "roc_pct",
                     "market_price", "total_received"],
        )
        return deduped.sort_values("ex_date").reset_index(drop=True), conflicts

    def series(self, symbol):
        """Deduped, validated per-share series for one symbol.

        Returns a dict with the validated values oldest-first, the last-4
        window, ROC aligned to that window, last-logged date, distinct
        payout count, and any conflicts / excluded values / warnings.
        """
        result = {
            "symbol": symbol,
            "values": [],          # validated per-share values, oldest first
            "dates": [],           # ex-dates matching values
            "last4": [],           # last 4 validated values
            "last4_dates": [],
            "roc_last4": [],       # roc_pct aligned with last4 (NaN unlogged)
            "latest_roc": float("nan"),
            "last_date": None,
            "n_distinct": 0,
            "excluded": [],        # (date_str, value, reason)
            "conflicts": [],
            "issues": [],
        }
        if self.df.empty or symbol not in set(self.df["symbol"].unique()):
            return result
        deduped, conflicts = self._collapse(self.df[self.df["symbol"] == symbol])
        result["conflicts"] = conflicts
        logged = deduped.dropna(subset=["distribution_per_share"]).reset_index(drop=True)
        blank = deduped[deduped["distribution_per_share"].isna()]
        for _, r in blank.iterrows():
            result["issues"].append(
                "{} {}: no per-share amount logged -- payout excluded from "
                "the average (window reaches one payout further back).".format(
                    symbol, pd.Timestamp(r["ex_date"]).strftime("%Y-%m-%d")
                )
            )
        if logged.empty:
            return result
        result["n_distinct"] = int(len(logged))
        result["last_date"] = logged["ex_date"].iloc[-1]

        # Validate the last-4 window (the values a projection actually
        # uses): non-positive, or >3x the median of the symbol's OTHER
        # logged payouts across its full history, is a likely logging
        # slip, not a payout. The reference is the full history, not
        # just the window: a monthly fund with only two payouts logged
        # has no window median to judge against, and a decimal slip is
        # 10x, far above any legitimate weekly swing (AMDY's widest
        # legitimate range is ~3x peak-to-trough across its history,
        # and the median-based test keeps it). Only the high side is
        # flagged: a low value is usually a real payout cut, and
        # flagging both sides would exclude the good value too when
        # only two payouts are logged (0.5087 looks 0.1x a 5.087 slip).
        window = logged.tail(4).reset_index(drop=True)
        all_vals = logged["distribution_per_share"].astype(float).tolist()
        window_idx = list(logged.tail(4).index)
        vals = window["distribution_per_share"].astype(float).tolist()
        keep = [True] * len(vals)
        for i, v in enumerate(vals):
            if v <= 0:
                keep[i] = False
                result["excluded"].append(
                    (
                        pd.Timestamp(window["ex_date"].iloc[i]).strftime("%Y-%m-%d"),
                        v,
                        "non-positive per-share amount",
                    )
                )
                continue
            others = [x for j, x in enumerate(all_vals) if j != window_idx[i]]
            if len(others) >= 1:
                med = float(pd.Series(others).median())
                if med > 0 and v > OUTLIER_FACTOR * med:
                    keep[i] = False
                    result["excluded"].append(
                        (
                            pd.Timestamp(window["ex_date"].iloc[i]).strftime("%Y-%m-%d"),
                            v,
                            "value is {:.1f}x the median of the symbol's other "
                            "logged payouts ({:.4f}) -- likely logging slip".format(
                                v / med, med
                            ),
                        )
                    )
        for (_, r), k in zip(window.iterrows(), keep):
            if k:
                result["values"].append(float(r["distribution_per_share"]))
                result["dates"].append(r["ex_date"])
        # Full validated history (for the distinct-count and last-date),
        # last-4 window, and ROC aligned to it.
        result["last4"] = result["values"][-4:]
        result["last4_dates"] = result["dates"][-4:]
        roc_by_date = {
            pd.Timestamp(d): (None if pd.isna(r) else float(r))
            for d, r in zip(deduped["ex_date"], deduped["roc_pct"])
        }
        result["roc_last4"] = [roc_by_date.get(pd.Timestamp(d)) for d in result["last4_dates"]]
        result["latest_roc"] = (
            result["roc_last4"][-1] if result["roc_last4"] else float("nan")
        )
        return result

    def window_rows(self, symbols, start_date, end_date):
        """Deduped payout rows in [start_date, end_date] for the given
        symbols. Each row: symbol, ex_date, per_share (validated value or
        None if excluded/unlogged), total_received (cash for that payout
        event, summed across accounts)."""
        rows = []
        if self.df.empty:
            return rows
        for symbol in symbols:
            info = self.series(symbol)
            kept = {pd.Timestamp(d): v for d, v in zip(info["dates"], info["values"])}
            deduped, _ = self._collapse(self.df[self.df["symbol"] == symbol])
            for _, r in deduped.iterrows():
                d = pd.Timestamp(r["ex_date"])
                if not (pd.Timestamp(start_date) <= d <= pd.Timestamp(end_date)):
                    continue
                tr = r["total_received"]
                rows.append(
                    {
                        "symbol": symbol,
                        "ex_date": d,
                        "per_share": kept.get(d),
                        "total_received": (None if pd.isna(tr) else float(tr)),
                    }
                )
        rows.sort(key=lambda r: (r["ex_date"], r["symbol"]))
        return rows
