#!/usr/bin/env python3
"""Build categorical vocabularies from a few sample days of the training window."""
import argparse
import json
import os
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from glob import glob

from common import parse_file_vocab, bounded_imap, extract_snapshot_ts, fmt_ts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', required=True, help='comma separated YYYY-MM-DD')
    ap.add_argument('--estimations', default='/home/yan/bikerouter/data/estimations')
    ap.add_argument('--out', required=True)
    ap.add_argument('--workers', type=int, default=6)
    args = ap.parse_args()

    days = set(args.days.split(','))
    files = []
    for f in glob(os.path.join(args.estimations, 'departures_*')):
        ts = extract_snapshot_ts(f)
        if ts is None:
            continue
        d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')
        if d in days:
            files.append(f)
    files.sort(key=extract_snapshot_ts)
    print(f'days={sorted(days)} files={len(files):,}', flush=True)

    counters = {c: Counter() for c in ('route', 'stop_id', 'vehicle_service', 'headsign')}
    t0 = time.time()
    pool = ProcessPoolExecutor(max_workers=args.workers)
    stream = bounded_imap(pool, parse_file_vocab, files, max_pending=args.workers * 2)
    try:
        for i, res in enumerate(stream, 1):
            if res is None:
                continue
            _, rows, _ = res
            for route, stop, vsvc, hs in rows:
                counters['route'][route] += 1
                counters['stop_id'][stop] += 1
                counters['vehicle_service'][vsvc] += 1
                counters['headsign'][hs] += 1
            if i % 500 == 0:
                print(f'  {i}/{len(files)} elapsed={time.time()-t0:.0f}s', flush=True)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)

    encoders = {}
    unk = {}
    for c, cnt in counters.items():
        vocab = {v: i for i, (v, _) in enumerate(cnt.most_common())}
        encoders[c] = vocab
        unk[c] = len(vocab)
        print(f'{c}: {len(vocab)} values', flush=True)

    meta = {
        'encoders': encoders,
        'unk_index': unk,
        'source_days': sorted(days),
        'source_files': len(files),
        'counts': {c: dict(cnt.most_common()) for c, cnt in counters.items()},
    }
    with open(args.out, 'w') as f:
        json.dump(meta, f)
    print('wrote', args.out, flush=True)


if __name__ == '__main__':
    main()
