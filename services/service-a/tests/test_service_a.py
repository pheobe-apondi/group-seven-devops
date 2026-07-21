import json
import unittest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from service_a import app, wait_for_callback


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

    @patch('service_a.callbacks_table')
    @patch('service_a.requests.get')
    def test_greet_service_b_success(self, mock_get, mock_table):
        mock_get.return_value = MagicMock(status_code=200)
        # Callback already present on first poll, so wait_for_callback returns immediately
        mock_table.get_item.return_value = {'Item': {'request_id': 'test-001'}}

        response = self.client.get(
            '/greet-service-b',
            headers={'X-Request-ID': 'test-001'}
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['request_id'], 'test-001')
        mock_table.delete_item.assert_called_once_with(Key={'request_id': 'test-001'})

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

    @patch('service_a.callbacks_table')
    def test_greet_service_b_propagates_request_id(self, mock_table):
        mock_table.get_item.return_value = {'Item': {'request_id': 'trace-abc'}}
        with patch('service_a.requests.get') as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            response = self.client.get(
                '/greet-service-b',
                headers={'X-Request-ID': 'trace-abc'}
            )
            call_headers = mock_get.call_args[1]['headers']
            self.assertEqual(call_headers['X-Request-ID'], 'trace-abc')



class TestWaitForCallback(unittest.TestCase):
    """Callback coordination lives in DynamoDB (shared across service-a's replicas), not an
    in-process dict, since Service Connect load-balances the /greeting-rcvd callback across
    whichever tasks are running and can't guarantee it lands back on the task that is waiting."""

    @patch('service_a.callbacks_table')
    def test_returns_true_when_callback_found(self, mock_table):
        mock_table.get_item.return_value = {'Item': {'request_id': 'x'}}
        self.assertTrue(wait_for_callback('x', timeout=1, poll_interval=0.05))
        mock_table.delete_item.assert_called_once_with(Key={'request_id': 'x'})

    @patch('service_a.callbacks_table')
    def test_returns_false_on_timeout(self, mock_table):
        mock_table.get_item.return_value = {}
        self.assertFalse(wait_for_callback('x', timeout=0.2, poll_interval=0.05))
        mock_table.delete_item.assert_not_called()


class TestServiceACallback(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch('service_a.callbacks_table')
    def test_greeting_rcvd_returns_200(self, mock_table):
        response = self.client.post(
            '/greeting-rcvd',
            json={'request_id': 'cb-001', 'source_service': 'service-c'}
        )
        self.assertEqual(response.status_code, 200)

    @patch('service_a.callbacks_table')
    def test_greeting_rcvd_stores_callback_in_table(self, mock_table):
        self.client.post(
            '/greeting-rcvd',
            json={'request_id': 'cb-signal-001', 'source_service': 'service-c'}
        )
        mock_table.put_item.assert_called_once()
        stored_item = mock_table.put_item.call_args[1]['Item']
        self.assertEqual(stored_item['request_id'], 'cb-signal-001')
        self.assertEqual(stored_item['source_service'], 'service-c')
        self.assertIn('expires_at', stored_item)


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
