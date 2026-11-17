"""Forecast GTA VI's launch-day Twitch viewers, hour by hour, as quantiles.

Approach: shape transfer from past big game launches.

A launch day on Twitch has a characteristic shape once you anchor it on the
first hour: viewers dip in the small hours, then climb as the world's time
zones unlock the game one by one (New Zealand first, Europe at 23:00-00:00Z,
the US east coast at 05:00Z, the west coast at 08:00Z) and peak in the
evening.  The size of that climb depends strongly on how much of the world
was already playing in hour 1: when hour 1 is small, the day can grow 5-10x;
when hour 1 is already huge, the day stays nearly flat.  Across the
comparable launches in the case file, the log ratio of each later hour to
hour 1 is close to linear in log(hour-1 viewers), so this program:

1. takes every comparable launch whose unlock was a rolling midnight
   (the unlock note says "midnight local" or "rolling", and not
   "simultaneous" / "single global" / "single time" -- a single worldwide
   unlock leaves hour 1 nearly empty and follows a different shape),
   with a real hour-1 count (>= 1,000 viewers);
2. for each forecast hour, regresses log(viewers / hour-1 viewers) on
   log(hour-1 viewers) across those launches (ordinary least squares) and
   predicts the ratio at this case's hour-1 count -- clamped to the range
   of hour-1 counts actually seen, so the program never extrapolates
   beyond the evidence;
3. sets the quantile spread from the regression's own residuals: the
   empirical 5/25/75/95% residual quantiles per hour, lightly smoothed
   across neighbouring hours so one noisy hour cannot pinch or blow up
   the band.

If too few rolling-midnight launches are in the case, it falls back to all
launches whose day did not explode from a near-empty hour 1 (peak / hour-1
<= 20x); if even that fails, it falls back to the persistence forecast
(every hour at hour 1's count, widening spread), so the output is always
a valid forecast.  Everything is computed from the case file at run time:
no network, no fitted constants smuggled in, standard library only,
deterministic (sorted iteration, no randomness, no wall-clock use).

Run locally:  mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
The grader runs:  python3 -P -s /bot/main.py  (Python 3.13, 8 s, 1 CPU).
"""

import json
import math
import os
import sys
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so `import model`
# finds a module shipped beside this file (none is needed today).
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# The quantile levels the contest scores, in the order each row lists them.
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# The standard normal's quantile at each level (persistence fallback only).
Z = [-1.645, -0.674, 0, 0.674, 1.645]

# A comparable only counts as a launch-hour anchor when hour 1 was real.
MIN_HOUR1 = 1000.0
# A day that grew more than this from hour 1 started from a near-empty
# hour 1 (a single worldwide unlock): a different shape, not a fallback.
MAX_PEAK_RATIO = 20.0
# How many rolling-midnight launches make the main fit trustworthy.
MIN_ROLLING = 6


