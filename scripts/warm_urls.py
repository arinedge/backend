#!/usr/bin/env python3
"""Warm required and optional URLs without blocking deploy on optional failures."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class WarmResult:
    url: str
    required: bool
    ok: bool
    status: int | None
    elapsed_ms: int
    attempts: int
    error: str | None = None


def read_urls(path: str | None, base_url: str) -> list[str]:
    if not path:
        return []
    urls: list[str] = []
    for raw in Path(path).read_text().splitlines():
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        if value.startswith("http://") or value.startswith("https://"):
            urls.append(value)
        else:
            urls.append(urllib.parse.urljoin(base_url.rstrip("/") + "/", value.lstrip("/")))
    return urls


def fetch_url(url: str, required: bool, timeout: float, retries: int) -> WarmResult:
    started = time.monotonic()
    last_status: int | None = None
    last_error: str | None = None
    attempts = retries + 1

    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "arinedge-url-warmer/1.0"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = response.status
                response.read(1024)
            ok = 200 <= status < 400
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if ok or attempt == attempts:
                return WarmResult(url, required, ok, status, elapsed_ms, attempt, None if ok else f"HTTP {status}")
            last_status = status
            last_error = f"HTTP {status}"
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            last_error = f"HTTP {exc.code}"
        except Exception as exc:
            last_error = str(exc)

        if attempt < attempts:
            time.sleep(min(2 ** attempt, 8))

    elapsed_ms = int((time.monotonic() - started) * 1000)
    return WarmResult(url, required, False, last_status, elapsed_ms, attempts, last_error)


def warm_all(urls: list[tuple[str, bool]], concurrency: int, timeout: float, retries: int) -> list[WarmResult]:
    if not urls:
        return []
    results: list[WarmResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        futures = [
            executor.submit(fetch_url, url, required, timeout, retries)
            for url, required in urls
        ]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            label = "required" if result.required else "optional"
            status = result.status if result.status is not None else "ERR"
            outcome = "OK" if result.ok else "WARN"
            print(f"{outcome}: {label} {status} {result.elapsed_ms}ms {result.url}")
    return results


def write_outputs(results: list[WarmResult], output_dir: str) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    success = [asdict(result) for result in results if result.ok]
    failed = [asdict(result) for result in results if not result.ok]
    (out / "warm-success.json").write_text(json.dumps(success, indent=2) + "\n")
    (out / "warm-failed.json").write_text(json.dumps(failed, indent=2) + "\n")
    required_failed = sum(1 for result in results if result.required and not result.ok)
    optional_failed = sum(1 for result in results if not result.required and not result.ok)
    summary = [
        f"total={len(results)}",
        f"success={len(success)}",
        f"failed={len(failed)}",
        f"required_failed={required_failed}",
        f"optional_failed={optional_failed}",
    ]
    (out / "warm-summary.txt").write_text("\n".join(summary) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Warm URLs with required/optional failure policy.")
    parser.add_argument("--base-url", default="https://api.arinedge.com", help="Base URL for relative paths.")
    parser.add_argument("--required-file", help="Newline-delimited required URLs or paths.")
    parser.add_argument("--optional-file", help="Newline-delimited optional URLs or paths.")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--output-dir", default="warm-results")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    required_urls = read_urls(args.required_file, args.base_url)
    optional_urls = read_urls(args.optional_file, args.base_url)
    urls = [(url, True) for url in required_urls] + [(url, False) for url in optional_urls]
    results = warm_all(urls, args.concurrency, args.timeout, args.retries)
    write_outputs(results, args.output_dir)

    required_failures = [result for result in results if result.required and not result.ok]
    if required_failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
