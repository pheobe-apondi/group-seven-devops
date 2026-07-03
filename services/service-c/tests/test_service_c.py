import importlib.util
import pathlib
import unittest

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "service_c.py"
SPEC = importlib.util.spec_from_file_location("service_c", MODULE_PATH)
service_c = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(service_c)


class ServiceCTests(unittest.TestCase):
    def test_build_service_url_normalizes_paths(self):
        self.assertEqual(
            service_c.build_service_url("http://service-a:3001", "/greeting-rcvd"),
            "http://service-a:3001/greeting-rcvd",
        )
        self.assertEqual(
            service_c.build_service_url("http://service-a:3001/", "greeting-rcvd"),
            "http://service-a:3001/greeting-rcvd",
        )


if __name__ == "__main__":
    unittest.main()
