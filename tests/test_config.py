import json
import tempfile
import unittest
from pathlib import Path

from rooomtech_router.config import RouterConfig, load_config
from rooomtech_router.errors import ConfigurationError

from tests.helpers import make_config


class ConfigTests(unittest.TestCase):
    def test_valid_config(self):
        config = make_config()
        self.assertEqual(len(config.models), 3)
        self.assertEqual(config.tenant("missing"), config.tenants["default"])

    def test_duplicate_model_rejected(self):
        raw = {
            "models": [
                {"id": "x", "provider": "p", "base_url": "http://a/v1", "model": "m"},
                {"id": "x", "provider": "p", "base_url": "http://b/v1", "model": "m"},
            ]
        }
        with self.assertRaises(ConfigurationError):
            RouterConfig.from_dict(raw)

    def test_load_utf8_json(self):
        config = make_config()
        raw = {
            "models": [
                {
                    "id": model.id,
                    "provider": model.provider,
                    "base_url": model.base_url,
                    "model": model.model,
                }
                for model in config.models
            ]
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "設定.json"
            path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            loaded = load_config(path)
            self.assertEqual(len(loaded.models), 3)


if __name__ == "__main__":
    unittest.main()

