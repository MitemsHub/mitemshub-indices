from __future__ import annotations

import csv
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

from synthetic_trader.domain import Tick

# CSV columns: the 3 originals + 3 derived rich columns
CSV_FIELDNAMES = ["epoch", "symbol", "price", "spread", "direction", "vol_proxy"]
# Legacy header for backward-compatible reading of old CSVs
_CSV_LEGACY_HEADER = "epoch,symbol,price"

MAX_TICKS_PER_CSV = 200_000
MAX_CSV_SIZE_TRIGGER = 20 * 1024 * 1024


@dataclass(frozen=True)
class TickDatasetReport:
    ticks: int
    symbols: tuple[str, ...]
    duplicates: int
    out_of_order: int
    first_epoch: float | None
    last_epoch: float | None
    min_price: float | None
    max_price: float | None
    mean_interval_sec: float
    max_interval_sec: float
    max_abs_return: float


def normalize_ticks(ticks: list[Tick]) -> tuple[list[Tick], int]:
    """Sort, deduplicate, and compute derived tick columns.

    After deduplication by (symbol, epoch, price), we compute per-symbol:
    - spread: half the absolute price change from the previous tick (bid-ask proxy)
    - tick_direction: +1 (up), -1 (down), 0 (flat)
    - volume_proxy: ticks-per-second (1 / time_delta) — higher = more activity
    """
    seen: set[tuple[str, float, float]] = set()
    normalized: list[Tick] = []
    duplicates = 0
    dropped_junk = 0
    for tick in sorted(ticks, key=lambda item: (item.symbol, item.epoch, item.price)):
        # Junk-row defense: drop ticks with epochs before year 2001 or in the
        # far future, and non-positive prices.  MT5's copy_rates_range can
        # return uninitialised rows (epoch 0, price 0.0/1.0/4.0) while the
        # terminal is still downloading history; without this filter those
        # rows get merged into the compounding corpus (mirrors the existing
        # epoch>1e9 guard in backfill_derived_columns).
        if tick.epoch < 1_000_000_000 or tick.epoch > time.time() + 3600:
            dropped_junk += 1
            continue
        if not (tick.price > 0.0):
            dropped_junk += 1
            continue
        key = (tick.symbol, tick.epoch, tick.price)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        normalized.append(tick)

    # Compute derived columns per symbol
    enriched: list[Tick] = []
    i = 0
    while i < len(normalized):
        sym = normalized[i].symbol
        group_start = i
        while i < len(normalized) and normalized[i].symbol == sym:
            i += 1
        group = normalized[group_start:i]
        prev_price: float | None = None
        prev_epoch: float | None = None
        for t in group:
            spread = 0.0
            direction = 0
            vol_proxy = 0.0
            if prev_price is not None:
                delta = t.price - prev_price
                spread = abs(delta) / 2.0
                if delta > 0:
                    direction = 1
                elif delta < 0:
                    direction = -1
                if prev_epoch is not None:
                    dt = t.epoch - prev_epoch
                    if dt > 0:
                        vol_proxy = 1.0 / dt
            enriched.append(Tick(
                symbol=t.symbol, epoch=t.epoch, price=t.price,
                spread=spread, tick_direction=direction, volume_proxy=vol_proxy,
            ))
            prev_price = t.price
            prev_epoch = t.epoch
    return enriched, duplicates