def round2(x: float) -> float | int:
    """x rounded to 2 decimals, half up, as JavaScript's Math.round rounds it."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value.is_integer() else value


def quantile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation quantile of an already sorted list."""
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def ols(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Ordinary least squares: returns (intercept, slope) of y ~ a + b*x."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return my, 0.0
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    return my - b * mx, b


def smooth(values: list[float]) -> list[float]:
    """Three-point moving average (edges use the points that exist)."""
    out = []
    for i in range(len(values)):
        seg = values[max(0, i - 1):i + 2]
        out.append(sum(seg) / len(seg))
    return out


def is_rolling_midnight(comp: dict) -> bool:
    """True when the unlock note describes a rolling midnight launch."""
    text = (comp.get("unlock") or "").lower()
    rolling = "midnight local" in text or "rolling" in text
    single = ("simultaneous" in text or "single global" in text
              or "single time" in text)
    return rolling and not single


def release_day_hours(comp: dict) -> dict[int, float]:
    """Hour-of-day (0..23) -> viewers for the comparable's release day."""
    day_start = comp.get("day_start", "")[:10]  # YYYY-MM-DD of release day
    hours: dict[int, float] = {}
    for point in comp.get("hourly") or []:
        stamp = point.get("from") or ""
        if stamp[:10] != day_start:
            continue
        try:
            hour = int(stamp[11:13])
        except (ValueError, IndexError):
            continue
        viewers = point.get("viewers")
        if isinstance(viewers, (int, float)) and viewers > 0:
            hours[hour] = float(viewers)
    return hours


def collect_ratios(comps: list[dict]) -> list[tuple[float, dict[int, float]]]:
    """Per comparable: (log hour-1 viewers, {forecast hour: log ratio}).

    Forecast hour h covers [h-1, h) UTC, so its log ratio uses the
    release day's hour-of-day h-1, divided by hour-of-day 0 (hour 1).
    """
    out = []
    for comp in comps:
        day = release_day_hours(comp)
        if 0 not in day:
            continue
        v0 = day[0]
        if v0 < MIN_HOUR1:
            continue
        ratios: dict[int, float] = {}
        for h in range(2, 25):
            v = day.get(h - 1)
            if v is not None and v > 0:
                ratios[h] = math.log(v / v0)
        if ratios:
            out.append((math.log(v0), ratios))
    return out


def persistence_quantiles(p1: float, h: int) -> list[float | int]:
    """House-baseline fallback: flat at hour 1, widening spread."""
    return [round2(p1 * math.exp(z * 0.15 * math.sqrt(h - 1))) for z in Z]


def forecast_case(case: dict, name: str) -> dict:
    if case["levels"] != LEVELS:
        raise ValueError(f"{name} asks for levels {case['levels']}, not {LEVELS}")
    first = next((k for k in case["known"] if k["hour"] == 1), None)
    if first is None:
        raise ValueError(f"{name} has no hour-1 print")
    p1 = max(1.0, float(first["viewers"]))

    comps = case.get("comparables") or []
    rolling = [c for c in comps if is_rolling_midnight(c)]
    ratios = collect_ratios(rolling)
    if len(ratios) < MIN_ROLLING:
        # Fallback pool: every launch whose day did not explode from a
        # near-empty hour 1 (a single worldwide unlock follows another
        # shape entirely and would bend the fit).
        pool = []
        for comp in comps:
            day = release_day_hours(comp)
            if 0 not in day or day[0] < MIN_HOUR1:
                continue
            peak = max(day.values()) / day[0]
            if peak <= MAX_PEAK_RATIO:
                pool.append(comp)
        ratios = collect_ratios(pool)
    if len(ratios) < 3:
        return {"hours": [{"hour": h, "q": persistence_quantiles(p1, h)}
                          for h in range(2, 25)]}

    log_p1 = math.log(p1)
    lo = min(lv for lv, _ in ratios)
    hi = max(lv for lv, _ in ratios)
    # Never extrapolate the size trend beyond the launches actually seen.
    log_anchor = min(max(log_p1, lo), hi)

    medians: dict[int, float] = {}
    offsets: dict[float, list[float]] = {q: [] for q in (0.05, 0.25, 0.75, 0.95)}
    pooled_residuals: list[float] = []
    fits: dict[int, tuple[float, float, list[float]]] = {}
    for h in range(2, 25):
        points = [(lv, r[h]) for lv, r in ratios if h in r]
        if len(points) < 3:
            continue
        xs = [lv for lv, _ in points]
        ys = [y for _, y in points]
        a, b = ols(xs, ys)
        fits[h] = (a, b, sorted(y - (a + b * x) for x, y in points))
        pooled_residuals.extend(fits[h][2])
    pooled_residuals.sort()
    pooled = {q: quantile(pooled_residuals, q) for q in offsets}
    for h in range(2, 25):
        if h in fits:
            a, b, residuals = fits[h]
            medians[h] = a + b * log_anchor
            for q in offsets:
                offsets[q].append(quantile(residuals, q))
        else:
            # Too little evidence for this hour: stay near the ratios
            # actually seen for it (or flat), with the pooled band, so
            # one sparse hour can neither pinch nor blow up the forecast.
            seen = [r[h] for _, r in ratios if h in r]
            seen.sort()
            medians[h] = seen[len(seen) // 2] if seen else 0.0
            for q in offsets:
                offsets[q].append(pooled[q])
    for q in offsets:
        offsets[q] = smooth(offsets[q])

    hours = []
    for i, h in enumerate(range(2, 25)):
        qs = [p1 * math.exp(medians[h] + off)
              for off in (offsets[0.05][i], offsets[0.25][i], 0.0,
                          offsets[0.75][i], offsets[0.95][i])]
        # Enforce non-decreasing quantiles and the contest's bounds.
        clean: list[float | int] = []
        prev = 0.0
        for value in qs:
            value = min(max(value, 1.0), 1e9)
            value = max(value, prev)
            clean.append(round2(value))
            prev = float(clean[-1])
        hours.append({"hour": h, "q": clean})
    return {"hours": hours}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Every case file, in name order, so two runs write the same bytes.
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
