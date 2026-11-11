#!/usr/bin/env python3
"""Compute and save training-window priors for a date range."""
import argparse
import json

import numpy as np

from common import IDX
from features import compute_priors, save_priors


def day(iso):
    from datetime import datetime, timezone
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() // 86400


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dumps', nargs='+', required=True)
    ap.add_argument('--train-start', default='')
    ap.add_argument('--train-end', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    arrs = []
    for p in args.dumps:
        meta = json.load(open(p + '.json'))
        arrs.append(np.fromfile(p, dtype=np.float32).reshape(-1, meta['ncols']))
    arr = arrs[0] if len(arrs) == 1 else np.concatenate(arrs, axis=0)
    theo_day = arr[:, IDX['theo_day']].astype(np.int64)
    lo = day(args.train_start) if args.train_start else -10**9
    hi = day(args.train_end)
    mask = (theo_day >= lo) & (theo_day < hi)
    print('prior rows', int(mask.sum()))
    pri = compute_priors(arr, mask)
    save_priors(pri, args.out)
    print('saved', args.out)


if __name__ == '__main__':
    main()
