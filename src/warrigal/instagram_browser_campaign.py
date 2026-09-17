from __future__ import annotations

import argparse
import json
import re
import shutil
import ssl
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse, urlunparse

import certifi

from warrigal.acquisition import instagram as instagram_acquisition
from warrigal.database import initialize_database
from warrigal.models import Batch, Collection, Job, Node
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


APPLESCRIPT = r'''
on run argv
    set postURL to item 1 of argv

    tell application "Brave Browser"
        if (count windows) = 0 then error "NO BRAVE WINDOW"

        set targetTab to missing value

        repeat with windowNumber from 1 to count windows
            repeat with tabNumber from 1 to count tabs of window windowNumber
                set candidateTab to tab tabNumber of window windowNumber

                if URL of candidateTab contains "instagram.com" then
                    set targetTab to candidateTab
                    set active tab index of window windowNumber to tabNumber
                    set index of window windowNumber to 1
                    exit repeat
                end if
            end repeat

            if targetTab is not missing value then exit repeat
        end repeat

        if targetTab is missing value then
            set targetTab to make new tab at end of tabs of front window with properties {URL:postURL}
            set active tab index of front window to count tabs of front window
        else
            set URL of targetTab to postURL
        end if

        activate
        delay 8

        set initialized to execute targetTab javascript "(() => { const time=document.querySelector('time'); if(!time)return 'NO_TIME'; let root=time.parentElement; while(root && ![...root.querySelectorAll('img')].some(img=>img.naturalWidth>=300) && !root.querySelector('video'))root=root.parentElement; if(!root)return 'NO_POST_CONTAINER'; window.__wrgRoot=root; window.__wrgMedia={}; window.__wrgCollect=()=>{ [...window.__wrgRoot.querySelectorAll('img')].filter(img=>img.naturalWidth>=300).forEach(img=>{const url=img.currentSrc||img.src;if(url)window.__wrgMedia[url]={type:'image',alt:img.alt||''};}); [...window.__wrgRoot.querySelectorAll('video')].forEach(video=>{const url=video.currentSrc||video.src;if(url && !url.startsWith('blob:'))window.__wrgMedia[url]={type:'video',poster:video.poster||''};}); }; window.__wrgCollect(); return 'OK'; })();"

        if initialized is not "OK" then error initialized

        if postURL does not contain "/reel/" then
            repeat with slideNumber from 1 to 20
                set advanced to execute targetTab javascript "(() => { window.__wrgCollect(); const button=window.__wrgRoot.querySelector('button[aria-label=\"Next\"]'); if(!button)return 'STOP'; button.click(); return 'NEXT'; })();"

                if advanced is "STOP" then exit repeat
                delay 2
                execute targetTab javascript "window.__wrgCollect();"
            end repeat
        else
            delay 5
        end if

        return execute targetTab javascript "(() => { window.__wrgCollect(); const rows=[...new Set(performance.getEntriesByType('resource').map(entry=>entry.name).filter(url=>/\\.mp4/i.test(url)))].map(raw=>{try{const url=new URL(raw);const encoded=url.searchParams.get('efg');const metadata=encoded?JSON.parse(atob(encoded)):{};url.searchParams.delete('bytestart');url.searchParams.delete('byteend');return{url:url.href,tag:metadata.vencode_tag||'',bitrate:Number(metadata.bitrate||0),duration:Number(metadata.duration_s||0)};}catch{return null;}}).filter(Boolean); const audio=rows.filter(row=>/audio|heaac|aac/i.test(row.tag)).sort((a,b)=>b.bitrate-a.bitrate)[0]||null; const video=rows.filter(row=>!/audio|heaac|aac/i.test(row.tag)).sort((a,b)=>b.bitrate-a.bitrate)[0]||null; return JSON.stringify({source_url:location.href.split('?')[0],shortcode:location.pathname.split('/').filter(Boolean).pop(),date_utc:document.querySelector('time')?.getAttribute('datetime')||null,caption:document.querySelector('meta[property=\"og:description\"]')?.content||'',media:Object.entries(window.__wrgMedia).map(([url,data])=>({url,...data})),dash_video:video,dash_audio:audio}); })();"
    end tell
end run
'''


