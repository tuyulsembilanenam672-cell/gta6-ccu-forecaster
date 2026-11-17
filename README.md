# gta6-ccu-forecaster

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/tuyulsembilanenam672-cell/gta6-ccu-forecaster/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/tuyulsembilanenam672-cell/gta6-ccu-forecaster/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Forecasts Grand Theft Auto VI's launch-day Twitch concurrent viewers, hour by hour (hours 2–24 of 2026-11-19 UTC), as five quantiles per hour, from everything recorded up to the end of hour 1.

## Approach

A launch day has a characteristic shape once anchored on hour 1: viewers dip in the small hours, then climb as time zones unlock the game one by one (New Zealand first, Europe at 23:00–00:00Z, the US east coast at 05:00Z, the west coast at 08:00Z) and peak in the evening. How far the day climbs depends strongly on how much of the world was already playing in hour 1 — a small hour 1 can grow 5–10x, a huge one stays nearly flat. Across the comparable launches shipped in each case file, the log ratio of each later hour to hour 1 is close to linear in log(hour-1 viewers), so `main.py`:

1. takes the comparable launches whose unlock was a rolling midnight (unlock note says "midnight local" or "rolling", not "simultaneous" / "single global"), with a real hour-1 count;
2. regresses each hour's log ratio on log(hour-1 viewers) across those launches and predicts at this case's hour-1 count, clamped to the range actually seen, so it never extrapolates beyond the evidence;
3. sets the quantile spread from the regression's own residuals (empirical 5/25/75/95% quantiles per hour, lightly smoothed across neighbouring hours).

Everything is computed from the case file at run time — no network, no fitted constants, standard library only, deterministic. If too few rolling-midnight launches are present it falls back to launches whose day did not explode from a near-empty hour 1, and then to a flat persistence forecast, so the output is always valid.

On the kit's four practice launches (Marvel's Wolverine, Red Dead Redemption 2, God of War Ragnarök, Marvel's Spider-Man 2, scored against the historical hourly counts) this scores a mean pinball loss of **0.158**, against **0.387** for the house persistence baseline — a 59% improvement, with a typical median miss of ~26% vs ~83%.

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

`main.py` reads every `*.in` case in the input directory and writes one `*.out` forecast per case (23 rows, hours 2–24, five quantiles each). Python 3.13, standard library only.

---

<sub>Entered on [make.fun](https://make.fun/?ref=sq78y28z&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