def _read_tail_ticks(csv_path: Path, symbol: str, max_count: int) -> list[Tick]:
    """Read the last *max_count* tick rows from a CSV file.

    Used by append_ticks_csv() to build a dedup set before appending.
    Reads only the tail of the file (up to 2 MB) for efficiency.
    Supports both legacy (3-col) and rich (6-col) CSV formats.
    """
    BUFFER_SIZE = 256 * 1024  # 256 KB
    MAX_READ = BUFFER_SIZE * 8  # 2 MB ceiling
    file_size = csv_path.stat().st_size
    if file_size <= 0:
        return []
    with csv_path.open("rb") as fh:
        fh.seek(0, 2)
        tail_chunks: list[bytes] = []
        accumulated = 0
        pos = file_size
        while pos > 0 and accumulated < MAX_READ:
            read = min(BUFFER_SIZE, pos)
            pos -= read
            fh.seek(pos)
            data = fh.read(read)
            tail_chunks.append(data)
            accumulated += read
            if data.startswith(b"\n") and accumulated > BUFFER_SIZE:
                break
    tail_bytes = b"".join(reversed(tail_chunks))
    if tail_bytes.startswith(b"\n"):
        tail_bytes = tail_bytes[1:]
    if not tail_bytes:
        return []
    # Skip the header line
    first_newline = tail_bytes.find(b"\n")
    if first_newline > 0:
        tail_bytes = tail_bytes[first_newline + 1:]
    lines = tail_bytes.decode("utf-8", errors="replace").splitlines()
    ticks: list[Tick] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) < 3:
            continue
        try:
            # Support both legacy (3-col) and rich (6-col) CSV formats
            spread = float(parts[3]) if len(parts) > 3 else 0.0
            direction = int(parts[4]) if len(parts) > 4 else 0
            vol_proxy = float(parts[5]) if len(parts) > 5 else 0.0
            ticks.append(Tick(
                symbol=symbol, epoch=float(parts[0]), price=float(parts[2]),
                spread=spread, tick_direction=direction, volume_proxy=vol_proxy,
            ))
        except (ValueError, IndexError):
            continue
        if len(ticks) >= max_count:
            break
    ticks.reverse()
    return ticks


def read_ticks_csv(path: str | Path, symbol: str = "") -> list[Tick]:
    """Read ALL ticks from a tick CSV (legacy 3-col or rich 6-col).

    Returns an empty list when the file is missing or empty.  *symbol* is
    only used to tag the returned :class:`Tick` objects (the rows carry no
    per-row symbol in the legacy format); pass the corpus symbol to get
    correctly-tagged ticks.
    """
    target = Path(path)
    if not target.exists() or target.stat().st_size == 0:
        return []
    return _read_full_ticks(target, symbol)


def write_ticks_csv(path: str | Path, ticks: list[Tick], append: bool = False) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    needs_header = not append or not target.exists() or target.stat().st_size == 0

    with target.open(mode, encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDNAMES)
        if needs_header:
            writer.writeheader()
        for tick in ticks:
            writer.writerow({
                "epoch": tick.epoch, "symbol": tick.symbol, "price": tick.price,
                "spread": tick.spread, "direction": tick.tick_direction,
                "vol_proxy": tick.volume_proxy,
            })


def _enrich_from_reference(reference: Tick, batch: list[Tick]) -> list[Tick]:
    """Compute spread/direction/volume_proxy for a batch of ticks.

    Uses *reference* as the previous tick to compute the first derived
    values, then chains through the batch sequentially.  Ticks that
    already carry non-zero spread values are left untouched.
    """
    enriched: list[Tick] = []
    prev_price: float = reference.price
    prev_epoch: float = reference.epoch
    for t in batch:
        # If tick already has computed columns, keep it as-is
        if t.spread != 0.0 or t.tick_direction != 0 or t.volume_proxy != 0.0:
            enriched.append(t)
            prev_price = t.price
            prev_epoch = t.epoch
            continue
        delta = t.price - prev_price
        spread = abs(delta) / 2.0
        if delta > 0:
            direction = 1
        elif delta < 0:
            direction = -1
        else:
            direction = 0
        dt = t.epoch - prev_epoch
        vol_proxy = 1.0 / dt if dt > 0 else 0.0
        enriched.append(Tick(
            symbol=t.symbol, epoch=t.epoch, price=t.price,
            spread=spread, tick_direction=direction, volume_proxy=vol_proxy,
        ))
        prev_price = t.price
        prev_epoch = t.epoch
    return enriched


