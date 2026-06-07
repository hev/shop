import unittest

from hev_shop_common.config import Settings


class SettingsTests(unittest.TestCase):
    def test_gateway_url_is_trimmed(self):
        settings = Settings(LAYER_GATEWAY_URL="https://example.test/")

        self.assertEqual(settings.layer_gateway_url, "https://example.test")

    def test_resolved_worker_id_defaults_to_worker_type(self):
        settings = Settings(WORKER_TYPE="gpu")

        self.assertEqual(settings.resolved_worker_id, "gpu-worker")

    def test_explicit_worker_id_wins(self):
        settings = Settings(WORKER_TYPE="gpu", WORKER_ID="pod-1")

        self.assertEqual(settings.resolved_worker_id, "pod-1")


if __name__ == "__main__":
    unittest.main()
