import json
import unittest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from service_b import app


class TestServiceBHealth(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch('service_b.requests.get')
    def test_health_returns_200(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)

    @patch('service_b.requests.get')
    def test_health_returns_json(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        response = self.client.get('/health')
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['service'], 'service-b')

    @patch('service_b.requests.get')
    def test_health_includes_port(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        response = self.client.get('/health')
        data = json.loads(response.data)
        self.assertIn('port', data)

    @patch('service_b.requests.get')
    def test_health_includes_version(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        response = self.client.get('/health')
        data = json.loads(response.data)
        self.assertIn('version', data)

    @patch('service_b.requests.get')
    def test_health_ok_when_dependency_ok(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        response = self.client.get('/health')
        data = json.loads(response.data)
        self.assertEqual(data['dependencies']['service-c'], 'ok')

    @patch('service_b.requests.get')
    def test_health_degraded_when_dependency_unreachable(self, mock_get):
        mock_get.side_effect = Exception('Connection refused')
        response = self.client.get('/health')
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'degraded')
        self.assertEqual(data['dependencies']['service-c'], 'unreachable')


class TestServiceBVersion(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_version_returns_200(self):
        response = self.client.get('/version')
        self.assertEqual(response.status_code, 200)

    def test_version_returns_json(self):
        response = self.client.get('/version')
        data = json.loads(response.data)
        self.assertEqual(data['service'], 'service-b')
        self.assertEqual(data['status'], 'ok')
        self.assertIn('version', data)


class TestServiceBGreet(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch('service_b.requests.get')
    def test_greet_forwards_to_service_c(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)

        response = self.client.get(
            '/greet',
            headers={'X-Request-ID': 'test-b-001'}
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'forwarded')
        self.assertEqual(data['target'], 'service-c')

    @patch('service_b.requests.get')
    def test_greet_propagates_request_id(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)

        self.client.get('/greet', headers={'X-Request-ID': 'trace-b-001'})
        call_headers = mock_get.call_args[1]['headers']
        self.assertEqual(call_headers['X-Request-ID'], 'trace-b-001')

    @patch('service_b.requests.get')
    def test_greet_downstream_failure_returns_500(self, mock_get):
        mock_get.side_effect = Exception('Connection refused')

        response = self.client.get(
            '/greet',
            headers={'X-Request-ID': 'test-b-fail-001'}
        )
        self.assertEqual(response.status_code, 500)
        data = json.loads(response.data)
        self.assertIn('error', data)


class TestServiceB404(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_unknown_route_returns_404(self):
        response = self.client.get('/does-not-exist')
        self.assertEqual(response.status_code, 404)

    def test_unknown_route_returns_json(self):
        response = self.client.get('/does-not-exist')
        data = json.loads(response.data)
        self.assertIn('error', data)


class TestBuildServiceUrl(unittest.TestCase):
    def setUp(self):
        from service_b import build_service_url
        self.build_service_url = build_service_url

    def test_normalizes_trailing_slash(self):
        self.assertEqual(
            self.build_service_url('http://service-c:3003/', '/greet-c'),
            'http://service-c:3003/greet-c'
        )

    def test_normalizes_no_slash(self):
        self.assertEqual(
            self.build_service_url('http://service-c:3003', '/greet-c'),
            'http://service-c:3003/greet-c'
        )


if __name__ == '__main__':
    unittest.main()
