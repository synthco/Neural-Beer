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

    def _download_querry(self, klass_dir: Path, query: str) -> List[Path]:
        qdir = klass_dir / _safe(query)
        qdir.mkdir(parents=True, exist_ok=True)

        crawler = BingImageCrawler(storage={"root_dir": str(qdir)})
        crawler.crawl(keyword=query, max_num=self.per_query)
        return [p for p in qdir.rglob("*") if p.suffix.lower() in {".jpg", ".png", ".jpeg"}]

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
            for p in self._download_querry(kdir, q):
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