def backfill_derived_columns(path: str | Path, symbol: str = "") -> int:
    """Recompute spread/direction/vol_proxy for every row in a CSV file.

    MT5 ticks arrive with zeros for these columns.  This function reads
    the entire CSV, computes the derived columns from consecutive price
    and epoch deltas, and atomically rewrites the file.

    Returns the number of rows rewritten.
    """
    target = Path(path)
    if not target.exists() or target.stat().st_size == 0:
        return 0

    # Read all ticks from the CSV
    if not symbol:
        # Try to detect symbol from filename: data/R_75_ticks.csv -> R_75
        stem = target.stem  # e.g. "R_75_ticks"
        symbol = stem.replace("_ticks", "")

    all_ticks = _read_full_ticks(target, symbol)
    if not all_ticks:
        return 0

    # Sort by epoch and filter junk rows (epoch < 2001 = before year 2001)
    # Legacy CSVs sometimes contain rows with tiny epochs and price=1.0/2.0
    all_ticks = [t for t in all_ticks if t.epoch > 1_000_000_000]
    all_ticks.sort(key=lambda t: t.epoch)

    # Deduplicate by (epoch, price)
    seen: set[tuple[float, float]] = set()
    deduped: list[Tick] = []
    for t in all_ticks:
        key = (t.epoch, t.price)
        if key not in seen:
            seen.add(key)
            deduped.append(t)
    all_ticks = deduped

    # Compute derived columns
    enriched: list[Tick] = []
    prev_price: float | None = None
    prev_epoch: float | None = None
    for t in all_ticks:
        spread = 0.0
        direction = 0
        vol_proxy = 0.0
        if prev_price is not None:
            delta = t.price - prev_price
            spread = abs(delta) / 2.0
            if delta > 0:
                direction = 1
            elif delta < 0:
                direction = -1
        if prev_epoch is not None:
            dt = t.epoch - prev_epoch
            if dt > 0:
                vol_proxy = 1.0 / dt
        enriched.append(Tick(
            symbol=t.symbol, epoch=t.epoch, price=t.price,
            spread=spread, tick_direction=direction, volume_proxy=vol_proxy,
        ))
        prev_price = t.price
        prev_epoch = t.epoch

    # Atomic rewrite
    fd, tmp_path = tempfile.mkstemp(suffix=".csv", dir=target.parent, prefix=target.stem + "_")
    try:
        os.close(fd)
        with open(tmp_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_FIELDNAMES)
            writer.writeheader()
            for t in enriched:
                writer.writerow({
                    "epoch": t.epoch, "symbol": t.symbol, "price": t.price,
                    "spread": t.spread, "direction": t.tick_direction,
                    "vol_proxy": t.volume_proxy,
                })
        os.replace(tmp_path, str(target))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return len(enriched)


def _read_full_ticks(csv_path: Path, symbol: str) -> list[Tick]:
    """Read ALL ticks from a CSV file (not just the tail).

    Used by backfill_derived_columns to process the entire file.
    Reads line-by-line (see the readline note below).
    """
    if not csv_path.exists() or csv_path.stat().st_size <= 0:
        return []

    ticks: list[Tick] = []
    with csv_path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        # Skip header.  Iterating with readline() is correct where chunked
        # reads are NOT: a 256KB chunk boundary can split a CSV line in half,
        # and parsing the fragments independently fabricates garbage ticks
        # (e.g. the tail "9999999999482,-1,4.0" of a split price becomes a
        # bogus epoch of ~1e13).  readline() never fragments lines.
        fh.readline()
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 3:
                continue
            try:
                spread = float(parts[3]) if len(parts) > 3 else 0.0
                direction = int(parts[4]) if len(parts) > 4 else 0
                vol_proxy = float(parts[5]) if len(parts) > 5 else 0.0
                ticks.append(Tick(
                    symbol=symbol, epoch=float(parts[0]), price=float(parts[2]),
                    spread=spread, tick_direction=direction, volume_proxy=vol_proxy,
                ))
            except (ValueError, IndexError):
                continue
    return ticks


