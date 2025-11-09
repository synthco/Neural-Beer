from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Iterable, Optional, Any
import hashlib

import pandas as pd
import requests
import yaml
from PIL import Image


@dataclass
class MetaRow:
    image_id: str
    klass: str
    source: str
    source_url: str | None
    orig_path: str
    orig_filename: str
    width: int
    height: int
    added_at: str


@dataclass
class AttributionRow:
    image_id: str
    photographer: Optional[str]
    photographer_url: Optional[str]
    license_note: str
    source_url: Optional[str]


def _ensure_csv(path: Path, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        pd.DataFrame(columns=columns).to_csv(path, index=False)


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


class PexelsSource:
    API_URL = "https://api.pexels.com/v1/search"
    MAX_PER_PAGE = 80

    def __init__(
        self,
        raw_root: Path,
        meta_csv: Path,
        attr_csv: Path,
        secrets_yaml: Path,
        per_query: int = 80,
        min_side: int = 512,
        max_pages: int = 10,
        preferred_size: str = "original",
        orientation: Optional[str] = "landscape",
        locale: Optional[str] = None,
    ) -> None:
        self.root = raw_root / "pexels"
        self.root.mkdir(parents=True, exist_ok=True)
        self.meta_csv = meta_csv
        self.attr_csv = attr_csv
        self.per_query = max(1, per_query)
        self.min_side = min_side
        self.max_pages = max_pages
        self.preferred_size = preferred_size
        self.orientation = orientation
        self.locale = locale

        _ensure_csv(self.meta_csv, [f.name for f in MetaRow.__dataclass_fields__.values()])
        _ensure_csv(self.attr_csv, [f.name for f in AttributionRow.__dataclass_fields__.values()])

        self.api_key = self._load_api_key(secrets_yaml)
        self._seen_ids = self._load_seen_ids()

    def _load_seen_ids(self) -> set[str]:
        if not self.meta_csv.exists():
            return set()
        try:
            df = pd.read_csv(self.meta_csv, usecols=["image_id"])
            return set(df["image_id"].astype(str).tolist())
        except Exception:
            return set()

    @staticmethod
    def _load_api_key(secrets_yaml: Path) -> str:
        with Path(secrets_yaml).open("r", encoding="utf-8") as fh:
            sec = yaml.safe_load(fh) or {}

        # Support both "pexels" and typo "pexel" in secrets files.
        candidates: list[str] = []
        for key_name in ("pexels", "pexel"):
            if key_name in sec:
                candidates.extend(PexelsSource._extract_key_candidates(sec[key_name]))

        api_key = next((k for k in candidates if k), None)
        if not api_key:
            raise ValueError("Pexels API key not found in secrets YAML.")
        return api_key

    @staticmethod
    def _extract_key_candidates(node: Any) -> list[str]:
        """Recursively collect potential API keys from mixed YAML structures."""
        keys: list[str] = []

        if isinstance(node, str):
            candidate = node.strip()
            # Handle common typo where "-value" (without a space) is used instead of YAML list "- value".
            if candidate.startswith("-") and not candidate.startswith("--") and " " not in candidate[:2]:
                candidate = candidate[1:]
            if candidate:
                keys.append(candidate)
            return keys

        if isinstance(node, (list, tuple, set)):
            for item in node:
                keys.extend(PexelsSource._extract_key_candidates(item))
            return keys

        if isinstance(node, dict):
            preferred_fields = ("key", "keys", "api_key", "apiKey")
            matched = False
            for field in preferred_fields:
                if field in node:
                    keys.extend(PexelsSource._extract_key_candidates(node[field]))
                    matched = True
            if not matched:
                for value in node.values():
                    keys.extend(PexelsSource._extract_key_candidates(value))
            return keys

        return keys

    def _request_json(self, query: str, page: int, per_page: int) -> dict:
        headers = {"Authorization": self.api_key}
        params: dict[str, str | int] = {
            "query": query,
            "page": page,
            "per_page": per_page,
        }
        if self.orientation:
            params["orientation"] = self.orientation
        if self.locale:
            params["locale"] = self.locale

        resp = requests.get(self.API_URL, headers=headers, params=params, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"Pexels API error {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def _pick_download_url(self, photo: dict) -> Optional[str]:
        src_map = photo.get("src") or {}
        if self.preferred_size and self.preferred_size in src_map:
            return src_map[self.preferred_size]
        for key in ("original", "large2x", "large", "medium"):
            if key in src_map:
                return src_map[key]
        return None

    def _download_photo(self, url: str) -> Optional[bytes]:
        resp = requests.get(url, timeout=60)
        if resp.status_code != 200 or not resp.content:
            return None
        return resp.content

    def _process_photo(self, photo: dict, klass_dir: Path, klass: str) -> Optional[tuple[MetaRow, AttributionRow]]:
        download_url = self._pick_download_url(photo)
        if not download_url:
            return None

        blob = self._download_photo(download_url)
        if not blob:
            return None

        image_id = _sha1(blob)
        if image_id in self._seen_ids:
            return None

        try:
            with Image.open(BytesIO(blob)) as im:
                width, height = im.size
                if min(width, height) < self.min_side:
                    return None
                fmt = (im.format or "JPEG").lower()
        except Exception:
            return None

        ext = ".jpg" if fmt.lower() in {"jpeg", "jpg"} else f".{fmt}"
        dest = klass_dir / f"{image_id}{ext}"
        dest.write_bytes(blob)

        meta = MetaRow(
            image_id=image_id,
            klass=klass,
            source="pexels",
            source_url=photo.get("url"),
            orig_path=str(dest),
            orig_filename=dest.name,
            width=width,
            height=height,
            added_at=_now_iso(),
        )
        attr = AttributionRow(
            image_id=image_id,
            photographer=photo.get("photographer"),
            photographer_url=photo.get("photographer_url"),
            license_note="Licensed via Pexels. Provide credit per https://www.pexels.com/license/",
            source_url=download_url,
        )

        self._seen_ids.add(image_id)
        return meta, attr

    def _append_rows(self, rows: list[MetaRow], attrs: list[AttributionRow]) -> int:
        if not rows:
            return 0

        df_new = pd.DataFrame([asdict(r) for r in rows])
        df_attr_new = pd.DataFrame([asdict(a) for a in attrs]) if attrs else pd.DataFrame(
            columns=[f.name for f in AttributionRow.__dataclass_fields__.values()]
        )

        df_meta = pd.read_csv(self.meta_csv) if self.meta_csv.exists() else pd.DataFrame(
            columns=df_new.columns
        )
        df_meta = pd.concat([df_meta, df_new], ignore_index=True).drop_duplicates(subset=["image_id"])
        df_meta.to_csv(self.meta_csv, index=False)

        df_attr = pd.read_csv(self.attr_csv) if self.attr_csv.exists() else pd.DataFrame(
            columns=df_attr_new.columns
        )
        df_attr = pd.concat([df_attr, df_attr_new], ignore_index=True).drop_duplicates(subset=["image_id"])
        df_attr.to_csv(self.attr_csv, index=False)

        return len(df_new)

    def collect_class(self, klass: str, queries: Iterable[str]) -> int:
        klass_dir = self.root / klass
        klass_dir.mkdir(parents=True, exist_ok=True)

        total_added = 0
        all_rows: list[MetaRow] = []
        all_attrs: list[AttributionRow] = []

        for query in (q.strip() for q in queries if q and q.strip()):
            print(f"[pexels] '{klass}': query='{query}' target={self.per_query}")
            added_for_query = 0
            page = 1

            while added_for_query < self.per_query and page <= self.max_pages:
                per_page = min(self.MAX_PER_PAGE, max(self.per_query, 20))
                try:
                    payload = self._request_json(query, page, per_page)
                except Exception as exc:
                    print(f"[pexels] query='{query}' page={page} failed: {exc}")
                    break

                photos = payload.get("photos") or []
                if not photos:
                    print(f"[pexels] query='{query}' page={page} returned 0 photos")
                    break

                for photo in photos:
                    processed = self._process_photo(photo, klass_dir, klass)
                    if not processed:
                        continue
                    meta, attr = processed
                    all_rows.append(meta)
                    all_attrs.append(attr)
                    added_for_query += 1
                    total_added += 1
                    if added_for_query >= self.per_query:
                        break

                page += 1

        if all_rows:
            self._append_rows(all_rows, all_attrs)

        return total_added
