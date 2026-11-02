from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from warrigal.config import load_config


class ConfigTests(unittest.TestCase):
    def test_archive_override_drives_default_runtime_path(self):
        with patch.dict(os.environ, {"WARRIGAL_ARCHIVE_ROOT": "/tmp/warrigal-archive"}, clear=True):
            config = load_config()
        self.assertEqual(config.archive_root, Path("/tmp/warrigal-archive"))
        self.assertEqual(
            config.runtime_root,
            Path("/tmp/warrigal-archive/SYSTEM/WARRIGAL/runtime"),
        )

    def test_explicit_paths_and_tools_are_respected(self):
        values = {
            "WARRIGAL_DATABASE_PATH": "/tmp/warrigal.db",
            "WARRIGAL_OBJECT_STORE": "/tmp/objects",
            "WARRIGAL_FFMPEG": "/tools/ffmpeg",
        }
        with patch.dict(os.environ, values, clear=True):
            config = load_config()
        self.assertEqual(config.database_path, Path("/tmp/warrigal.db"))
        self.assertEqual(config.object_store_path, Path("/tmp/objects"))
        self.assertEqual(config.ffmpeg, "/tools/ffmpeg")

    def test_local_toml_supplies_machine_specific_models(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "warrigal.local.toml"
            path.write_text(
                '[paths]\narchive_root = "/archive"\n'
                '[tools]\nllama = "/tools/llama-cli"\n'
                '[models]\nqwen = "/models/qwen.gguf"\n',
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                config = load_config(path)
        self.assertEqual(config.archive_root, Path("/archive"))
        self.assertEqual(config.llama, "/tools/llama-cli")
        self.assertEqual(config.qwen_model, Path("/models/qwen.gguf"))

    def test_brave_api_key_env_var_takes_precedence_over_toml_value(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "warrigal.local.toml"
            path.write_text(
                '[search]\nbrave_api_key = "toml-test-only-fake-key"\n',
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"WARRIGAL_BRAVE_API_KEY": "env-test-only-fake-key"},
                clear=True,
            ):
                config = load_config(path)
        self.assertEqual(config.brave_api_key, "env-test-only-fake-key")

    def test_brave_api_key_falls_back_to_toml_value_when_env_var_absent(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "warrigal.local.toml"
            path.write_text(
                '[search]\nbrave_api_key = "toml-test-only-fake-key"\n',
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                config = load_config(path)
        self.assertEqual(config.brave_api_key, "toml-test-only-fake-key")

    def test_brave_api_key_is_none_when_neither_env_var_nor_toml_value_is_set(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "warrigal.local.toml"
            path.write_text("", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                config = load_config(path)
        self.assertIsNone(config.brave_api_key)

    def test_tavily_api_key_env_var_takes_precedence_over_toml_value(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "warrigal.local.toml"
            path.write_text(
                '[search]\ntavily_api_key = "toml-test-only-fake-key"\n',
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"WARRIGAL_TAVILY_API_KEY": "env-test-only-fake-key"},
                clear=True,
            ):
                config = load_config(path)
        self.assertEqual(config.tavily_api_key, "env-test-only-fake-key")

    def test_tavily_api_key_falls_back_to_toml_value_when_env_var_absent(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "warrigal.local.toml"
            path.write_text(
                '[search]\ntavily_api_key = "toml-test-only-fake-key"\n',
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                config = load_config(path)
        self.assertEqual(config.tavily_api_key, "toml-test-only-fake-key")

    def test_tavily_api_key_is_none_when_neither_env_var_nor_toml_value_is_set(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "warrigal.local.toml"
            path.write_text("", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                config = load_config(path)
        self.assertIsNone(config.tavily_api_key)

    def test_searxng_instance_url_env_var_takes_precedence_over_toml_value(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "warrigal.local.toml"
            path.write_text(
                '[search]\nsearxng_instance_url = "https://toml-instance.test"\n',
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"WARRIGAL_SEARXNG_URL": "https://env-instance.test"},
                clear=True,
            ):
                config = load_config(path)
        self.assertEqual(config.searxng_instance_url, "https://env-instance.test")

    def test_searxng_instance_url_falls_back_to_toml_value_when_env_var_absent(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "warrigal.local.toml"
            path.write_text(
                '[search]\nsearxng_instance_url = "https://toml-instance.test"\n',
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                config = load_config(path)
        self.assertEqual(config.searxng_instance_url, "https://toml-instance.test")

    def test_searxng_instance_url_defaults_to_the_builtin_public_instance_when_unset(self):
        from tempfile import TemporaryDirectory

        from warrigal.config import DEFAULT_SEARXNG_INSTANCE_URL

        with TemporaryDirectory() as directory:
            path = Path(directory) / "warrigal.local.toml"
            path.write_text("", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                config = load_config(path)
        self.assertEqual(config.searxng_instance_url, DEFAULT_SEARXNG_INSTANCE_URL)
        # The default must require no account/key - it's a bare URL string.
        self.assertTrue(config.searxng_instance_url.startswith("https://"))

    def test_online_search_provider_env_var_takes_precedence_over_toml_value(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "warrigal.local.toml"
            path.write_text('[search]\nprovider = "brave"\n', encoding="utf-8")
            with patch.dict(
                os.environ,
                {"WARRIGAL_ONLINE_SEARCH_PROVIDER": "searxng"},
                clear=True,
            ):
                config = load_config(path)
        self.assertEqual(config.online_search_provider, "searxng")

    def test_online_search_provider_falls_back_to_toml_value_when_env_var_absent(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "warrigal.local.toml"
            path.write_text('[search]\nprovider = "brave"\n', encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                config = load_config(path)
        self.assertEqual(config.online_search_provider, "brave")

    def test_online_search_provider_defaults_to_searxng_when_unset(self):
        from tempfile import TemporaryDirectory

        from warrigal.config import DEFAULT_ONLINE_SEARCH_PROVIDER

        with TemporaryDirectory() as directory:
            path = Path(directory) / "warrigal.local.toml"
            path.write_text("", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                config = load_config(path)
        self.assertEqual(config.online_search_provider, DEFAULT_ONLINE_SEARCH_PROVIDER)
        self.assertEqual(config.online_search_provider, "searxng")


if __name__ == "__main__":
    unittest.main()
