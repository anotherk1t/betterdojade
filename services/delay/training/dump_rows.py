#!/usr/bin/env python3
"""
Dump feature rows for one time window to a raw float32 binary file.

Events are assembled across snapshots (keyed by trip, stop, theoretical time),
then each observation except the last becomes one row.  All row construction is
vectorised per event.

Usage:
  python dump_rows.py --start 2026-09-01T00:00:00 --end 2026-10-25T00:00:00 \
      --estimations /home/yan/bikerouter/data/estimations \
      --vocab vocab.json --old-encoders tree_delay_encoders.json \
      --out dumps/train.bin --event-rate 0.08 --workers 6
"""
import argparse
import hashlib
import heapq
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from glob import glob

import numpy as np

from common import (COLS, NCOLS, IDX, GDANSK_ROUTES, _HSIN, _HCOS, _DSIN, _DCOS,
                    parse_file, bounded_imap, fmt_ts, extract_snapshot_ts)


def dt_ts(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()


def keep_event(key, rate):
    if rate >= 1.0:
        return True
    h = hashlib.blake2b(('|'.join(key)).encode(), digest_size=8).digest()
    return int.from_bytes(h, 'little') < rate * (1 << 64)


class Writer:
    def __init__(self, path, ncols):
        self.path = path
        self.f = open(path, 'wb')
        self.n = 0
        self.ncols = ncols

    def add(self, arr):
        arr = np.ascontiguousarray(arr, dtype=np.float32)
        arr.tofile(self.f)
        self.n += arr.shape[0]

    def close(self):
        self.f.close()


def build_event_array(obs, codes, event_id, keep):
    """obs: list of (snap, delay, route, stop, vsvc, theo, headsign), sorted."""
    n = len(obs)
    nr = n - 1
    if nr <= 0:
        return None
    snaps = np.fromiter((o[0] for o in obs), dtype=np.float64, count=n)
    delays = np.fromiter((o[1] for o in obs), dtype=np.float64, count=n)
    theo = obs[0][5]
    idx = np.arange(nr)

    cur = delays[:-1]
    prev1 = np.where(idx >= 1, delays[np.maximum(idx - 1, 0)], delays[0])
    prev2 = np.where(idx >= 2, delays[np.maximum(idx - 2, 0)], prev1)

    def win_stats(k):
        cs = np.concatenate(([0.0], np.cumsum(delays)))
        cs2 = np.concatenate(([0.0], np.cumsum(delays * delays)))
        lo = np.maximum(0, idx - (k - 1))
        cnt = idx + 1 - lo
        s = cs[idx + 1] - cs[lo]
        s2 = cs2[idx + 1] - cs2[lo]
        mean = s / cnt
        var = np.maximum(s2 / cnt - mean * mean, 0.0)
        return mean, np.sqrt(var)

    hm3, hs3 = win_stats(3)
    hm5, hs5 = win_stats(5)

    span_min = (snaps[:-1] - snaps[0]) / 60.0
    trend = np.where(span_min > 0.5, (cur - delays[0]) / np.maximum(span_min, 0.5), 0.0)

    hour = ((snaps[:-1].astype(np.int64) % 86400) // 3600).astype(np.int64)
    dow = ((snaps[:-1].astype(np.int64) // 86400 + 3) % 7).astype(np.int64)

    arr = np.empty((nr, NCOLS), dtype=np.float32)
    arr[:, IDX['route']] = codes[0]
    arr[:, IDX['stop']] = codes[1]
    arr[:, IDX['vsvc']] = codes[2]
    arr[:, IDX['headsign']] = codes[3]
    arr[:, IDX['lead_min']] = (theo - snaps[:-1]) / 60.0
    arr[:, IDX['hour']] = hour
    arr[:, IDX['dow']] = dow
    arr[:, IDX['hour_sin']] = np.take(_HSIN, hour)
    arr[:, IDX['hour_cos']] = np.take(_HCOS, hour)
    arr[:, IDX['dow_sin']] = np.take(_DSIN, dow)
    arr[:, IDX['dow_cos']] = np.take(_DCOS, dow)
    arr[:, IDX['current_delay']] = cur
    arr[:, IDX['prev1']] = prev1
    arr[:, IDX['prev2']] = prev2
    arr[:, IDX['delta_prev1']] = cur - prev1
    arr[:, IDX['delta_prev2']] = prev1 - prev2
    arr[:, IDX['hist_mean3']] = hm3
    arr[:, IDX['hist_std3']] = hs3
    arr[:, IDX['obs_index']] = idx
    arr[:, IDX['obs_total']] = n
    arr[:, IDX['obs_count']] = idx + 1
    arr[:, IDX['target']] = delays[-1]
    arr[:, IDX['event_id']] = event_id
    arr[:, IDX['theo_day']] = theo // 86400
    arr[:, IDX['snap_day']] = snaps[:-1] // 86400
    arr[:, IDX['hist_mean5']] = hm5
    arr[:, IDX['hist_std5']] = hs5
    arr[:, IDX['obs_span_min']] = span_min
    arr[:, IDX['trend_per_min']] = trend
    arr[:, IDX['old_route']] = codes[4]
    arr[:, IDX['old_stop']] = codes[5]
    arr[:, IDX['old_vsvc']] = codes[6]
    arr[:, IDX['old_headsign']] = codes[7]
    return arr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    ap.add_argument('--estimations', default='/home/yan/bikerouter/data/estimations')
    ap.add_argument('--vocab', required=True)
    ap.add_argument('--old-encoders', default='')
    ap.add_argument('--out', required=True)
    ap.add_argument('--event-rate', type=float, default=1.0)
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--flush-rows', type=int, default=400000)
    ap.add_argument('--max-events', type=int, default=0)
    args = ap.parse_args()

    t_start = time.time()
    t0 = dt_ts(args.start)
    t1 = dt_ts(args.end)

    meta = json.load(open(args.vocab))
    enc = meta['encoders']
    unk = meta['unk_index']
    if args.old_encoders:
        old = json.load(open(args.old_encoders))
        oenc = old['encoders']
        ounk = old['unk_index']
    else:
        oenc, ounk = {}, {}

    files = []
    for f in glob(os.path.join(args.estimations, 'departures_*')):
        ts = extract_snapshot_ts(f)
        if ts is not None and t0 - 4200 <= ts <= t1 + 60:
            files.append(f)
    files.sort(key=extract_snapshot_ts)
    print(f'window {fmt_ts(t0)} -> {fmt_ts(t1)} | files={len(files):,}', flush=True)

    pool = ProcessPoolExecutor(max_workers=args.workers)
    stream = bounded_imap(pool, parse_file, files, max_pending=args.workers * 2)

    open_events = {}
    heap = []
    writer = Writer(args.out, NCOLS)
    pending = []
    pending_rows = 0
    event_seq = 0
    n_obs = n_events = n_rows = n_dropped = n_parse_fail = 0
    dt_cache = {}

    def flush():
        nonlocal pending, pending_rows
        if not pending:
            return
        arr = np.concatenate(pending, axis=0)
        writer.add(arr)
        pending = []
        pending_rows = 0

    def emit(obs):
        nonlocal event_seq, n_events, n_rows, pending_rows, n_dropped
        if obs is None or len(obs) < 2:
            return
        obs.sort(key=lambda x: x[0])
        theo = obs[0][5]
        if not (t0 <= theo < t1):
            return
        n_events += 1
        if args.max_events and n_events > args.max_events:
            return
        key = (str(obs[0][2]), str(obs[0][3]), str(theo))
        if not keep_event(key, args.event_rate):
            n_dropped += 1
            return
        route = obs[0][2]
        stop_id = obs[0][3]
        vsvc = obs[0][4]
        headsign = obs[0][6]
        codes = (
            enc['route'].get(route, unk['route']),
            enc['stop_id'].get(stop_id, unk['stop_id']),
            enc['vehicle_service'].get(vsvc, unk['vehicle_service']),
            enc['headsign'].get(headsign, unk['headsign']),
            oenc.get('route', {}).get(route, ounk.get('route', 0)) if oenc else 0,
            oenc.get('stop_id', {}).get(stop_id, ounk.get('stop_id', 0)) if oenc else 0,
            oenc.get('vehicle_service', {}).get(vsvc, ounk.get('vehicle_service', 0)) if oenc else 0,
            oenc.get('headsign', {}).get(headsign, ounk.get('headsign', 0)) if oenc else 0,
        )
        arr = build_event_array(obs, codes, event_seq, True)
        if arr is None:
            return
        event_seq += 1
        pending.append(arr)
        pending_rows += arr.shape[0]
        n_rows += arr.shape[0]
        if pending_rows >= args.flush_rows:
            flush()

    try:
        for i, res in enumerate(stream, 1):
            if res is None:
                continue
            snap, items, failed = res
            n_parse_fail += failed
            while heap and heap[0][0] < snap:
                emit(open_events.pop(heapq.heappop(heap)[1]))
            for key, o in items:
                if key not in open_events:
                    open_events[key] = []
                    heapq.heappush(heap, (o[5], key))
                open_events[key].append(o)
                n_obs += 1
            if i % 500 == 0:
                print(f'  files {i}/{len(files)} | obs={n_obs:,} events={n_events:,} '
                      f'rows={n_rows:,} kept_events={event_seq:,} elapsed={time.time()-t_start:.0f}s',
                      flush=True)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    while heap:
        emit(open_events.pop(heapq.heappop(heap)[1]))
    flush()
    writer.close()

    out_meta = {
        'path': os.path.abspath(args.out),
        'cols': COLS,
        'ncols': NCOLS,
        'n_rows': writer.n,
        'n_events_kept': event_seq,
        'n_events_in_window': n_events,
        'n_events_dropped_by_rate': n_dropped,
        'event_rate': args.event_rate,
        'window': {'start': fmt_ts(t0), 'end': fmt_ts(t1)},
        'snapshots': len(files),
        'observations': n_obs,
        'parse_failures': n_parse_fail,
        'vocab': args.vocab,
        'old_encoders': args.old_encoders,
    }
    with open(args.out + '.json', 'w') as f:
        json.dump(out_meta, f, indent=2)
    print(json.dumps(out_meta, indent=2), flush=True)
    print(f'DONE in {time.time()-t_start:.1f}s', flush=True)


if __name__ == '__main__':
    main()
