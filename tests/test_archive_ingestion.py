from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from warrigal.acquisition.archive import discover_pdf_files


class ArchiveIngestionTests(unittest.TestCase):
    def test_discover_pdf_files_recursively_finds_only_pdfs(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            nested = root / "COLLECTIONS" / "TEST" / "ORIGINALS"
            nested.mkdir(parents=True)

            (root / "root.pdf").write_bytes(b"root")
            (nested / "nested.PDF").write_bytes(b"nested")
            (nested / "notes.txt").write_text("ignore me", encoding="utf-8")
            (nested / "image.jpg").write_bytes(b"ignore me")

            discovered = discover_pdf_files(root)

            self.assertEqual(
                discovered,
                sorted(
                    [
                        (root / "root.pdf").resolve(),
                        (nested / "nested.PDF").resolve(),
                    ],
                    key=lambda path: str(path).casefold(),
                ),
            )

    def test_discover_pdf_files_rejects_missing_directory(self):
        with TemporaryDirectory() as temporary_directory:
            missing = Path(temporary_directory) / "missing"

            with self.assertRaises(NotADirectoryError):
                discover_pdf_files(missing)


    def test_ingest_pdf_archive_preserves_deduplication_and_searchable_passages(self):
        from pypdf import PdfWriter
        from pypdf.generic import (
            DecodedStreamObject,
            DictionaryObject,
            NameObject,
        )

        from warrigal.acquisition.archive import ingest_pdf_archive
        from warrigal.database import initialize_database
        from warrigal.models import Batch, Collection, Job, Node
        from warrigal.object_store import ObjectStore
        from warrigal.repository import WarrigalRepository

        def make_pdf(path: Path, text: str | None) -> bytes:
            writer = PdfWriter()
            page = writer.add_blank_page(width=612, height=792)

            if text is not None:
                font = DictionaryObject(
                    {
                        NameObject("/Type"): NameObject("/Font"),
                        NameObject("/Subtype"): NameObject("/Type1"),
                        NameObject("/BaseFont"): NameObject("/Helvetica"),
                    }
                )

                resources = DictionaryObject(
                    {
                        NameObject("/Font"): DictionaryObject(
                            {
                                NameObject("/F1"): font,
                            }
                        ),
                    }
                )
                page[NameObject("/Resources")] = resources

                stream = DecodedStreamObject()
                stream.set_data(
                    (
                        "BT\n"
                        "/F1 12 Tf\n"
                        "72 720 Td\n"
                        f"({text}) Tj\n"
                        "ET\n"
                    ).encode("ascii")
                )
                page[NameObject("/Contents")] = stream

            with path.open("wb") as handle:
                writer.write(handle)

            return path.read_bytes()

        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            archive_root = temporary_root / "archive"
            archive_root.mkdir()

            first_path = archive_root / "first.pdf"
            duplicate_path = archive_root / "duplicate.pdf"
            no_text_path = archive_root / "no_text.pdf"

            first_bytes = make_pdf(
                first_path,
                "respiratory syncytial virus evidence",
            )
            duplicate_path.write_bytes(first_bytes)
            make_pdf(no_text_path, None)
            (archive_root / "ignore.txt").write_text(
                "not a PDF",
                encoding="utf-8",
            )

            connection = initialize_database(temporary_root / "warrigal.db")
            repository = WarrigalRepository(connection)
            object_store = ObjectStore(temporary_root / "objects")

            node = Node(name="Archive Test")
            repository.save_node(node)

            batch = Batch(
                node_id=node.node_id,
                label="Archive test batch",
            )
            repository.save_batch(batch)

            job = Job(
                name="Archive test job",
                node_id=node.node_id,
                batch_id=batch.batch_id,
            )
            repository.save_job(job)

            collection = Collection(
                name="Archive Test Collection",
            )
            repository.save_collection(collection)

            result = ingest_pdf_archive(
                archive_root,
                repository=repository,
                object_store=object_store,
                job_id=job.job_id,
                node_id=node.node_id,
                batch_id=batch.batch_id,
                collection_id=collection.collection_id,
            )

            self.assertEqual(result.discovered_count, 3)
            self.assertEqual(result.ingested_count, 1)
            self.assertEqual(result.duplicate_count, 1)
            self.assertEqual(result.no_text_count, 1)
            self.assertEqual(result.failed_count, 0)
            self.assertGreater(result.passage_count, 0)

            statuses = {
                file_result.path.name: file_result.status
                for file_result in result.files
            }

            duplicate_pair_statuses = {
                statuses["first.pdf"],
                statuses["duplicate.pdf"],
            }

            self.assertEqual(
                duplicate_pair_statuses,
                {"ingested", "duplicate"},
            )
            self.assertEqual(statuses["no_text.pdf"], "no_text")

            acquisition_count = connection.execute(
                "SELECT COUNT(*) FROM acquisitions"
            ).fetchone()[0]

            passage_count = connection.execute(
                "SELECT COUNT(*) FROM passages"
            ).fetchone()[0]

            object_count = connection.execute(
                "SELECT COUNT(*) FROM objects"
            ).fetchone()[0]

            self.assertEqual(acquisition_count, 3)
            self.assertEqual(object_count, 2)
            self.assertEqual(passage_count, result.passage_count)

            connection.close()


if __name__ == "__main__":
    unittest.main()
