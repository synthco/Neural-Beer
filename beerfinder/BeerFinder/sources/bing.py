from __future__ import annotations
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List
import hashlib
import pandas as pd
from PIL import Image
from icrawler.builtin import BingImageCrawler
from datetime import datetime
import random
import yaml

@dataclass
class MetaRow:
    image_id: str
    klass: str
    source: str
    source_url: str | None
    orig_path: str
    orig_filename: str
    width: int | None
    height: int | None
    added_at: str

def _now_iso():
    return datetime.utcnow().isoformat(timespec='seconds') + "Z"

def _sha1(p: Path) -> str:
    return hashlib.sha1(p.read_bytes()).hexdigest()

def _safe(q: str) -> str:
    return "".join(c if c.isalnum() or c in "-._" else "_" for c in q)[:120]

class _QueryExpander:
    """
    Private helper to expand per-class query lists with context / glassware / lighting variants
    while preserving the user's negative tokens. Designed to be called from code (not part of the public API).
    """
    CONTEXTS = [
        "in glass on bar table", "poured from tap", "close-up with foam head", "outdoor natural light",
        "condensation closeup", "on wooden table", "with food background", "draft beer pub lighting",
        "moody lighting", "sunlit window", "bartop stainless", "bokeh background"
    ]
    GLASSWARE = ["pint", "nonic pint", "tulip", "teku", "snifter", "weizen", "goblet", "stein", "seidel", "shaker pint", "pilsner flute"]
    MODIFIERS = ["photo", "high detail", "macro", "depth of field", "natural light"]
    DEFAULT_NEG = "-logo -mockup -illustration -advertisement -stockphoto"

    @staticmethod
    def _extract_neg(original: str) -> str:
        """Keep user's existing negative tokens; if absent, use DEFAULT_NEG."""
        parts = [t for t in original.split() if t.startswith("-")]
        return " ".join(parts) if parts else _QueryExpander.DEFAULT_NEG

    @staticmethod
    def _base_terms(original: str) -> str:
        """Remove negative tokens to keep only the positive seed."""
        return " ".join([t for t in original.split() if not t.startswith("-")])

    def expand_from_list(self, originals: list[str], target_count: int) -> list[str]:
        """
        Given the user's original queries for a class, synthesize additional variants until we reach target_count.
        Keeps originals first; then appends generated ones without duplicates.
        """
        originals = [q.strip() for q in originals if q and q.strip()]
        pool = list(dict.fromkeys(originals))  # preserve order & uniqueness
        if not pool:
            return pool

        # Build a candidate set
        cand: set[str] = set(pool)
        for seed in pool:
            pos = self._base_terms(seed)
            neg = self._extract_neg(seed)
            for ctx in self.CONTEXTS:
                for gl in self.GLASSWARE:
                    for mod in self.MODIFIERS:
                        q = f"{pos} {gl} {ctx} {mod} {neg}".strip()
                        cand.add(q)

        # Stabilize order: originals first, then a deterministic shuffle of the rest
        generated = [q for q in cand if q not in pool]
        random.Random(42).shuffle(generated)
        out = pool + generated
        return out[:target_count] if target_count > 0 else out

def expand_queries_dict(bing_queries: dict[str, list[str]], per_class: int = 24) -> dict[str, list[str]]:
    """
    Expand a {class: [queries]} mapping into a larger set with up to `per_class` queries per class.
    """
    exp = _QueryExpander()
    out: dict[str, list[str]] = {}
    for cls, qlist in (bing_queries or {}).items():
        out[cls] = exp.expand_from_list(qlist or [], per_class)
    return out

def expand_queries_file(in_yaml: Path, out_yaml: Path, per_class: int = 24) -> None:
    """
    Read configs/queries.yaml-like file and write an expanded version to out_yaml.
    Input structure:
      bing:
        lager: [ "...", ... ]
        ipa:   [ "...", ... ]
    """
    data = yaml.safe_load(Path(in_yaml).read_text(encoding="utf-8")) or {}
    bing_section = data.get("bing") or {}
    expanded = expand_queries_dict(bing_section, per_class=per_class)
    out_data = {"bing": expanded}
    out_yaml.parent.mkdir(parents=True, exist_ok=True)
    out_yaml.write_text(yaml.safe_dump(out_data, sort_keys=False, allow_unicode=True), encoding="utf-8")

