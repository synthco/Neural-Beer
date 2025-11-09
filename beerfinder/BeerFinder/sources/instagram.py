from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Optional
import hashlib
import pandas as pd
from PIL import Image
from datetime import datetime, timezone
import yaml
import time
import instaloader
from instaloader import Post


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
    author_username: Optional[str]
    owner_id: Optional[str]
    license_note: str


def _ensure_csv(path: Path, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        pd.DataFrame(columns=columns).to_csv(path, index=False)


def _utc_aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _shortcode_url(sc) -> str:
    return f"https://www.instagram.com/p/{sc}/"


def _keep_by_size(p: Path, min_side: int) -> tuple[bool, int | None, int | None]:
    try:
        with Image.open(p) as im:
            w, h = im.size
            if min(w, h) < min_side:
                p.unlink(missing_ok=True)
                return False, None, None
            return True, w, h
    except Exception:
        p.unlink(missing_ok=True)
        return False, None, None

def _sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


class InstagramSource:

    def __init__(self,
                 raw_root: Path,
                 meta_csv: Path,
                 attr_csv: Path,
                 secrets_yaml: Path,
                 per_hashtag: int= 450,
                 since_date: str = "2023-01-01",
                 include_carousel: bool = True):

        self.root = raw_root / "instagram"
        self.root.mkdir(parents=True, exist_ok=True)
        self.meta_csv = meta_csv
        self.attr_csv = attr_csv
        _ensure_csv(self.meta_csv, [f.name for f in MetaRow.__dataclass_fields__.values()])
        _ensure_csv(self.attr_csv, [f.name for f in AttributionRow.__dataclass_fields__.values()])

        with open(secrets_yaml, "r") as f:
            sec = yaml.safe_load(f) or {}
        sec = sec.get("instagram", {})

        self.loader = instaloader.Instaloader(
            download_videos= False,
            download_pictures=True,
            download_video_thumbnails=False,
            save_metadata=False,
            download_comments=False,
            compress_json=False,
            post_metadata_txt_pattern="",
            dirname_pattern = str((raw_root / "meta" / "ig_tmp" / "{target}").as_posix()),
            max_connection_attempts=3,
            #user_agent= <For future>
        )

        username = sec.get("username")
        sessionfile = sec.get("sessionfile")
        password = sec.get("password")

        if sessionfile:
            try:
                self.loader.load_session_from_file(username, sessionfile)
            except Exception:
                if username and password:
                    self.loader.login(username, password)
                    self.loader.save_session_to_file(sessionfile=sessionfile)
        elif username and password:
            self.loader.login(username, password)

        self.per_hashtag = per_hashtag
        self.since_date = _utc_aware(datetime.fromisoformat(since_date))

        self._seen_ids = set(pd.read_csv(self.meta_csv)["image_id"].unique()) if self.meta_csv.exists() else set()

    def _append_rows(self, rows: list[MetaRow], attrs: list[AttributionRow]) -> int:
        if not rows:
            return 0

        df_new = pd.DataFrame([asdict(r) for r in rows])
        df_attr_new = pd.DataFrame([asdict(a) for a in attrs]) if  attrs else pd.DataFrame(columns=[f.name for f in AttributionRow.__dataclass_fields__.values()])

        if self.meta_csv.exists():
            df_old = pd.read_csv(self.meta_csv)
            df = pd.concat([df_old, df_new], ignore_index=True).drop_duplicates(subset=["image_id"])
        else:
            df = df_new
        df.to_csv(self.meta_csv, index=False)

        if self.attr_csv.exists():
            df_attr_old = pd.read_csv(self.attr_csv)
            df_attr = pd.concat([df_attr_old, df_attr_new], ignore_index=True).drop_duplicates(subset=["image_id"])

        else:
            df_attr = df_attr_new
        df_attr.to_csv(self.attr_csv, index=False)

        self._seen_ids.update(df_new["image_id"].tolist())

        return len(df_new)

    def collect_class_by_hashtags(self, klass: str, hastags: Iterable[str], min_side: int) -> int:
        kdir = self.root / klass
        kdir.mkdir(parents=True, exist_ok=True)

        total_added = 0

        for tag in hastags:
            rows: list[MetaRow] = []
            attrs: list[AttributionRow] = []

            try:
                ht = instaloader.Hashtag.from_name(self.loader.context, tag.lstrip("#"))
            except Exception as e:
                print(f"[warn] failed to resolve #'{tag}: {e}'")
                continue

            count = 0

            #posts most revent first
            for post in ht.get_posts():
                if _utc_aware(post.date) < self.since_date:
                    break

                if post.is_video:
                    continue
                if not self._post_has_photo(post):
                    continue
                
                time.sleep(0.2)
                
                sc = post.shortcode
                url = _shortcode_url(sc)
                try:
                    self.loader.download_post(post, target=f"HASHTAG_{tag}")
                except Exception as e:
                    print(f"[warn] failed to download post: '{post.id}': {e}")
                    continue

                img_paths = self._find_downloaded_images(sc)
                if not img_paths:
                    continue

                saved_any = False
                for p in img_paths:
                    ok, w, h = _keep_by_size(p, min_side)
                    if not ok:
                        continue
                    img_id = _sha1(p)
                    if img_id in self._seen_ids:
                        continue

                    dst = kdir / f"{img_id}.jpg"
                    dst.write_bytes(p.read_bytes())

                    rows.append(MetaRow(
                        image_id=img_id,
                        klass=klass,
                        source="instagram",
                        source_url=url,
                        orig_path=str(dst),
                        orig_filename=dst.name,
                        width=w,
                        height=h,
                        added_at=_now_iso()
                    ))
                    attrs.append(AttributionRow(
                        image_id=img_id,
                        author_username=getattr(post.owner_profile, "username", None),
                        owner_id=getattr(post.owner_profile, "userid", None),
                        license_note="Copyright belongs to the original Instagram author. Collected for research/non-commercial use; follow Instagram Terms."
                    ))
                    saved_any = True
                    break
                if saved_any:
                    count += 1
                    if count >= self.per_hashtag:
                        break
            total_added += self._append_rows(rows, attrs)
        return total_added

    @staticmethod
    def _post_has_photo(post: Post) -> bool:
        if post.typename == "GraphImage":
            return True
        if post.typename == "GraphSidecar" and any(not r.is_video for r in post.get_sidecar_nodes()):
            return True
        return False

    def _find_downloaded_images(self, sc: str) -> list[Path]:
        """Locate downloaded files that include the shortcode in their filename."""
        pattern = self.loader.dirname_pattern
        base_str = pattern.split("{target}")[0] if "{target}" in pattern else pattern
        search_root = Path(base_str).expanduser()
        if not search_root.exists():
            return []
        return sorted([p for p in search_root.rglob(f\"*{sc}*.jpg\") if p.is_file()])









