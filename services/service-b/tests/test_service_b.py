import importlib.util
import pathlib
import unittest

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "service_b.py"
SPEC = importlib.util.spec_from_file_location("service_b", MODULE_PATH)
service_b = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(service_b)


class ServiceBTests(unittest.TestCase):
    def test_build_service_url_normalizes_paths(self):
        self.assertEqual(
            service_b.build_service_url("http://service-c:3003", "/greet-c"),
            "http://service-c:3003/greet-c",
        )
        self.assertEqual(
            service_b.build_service_url("http://service-c:3003/", "greet-c"),
            "http://service-c:3003/greet-c",
        )


if __name__ == "__main__":
    unittest.main()
