from __future__ import annotations
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List
import hashlib
import pandas as pd
from PIL import Image
from icrawler.builtin import BingImageCrawler
from datetime import datetime

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


class BingSource:
    def __init__(self, raw_root: Path, meta_csv: Path,  per_query: int = 120, min_side: int = 512):
        self.root = raw_root / "bing"
        self.root.mkdir(parents=True, exist_ok=True)
        self.meta_csv = meta_csv
        self.meta_csv.parent.mkdir(parents=True, exist_ok=True)
        self.per_query = per_query
        self.min_side = min_side
        if not self.meta_csv.exists():
            pd.DataFrame(columns=[f.name for f in MetaRow.__dataclass_fields__.values()]).to_csv(self.meta_csv,
                                                                                                 index=False)

    def _download_query(self, klass_dir: Path, query: str, want: int) -> List[Path]:
        qdir = klass_dir / _safe(query)
        qdir.mkdir(parents=True, exist_ok=True)

        collected_before = {p.resolve() for p in qdir.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}}
        total_wanted = max(1, int(want))
        MAX_BATCH = 150  # practical upper bound per page for Bing
        saved = 0
        offset = 0
        round_no = 0

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
            offset += batch  # advance pagination
        return [Path(p) for p in sorted(collected_before)]

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
                    )
                )
        if rows:
            df_new = pd.DataFrame([asdict(r) for r in rows])
            if self.meta_csv.exists():
                df_old = pd.read_csv(self.meta_csv)
                df = pd.concat([df_old, df_new], ignore_index=True).drop_duplicates(subset=["image_id"])
            else:
                df = df_new
            df.to_csv(self.meta_csv, index=False)
            return len(rows)
        return 0