# Price-scale guard: a wrong-scale venue must never pollute the compounding
# corpus.  Synthetic indices trade on DIFFERENT numeric scales per venue:
# Blueberry SYN75 ~1,500-2,000 vs Deriv 1HZ75V ~7,000-8,000 (R_100: SYN100
# ~350-400 vs 1HZ100V ~1,800-1,900).  The MT5-first venue rule already forbids
# Deriv fallback when MT5 is configured, but a process without MT5 env vars
# (diagnostic runs, dev shells, mis-configured collectors) can still append
# wrong-scale ticks.  We guard the append itself: any tick whose price is more
# than SCALE_GUARD_MAX_RATIO away from the existing corpus median is dropped
# with a loud warning instead of being merged into the corpus.
SCALE_GUARD_MAX_RATIO = 4.0


def _apply_scale_guard(ticks: list[Tick], existing: list[Tick]) -> list[Tick]:
    """Drop ticks whose price deviates wildly from the existing corpus scale.

    Returns the filtered list.  If the existing corpus is too small to judge
    scale (< 20 ticks) the batch passes through unchanged.
    """
    if len(existing) < 20:
        return ticks
    prices = sorted(t.price for t in existing if t.price and t.price > 0)
    if not prices:
        return ticks
    median = prices[len(prices) // 2]
    if median <= 0:
        return ticks
    kept: list[Tick] = []
    dropped = 0
    for t in ticks:
        if t.price <= 0:
            kept.append(t)
            continue
        ratio = t.price / median
        if ratio > SCALE_GUARD_MAX_RATIO or ratio < 1.0 / SCALE_GUARD_MAX_RATIO:
            dropped += 1
            continue
        kept.append(t)
    if dropped:
        print(
            f"[tick_store] WARNING: dropped {dropped} tick(s) outside the corpus price scale "
            f"(corpus median {median:.2f}, ratio must be within 1/{SCALE_GUARD_MAX_RATIO:.0f}x-{SCALE_GUARD_MAX_RATIO:.0f}x) "
            "— refusing to pollute the compounding corpus with wrong-scale prices",
            file=sys.stderr,
            flush=True,
        )
    return kept


def append_ticks_csv(path: str | Path, ticks: list[Tick]) -> None:
    """Append ticks to CSV, deduplicating by (epoch, price) against existing data.

    New ticks are enriched with spread/direction/volume_proxy derived from
    the last existing tick in the CSV before writing.  A price-scale guard
    rejects ticks on a wildly different price scale (e.g. Deriv 1HZ75V ~7,000
    appended into a Blueberry SYN75 corpus ~1,770) so wrong-venue data can
    never pollute the compounding corpus.
    """
    if not ticks:
        return
    target = Path(path)
    if target.exists() and target.stat().st_size > 0:
        existing = _read_tail_ticks(target, ticks[0].symbol if ticks else '', max_count=len(ticks) * 10)
        ticks = _apply_scale_guard(ticks, existing)
        if not ticks:
            return
        existing_keys: set[tuple[float, float]] = {(t.epoch, t.price) for t in existing}
        fresh = [t for t in ticks if (t.epoch, t.price) not in existing_keys]
        if not fresh:
            return
        # Enrich raw ticks using the last existing tick as reference
        if existing:
            fresh = _enrich_from_reference(existing[-1], fresh)
        else:
            # Existing CSV but couldn't read tail — enrich from first fresh tick
            if len(fresh) > 1:
                fresh = [fresh[0]] + _enrich_from_reference(fresh[0], fresh[1:])
        write_ticks_csv(path, fresh, append=True)
    else:
        # No existing data - enrich starting from the first tick as reference
        if len(ticks) > 1:
            enriched = _enrich_from_reference(ticks[0], ticks[1:])
            write_ticks_csv(path, [ticks[0]] + enriched, append=True)
        else:
            write_ticks_csv(path, ticks, append=True)
    _prune_csv(path)



def _prune_csv(path: str | Path, max_ticks: int = MAX_TICKS_PER_CSV) -> None:
    target = Path(path)
    if not target.exists():
        return
    file_size = target.stat().st_size
    if file_size <= MAX_CSV_SIZE_TRIGGER:
        return
    try:
        _capped_rewrite(target, max_ticks)
    except Exception:
        pass


def _capped_rewrite(target: Path, max_ticks: int) -> None:
    BUFFER_SIZE = 256 * 1024
    file_size = target.stat().st_size
    tail_chunks: list[bytes] = []
    accumulated = 0
    pos = file_size
    while pos > 0 and accumulated < BUFFER_SIZE * 6:
        read = min(BUFFER_SIZE, pos)
        pos -= read
        with target.open("rb") as fh:
            fh.seek(pos)
            data = fh.read(read)
        tail_chunks.append(data)
        accumulated += read
        if data.startswith(b"\n") and accumulated > BUFFER_SIZE:
            break
    tail_bytes = b"".join(reversed(tail_chunks))
    if tail_bytes.startswith(b"\n"):
        tail_bytes = tail_bytes[1:]
    first_newline = tail_bytes.find(b"\n")
    if first_newline > 0:
        tail_bytes = tail_bytes[first_newline + 1:]
    lines = tail_bytes.decode("utf-8", errors="replace").splitlines()
    last_lines: list[str] = []
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        last_lines.append(stripped)
        if len(last_lines) >= max_ticks + 1:
            break
    last_lines.reverse()
    if not last_lines:
        return
    if last_lines[0].startswith("epoch"):
        last_lines = last_lines[1:]
    fd, tmp_path = tempfile.mkstemp(suffix=".csv", dir=target.parent, prefix=target.stem + "_")
    try:
        os.close(fd)
        with open(tmp_path, "w", encoding="utf-8", newline="") as fh:
            fh.write("epoch,symbol,price,spread,direction,vol_proxy\n")
            fh.write("\n".join(last_lines))
            fh.write("\n")
        os.replace(tmp_path, str(target))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def inspect_ticks(ticks: list[Tick], symbol: str | None = None) -> TickDatasetReport:
    selected = [tick for tick in ticks if symbol is None or tick.symbol == symbol]
    if not selected:
        return TickDatasetReport(
            ticks=0,
            symbols=(),
            duplicates=0,
            out_of_order=0,
            first_epoch=None,
            last_epoch=None,
            min_price=None,
            max_price=None,
            mean_interval_sec=0.0,
            max_interval_sec=0.0,
            max_abs_return=0.0,
        )

    _, duplicates = normalize_ticks(selected)
    out_of_order = sum(1 for previous, current in zip(selected[:-1], selected[1:]) if current.epoch < previous.epoch)
    ordered = sorted(selected, key=lambda item: item.epoch)
    intervals = [
        current.epoch - previous.epoch
        for previous, current in zip(ordered[:-1], ordered[1:])
        if current.symbol == previous.symbol
    ]
    returns = [
        abs((current.price - previous.price) / previous.price)
        for previous, current in zip(ordered[:-1], ordered[1:])
        if current.symbol == previous.symbol and previous.price != 0
    ]

    return TickDatasetReport(
        ticks=len(selected),
        symbols=tuple(sorted({tick.symbol for tick in selected})),
        duplicates=duplicates,
        out_of_order=out_of_order,
        first_epoch=ordered[0].epoch,
        last_epoch=ordered[-1].epoch,
        min_price=min(tick.price for tick in selected),
        max_price=max(tick.price for tick in selected),
        mean_interval_sec=mean(intervals) if intervals else 0.0,
        max_interval_sec=max(intervals) if intervals else 0.0,
        max_abs_return=max(returns) if returns else 0.0,
    )
