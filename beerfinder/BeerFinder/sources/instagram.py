"""Instagram data source for BeerFinder.

This module provides an object-oriented wrapper around the `instaloader`
package to collect Instagram photos by hashtag and store them as part of the
BeerFinder raw dataset together with metadata CSV.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import islice
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import hashlib

import pandas as pd
from PIL import Image

from instaloader import Hashtag, Instaloader, InstaloaderException, Post


@dataclass
class MetaRow:
    """Metadata row describing a downloaded Instagram image."""

    image_id: str
    klass: str
    source: str
    source_url: str | None
    orig_path: str
    orig_filename: str
    width: int | None
    height: int | None
    added_at: str


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def _safe_segment(value: str) -> str:
    """Return a filesystem-safe representation of ``value``."""

    return "".join(c if c.isalnum() or c in "-._" else "_" for c in value)[:120]


class InstagramSource:
    """Download Instagram photos by hashtags to build a beer dataset."""

    def __init__(
        self,
        raw_root: Path,
        meta_csv: Path,
        per_hashtag: int = 120,
        min_side: int = 512,
        login_user: str | None = None,
        login_password: str | None = None,
        request_timeout: int = 30,
    ) -> None:
        self.root = raw_root / "instagram"
        self.root.mkdir(parents=True, exist_ok=True)

        self.meta_csv = meta_csv
        self.meta_csv.parent.mkdir(parents=True, exist_ok=True)

        self.per_hashtag = per_hashtag
        self.min_side = min_side
        self.request_timeout = request_timeout

        self.loader = Instaloader(
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            compress_json=False,
            save_metadata=False,
            post_metadata_txt_pattern="",
        )

        if login_user and login_password:
            self.loader.login(login_user, login_password)

        self._existing_urls: set[str] = set()
        if self.meta_csv.exists():
            try:
                df_existing = pd.read_csv(self.meta_csv)
                if "source_url" in df_existing.columns:
                    self._existing_urls = {
                        str(url).split("?")[0]
                        for url in df_existing["source_url"].dropna().unique().tolist()
                    }
            except Exception:
                # If the CSV cannot be read (e.g., empty or malformed), treat as empty.
                self._existing_urls = set()

        if not self.meta_csv.exists():
            pd.DataFrame(
                columns=[f.name for f in MetaRow.__dataclass_fields__.values()]
            ).to_csv(self.meta_csv, index=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def collect_class(self, klass: str, hashtags: Iterable[str]) -> int:
        """Collect images for a beer ``klass`` using Instagram hashtags."""

        kdir = self.root / klass
        kdir.mkdir(parents=True, exist_ok=True)

        rows: list[MetaRow] = []

        for hashtag in hashtags:
            tag = hashtag.lstrip("#")
            safe_tag = _safe_segment(tag)
            tag_dir = kdir / safe_tag
            tag_dir.mkdir(parents=True, exist_ok=True)

            try:
                hashtag_posts = Hashtag.from_name(self.loader.context, tag)
            except InstaloaderException as exc:
                print(f"[instagram] skip '#{tag}': {exc}")
                continue

            new_rows = self._collect_hashtag(klass, tag_dir, hashtag_posts)
            rows.extend(new_rows)

        if rows:
            self._append_meta(rows)

        return len(rows)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _collect_hashtag(self, klass: str, tag_dir: Path, hashtag: Hashtag) -> list[MetaRow]:
        rows: list[MetaRow] = []

        for post in islice(hashtag.get_posts(), self.per_hashtag):
            post_url = f"https://www.instagram.com/p/{post.shortcode}/"
            if post_url in self._existing_urls:
                continue

            for idx, image_url in self._iter_image_urls(post):
                parsed = urlparse(image_url)
                ext = Path(parsed.path).suffix.lower()
                if ext not in {".jpg", ".jpeg", ".png"}:
                    ext = ".jpg"

                dest_path = tag_dir / f"{post.shortcode}_{idx}{ext}"

                if not self._download_image(image_url, dest_path):
                    continue

                keep, width, height = self._keep_by_size(dest_path)
                if not keep:
                    continue

                image_id = _sha1(dest_path)
                timestamp = _now_iso()

                rows.append(
                    MetaRow(
                        image_id=image_id,
                        klass=klass,
                        source="instagram",
                        source_url=f"{post_url}?img={idx}",
                        orig_path=str(dest_path),
                        orig_filename=dest_path.name,
                        width=width,
                        height=height,
                        added_at=timestamp,
                    )
                )

            self._existing_urls.add(post_url)

        return rows

    def _iter_image_urls(self, post: Post):
        """Yield image index and URL pairs for a post, skipping videos."""

        if post.typename == "GraphSidecar":
            for idx, node in enumerate(post.get_sidecar_nodes()):
                if getattr(node, "is_video", False):
                    continue
                yield idx, node.display_url
        else:
            if not post.is_video:
                yield 0, post.url

    def _download_image(self, url: str, dest: Path) -> bool:
        """Download image from ``url`` to ``dest`` using urllib."""

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)

            request = Request(url, headers={"User-Agent": self.loader.context.user_agent})
            with urlopen(request, timeout=self.request_timeout) as response:
                data = response.read()

            dest.write_bytes(data)
            return True
        except Exception as exc:
            print(f"[instagram] failed to download {url}: {exc}")
            dest.unlink(missing_ok=True)
            return False

    def _keep_by_size(self, path: Path) -> tuple[bool, int | None, int | None]:
        try:
            with Image.open(path) as image:
                width, height = image.size
                if min(width, height) < self.min_side:
                    path.unlink(missing_ok=True)
                    return False, None, None
                return True, width, height
        except Exception:
            path.unlink(missing_ok=True)
            return False, None, None

    def _append_meta(self, rows: list[MetaRow]) -> None:
        df_new = pd.DataFrame([asdict(row) for row in rows])

        try:
            df_old = pd.read_csv(self.meta_csv)
        except Exception:
            df_old = pd.DataFrame(columns=df_new.columns)

        df = pd.concat([df_old, df_new], ignore_index=True).drop_duplicates(subset=["image_id"])
        df.to_csv(self.meta_csv, index=False)

