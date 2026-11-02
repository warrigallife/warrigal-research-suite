import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from warrigal.acquisition.web import WebResponse
from warrigal.acquisition.service import AcquisitionResult
from warrigal.cli import run_acquire


def _patched(**overrides):
    defaults = dict(
        initialize_database=Mock(return_value=Mock()),
        WarrigalRepository=Mock(),
        ObjectStore=Mock(),
        Node=Mock(return_value=SimpleNamespace(node_id="WRG-NODE-TEST")),
        Batch=Mock(return_value=SimpleNamespace(batch_id="WRG-BATCH-TEST")),
        Job=Mock(return_value=SimpleNamespace(job_id="WRG-JOB-TEST")),
        Collection=Mock(
            return_value=SimpleNamespace(collection_id="WRG-COL-TEST")
        ),
        Source=Mock(return_value=SimpleNamespace(source_id="WRG-SRC-TEST")),
    )
    defaults.update(overrides)
    return defaults


class RunAcquirePassageExtractionTests(unittest.TestCase):
    def _run(self, response, repository):
        patched = _patched(
            WarrigalRepository=Mock(return_value=repository),
        )

        with (
            patch("warrigal.cli.initialize_database", patched["initialize_database"]),
            patch("warrigal.cli.WarrigalRepository", patched["WarrigalRepository"]),
            patch("warrigal.cli.ObjectStore", patched["ObjectStore"]),
            patch("warrigal.cli.Node", patched["Node"]),
            patch("warrigal.cli.Batch", patched["Batch"]),
            patch("warrigal.cli.Job", patched["Job"]),
            patch("warrigal.cli.Collection", patched["Collection"]),
            patch("warrigal.cli.Source", patched["Source"]),
            patch("warrigal.cli.WebFetcher") as fetcher_cls,
            patch(
                "warrigal.cli.AcquisitionService.acquire_bytes",
                return_value=AcquisitionResult(
                    object_id="WRG-OBJ-TEST",
                    acquisition_id="WRG-ACQ-TEST",
                    sha256="deadbeef",
                    size_bytes=len(response.data),
                    archive_path="archive/objects/de/ad/deadbeef",
                    deduplicated=False,
                ),
            ),
        ):
            fetcher_cls.return_value.fetch.return_value = response
            result = run_acquire(response.requested_url)

        return result

    def test_html_response_is_split_into_passages_and_saved(self):
        html = (
            b"<html><head><title>Ganoderma australe</title></head>"
            b"<body><p>" + (b"word " * 150) + b"</p></body></html>"
        )
        response = WebResponse(
            requested_url="https://example.com/page",
            final_url="https://example.com/page",
            status=200,
            content_type="text/html",
            data=html,
        )
        repository = Mock()
        repository.object_has_passages.return_value = False

        result = self._run(response, repository)

        self.assertEqual(result, 0)
        repository.object_has_passages.assert_called_once_with("WRG-OBJ-TEST")
        self.assertGreaterEqual(repository.save_passage.call_count, 2)

        saved_passages = [
            call.args[0] for call in repository.save_passage.call_args_list
        ]
        self.assertTrue(
            all(p.object_id == "WRG-OBJ-TEST" for p in saved_passages)
        )
        self.assertTrue(
            all(p.acquisition_id == "WRG-ACQ-TEST" for p in saved_passages)
        )
        self.assertTrue(
            all(p.source_title == "Ganoderma australe" for p in saved_passages)
        )

    def test_already_indexed_object_is_not_re_extracted(self):
        response = WebResponse(
            requested_url="https://example.com/page",
            final_url="https://example.com/page",
            status=200,
            content_type="text/html",
            data=b"<html><body>irrelevant</body></html>",
        )
        repository = Mock()
        repository.object_has_passages.return_value = True

        result = self._run(response, repository)

        self.assertEqual(result, 0)
        repository.save_passage.assert_not_called()

    def test_unsupported_content_type_is_preserved_without_extraction(self):
        response = WebResponse(
            requested_url="https://example.com/data.bin",
            final_url="https://example.com/data.bin",
            status=200,
            content_type="application/octet-stream",
            data=b"\x00\x01\x02\x03",
        )
        repository = Mock()
        repository.object_has_passages.return_value = False

        result = self._run(response, repository)

        self.assertEqual(result, 0)
        repository.save_passage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