class BingSource:
    def __init__(self, raw_root: Path, meta_csv: Path,  per_query: int = 120, min_side: int = 512):
        self.root = raw_root / "bing"
        self.root.mkdir(parents=True, exist_ok=True)
        self.meta_csv = meta_csv
        self.meta_csv.parent.mkdir(parents=True, exist_ok=True)
        self.per_query = per_query
        self.min_side = min_side
        if not self.meta_csv.exists():
            pd.DataFrame(columns=[f.name for f in MetaRow.__dataclass_fields__.values()]).to_csv(self.meta_csv, index=False)

    def _download_query(self, klass_dir: Path, query: str, want: int) -> List[Path]:
        qdir = klass_dir / _safe(query)
        qdir.mkdir(parents=True, exist_ok=True)

        # Files that existed before this call
        collected_before = {p.resolve() for p in qdir.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}}
        total_wanted = max(1, int(want))
        MAX_BATCH = 150  # practical upper bound per page for Bing
        saved = 0
        offset = 0
        round_no = 0
        added_this_call: list[Path] = []  # only return truly new files from this call

        while saved < total_wanted:
            batch = min(MAX_BATCH, total_wanted - saved)
            round_no += 1
            print(f"[bing] q='{query}' round={round_no} offset={offset} batch={batch}")

            crawler = BingImageCrawler(storage={"root_dir": str(qdir)})
            # icrawler will fetch up to max_num results starting from the given offset
            crawler.crawl(keyword=query, max_num=batch, offset=offset)

            # Collect newly downloaded files
            current = {p.resolve() for p in qdir.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}}
            new_files = sorted(current - collected_before)
            if not new_files:
                # No new images appeared - likely exhausted this query
                print(f"[bing] q='{query}' exhausted at offset={offset}")
                break

            saved += len(new_files)
            collected_before |= set(new_files)
            added_this_call.extend(Path(p) for p in new_files)
            offset += batch  # advance pagination

        return added_this_call

    def _keep_by_size(self, p: Path) -> tuple[bool, int | None, int | None]:
        try:
            with Image.open(p) as im:
               w, h = im.size
               if min(w, h) < self.min_side:
                   p.unlink(missing_ok=True)
                   return False, None, None
               return True, w, h
        except Exception:
            p.unlink(missing_ok=True)
            return False, None, None

    def collect_class(self, klass: str, queries: Iterable[str]) -> int:
        kdir = self.root / klass
        kdir.mkdir(parents=True, exist_ok=True)
        rows: list[MetaRow] = []
        total_planned = self.per_query * len(list(queries))
        queries = list(queries)

        # ---------- PASS 1: base quota per query ----------
        for q in queries:
            print(f"[bing] '{klass}': pulling query '{q}' target-per-query={self.per_query}")
            for p in self._download_query(kdir, q, self.per_query):
                ok, w, h = self._keep_by_size(p)
                if not ok:
                    continue
                rows.append(MetaRow(
                    image_id=_sha1(p),
                    klass=klass,
                    source="bing",
                    source_url="",
                    orig_path=str(p),
                    orig_filename=p.name,
                    width=w,
                    height=h,
                    added_at=_now_iso(),
                ))

        # ---------- PASS 2: top-up remaining across queries ----------
        # Count how many unique rows are already in meta (to avoid overstating when CSV has older entries)
        already_in_csv_ids = set()
        if self.meta_csv.exists():
            try:
                already_in_csv_ids = set(pd.read_csv(self.meta_csv)["image_id"].astype(str).tolist())
            except Exception:
                already_in_csv_ids = set()

        unique_now = set(r.image_id for r in rows if r.image_id not in already_in_csv_ids)
        remaining = max(0, total_planned - len(unique_now))
        if remaining > 0:
            per_q_extra = max(1, int((remaining + len(queries) - 1) // len(queries)))
            print(f"[bing] '{klass}': remaining={remaining} → extra≈{per_q_extra}/query")
            for q in queries:
                if remaining <= 0:
                    break
                for p in self._download_query(kdir, q, per_q_extra):
                    ok, w, h = self._keep_by_size(p)
                    if not ok:
                        continue
                    mr = MetaRow(
                        image_id=_sha1(p),
                        klass=klass,
                        source="bing",
                        source_url="",
                        orig_path=str(p),
                        orig_filename=p.name,
                        width=w,
                        height=h,
                        added_at=_now_iso(),
                    )
                    if mr.image_id in already_in_csv_ids or mr.image_id in (r.image_id for r in rows):
                        continue
                    rows.append(mr)
                    remaining -= 1
                    if remaining <= 0:
                        break

        # ---------- Write meta (dedup by image_id) ----------
        if rows:
            df_new = pd.DataFrame([asdict(r) for r in rows])
            if self.meta_csv.exists():
                df_old = pd.read_csv(self.meta_csv)
                before = len(df_old)
                df = pd.concat([df_old, df_new], ignore_index=True).drop_duplicates(subset=["image_id"])
                added_unique = len(df) - before
            else:
                df = df_new.drop_duplicates(subset=["image_id"])
                added_unique = len(df)
            df.to_csv(self.meta_csv, index=False)
            print(f"[bing] '{klass}': planned={total_planned}, added_unique={added_unique}")
            return added_unique
        return 0

    def expand_queries(self, in_yaml: Path, out_yaml: Path, per_class: int = 32):
        """
        Convenience wrapper to expand a Bing queries YAML file using the internal _QueryExpander.
        Usage example:
            BingSource(...).expand_queries(Path("configs/queries.yaml"), Path("configs/queries_expanded.yaml"), per_class=24)
        """
        expand_queries_file(in_yaml, out_yaml, per_class=per_class)
        print(f"[bing] Expanded queries saved to {out_yaml} (≈{per_class} per class)")
