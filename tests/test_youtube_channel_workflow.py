from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace


def _module(name: str, **values):
    module = types.ModuleType(name)
    for key, value in values.items():
        setattr(module, key, value)
    sys.modules[name] = module


class _YouTubeVideo:
    def __init__(self, video_id: str, title: str, url: str):
        self.video_id = video_id
        self.title = title
        self.url = url


_STUB_NAMES = (
    "warrigal.acquisition.service",
    "warrigal.acquisition.youtube",
    "warrigal.acquisition.youtube_comment_index",
    "warrigal.acquisition.youtube_comments",
    "warrigal.acquisition.youtube_posts",
    "warrigal.models",
    "warrigal.object_store",
    "warrigal.repository",
)
_original_modules = {name: sys.modules.get(name) for name in _STUB_NAMES}
try:
    _module("warrigal.acquisition.service", AcquisitionService=object)
    _module(
        "warrigal.acquisition.youtube",
        YouTubeVideo=_YouTubeVideo,
        discover_channel_videos=lambda *_a, **_k: [],
        ingest_video_transcript=lambda *_a, **_k: None,
    )
    _module("warrigal.acquisition.youtube_comment_index", index_archived_youtube_comments=lambda **_k: None)
    _module("warrigal.acquisition.youtube_comments", preserve_youtube_comment_snapshot=lambda *_a, **_k: None)
    _module("warrigal.acquisition.youtube_posts", ingest_youtube_posts=lambda *_a, **_k: None)
    _module("warrigal.models", Source=object)
    _module("warrigal.object_store", ObjectStore=object)
    _module("warrigal.repository", WarrigalRepository=object)

    SPEC = importlib.util.spec_from_file_location(
        "youtube_channel_workflow_under_test",
        Path(__file__).parents[1] / "src" / "warrigal" / "acquisition" / "youtube_channel_workflow.py",
    )
    assert SPEC and SPEC.loader
    WORKFLOW = importlib.util.module_from_spec(SPEC)
    sys.modules[SPEC.name] = WORKFLOW
    SPEC.loader.exec_module(WORKFLOW)
finally:
    for name, original in _original_modules.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


def _acquisition(**extra):
    values = {
        "object_id": "object-1",
        "acquisition_id": "acquisition-1",
        "sha256": "abc",
        "passage_count": 4,
        "collected_count": 7,
        "new_count": 2,
    }
    values.update(extra)
    return SimpleNamespace(**values)


class YouTubeChannelWorkflowTests(unittest.TestCase):
    def test_resumes_completed_video_and_processes_next(self):
        videos = [
            _YouTubeVideo("one", "One", "https://youtu.be/one"),
            _YouTubeVideo("two", "Two", "https://youtu.be/two"),
        ]
        transcript_calls = []
        comment_calls = []

        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "channel.json"

            def run(max_videos):
                return WORKFLOW.run_youtube_channel_workflow(
                    "https://youtube.com/@example",
                    checkpoint_path=checkpoint,
                    posts_checkpoint_path=Path(directory) / "posts.json",
                    max_videos=max_videos,
                    repository=object(), object_store=object(),
                    job_id="j", node_id="n", batch_id="b", collection_id="c",
                    discoverer=lambda *_a, **_k: videos,
                    inventory_preserver=lambda *_a, **_k: _acquisition(),
                    transcript_ingestor=lambda url, **_k: transcript_calls.append(url) or _acquisition(),
                    comment_preserver=lambda url, **_k: comment_calls.append(url) or _acquisition(),
                    posts_ingestor=lambda *_a, **_k: _acquisition(),
                    comment_indexer=lambda **_k: SimpleNamespace(passages_created=7),
                )

            first = run(1)
            second = run(1)

            self.assertEqual(first.selected_count, 1)
            self.assertEqual(second.selected_count, 1)
            self.assertEqual(transcript_calls, [videos[0].url, videos[1].url])
            self.assertEqual(comment_calls, [videos[0].url, videos[1].url])
            payload = json.loads(checkpoint.read_text())
            self.assertEqual(payload["videos"]["one"]["comments"]["status"], "completed")
            self.assertEqual(payload["videos"]["two"]["comments"]["status"], "completed")

    def test_missing_caption_is_unavailable_not_failed(self):
        video = _YouTubeVideo("one", "One", "https://youtu.be/one")

        def no_caption(*_a, **_k):
            raise ValueError("No JSON3 caption track found for this video")

        with tempfile.TemporaryDirectory() as directory:
            result = WORKFLOW.run_youtube_channel_workflow(
                "https://youtube.com/@example",
                checkpoint_path=Path(directory) / "channel.json",
                posts_checkpoint_path=Path(directory) / "posts.json",
                repository=object(), object_store=object(),
                job_id="j", node_id="n", batch_id="b", collection_id="c",
                discoverer=lambda *_a, **_k: [video],
                inventory_preserver=lambda *_a, **_k: _acquisition(),
                transcript_ingestor=no_caption,
                comment_preserver=lambda *_a, **_k: _acquisition(),
                posts_ingestor=lambda *_a, **_k: _acquisition(),
                comment_indexer=lambda **_k: SimpleNamespace(passages_created=0),
            )
            self.assertEqual(result.failed_count, 0)
            self.assertEqual(result.unavailable_transcript_count, 1)
            self.assertEqual(result.completed_count, 1)

    def test_checkpoint_rejects_different_channel(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WORKFLOW.YouTubeChannelCheckpointStore(Path(directory) / "checkpoint.json")
            payload = store.load("https://youtube.com/@one")
            store.save(payload)
            with self.assertRaisesRegex(ValueError, "different channel"):
                store.load("https://youtube.com/@two")


if __name__ == "__main__":
    unittest.main()
