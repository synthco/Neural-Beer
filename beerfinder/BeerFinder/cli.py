from __future__ import annotations

import argparse
import math
from pathlib import Path

from config import META_DIR, RAW_DIR, ensure_dirs, load_yaml
from sources import BingSource, InstagramSource, PexelsSource


def main() -> None:
    parser = argparse.ArgumentParser(prog="BeerFinder", description="Beer dataset helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ----------------------- BING -----------------------
    p_bing = sub.add_parser("download-bing", help="Download images from Bing using YAML configs")
    p_bing.add_argument("--classes", type=Path, default=Path("configs/classes.yaml"))
    p_bing.add_argument("--queries", type=Path, default=Path("configs/queries.yaml"))
    p_bing.add_argument("--per-query", type=int, default=120)
    p_bing.add_argument("--min-side", type=int, default=512)
    p_bing.add_argument(
        "--target-per-class",
        type=int,
        default=None,
        help="Desired minimum images per class; auto-allocates per-query",
    )
    p_bing.add_argument(
        "--expand-per-class",
        type=int,
        default=None,
        help="If set, auto-expand queries to this many variants per class before download",
    )
    p_bing.add_argument(
        "--expanded-queries-out",
        type=Path,
        default=META_DIR / "queries_expanded.yaml",
        help="Path to save expanded queries YAML (used if --expand-per-class is set)",
    )

    # -------------------- INSTAGRAM --------------------
    p_ig = sub.add_parser("download-instagram", help="Download images from Instagram hashtags")
    p_ig.add_argument("--classes", type=Path, default=Path("configs/classes.yaml"))
    p_ig.add_argument("--queries", type=Path, default=Path("configs/queries.yaml"))
    p_ig.add_argument("--secrets", type=Path, default=Path("secrets/instagram.yaml"))
    p_ig.add_argument("--per-hashtag", type=int, default=450)
    p_ig.add_argument("--since", type=str, default="2023-01-01")  # YYYY-MM-DD
    p_ig.add_argument("--min-side", type=int, required=True)

    # ----------------- BING: EXPAND QUERIES ONLY -----------------
    p_bing_expand = sub.add_parser("expand-bing-queries", help="Generate expanded Bing queries YAML")
    p_bing_expand.add_argument("--input", "-i", type=Path, required=True, help="Path to source queries.yaml")
    p_bing_expand.add_argument("--output", "-o", type=Path, required=True, help="Where to save expanded YAML")
    p_bing_expand.add_argument("--per-class", "-n", type=int, default=24, help="Target number of queries per class")

    # ----------------- PEXELS -----------------
    p_pexels = sub.add_parser("download-pexels", help="Download images from the Pexels API")
    p_pexels.add_argument("--classes", type=Path, default=Path("configs/classes.yaml"))
    p_pexels.add_argument("--queries", type=Path, default=Path("configs/queries.yaml"))
    p_pexels.add_argument("--secrets", type=Path, default=Path("secrets/pexels.yaml"))
    p_pexels.add_argument("--per-query", type=int, default=60)
    p_pexels.add_argument("--min-side", type=int, default=512)
    p_pexels.add_argument("--max-pages", type=int, default=10)
    p_pexels.add_argument("--preferred-size", type=str, default="original")
    p_pexels.add_argument(
        "--orientation",
        choices=["any", "landscape", "portrait", "square"],
        default="landscape",
        help="Image orientation filter; use 'any' to disable.",
    )
    p_pexels.add_argument(
        "--locale",
        type=str,
        default=None,
        help="Optional locale code for localized search results (e.g. 'en-US').",
    )
    args = parser.parse_args()
    ensure_dirs()

    if args.cmd == "download-bing":
        cls_cfg = load_yaml(args.classes)

        # Optionally expand the query file before loading
        if args.expand_per_class:
            tmp_out = args.expanded_queries_out
            BingSource(raw_root=RAW_DIR, meta_csv=META_DIR / "bing.csv").expand_queries(
                args.queries, tmp_out, per_class=args.expand_per_class
            )
            queries_yaml_path = tmp_out
        else:
            queries_yaml_path = args.queries

        qry_cfg = load_yaml(queries_yaml_path)

        raw_classes = cls_cfg.get("classes", [])
        class_map = cls_cfg.get("class_map", {})
        classes = [class_map.get(c, c) for c in raw_classes]

        queries = qry_cfg.get("bing") or {}

        total = 0
        for klass in classes:
            qlist = queries.get(klass, [])
            if not qlist:
                print(f"[bing] skip '{klass}': no queries in YAML")
                continue
            if args.target_per_class:
                per_query_for_class = max(1, math.ceil(args.target_per_class / max(1, len(qlist))))
            else:
                per_query_for_class = args.per_query
            src = BingSource(
                raw_root=RAW_DIR,
                meta_csv=META_DIR / "bing.csv",
                per_query=per_query_for_class,
                min_side=args.min_side,
            )
            print(
                "[bing] '%s': %d queries, per-query=%d (target-per-class=%s)"
                % (klass, len(qlist), per_query_for_class, args.target_per_class)
            )
            added = src.collect_class(klass, qlist) or 0
            total += added
            print(f"[bing] {klass}: +{added} images")

        print(f"[bing] Done! Meta -> {META_DIR / 'bing.csv'}, total -> {total}")

    elif args.cmd == "expand-bing-queries":
        BingSource(raw_root=RAW_DIR, meta_csv=META_DIR / "bing.csv").expand_queries(
            args.input, args.output, per_class=args.per_class
        )
        print(f"[bing] Queries expanded to {args.output}")

    elif args.cmd == "download-instagram":
        cls_cfg = load_yaml(args.classes)
        qry_cfg = load_yaml(args.queries)

        raw_classes = cls_cfg.get("classes", [])
        class_map = cls_cfg.get("class_map", {})
        classes = [class_map.get(c, c) for c in raw_classes]

        ig_cfg = qry_cfg.get("instagram") or {}
        hashtags_map = ig_cfg.get("hashtags", {})

        def norm_tag(tag: str) -> str:
            return tag.lstrip("#").lower().strip()

        ig = InstagramSource(
            raw_root=RAW_DIR,
            meta_csv=META_DIR / "instagram.csv",
            attr_csv=META_DIR / "instagram_attribution.csv",
            secrets_yaml=args.secrets,
            per_hashtag=args.per_hashtag,
            since_date=args.since,
        )

        total = 0
        for klass in classes:
            tag_list = [norm_tag(t) for t in hashtags_map.get(klass, [])]
            if not tag_list:
                print(f"[instagram] skip '{klass}': no hashtags in YAML")
                continue
            added = ig.collect_class_by_hashtags(klass, tag_list, min_side=args.min_side) or 0
            total += added
            print(f"[instagram] {klass}: +{added} images")

        print(
            f"[instagram] Done! Meta -> {META_DIR / 'instagram.csv'}; "
            f"Attribution -> {META_DIR / 'instagram_attribution.csv'}; total -> {total}"
        )

    elif args.cmd == "download-pexels":
        cls_cfg = load_yaml(args.classes)
        qry_cfg = load_yaml(args.queries)

        raw_classes = cls_cfg.get("classes", [])
        class_map = cls_cfg.get("class_map", {})
        classes = [class_map.get(c, c) for c in raw_classes]

        queries_map = qry_cfg.get("pexels") or {}
        orientation = None if args.orientation == "any" else args.orientation
        locale = (args.locale or "").strip() or None

        src = PexelsSource(
            raw_root=RAW_DIR,
            meta_csv=META_DIR / "pexels.csv",
            attr_csv=META_DIR / "pexels_attribution.csv",
            secrets_yaml=args.secrets,
            per_query=args.per_query,
            min_side=args.min_side,
            max_pages=args.max_pages,
            preferred_size=args.preferred_size,
            orientation=orientation,
            locale=locale,
        )

        total = 0
        for klass in classes:
            qlist = [q for q in queries_map.get(klass, []) if q]
            if not qlist:
                print(f"[pexels] skip '{klass}': no queries in YAML")
                continue
            added = src.collect_class(klass, qlist) or 0
            total += added
            print(f"[pexels] {klass}: +{added} images")

        print(
            f"[pexels] Done! Meta -> {META_DIR / 'pexels.csv'}; "
            f"Attribution -> {META_DIR / 'pexels_attribution.csv'}; total -> {total}"
        )


if __name__ == "__main__":
    main()
