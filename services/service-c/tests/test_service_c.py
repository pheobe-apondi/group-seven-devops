import json
import unittest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from service_c import app


class TestServiceCHealth(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_health_returns_200(self):
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)

    def test_health_returns_json(self):
        response = self.client.get('/health')
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['service'], 'service-c')

    def test_health_includes_port(self):
        response = self.client.get('/health')
        data = json.loads(response.data)
        self.assertIn('port', data)


class TestServiceCGreet(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch('service_c.requests.post')
    def test_greet_c_sends_callback(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)

        response = self.client.get(
            '/greet-c',
            headers={'X-Request-ID': 'test-c-001'}
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['callback_sent'])
        self.assertEqual(data['status'], 'processed')

    @patch('service_c.requests.post')
    def test_greet_c_propagates_request_id(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)

        self.client.get('/greet-c', headers={'X-Request-ID': 'trace-c-001'})
        call_headers = mock_post.call_args[1]['headers']
        self.assertEqual(call_headers['X-Request-ID'], 'trace-c-001')

    @patch('service_c.requests.post')
    def test_greet_c_callback_failure_returns_500(self, mock_post):
        mock_post.side_effect = Exception('Connection refused')

        response = self.client.get(
            '/greet-c',
            headers={'X-Request-ID': 'test-c-fail-001'}
        )
        self.assertEqual(response.status_code, 500)
        data = json.loads(response.data)
        self.assertIn('error', data)

    @patch('service_c.requests.post')
    def test_greet_c_includes_request_id_in_response(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)

        response = self.client.get(
            '/greet-c',
            headers={'X-Request-ID': 'test-c-002'}
        )
        data = json.loads(response.data)
        self.assertEqual(data['request_id'], 'test-c-002')


class TestServiceC404(unittest.TestCase):
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
        from service_c import build_service_url
        self.build_service_url = build_service_url

    def test_normalizes_trailing_slash(self):
        self.assertEqual(
            self.build_service_url('http://service-a:3001/', '/greeting-rcvd'),
            'http://service-a:3001/greeting-rcvd'
        )

    def test_normalizes_no_slash(self):
        self.assertEqual(
            self.build_service_url('http://service-a:3001', '/greeting-rcvd'),
            'http://service-a:3001/greeting-rcvd'
        )


if __name__ == '__main__':
    unittest.main()
