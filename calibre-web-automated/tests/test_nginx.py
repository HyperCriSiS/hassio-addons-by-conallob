"""Linux CI integration test for the unmodified production nginx ACL."""

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest


@unittest.skipUnless(os.environ.get('CWA_TEST_NGINX') == '1',
                     'requires nginx and 172.30.32.2 on loopback (Linux CI)')
class NginxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Backend(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps(dict(self.headers)).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        cls.backend = ThreadingHTTPServer(('127.0.0.1', 8083), Backend)
        cls.thread = threading.Thread(target=cls.backend.serve_forever, daemon=True)
        cls.thread.start()
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        template = (Path(__file__).resolve().parents[1]
                    / 'rootfs/etc/nginx/cwa-ingress.conf.template').read_text()
        config = template.replace('__CWA_INGRESS_PATH__', '/api/hassio_ingress/test')
        config = config.replace('/run/nginx.pid', str(root / 'nginx.pid'))
        paths = '\n'.join(f'{name}_temp_path {root / name};'
                          for name in ('client_body', 'proxy', 'fastcgi', 'uwsgi', 'scgi'))
        config = config.replace('http {', 'http {\n' + paths)
        cls.config = root / 'nginx.conf'
        cls.config.write_text(config)
        subprocess.run(['nginx', '-t', '-c', str(cls.config)], check=True)
        cls.log = open(root / 'nginx.log', 'w+')
        cls.proc = subprocess.Popen(['nginx', '-c', str(cls.config), '-g', 'daemon off;'],
                                    stdout=cls.log, stderr=cls.log)
        for _ in range(100):
            try:
                with socket.create_connection(('127.0.0.1', 8084), timeout=.1):
                    return
            except OSError:
                if cls.proc.poll() is not None:
                    cls.log.seek(0)
                    raise RuntimeError(cls.log.read())
                time.sleep(.05)
        raise RuntimeError('nginx did not start')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        cls.log.close()
        cls.backend.shutdown()
        cls.backend.server_close()
        cls.thread.join(timeout=5)
        cls.temp.cleanup()

    def request(self, source, headers):
        conn = http.client.HTTPConnection('127.0.0.1', 8084, timeout=5,
                                          source_address=(source, 0))
        try:
            conn.request('GET', '/', headers=headers)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_non_supervisor_denied_even_with_forged_headers(self):
        status, _ = self.request('127.0.0.1', {
            'X-Forwarded-For': '172.30.32.2', 'X-CWA-Ingress': '1',
            'X-Remote-User-Id': 'a' * 32, 'X-Remote-User-Groups': 'system-admin'})
        self.assertEqual(status, 403)

    def test_supervisor_identity_forwarded_and_marker_overwritten(self):
        status, body = self.request('172.30.32.2', {
            'X-CWA-Ingress': 'forged', 'X-Remote-User-Id': 'b' * 32,
            'X-Remote-User-Groups': 'system-users,system-admin'})
        self.assertEqual(status, 200)
        headers = json.loads(body)
        self.assertEqual(headers['X-CWA-Ingress'], '1')
        self.assertEqual(headers['X-Remote-User-Id'], 'b' * 32)
        self.assertEqual(headers['X-Remote-User-Groups'], 'system-users,system-admin')
        self.assertEqual(headers['X-Script-Name'], '/api/hassio_ingress/test')
