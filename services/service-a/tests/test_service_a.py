import json
import unittest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from service_a import app, _pending_callbacks


class TestServiceAHealth(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch('service_a.requests.get')
    def test_health_returns_200(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)

    @patch('service_a.requests.get')
    def test_health_returns_json(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        response = self.client.get('/health')
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['service'], 'service-a')

    @patch('service_a.requests.get')
    def test_health_includes_port(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        response = self.client.get('/health')
        data = json.loads(response.data)
        self.assertIn('port', data)

    @patch('service_a.requests.get')
    def test_health_ok_when_dependency_ok(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        response = self.client.get('/health')
        data = json.loads(response.data)
        self.assertEqual(data['dependencies']['service-b'], 'ok')

    @patch('service_a.requests.get')
    def test_health_degraded_when_dependency_unreachable(self, mock_get):
        mock_get.side_effect = Exception('Connection refused')
        response = self.client.get('/health')
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'degraded')
        self.assertEqual(data['dependencies']['service-b'], 'unreachable')


class TestServiceAGreet(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch('service_a.requests.get')
    def test_greet_service_b_success(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)

        # Simulate callback arriving by pre-setting the event
        def fake_get(*args, **kwargs):
            request_id = kwargs.get('headers', {}).get('X-Request-ID')
            if request_id and request_id in _pending_callbacks:
                _pending_callbacks[request_id].set()
            return MagicMock(status_code=200)

        mock_get.side_effect = fake_get

        response = self.client.get(
            '/greet-service-b',
            headers={'X-Request-ID': 'test-001'}
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['request_id'], 'test-001')

    @patch('service_a.requests.get')
    def test_greet_service_b_downstream_failure(self, mock_get):
        mock_get.side_effect = Exception('Connection refused')

        response = self.client.get(
            '/greet-service-b',
            headers={'X-Request-ID': 'test-fail-001'}
        )
        self.assertEqual(response.status_code, 500)
        data = json.loads(response.data)
        self.assertIn('error', data)

    def test_greet_service_b_propagates_request_id(self):
        with patch('service_a.requests.get') as mock_get:
            def capture_and_signal(*args, **kwargs):
                request_id = kwargs.get('headers', {}).get('X-Request-ID')
                if request_id and request_id in _pending_callbacks:
                    _pending_callbacks[request_id].set()
                return MagicMock(status_code=200)

            mock_get.side_effect = capture_and_signal
            response = self.client.get(
                '/greet-service-b',
                headers={'X-Request-ID': 'trace-abc'}
            )
            call_headers = mock_get.call_args[1]['headers']
            self.assertEqual(call_headers['X-Request-ID'], 'trace-abc')


class TestServiceACallback(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_greeting_rcvd_returns_200(self):
        response = self.client.post(
            '/greeting-rcvd',
            json={'request_id': 'cb-001', 'source_service': 'service-c'}
        )
        self.assertEqual(response.status_code, 200)

    def test_greeting_rcvd_signals_pending_event(self):
        import threading
        event = threading.Event()
        _pending_callbacks['cb-signal-001'] = event

        self.client.post(
            '/greeting-rcvd',
            json={'request_id': 'cb-signal-001', 'source_service': 'service-c'}
        )
        self.assertTrue(event.is_set())


class TestServiceA404(unittest.TestCase):
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
        from service_a import build_service_url
        self.build_service_url = build_service_url

    def test_normalizes_trailing_slash(self):
        self.assertEqual(
            self.build_service_url('http://service-b:3002/', '/greet'),
            'http://service-b:3002/greet'
        )

    def test_normalizes_no_slash(self):
        self.assertEqual(
            self.build_service_url('http://service-b:3002', '/greet'),
            'http://service-b:3002/greet'
        )


if __name__ == '__main__':
    unittest.main()
