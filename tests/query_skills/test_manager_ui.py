"""Real HTTP boundaries and local-only management, using synthetic credentials."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import http.client
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/query_skills'))
from query_core import manager_ui as ui
from query_core.store import Store


class ManagerUITests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / '.smoke/query-core-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'personal')
        self.credentials = {'user': 'fixture_reader', 'password': 'PRIVATE-fixture-only',
                            'dsn': '(DESCRIPTION=\n(ADDRESS=(HOST=fixture.invalid)(PORT=1521)))'}
        self.store.save_profile({'id': 'production', 'engine': 'oracle', 'name': '생산 DB',
                                 'mode': 'thick', 'client_lib_dir': 'fixture-client'}, self.credentials)
        for profile_id, engine, name in [('lake', 'datalake', '다른 연결'), ('hub', 'ehub', '허브 연결')]:
            self.store.save_profile({'id': profile_id, 'engine': engine, 'name': name,
                                     'api_base': 'https://' + engine + '.invalid', 'cluster': 'reporting',
                                     'tls_ca': 'C:/fixture/company-ca.pem', 'allow_http': False,
                                     'allow_cluster_start': True, 'connect_timeout': 23, 'mode': 'thin'},
                                    {'user_id': 'private-id', 'token': 'PRIVATE-' + engine + '-only'})
        self.query = {'name': '생산 실적', 'profile': 'production', 'sql': 'SELECT amount FROM fixtures WHERE work_date = :day',
                      'parameters': {'day': {'type': 'date'}}, 'description': '<script>not executable</script>'}
        with self.store.connect() as conn:
            conn.execute('INSERT INTO queries(name,profile,body,updated) VALUES (?,?,?,?)',
                         (self.query['name'], 'production', json.dumps(self.query), 123))
            conn.execute('INSERT INTO queries(name,profile,body,updated) VALUES (?,?,?,?)',
                         ('다른 조회', 'lake', json.dumps(dict(self.query, profile='lake')), 123))
            conn.execute('INSERT INTO queries(name,profile,body,updated) VALUES (?,?,?,?)',
                         ('허브 조회', 'hub', json.dumps(dict(self.query, profile='hub')), 123))
        self.server = ui.ManagerServer(self.store)
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=2)

    def request(self, method='POST', payload=None, *, path=None, headers=None, raw=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        defaults = {'Host': self.server.origin.removeprefix('http://')}
        if method == 'POST':
            defaults.update({'Origin': self.server.origin, 'X-Query-Token': self.server.token, 'Content-Type': 'application/json'})
        if headers:
            for key, value in headers.items():
                if value is None:
                    defaults.pop(key, None)
                else:
                    defaults[key] = value
        body = raw if raw is not None else json.dumps(payload).encode() if payload is not None else None
        connection.request(method, path or self.server.prefix + ('api' if method == 'POST' else ''), body=body, headers=defaults)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def api(self, action, **values):
        code, headers, raw = self.request(payload=dict(action=action, **values))
        return code, json.loads(raw)

    def save_values(self, **overrides):
        return dict({'id': None, 'name': '새 DB', 'user': 'new_reader', 'password': 'NEW-private-only',
                     'dsn': 'fixture.invalid:1521/TEST'}, **overrides)

    def lake_values(self, **overrides):
        return dict({'id': None, 'name': '새 분석 DB', 'user_id': '12345678', 'token': 'NEW-token-fixture-only',
                     'api_base': 'https://lake.invalid/', 'cluster': '', 'tls_ca': '',
                     'allow_cluster_start': False, 'allow_http': False}, **overrides)

    @contextmanager
    def using_engine(self, engine, **options):
        original = self.server
        server = ui.ManagerServer(self.store, engine, **options)
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        worker.start()
        self.server = server
        try:
            yield server
        finally:
            self.server = original
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def test_page_is_local_uncached_and_has_no_embedded_credentials_or_catalog_content(self):
        code, headers, raw = self.request('GET')
        self.assertEqual(200, code)
        self.assertEqual('127.0.0.1', self.server.server_address[0])
        self.assertEqual('no-store', headers['Cache-Control'])
        self.assertEqual('no-referrer', headers['Referrer-Policy'])
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        page = raw.decode()
        for private in [*self.credentials.values(), self.query['sql'], self.query['description']]:
            self.assertNotIn(private, page)
        self.assertNotIn('innerHTML', page)
        self.assertNotRegex(page, r'(?:src|href)=["\']https?://')
        self.assertIn('report_reader', page)
        self.assertIn('SERVICE_NAME=PROD', page)
        self.assertIn('비워 두면 저장된 비밀번호를 유지합니다', page)
        self.assertIn('overflow:auto', page)

    def test_catalog_includes_all_oracle_profiles_and_queries_without_secrets(self):
        for i in range(80):
            self.store.save_profile({'id': f'db_{i}', 'name': f'검증 DB {i}', 'engine': 'oracle'})
        code, data = self.api('catalog')
        self.assertEqual(200, code)
        self.assertEqual(81, len(data['profiles']))
        self.assertEqual(['생산 실적'], [q['name'] for q in data['queries']])
        serialized = json.dumps(data)
        for private in self.credentials.values():
            self.assertNotIn(private, serialized)
        self.assertNotIn('password', serialized)

    def test_selected_profile_exposes_user_and_dsn_but_never_password(self):
        code, data = self.api('profile', id='production')
        self.assertEqual(200, code)
        self.assertEqual(self.credentials['user'], data['profile']['user'])
        self.assertEqual(self.credentials['dsn'], data['profile']['dsn'])
        self.assertTrue(data['profile']['passwordSaved'])
        self.assertNotIn('password', data['profile'])
        self.assertNotIn(self.credentials['password'], json.dumps(data))

    def test_query_detail_is_read_only_with_sql_and_parameter_definitions(self):
        with patch.object(self.store, 'save_query', side_effect=AssertionError('must not write a query')):
            code, data = self.api('query', id=1)
        self.assertEqual(200, code)
        self.assertEqual(self.query['sql'], data['query']['sql'])
        self.assertEqual(self.query['parameters'], data['query']['parameters'])
        self.assertEqual('생산 DB', data['sourceName'])
        self.assertFalse(data['executed'])
        self.assertEqual(0, self.server.saved_count)

    def test_save_creates_once_and_does_not_return_credentials(self):
        with patch.object(self.store, 'save_profile', wraps=self.store.save_profile) as saving:
            code, data = self.api('save', **self.save_values())
            self.assertEqual(1, saving.call_count)
        self.assertEqual(200, code)
        self.assertFalse(data['connected'])
        profile_id = data['profile']['id']
        self.assertEqual('NEW-private-only', self.store.secrets(profile_id)['password'])
        self.assertNotIn('NEW-private-only', json.dumps(data))
        self.assertEqual(1, self.server.saved_count)
        self.assertEqual(400, self.api('save', **self.save_values())[0])
        self.assertEqual(2, len(self.store.profiles('oracle')))

    def test_blank_password_on_edit_preserves_existing_secret_and_advanced_settings(self):
        code, data = self.api('save', **self.save_values(id='production', name='수정 DB', password=''))
        self.assertEqual(200, code)
        self.assertEqual(self.credentials['password'], self.store.secrets('production')['password'])
        self.assertEqual('thick', self.store.profile('production')['mode'])
        self.assertEqual('fixture-client', self.store.profile('production')['client_lib_dir'])
        self.assertEqual('new_reader', self.store.secrets('production')['user'])
        self.assertNotIn(self.credentials['password'], json.dumps(data))

    def test_required_fields_wrong_types_and_cross_engine_access_do_not_mutate(self):
        bad = [self.save_values(password=''), self.save_values(user=''), self.save_values(dsn=''),
               self.save_values(id='lake'), self.save_values(id='../escape'), self.save_values(name=['bad']),
               self.save_values(dsn='x' * 16001)]
        with patch.object(self.store, 'save_profile', wraps=self.store.save_profile) as saving:
            for fields in bad:
                with self.subTest(fields=list(fields)):
                    self.assertEqual(400, self.api('save', **fields)[0])
            self.assertFalse(saving.called)
        for action, identity in [('profile', 'lake'), ('profile', '../escape'), ('query', 2), ('query', True)]:
            self.assertEqual(400, self.api(action, id=identity)[0])

    def test_host_origin_token_and_fetch_site_are_checked(self):
        invalid = [{'Host': 'evil.example'}, {'Host': 'localhost:' + str(self.server.server_port)},
                   {'Origin': 'https://evil.example'}, {'Origin': 'null'}, {'Origin': None},
                   {'Origin': self.server.origin.replace('http:', 'https:')}, {'X-Query-Token': None},
                   {'X-Query-Token': 'wrong'}, {'Sec-Fetch-Site': 'cross-site'},
                   {'X-Forwarded-Proto': 'https'}, {'Forwarded': 'host=evil.example'}]
        for headers in invalid:
            with self.subTest(headers=list(headers)):
                self.assertEqual(403, self.request(payload={'action': 'catalog'}, headers=headers)[0])
        self.assertEqual(200, self.request(payload={'action': 'catalog'}, headers={'Sec-Fetch-Site': 'same-origin'})[0])

    def test_url_paths_absolute_schemes_and_query_strings_cannot_access_data(self):
        paths = ['/', '/wrong/', self.server.prefix + '../', self.server.prefix + '%2e%2e/',
                 self.server.prefix + '?password=PRIVATE-fixture-only', self.server.url,
                 self.server.url.replace('http:', 'https:'), '//127.0.0.1' + self.server.prefix]
        for path in paths:
            with self.subTest(path=path[:20]):
                self.assertEqual(403, self.request('GET', path=path)[0])
        self.assertEqual(403, self.request('GET', path=self.server.prefix + 'api')[0])
        self.assertEqual(501, self.request('OPTIONS')[0])

    def test_duplicate_boundary_headers_are_rejected(self):
        for header, value in [('Host', self.server.origin[7:]), ('Origin', self.server.origin), ('X-Query-Token', self.server.token)]:
            conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
            body = b'{"action":"catalog"}'
            conn.putrequest('POST', self.server.prefix + 'api', skip_host=True)
            for key, item in [('Host', self.server.origin[7:]), ('Origin', self.server.origin), ('X-Query-Token', self.server.token),
                              ('Content-Type', 'application/json'), ('Content-Length', str(len(body))), (header, value)]:
                conn.putheader(key, item)
            conn.endheaders(body)
            response = conn.getresponse()
            self.assertEqual(403, response.status)
            response.read()
            conn.close()

    def test_body_limits_content_type_and_unsupported_actions_are_rejected(self):
        self.assertEqual(413, self.request(raw=b'x' * (ui.MAX_BODY + 1))[0])
        self.assertEqual(415, self.request(payload={'action': 'catalog'}, headers={'Content-Type': 'text/plain'})[0])
        self.assertEqual(400, self.request(raw=b'not-json')[0])
        self.assertEqual(400, self.request(raw=b'[]')[0])
        self.assertEqual(400, self.request(raw=b'{}', headers={'Transfer-Encoding': 'chunked'})[0])
        for payload in [{'action': 'run', 'sql': 'SELECT 1'}, {'action': 'catalog', 'path': 'elsewhere'},
                        {'action': 'save', **self.save_values(), 'engine': 'datalake'}]:
            self.assertEqual(400, self.request(payload=payload)[0])

    def test_errors_and_accesses_do_not_log_or_echo_secret_exception_text(self):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output), patch.object(self.store, 'save_profile', side_effect=RuntimeError(self.credentials['password'])):
            code, data = self.api('save', **self.save_values())
            denied = self.request('GET', path=self.server.prefix + '?password=' + self.credentials['password'])
        self.assertEqual(400, code)
        self.assertEqual(403, denied[0])
        self.assertEqual('', output.getvalue())
        self.assertNotIn(self.credentials['password'], json.dumps(data) + denied[2].decode())

    def test_close_rejects_further_requests_and_show_stops_listening_with_short_result(self):
        self.assertEqual(200, self.api('close')[0])
        # Closing is signalled after the response body is sent. The HTTP client
        # may finish reading that body before the handler's next instruction.
        self.assertTrue(self.server.closed.wait(1))
        self.assertEqual(403, self.api('catalog')[0])
        opened = []

        def open_and_close(url, **kwargs):
            opened.append(url)
            parsed = urlsplit(url)
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
            token = parsed.path.strip('/')
            conn.request('POST', parsed.path + 'api', body=b'{"action":"close"}', headers={
                'Origin': 'http://' + parsed.netloc, 'Content-Type': 'application/json', 'X-Query-Token': token})
            response = conn.getresponse()
            self.assertEqual(200, response.status)
            response.read()
            conn.close()
            return True

        output = io.StringIO()
        with patch.object(ui.webbrowser, 'open', side_effect=open_and_close), redirect_stdout(output):
            result = ui.show(self.store, 'oracle', start_view='queries')
        self.assertEqual('closed', result['status'])
        self.assertEqual(0, result['savedCount'])
        self.assertFalse(result['connected'])
        self.assertEqual('', output.getvalue())
        self.assertNotIn(self.credentials['user'], json.dumps(result))
        address = urlsplit(opened[0])
        with socket.socket() as probe:
            self.assertNotEqual(0, probe.connect_ex((address.hostname, address.port)))

    def test_idle_expiry_and_browser_failure_stop_temporary_server(self):
        with patch.object(ui, 'IDLE_TIMEOUT', 0), patch.object(ui.webbrowser, 'open', return_value=True):
            self.assertEqual('expired', ui.show(self.store, 'oracle')['status'])
        with patch.object(ui.webbrowser, 'open', return_value=False):
            with self.assertRaisesRegex(ValueError, '기본 브라우저'):
                ui.show(self.store, 'oracle')

    def test_connection_setup_keeps_validation_failure_open_then_returns_saved_summary(self):
        def fill_connection(url, **kwargs):
            parsed = urlsplit(url)
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
            conn.request('GET', parsed.path)
            page = conn.getresponse().read().decode()
            self.assertIn('"closeOnSave": true', page)
            self.assertIn('"profileId": "production"', page)
            headers = {'Origin': 'http://' + parsed.netloc, 'Content-Type': 'application/json',
                       'X-Query-Token': parsed.path.strip('/')}
            for name, status in [(' ', 400), ('수정된 생산 DB', 200)]:
                data = {'action': 'save', **self.save_values(id='production', name=name, password='')}
                conn.request('POST', parsed.path + 'api', json.dumps(data).encode(), headers)
                response = conn.getresponse()
                self.assertEqual(status, response.status)
                self.assertNotIn(self.credentials['password'], response.read().decode())
            conn.close()
            return True

        with patch.object(ui.webbrowser, 'open', side_effect=fill_connection):
            result = ui.show(self.store, 'oracle', profile_id='production', start_view='connection')
        self.assertEqual('saved', result['status'])
        self.assertEqual('production', result['profile']['id'])
        self.assertFalse(result['connected'])
        self.assertEqual(self.credentials['password'], self.store.secrets('production')['password'])

    def test_detach_then_browser_reload_keeps_session_usable(self):
        self.assertEqual(200, self.api('detach')[0])
        self.assertIsNotNone(self.server.detached_at)
        self.assertFalse(self.server.closed.is_set())
        self.assertEqual(200, self.request('GET')[0])
        self.assertIsNone(self.server.detached_at)
        self.assertEqual(200, self.api('catalog')[0])

    def test_detached_tab_without_reload_stops_after_grace(self):
        def detach(url, **kwargs):
            parsed = urlsplit(url)
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
            conn.request('POST', parsed.path + 'api', b'{"action":"detach"}',
                         {'Origin': 'http://' + parsed.netloc, 'Content-Type': 'application/json',
                          'X-Query-Token': parsed.path.strip('/')})
            response = conn.getresponse()
            self.assertEqual(200, response.status)
            response.read()
            conn.close()
            return True

        with patch.object(ui, 'DETACH_GRACE', 0), patch.object(ui.webbrowser, 'open', side_effect=detach):
            self.assertEqual('closed', ui.show(self.store, 'oracle')['status'])

    def test_manager_rejects_other_engines_and_unknown_start_views(self):
        for engine, profile, view in [('unknown', None, 'profiles'), ('oracle', 'lake', 'profiles'), ('oracle', None, 'run')]:
            with self.assertRaises(ValueError):
                ui.ManagerServer(self.store, engine, profile, view)

    def test_lake_and_ehub_catalog_and_profile_details_are_engine_scoped_without_tokens(self):
        for engine, identity, query_id in [('datalake', 'lake', 2), ('ehub', 'hub', 3)]:
            with self.subTest(engine=engine), self.using_engine(engine):
                code, catalog = self.api('catalog')
                self.assertEqual(200, code)
                self.assertEqual([identity], [p['id'] for p in catalog['profiles']])
                self.assertEqual([query_id], [q['id'] for q in catalog['queries']])
                code, detail = self.api('profile', id=identity)
                self.assertEqual(200, code)
                self.assertTrue(detail['profile']['tokenSaved'])
                self.assertNotIn('token', detail['profile'])
                self.assertEqual('private-id', detail['profile']['user_id'])
                self.assertEqual('https://' + engine + '.invalid', detail['profile']['api_base'])
                self.assertTrue(detail['profile']['allow_cluster_start'])
                self.assertFalse(detail['profile']['allow_http'])
                self.assertNotIn('PRIVATE-' + engine + '-only', json.dumps(detail))
                self.assertFalse(self.api('query', id=query_id)[1]['executed'])
                page = self.request('GET')[2].decode()
                self.assertIn('"engine": "' + engine + '"', page)
                self.assertIn('id="token" type="password"', page)
                self.assertNotIn('PRIVATE-' + engine + '-only', page)

    def test_lake_and_ehub_new_profile_defaults_are_explicit_and_store_write_is_only_once(self):
        for engine in ('datalake', 'ehub'):
            with self.subTest(engine=engine), self.using_engine(engine):
                with patch.object(self.store, 'save_profile', wraps=self.store.save_profile) as saving:
                    code, result = self.api('save', **self.lake_values())
                    self.assertEqual(1, saving.call_count)
                self.assertEqual(200, code)
                self.assertFalse(result['connected'])
                self.assertEqual(engine, result['profile']['engine'])
                profile = self.store.profile(result['profile']['id'])
                self.assertEqual('https://lake.invalid', profile['api_base'])
                self.assertFalse(profile['allow_http'])
                self.assertFalse(profile['allow_cluster_start'])
                self.assertEqual('', profile['cluster'])
                self.assertEqual('', profile['tls_ca'])
                self.assertEqual('NEW-token-fixture-only', self.store.secrets(profile['id'])['token'])
                self.assertNotIn('NEW-token-fixture-only', json.dumps(result))

    def test_lake_and_ehub_edit_keeps_blank_token_and_unexposed_settings(self):
        for engine, identity in [('datalake', 'lake'), ('ehub', 'hub')]:
            with self.subTest(engine=engine), self.using_engine(engine):
                values = self.lake_values(id=identity, name='수정된 분석 DB', token='', cluster='daily',
                                          tls_ca='C:/fixture/changed.pem', allow_cluster_start=True)
                self.assertEqual(200, self.api('save', **values)[0])
                profile = self.store.profile(identity)
                self.assertEqual(23, profile['connect_timeout'])
                self.assertEqual('thin', profile['mode'])
                self.assertTrue(profile['allow_cluster_start'])
                self.assertEqual('daily', profile['cluster'])
                self.assertEqual('C:/fixture/changed.pem', profile['tls_ca'])
                self.assertEqual('PRIVATE-' + engine + '-only', self.store.secrets(identity)['token'])
                values['token'] = 'REPLACED-token-only'
                self.assertEqual(200, self.api('save', **values)[0])
                self.assertEqual('REPLACED-token-only', self.store.secrets(identity)['token'])

    def test_lake_and_ehub_invalid_urls_and_unconfirmed_http_never_write(self):
        addresses = ['', 'lake.invalid', 'ftp://lake.invalid', 'http://lake.invalid',
                     'https://person:PRIVATE-token@lake.invalid', 'https://@lake.invalid',
                     'https://lake.invalid?token=PRIVATE-token', 'https://lake.invalid?',
                     'https://lake.invalid#PRIVATE-token', 'https://lake.invalid#',
                     'https://lake.invalid:bad', 'https://lake.invalid:65536',
                     'https://lake.invalid\\path', 'https://lake.\ninvalid', 'https://lake.invalid/path with space']
        for engine in ('datalake', 'ehub'):
            with self.subTest(engine=engine), self.using_engine(engine):
                with patch.object(self.store, 'save_profile', wraps=self.store.save_profile) as saving:
                    for address in addresses:
                        code, result = self.api('save', **self.lake_values(api_base=address))
                        self.assertEqual(400, code, address)
                        self.assertNotIn('PRIVATE-token', json.dumps(result))
                    self.assertFalse(saving.called)

    def test_lake_and_ehub_http_opt_in_is_saved_without_rewriting_scheme_or_starting_cluster(self):
        for engine in ('datalake', 'ehub'):
            with self.subTest(engine=engine), self.using_engine(engine):
                code, result = self.api('save', **self.lake_values(api_base='http://lake.invalid/api/', allow_http=True))
                self.assertEqual(200, code)
                profile = self.store.profile(result['profile']['id'])
                self.assertEqual('http://lake.invalid/api', profile['api_base'])
                self.assertTrue(profile['allow_http'])
                self.assertFalse(profile['allow_cluster_start'])
                self.assertFalse(result['connected'])

    def test_lake_and_ehub_reject_invalid_field_types_and_cross_engine_ids(self):
        for engine, other in [('datalake', 'hub'), ('ehub', 'lake')]:
            with self.subTest(engine=engine), self.using_engine(engine):
                invalid = [self.lake_values(token=''), self.lake_values(user_id='  '), self.lake_values(user_id=[]),
                           self.lake_values(allow_http='true'), self.lake_values(allow_cluster_start=1),
                           self.lake_values(id='production'), self.lake_values(id=other),
                           {**self.lake_values(), 'password': 'not-accepted'}]
                with patch.object(self.store, 'save_profile', wraps=self.store.save_profile) as saving:
                    for values in invalid:
                        self.assertEqual(400, self.api('save', **values)[0])
                    self.assertFalse(saving.called)
                self.assertEqual(400, self.api('profile', id='production')[0])
                self.assertEqual(400, self.api('profile', id=other)[0])
                self.assertEqual(400, self.api('query', id=1)[0])
                self.assertEqual(400, self.api('query', id=3 if engine == 'datalake' else 2)[0])

    def test_lake_and_ehub_use_same_http_boundary_and_do_not_log_token_failures(self):
        for engine in ('datalake', 'ehub'):
            with self.subTest(engine=engine), self.using_engine(engine):
                for headers in [{'Origin': 'https://evil.invalid'}, {'Host': 'evil.invalid'}, {'X-Query-Token': 'wrong'}]:
                    self.assertEqual(403, self.request(payload={'action': 'catalog'}, headers=headers)[0])
                output = io.StringIO()
                with redirect_stderr(output), redirect_stdout(output), patch.object(self.store, 'save_profile', side_effect=RuntimeError('PRIVATE-token-error')):
                    code, data = self.api('save', **self.lake_values())
                self.assertEqual(400, code)
                self.assertNotIn('PRIVATE-token-error', json.dumps(data))
                self.assertEqual('', output.getvalue())

    def test_lake_and_ehub_setup_saves_and_returns_while_manage_stays_open(self):
        for engine in ('datalake', 'ehub'):
            def fill_connection(url, **kwargs):
                parsed = urlsplit(url)
                conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
                conn.request('POST', parsed.path + 'api', json.dumps({'action': 'save', **self.lake_values()}).encode(),
                             {'Origin': 'http://' + parsed.netloc, 'Content-Type': 'application/json',
                              'X-Query-Token': parsed.path.strip('/')})
                response = conn.getresponse()
                self.assertEqual(200, response.status)
                self.assertNotIn('NEW-token-fixture-only', response.read().decode())
                conn.close()
                return True

            with self.subTest(engine=engine), patch.object(ui.webbrowser, 'open', side_effect=fill_connection):
                result = ui.show(self.store, engine, start_view='connection')
                self.assertEqual('saved', result['status'])
                self.assertEqual(engine, result['profile']['engine'])
                self.assertFalse(result['connected'])
            with self.using_engine(engine):
                self.assertEqual(200, self.api('save', **self.lake_values(name='계속 관리할 DB'))[0])
                self.assertFalse(self.server.closed.is_set())
                self.assertEqual(200, self.api('catalog')[0])

    def test_setup_routes_all_live_engines_to_browser_connection_flow_without_tk(self):
        from query_core import setup_ui
        for engine in ('oracle', 'datalake', 'ehub'):
            with patch.object(ui, 'show', return_value={'ok': True, 'status': 'saved'}) as manager:
                self.assertEqual('saved', setup_ui.show(self.store, engine, 'selected')['status'])
                manager.assert_called_once_with(self.store, engine, 'selected', start_view='connection')
        with patch.object(ui, 'show') as manager:
            with self.assertRaisesRegex(ValueError, '실습에는 인증정보'):
                setup_ui.show(self.store, 'demo')
            self.assertFalse(manager.called)


if __name__ == '__main__':
    unittest.main()
