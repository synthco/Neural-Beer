from __future__ import annotations
import argparse
import math
from pathlib import Path
from config import ensure_dirs, RAW_DIR, META_DIR, load_yaml
from sources import InstagramSource
from sources import BingSource

def main():
    parser = argparse.ArgumentParser(prog='BeerFinder', description="Beer dataset helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ----------------------- BING -----------------------
    p_bing = sub.add_parser("download-bing", help="Download images from Bing using YAML configs")
    p_bing.add_argument("--classes", type=Path, default=Path("configs/classes.yaml"))
    p_bing.add_argument("--queries", type=Path, default=Path("configs/queries.yaml"))
    p_bing.add_argument("--per-query", type=int, default=120)
    p_bing.add_argument("--min-side", type=int, default=512)
    p_bing.add_argument("--target-per-class", type=int, default=None, help="Desired minimum images per class; auto-allocates per-query")

    # -------------------- INSTAGRAM --------------------
    p_ig = sub.add_parser("download-instagram", help="Download images from Instagram hashtags")
    p_ig.add_argument("--classes", type=Path, default=Path("configs/classes.yaml"))
    p_ig.add_argument("--queries", type=Path, default=Path("configs/queries.yaml"))
    p_ig.add_argument("--secrets", type=Path, default=Path("secrets/instagram.yaml"))
    p_ig.add_argument("--per-hashtag", type=int, default=450)
    p_ig.add_argument("--since", type=str, default="2023-01-01")  # YYYY-MM-DD
    p_ig.add_argument("--min-side", type=int, required=True)

    args = parser.parse_args()
    ensure_dirs()

    if args.cmd == "download-bing":
        cls_cfg = load_yaml(args.classes)
        qry_cfg = load_yaml(args.queries)

        raw_classes = cls_cfg.get("classes", [])
        class_map = cls_cfg.get("class_map", {})
        classes = [class_map.get(c, c) for c in raw_classes]

        queries = (qry_cfg.get("bing") or {})

        total = 0
        for k in classes:
            qlist = queries.get(k, [])
            if not qlist:
                print(f"[bing] skip '{k}': no queries in YAML")
                continue
            # Determine per-query allocation: either user-specified or computed from target-per-class
            if args.target_per_class:
                per_query_for_class = max(1, math.ceil(args.target_per_class / max(1, len(qlist))))
            else:
                per_query_for_class = args.per_query
            # Create a BingSource instance with class-specific per_query
            src = BingSource(
                raw_root=RAW_DIR,
                meta_csv=META_DIR / "bing.csv",
                per_query=per_query_for_class,
                min_side=args.min_side
            )
            print(f"[bing] '{k}': {len(qlist)} queries, per-query={per_query_for_class} (target-per-class={args.target_per_class})")
            n = src.collect_class(k, qlist) or 0
            total += n
            print(f"[bing] {k}: +{n} images")

        print(f"[bing] Done! Meta -> {META_DIR / 'bing.csv'}, total -> {total}")

    elif args.cmd == "download-instagram":
        cls_cfg = load_yaml(args.classes)
        qry_cfg = load_yaml(args.queries)

        raw_classes = cls_cfg.get("classes", [])
        class_map = cls_cfg.get("class_map", {})
        classes = [class_map.get(c, c) for c in raw_classes]

        ig_cfg = (qry_cfg.get("instagram") or {})
        hashtags_map = ig_cfg.get("hashtags", {})

        def norm_tag(t: str) -> str:
            return t.lstrip("#").lower().strip()

        ig = InstagramSource(
            raw_root=RAW_DIR,
            meta_csv=META_DIR / "instagram.csv",
            attr_csv=META_DIR / "instagram_attribution.csv",
            secrets_yaml=args.secrets,
            per_hashtag=args.per_hashtag,
            since_date=args.since,
        )

        total = 0
        for k in classes:
            tag_list = [norm_tag(t) for t in hashtags_map.get(k, [])]
            if not tag_list:
                print(f"[instagram] skip '{k}': no hashtags in YAML")
                continue
            added = ig.collect_class_by_hashtags(k, tag_list, min_side=args.min_side) or 0
            total += added
            print(f"[instagram] {k}: +{added} images")

        print(f"[instagram] Done! Meta -> {META_DIR / 'instagram.csv'}; "
              f"Attribution -> {META_DIR / 'instagram_attribution.csv'}; total -> {total}")

if __name__ == "__main__":
    main()