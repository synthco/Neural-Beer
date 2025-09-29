import argparse
import sys
from pathlib import Path

from beerfinder.BeerFinder.config import load_yaml
from config import ensure_dirs, RAW_DIR, META_DIR
from sources.bing import BingSource

def main():
    parser = argparse.ArgumentParser(prog='BeerFinder', description="Beer dataset helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_bing = sub.add_parser("download-bing", help="Download images form Bing using YAML configs")
    p_bing.add_argument("--classes", type=Path, default=Path("configs/classes.yaml"))
    p_bing.add_argument("--queries", type=Path, default=Path("configs/queries.yaml"))
    p_bing.add_argument("--per-query", type=int, default=120)
    p_bing.add_argument("--min-side", type=int, default=512)

    args = parser.parse_args()
    ensure_dirs()

    if args.cmd == "download-bing":
        cls_cfg = load_yaml(args.classes)
        qry_cfg = load_yaml(args.queries)
        raw_classes = cls_cfg.get("classes", [])
        class_map = cls_cfg.get("class_map", {})
        classes = [class_map.get(c, c) for c in raw_classes]

        queries = (qry_cfg.get("bing") or {})
        src = BingSource(raw_root=RAW_DIR, meta_csv=META_DIR / "bing.csv", per_query=args.per_query, min_side=args.min_side)

        total = 0
        for k in classes:
            qlist = queries.get(k, [])
            if not qlist:
                print(f"[bing] skip '{k}': no queries in YAML" )
                continue
            n = src.collect_class(k, qlist)
            total += n
            print(f"[bing] {k}: +{n} images")

        print(f"[bing] Done! Meta -> {META_DIR / 'bing.csv'}, total -> {total}")


if __name__ == "__main__":
    main()

