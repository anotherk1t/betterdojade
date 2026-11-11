#!/usr/bin/env python3
"""Shared parsing/feature helpers for the delay-predictor improvement experiments."""
import gzip
import json
import math
import os
from datetime import datetime, timezone

GDANSK_ROUTES = {
    '10', '100', '106', '107', '108', '11', '110', '111', '112', '113', '115', '116', '117', '118',
    '12', '120', '122', '123', '124', '126', '127', '130', '131', '132', '136', '138', '143', '148',
    '149', '154', '155', '156', '157', '158', '162', '166', '167', '168', '169', '171', '174', '175',
    '176', '178', '179', '183', '184', '186', '189', '195', '199', '2', '200', '205', '207', '208',
    '210', '212', '213', '227', '232', '255', '256', '258', '262', '267', '268', '269', '283', '289',
    '295', '3', '307', '4', '5', '512', '6', '7', '8', '9', '911',
    'N1', 'N14', 'N16', 'N2', 'N3', 'N4', 'N5', 'N6', 'N78', 'N8', 'N89', 'N9', 'T8',
}
MIDNIGHT_S = 79200
MAX_CORR_S = 7200

# Dump column layout (all float32).  Keep this list in sync with dump_rows.py.
COLS = [
    'route', 'stop', 'vsvc', 'headsign',
    'lead_min', 'hour', 'dow', 'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos',
    'current_delay', 'prev1', 'prev2', 'delta_prev1', 'delta_prev2',
    'hist_mean3', 'hist_std3', 'obs_index', 'obs_total', 'obs_count',
    'target', 'event_id', 'theo_day', 'snap_day',
    'hist_mean5', 'hist_std5', 'obs_span_min', 'trend_per_min',
    'old_route', 'old_stop', 'old_vsvc', 'old_headsign',
]
NCOLS = len(COLS)
IDX = {c: i for i, c in enumerate(COLS)}

_HSIN = [math.sin(2.0 * math.pi * h / 24.0) for h in range(24)]
_HCOS = [math.cos(2.0 * math.pi * h / 24.0) for h in range(24)]
_DSIN = [math.sin(2.0 * math.pi * d / 7.0) for d in range(7)]
_DCOS = [math.cos(2.0 * math.pi * d / 7.0) for d in range(7)]


def extract_snapshot_ts(path):
    base = os.path.basename(path)
    stem = base.replace('.json.gz', '').replace('.json', '')
    try:
        return int(stem.split('_')[-1]) / 1000.0
    except (ValueError, IndexError):
        return None


def parse_iso_ts(s):
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
    except (ValueError, AttributeError, TypeError):
        return None


def normalize_delay(d):
    if d is None:
        return None
    try:
        d = float(d)
    except (TypeError, ValueError):
        return None
    if abs(d) > MIDNIGHT_S:
        c = d - 86400 if d > 0 else d + 86400
        return c if abs(c) <= MAX_CORR_S else None
    return d


def parse_file(path):
    """Parse one snapshot file -> (snapshot_ts, items, failed_flag)."""
    snap = extract_snapshot_ts(path)
    if snap is None:
        return None
    try:
        opener = gzip.open if path.endswith('.gz') else open
        with opener(path, 'rb') as fh:
            data = json.loads(fh.read())
    except (OSError, ValueError, EOFError):
        return (snap, [], 1)
    if not isinstance(data, dict):
        return (snap, [], 1)
    items = []
    for stop_id, sd in data.items():
        if not isinstance(sd, dict):
            continue
        for dep in sd.get('departures', []) or []:
            if dep.get('status') != 'REALTIME':
                continue
            route = str(dep.get('routeShortName', '')).strip()
            if route not in GDANSK_ROUTES:
                continue
            delay = normalize_delay(dep.get('delayInSeconds'))
            if delay is None or delay < -1200 or delay > 3600:
                continue
            trip = dep.get('trip')
            theo = dep.get('theoreticalTime')
            if trip is None or not theo:
                continue
            ts = parse_iso_ts(theo)
            if ts is None or ts - snap < 0 or ts - snap > 3600:
                continue
            items.append((
                (str(trip), str(stop_id), str(theo)),
                (snap, delay, route, str(stop_id), str(dep.get('vehicleService', '')), ts,
                 str(dep.get('headsign', ''))),
            ))
    return (snap, items, 0)


def parse_file_vocab(path):
    """Cheap parse that only returns category values (no items)."""
    snap = extract_snapshot_ts(path)
    if snap is None:
        return None
    try:
        opener = gzip.open if path.endswith('.gz') else open
        with opener(path, 'rb') as fh:
            data = json.loads(fh.read())
    except (OSError, ValueError, EOFError):
        return (snap, [], 1)
    if not isinstance(data, dict):
        return (snap, [], 1)
    out = []
    for stop_id, sd in data.items():
        if not isinstance(sd, dict):
            continue
        for dep in sd.get('departures', []) or []:
            if dep.get('status') != 'REALTIME':
                continue
            route = str(dep.get('routeShortName', '')).strip()
            if route not in GDANSK_ROUTES:
                continue
            out.append((route, str(stop_id), str(dep.get('vehicleService', '')),
                        str(dep.get('headsign', ''))))
    return (snap, out, 0)


def bounded_imap(executor, fn, iterable, max_pending=12):
    from collections import deque
    it = iter(iterable)
    pending = deque()
    for _ in range(max_pending):
        try:
            pending.append(executor.submit(fn, next(it)))
        except StopIteration:
            break
    while pending:
        fut = pending.popleft()
        yield fut.result()
        try:
            pending.append(executor.submit(fn, next(it)))
        except StopIteration:
            pass


def fmt_ts(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)