def clean_caption(value: str) -> str:
    match = re.match(
        r'^\s*[\d,]+\s+likes?,\s*[\d,]+\s+comments?\s+-\s+'
        r'[^:]+:\s+"(.*)"\.\s*$',
        value,
        flags=re.DOTALL,
    )
    return match.group(1) if match else value


def extract_post(post_url: str) -> dict:
    process = subprocess.run(
        ["osascript", "-", post_url],
        input=APPLESCRIPT,
        text=True,
        capture_output=True,
    )

    if process.returncode:
        raise RuntimeError(process.stderr.strip())

    payload = json.loads(process.stdout)
    payload["caption"] = clean_caption(payload.get("caption", ""))

    if not payload.get("date_utc"):
        raise RuntimeError("Post timestamp was not extracted.")

    if "/reel/" in post_url:
        if not payload.get("dash_video"):
            raise RuntimeError("No complete reel video stream was found.")
    elif not payload.get("media"):
        raise RuntimeError("No isolated post media was found.")

    return payload


def remove_byte_range(source_url: str) -> str:
    parsed = urlparse(source_url)
    query = [
        part
        for part in parsed.query.split("&")
        if not part.startswith(("bytestart=", "byteend="))
    ]
    return urlunparse(parsed._replace(query="&".join(query)))


