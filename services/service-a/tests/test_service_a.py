import importlib.util
import pathlib
import unittest

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "service_a.py"
SPEC = importlib.util.spec_from_file_location("service_a", MODULE_PATH)
service_a = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(service_a)



class ServiceATests(unittest.TestCase):
    def test_build_service_url_normalizes_paths(self):
        self.assertEqual(
            service_a.build_service_url("http://service-b:3002", "/greet"),
            "http://service-b:3002/greet",
        )
        self.assertEqual(
            service_a.build_service_url("http://service-b:3002/", "greet"),
            "http://service-b:3002/greet",
        )


if __name__ == "__main__":
    unittest.main()
