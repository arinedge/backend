"""
Run INSIDE Docker container: python3 /tmp/generate-landing-cache.py
Generates all landing cache JSON files using direct DB access (fast).

Usage:
  docker exec arinedge_backend python3 /tmp/generate-landing-cache.py \
    --symbols RELIANCE,TCS,HDFCBANK \
    --out /tmp/landing_cache
"""
import argparse, concurrent.futures, json, os, sys, time, traceback

sys.path.insert(0, "/app")

SUB_PAGES = [
    "competitors", "fno-positioning", "oi-analysis",
    "open-interest", "put-call-ratio", "gamma-exposure",
    "events", "bulk-block-deals", "corporate-actions",
    "financials", "ratios",
]

SUB_PAGE_METHODS = {
    "competitors": "get_stock_competitors",
    "fno-positioning": "get_stock_fno_positioning",
    "oi-analysis": "get_stock_oi_analysis",
    "open-interest": "get_stock_oi_analysis",
    "put-call-ratio": "get_stock_pcr",
    "gamma-exposure": "get_stock_gamma_exposure",
    "events": "get_stock_events",
    "bulk-block-deals": "get_stock_bulk_block_deals",
    "corporate-actions": "get_stock_corporate_actions",
    "financials": "get_stock_financials",
    "ratios": "get_stock_ratios",
}


def worker(symbol, subpage, method_name, out_dir):
    from app.database import SessionLocal
    from app.services.landing_page_service import LandingPageService

    db = SessionLocal()
    try:
        service = LandingPageService(db)
        method = getattr(service, method_name)
        data = method(symbol)

        if subpage == "open-interest":
            sub_dir = "open-interest"
        else:
            sub_dir = subpage

        file_dir = os.path.join(out_dir, "stocks", symbol)
        os.makedirs(file_dir, exist_ok=True)
        file_path = os.path.join(file_dir, f"{sub_dir}.json")

        with open(file_path, "w") as f:
            json.dump(
                data.model_dump() if hasattr(data, "model_dump") else data,
                f, default=str, indent=2,
            )

        return symbol, subpage, True, None
    except Exception as e:
        return symbol, subpage, False, str(e)
    finally:
        db.close()


def generate_sectors(out_dir):
    from app.database import SessionLocal
    from app.services.landing_page_service import LandingPageService

    db = SessionLocal()
    try:
        service = LandingPageService(db)

        for slug, method_name in [
            (slug, "get_sector_overview"),
            (f"{slug}/fno-positioning", "get_sector_fno_positioning"),
            (f"{slug}/risk-signals", "get_sector_risk_signals"),
        ]:
            try:
                method = getattr(service, method_name)
                slug_clean = slug.split("/")[0]
                data = method(slug_clean)

                if "/" in slug:
                    sub = slug.split("/")[1]
                    file_dir = os.path.join(out_dir, "sectors", slug_clean)
                    os.makedirs(file_dir, exist_ok=True)
                    file_path = os.path.join(file_dir, f"{sub}.json")
                else:
                    file_path = os.path.join(out_dir, "sectors", f"{slug}.json")
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)

                with open(file_path, "w") as f:
                    json.dump(
                        data.model_dump() if hasattr(data, "model_dump") else data,
                        f, default=str, indent=2,
                    )
            except Exception as e:
                print(f"  SECTOR {slug}: {e}", file=sys.stderr)
    finally:
        db.close()


def generate_static(out_dir):
    from app.database import SessionLocal
    from app.services.landing_page_service import LandingPageService

    STATIC_ROUTES = [
        ("/market-flow/fii-dii", "get_market_flow_fii_dii", "market-flow/fii-dii"),
        ("/participant-oi", "get_participant_oi", "participant-oi"),
        ("/market-breadth", "get_market_breadth", "market-breadth"),
        ("/sector-rotation", "get_sector_rotation", "sector-rotation"),
        ("/ipos", "get_ipo_hub", "ipos"),
        ("/signals", "get_signal_catalog", "signals"),
    ]

    db = SessionLocal()
    try:
        service = LandingPageService(db)
        for _, method_name, output_path in STATIC_ROUTES:
            try:
                method = getattr(service, method_name)
                data = method()

                file_path = os.path.join(out_dir, f"{output_path}.json")
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "w") as f:
                    json.dump(
                        data.model_dump() if hasattr(data, "model_dump") else data,
                        f, default=str, indent=2,
                    )
                print(f"  STATIC {output_path}: OK")
            except Exception as e:
                print(f"  STATIC {output_path}: {e}", file=sys.stderr)
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", help="Comma-separated stock symbols")
    parser.add_argument("--symbols-file", help="Path to JSON array of symbols")
    parser.add_argument("--out", default="/tmp/landing_cache", help="Output directory")
    parser.add_argument("--workers", type=int, default=10, help="Thread worker count")
    parser.add_argument("--subpages", help="Comma-separated subpages (default: all)")
    parser.add_argument("--skip-sectors", action="store_true")
    parser.add_argument("--skip-static", action="store_true")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    if args.symbols_file and os.path.exists(args.symbols_file):
        with open(args.symbols_file) as f:
            raw = json.load(f)
            if isinstance(raw, list) and all(isinstance(x, str) for x in raw):
                symbols = raw
            elif isinstance(raw, dict):
                symbols = list(raw.keys())
            elif isinstance(raw, list):
                pairs = raw
                symbols = list(set(p["symbol1"] for p in pairs) | set(p["symbol2"] for p in pairs))
            else:
                symbols = []
    elif args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    else:
        print("ERROR: provide --symbols or --symbols-file")
        sys.exit(1)

    subpages = args.subpages.split(",") if args.subpages else SUB_PAGES
    method_map = {s: SUB_PAGE_METHODS[s] for s in subpages if s in SUB_PAGE_METHODS}

    total = len(symbols) * len(method_map)
    print(f"Generating {total} cache files for {len(symbols)} stocks x {len(method_map)} subpages ({args.workers} workers)")
    start = time.time()

    done, errors = 0, 0
    tasks = [(s, sp, mn, args.out) for s in symbols for sp, mn in method_map.items()]

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(worker, *t) for t in tasks]
        for fut in concurrent.futures.as_completed(futs):
            sym, sub, ok, err = fut.result()
            if ok:
                done += 1
            else:
                errors += 1
                print(f"  ERR {sym}/{sub}: {err}", file=sys.stderr)
            if (done + errors) % 200 == 0:
                elapsed = time.time() - start
                print(f"  Progress: {done + errors}/{total} ({elapsed:.0f}s)")

    elapsed = time.time() - start
    print(f"Stocks done: {done} OK, {errors} errors in {elapsed:.0f}s")

    if not args.skip_sectors:
        print("Generating sector pages...")
        generate_sectors(args.out)

    if not args.skip_static:
        print("Generating static pages...")
        generate_static(args.out)

    # Write marker
    with open(os.path.join(args.out, "_generated_at.txt"), "w") as f:
        f.write(f"{time.time()}\n")

    print(f"Done. Output: {args.out}")


if __name__ == "__main__":
    main()