class BrowserEvidenceDownloader:
    dirname_pattern = "{target}"

    def __init__(self, payload: dict):
        self.payload = payload
        self.context = ssl.create_default_context(cafile=certifi.where())

    def download(self, source_url: str, destination: Path) -> None:
        request = urllib.request.Request(
            remove_byte_range(source_url),
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": self.payload["source_url"],
            },
        )

        with urllib.request.urlopen(
            request,
            timeout=180,
            context=self.context,
        ) as response:
            destination.write_bytes(response.read())

    def download_post(self, post, target: str) -> None:
        destination = Path(
            self.dirname_pattern.format(target=target)
        )
        destination.mkdir(parents=True, exist_ok=True)

        metadata = destination / f"{post.shortcode}.browser.json"
        metadata.write_text(
            json.dumps(self.payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        if "/reel/" in self.payload["source_url"]:
            video = destination / f"{post.shortcode}.video.mp4"
            audio = destination / f"{post.shortcode}.audio.mp4"
            combined = destination / f"{post.shortcode}.mp4"

            self.download(self.payload["dash_video"]["url"], video)

            if self.payload.get("dash_audio"):
                self.download(self.payload["dash_audio"]["url"], audio)

                ffmpeg = shutil.which("ffmpeg")
                if not ffmpeg:
                    raise RuntimeError("ffmpeg is required for reel muxing.")

                subprocess.run(
                    [
                        ffmpeg,
                        "-y",
                        "-loglevel",
                        "error",
                        "-i",
                        str(video),
                        "-i",
                        str(audio),
                        "-map",
                        "0:v:0",
                        "-map",
                        "1:a:0",
                        "-c",
                        "copy",
                        "-shortest",
                        str(combined),
                    ],
                    check=True,
                )
            else:
                shutil.copy2(video, combined)

            return

        for number, item in enumerate(self.payload["media"], start=1):
            source_url = item["url"]
            suffix = Path(urlparse(source_url).path).suffix.lower()

            if not suffix or len(suffix) > 5:
                suffix = ".mp4" if item["type"] == "video" else ".jpg"

            self.download(
                source_url,
                destination / f"{post.shortcode}_{number:02d}{suffix}",
            )


def load_checkpoint(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "completed": {}, "failed": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_checkpoint(path: Path, checkpoint: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(checkpoint, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def archive_post(
    post_url: str,
    *,
    repository,
    object_store,
    job,
    node,
    batch,
    collection,
):
    payload = extract_post(post_url)

    if "/reel/" in post_url:
        typename = "GraphVideo"
    elif len(payload["media"]) > 1:
        typename = "GraphSidecar"
    elif payload["media"][0]["type"] == "video":
        typename = "GraphVideo"
    else:
        typename = "GraphImage"

    raw_post = SimpleNamespace(
        shortcode=payload["shortcode"],
        source_url=post_url,
        date_utc=datetime.fromisoformat(
            payload["date_utc"].replace("Z", "+00:00")
        ),
        typename=typename,
        caption=payload["caption"],
    )

    original_normalizer = instagram_acquisition.post_from_instaloader

    def browser_normalizer(post):
        if hasattr(post, "source_url"):
            return instagram_acquisition.InstagramPost(
                shortcode=post.shortcode,
                url=post.source_url,
                date_utc=post.date_utc,
                typename=post.typename,
                caption=post.caption or "",
            )
        return original_normalizer(post)

    instagram_acquisition.post_from_instaloader = browser_normalizer

    try:
        return instagram_acquisition.ingest_instagram_post(
            raw_post,
            downloader=BrowserEvidenceDownloader(payload),
            repository=repository,
            object_store=object_store,
            job_id=job.job_id,
            node_id=node.node_id,
            batch_id=batch.batch_id,
            collection_id=collection.collection_id,
        )
    finally:
        instagram_acquisition.post_from_instaloader = original_normalizer


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Checkpointed Instagram acquisition through logged-in Brave."
    )
    parser.add_argument("--post-url")
    parser.add_argument(
        "--inventory",
        type=Path,
        default=(
            Path.home()
            / "Desktop/INFORMATION_ARCHIVE/COLLECTIONS/INSTAGRAM/"
              "EEANIMATION/eeanimation-post-inventory.json"
        ),
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("workspace/eeanimation-instagram.checkpoint.json"),
    )
    parser.add_argument(
        "--max-posts",
        type=int,
        default=1,
        help="Maximum new posts; use 0 for every remaining post.",
    )
    parser.add_argument("--delay", type=float, default=3.0)
    args = parser.parse_args()

    if args.post_url:
        urls = [args.post_url]
    else:
        inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
        urls = inventory["post_urls"]

    checkpoint = load_checkpoint(args.checkpoint)
    remaining = [
        url for url in urls
        if url not in checkpoint["completed"]
    ]

    selected = (
        remaining
        if args.max_posts == 0
        else remaining[:args.max_posts]
    )

    db = initialize_database()

    try:
        repository = WarrigalRepository(db)
        object_store = ObjectStore()

        node = Node(name="Warrigal Instagram Browser")
        repository.save_node(node)

        batch = Batch(
            node_id=node.node_id,
            label="Instagram browser campaign",
        )
        repository.save_batch(batch)

        job = Job(
            name="Instagram browser campaign",
            node_id=node.node_id,
            batch_id=batch.batch_id,
        )
        repository.save_job(job)

        collection = Collection(
            name="Instagram Acquisitions",
            description="Instagram evidence preserved by Warrigal.",
        )
        repository.save_collection(collection)

        succeeded = 0
        failed = 0

        for number, post_url in enumerate(selected, start=1):
            print(f"[{number}/{len(selected)}] {post_url}", flush=True)

            try:
                result = archive_post(
                    post_url,
                    repository=repository,
                    object_store=object_store,
                    job=job,
                    node=node,
                    batch=batch,
                    collection=collection,
                )
            except Exception as exc:
                failed += 1
                checkpoint["failed"][post_url] = {
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "updated_at": datetime.now().astimezone().isoformat(),
                }
                print(
                    f"  FAILED: {type(exc).__name__}: {exc}",
                    flush=True,
                )
            else:
                succeeded += 1
                checkpoint["completed"][post_url] = {
                    "snapshot_object": result["snapshot"].object_id,
                    "snapshot_acquisition": result[
                        "snapshot"
                    ].acquisition_id,
                    "evidence_files": len(result["evidence"]),
                    "updated_at": datetime.now().astimezone().isoformat(),
                }
                checkpoint["failed"].pop(post_url, None)
                print(
                    f"  COMPLETED: evidence={len(result['evidence'])}",
                    flush=True,
                )

            save_checkpoint(args.checkpoint, checkpoint)

            if number < len(selected):
                time.sleep(args.delay)

        print()
        print("=== INSTAGRAM BROWSER CAMPAIGN COMPLETE ===")
        print("SELECTED:", len(selected))
        print("SUCCEEDED:", succeeded)
        print("FAILED:", failed)
        print("TOTAL CHECKPOINTED:", len(checkpoint["completed"]))
        print("CHECKPOINT:", args.checkpoint.resolve())

        return 1 if failed else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
