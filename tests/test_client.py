import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from prepare_synchrobook.client import NokturnClient

KEY = 'nk_sync_' + 'a' * 24 + '.' + 'b' * 43
EPUB = Path(__file__).parent / 'fixtures' / 'source.epub'


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        calls = self.calls
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def answer(self, value, status=200):
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(value).encode())

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                calls.append((self.path, self.headers.get('Authorization'), body, self.headers.get('Content-Type')))
                self.answer({'status': 'imported', 'audiobook_id': 42, 'paragraphs': 2})

            def do_GET(self):
                calls.append((self.path, self.headers.get('Authorization'), None, None))
                if not self.headers.get('User-Agent', '').startswith('PrepareSynchrobook/'):
                    self.answer({'detail': 'Identified client required'}, 403)
                    return
                if self.path == '/api/synchrobooks/capabilities':
                    self.answer({'schema': 1, 'existing_epub_only': True})
                elif self.path.startswith('/api/synchrobooks/books?'):
                    self.answer({'items': [{'id': 42, 'title': 'Żółw'}]})
                elif self.path.endswith('/epub'):
                    self.send_response(200)
                    self.send_header('Content-Type','application/epub+zip')
                    self.end_headers()
                    self.wfile.write(EPUB.read_bytes())
                elif self.path == '/expired':
                    self.answer({'detail': 'Klucz odwołany'}, 401)
                else:
                    self.send_response(302)
                    self.send_header('Location', '/must-not-receive-key')
                    self.end_headers()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = NokturnClient(f'http://127.0.0.1:{self.server.server_port}')

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_connect_download_search_upload_without_account_credentials(self):
        self.assertEqual(self.client.connect(KEY), 'klucz API')
        self.assertEqual(self.client.search('Żółw & głos')[0]['id'], 42)
        with tempfile.TemporaryDirectory() as name:
            source = self.client.download_epub(42, Path(name) / 'source.epub')
            self.assertEqual(source.read_bytes(), EPUB.read_bytes())
            package = Path(name) / 'book.zip'
            package.write_bytes(b'a-package')
            self.assertEqual(self.client.upload(42, package)['status'], 'imported')
        path, authorization, body, content_type = self.calls[-1]
        self.assertEqual(path, '/api/synchrobooks/42/import?reviewed=true')
        self.assertEqual(authorization, f'Bearer {KEY}')
        self.assertEqual(body, b'a-package')
        self.assertEqual(content_type, 'application/zip')
        self.assertFalse(any('/login' in call[0] for call in self.calls))

    def test_account_password_or_jwt_cannot_be_used_instead_of_scoped_key(self):
        for value in ['password', 'eyJ-account-token', KEY + '\n bad']:
            with self.assertRaisesRegex(ValueError, 'klucz API'):
                self.client.connect(value)
            self.assertEqual(self.client.token, '')
        self.assertEqual(len(self.calls), 0)

    def test_401_clears_revoked_key(self):
        self.client.connect(KEY)
        with self.assertRaisesRegex(ValueError, '401'):
            self.client.request('/expired')
        self.assertEqual(self.client.token, '')

    def test_redirect_does_not_forward_key(self):
        self.client.connect(KEY)
        with self.assertRaisesRegex(ValueError, '302'):
            self.client.request('/redirect')
        self.assertNotIn('/must-not-receive-key', [call[0] for call in self.calls])
