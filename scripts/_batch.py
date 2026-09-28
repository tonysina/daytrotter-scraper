"""
Shared harness for the three resumable scrape/enrich jobs in this project:
argparse --workers/--limit/--retry-errors, a done-set resume check against a
SQLite table, and a chunked commit + progress-print loop. Each script only
supplies what's unique to it: how to fetch an item and how to save the result.
"""
import time
import argparse
import sqlite3
import concurrent.futures as cf


def make_parser(default_workers=8):
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=default_workers)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--retry-errors", action="store_true")
    return ap


def connect(db_path, schema):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(schema)
    conn.commit()
    return conn


def run(conn, table, key_col, items, key_fn, worker_fn, save_fn, args,
        done_statuses=("ok",), sleep_after=0):
    """
    items: list of anything; key_fn(item) -> the value stored in `key_col`.
    worker_fn(item) -> result, run in a thread pool (or serially if sleep_after).
    save_fn(conn, item, result) -> INSERT/REPLACE the row(s) for one item.
    """
    placeholders = ",".join("?" * len(done_statuses))
    done = {r[0] for r in conn.execute(
        f"SELECT {key_col} FROM {table} WHERE status IN ({placeholders})", done_statuses)}
    if args.retry_errors:
        conn.execute(f"DELETE FROM {table} WHERE status='error'")
        conn.commit()
    else:
        done |= {r[0] for r in conn.execute(f"SELECT {key_col} FROM {table} WHERE status='error'")}

    todo = [it for it in items if key_fn(it) not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"total={len(items)} already_done={len(done)} todo={len(todo)}", flush=True)

    # A rate-limited API (sleep_after > 0) must stay serial; a thread pool
    # would fire requests concurrently regardless of the per-item sleep.
    workers = 1 if sleep_after else args.workers
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        results = ex.map(worker_fn, todo)
        t0 = time.time()
        for i, (item, result) in enumerate(zip(todo, results), 1):
            save_fn(conn, item, result)
            if i % 50 == 0:
                conn.commit()
                rate = i / (time.time() - t0)
                remaining = (len(todo) - i) / rate if rate else 0
                print(f"{i}/{len(todo)} done, {rate:.1f}/s, ~{remaining/60:.1f}min left", flush=True)
            if sleep_after:
                time.sleep(sleep_after)
    conn.commit()
    print("done", flush=True)
