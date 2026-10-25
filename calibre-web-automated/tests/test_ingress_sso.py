"""Focused adapter tests with Flask, real authentication and SQLite persistence.

Run: python -m unittest discover -s calibre-web-automated/tests -v
These tests do not replace a container build or live Supervisor test.
"""

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml
from flask import Blueprint, Flask, g, jsonify, session
from flask_httpauth import HTTPBasicAuth
from flask_login import LoginManager, UserMixin, current_user, login_required
from flask_wtf.csrf import CSRFProtect, generate_csrf
from sqlalchemy import Column, Integer, String, create_engine, select, text
from sqlalchemy.orm import declarative_base, sessionmaker

ADDON = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON / 'rootfs/opt/ha-cwa'))
from ingress_sso import install, read_options

# CI also runs against the actual login library from the packaged CWA commit.
# Loading it directly avoids booting CWA's unrelated conversion services.
if os.environ.get('CWA_SOURCE'):
    source = Path(os.environ['CWA_SOURCE']).resolve()
    sys.path.insert(0, str(source / 'scripts'))
    spec = importlib.util.spec_from_file_location('cwa_test_login', source / 'cps/cw_login/__init__.py')
    native_login = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = native_login
    spec.loader.exec_module(native_login)
    LoginManager = native_login.LoginManager
    UserMixin = native_login.UserMixin
    current_user = native_login.current_user
    login_required = native_login.login_required

Base = declarative_base()
ADMIN_ID = 'a' * 32
READER_ID = 'b' * 32


class User(UserMixin, Base):
    __tablename__ = 'user'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True)
    email = Column(String, unique=True)
    password = Column(String)
    role = Column(Integer)

    def role_admin(self):
        return bool(self.role & 1)

    def role_anonymous(self):
        return bool(self.role & 32)


class SSOTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(User(name='admin', role=1, email='admin@localhost'))
        self.db.commit()
        self.config = SimpleNamespace(config_default_role=511, config_default_show=1,
                                      config_default_locale='en', config_default_language='all')
        self.constants = SimpleNamespace(ROLE_DOWNLOAD=2, ROLE_VIEWER=256)
        self.options = read_options({'sso': dict(enabled=True, admin_users=[ADMIN_ID],
                                                auto_create_users=True)})

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def make_app(self):
        app = Flask(__name__)
        app.config.update(SECRET_KEY='test-only', TESTING=True)
        lm = LoginManager(app)
        lm.user_loader(lambda uid: self.db.get(User, int(uid)))
        auth = HTTPBasicAuth()
        um = SimpleNamespace(auth=auth)
        CSRFProtect(app)
        install(app, self.config, self.constants,
                SimpleNamespace(session=self.db, User=User), um, self.options)

        @app.get('/')
        @login_required
        def index():
            return jsonify(name=current_user.name, role=current_user.role,
                           proxy_user=um.load_user_from_reverse_proxy_header(None).name,
                           csrf=generate_csrf())

        @app.post('/write')
        @login_required
        def write():
            return jsonify(name=current_user.name)

        @app.get('/opds')
        @auth.login_required
        def opds():
            return jsonify(name=auth.current_user().name)

        @app.post('/login')
        def login():
            return 'must not run'

        @app.get('/login/generic/authorized')
        def oauth_callback():
            return 'must not run'

        bp = Blueprint('kosync', __name__)
        bp.route('/kosync/users/auth')(lambda: 'must not run')
        app.register_blueprint(bp)
        return app

    def headers(self, uid=READER_ID, **extra):
        return {'X-CWA-Ingress': '1', 'X-Remote-User-Id': uid, **extra}

    def test_admin_mapping_needs_no_auto_creation(self):
        self.options['auto_create_users'] = False
        response = self.make_app().test_client().get('/', headers=self.headers(ADMIN_ID))
        self.assertEqual(response.json['name'], 'admin')
        self.assertEqual(self.db.query(User).count(), 1)

    def test_normal_user_never_inherits_admin_defaults(self):
        client = self.make_app().test_client()
        response = client.get('/', headers=self.headers(**{'X-Remote-User-Name': 'admin'}))
        self.assertEqual(response.json['name'], 'ha_' + READER_ID)
        self.assertEqual(response.json['role'], 258)
        self.assertEqual(response.json['proxy_user'], 'ha_' + READER_ID)
        # Stable across rename, requests, and adapter/application restart.
        client.get('/', headers=self.headers(**{'X-Remote-User-Name': 'renamed'}))
        self.make_app().test_client().get('/', headers=self.headers())
        self.assertEqual(self.db.query(User).count(), 2)

    def test_missing_and_malformed_identity_cannot_use_admin_cookie(self):
        client = self.make_app().test_client()
        with client.session_transaction() as state:
            state['_user_id'] = '1'
        for headers in ({}, {'X-CWA-Ingress': '1'},
                        {'X-Remote-User-Id': ADMIN_ID}, self.headers('admin'),
                        self.headers(ADMIN_ID + 'x'), self.headers(ADMIN_ID.upper())):
            with self.subTest(headers=headers):
                self.assertEqual(client.get('/', headers=headers).status_code, 403)

    def test_user_switch_overrides_admin_cookie(self):
        client = self.make_app().test_client()
        client.get('/', headers=self.headers(ADMIN_ID))
        with client.session_transaction() as state:
            state['_user_id'] = '1'
        self.assertEqual(client.get('/', headers=self.headers()).json['name'], 'ha_' + READER_ID)

    def test_auto_create_disabled_denies_unknown_but_allows_bound_user(self):
        client = self.make_app().test_client()
        client.get('/', headers=self.headers())
        self.options['auto_create_users'] = False
        self.assertEqual(client.get('/', headers=self.headers()).status_code, 200)
        self.assertEqual(client.get('/', headers=self.headers('c' * 32)).status_code, 403)

    def test_no_implicit_link_to_existing_local_account(self):
        self.db.add(User(name='ha_' + READER_ID, role=1, email='existing@localhost'))
        self.db.commit()
        self.assertEqual(self.make_app().test_client().get('/', headers=self.headers()).status_code, 403)

    def test_promotion_of_regular_account_cannot_bypass_allowlist(self):
        client = self.make_app().test_client()
        client.get('/', headers=self.headers())
        user = self.db.query(User).filter_by(name='ha_' + READER_ID).one()
        user.role |= 1
        self.db.commit()
        self.assertEqual(client.get('/', headers=self.headers()).status_code, 403)

    def test_removed_admin_allowlist_entry_loses_admin(self):
        client = self.make_app().test_client()
        client.get('/', headers=self.headers(ADMIN_ID))
        self.options['admin_users'] = []
        response = self.make_app().test_client().get('/', headers=self.headers(ADMIN_ID))
        self.assertEqual(response.json['role'], 258)

    def test_automatic_ha_admin_needs_no_copied_id_or_auto_creation(self):
        self.options['admin_users'] = []
        self.options['auto_create_users'] = False
        # IDs do not have to be known in advance; ownership is reflected by
        # Supervisor including system-admin in its effective group list.
        client = self.make_app().test_client()
        for uid in (ADMIN_ID, 'c' * 32):
            headers = self.headers(uid, **{'X-Remote-User-Groups': 'system-users, system-admin'})
            response = client.get('/', headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['name'], 'admin')
        self.assertEqual(self.db.query(User).count(), 1)

    def test_automatic_regular_user_keeps_separate_reader_account(self):
        self.options['admin_users'] = []
        response = self.make_app().test_client().get('/', headers=self.headers(
            **{'X-Remote-User-Groups': 'system-users', 'X-Remote-User-Name': 'admin'}))
        self.assertEqual(response.json['name'], 'ha_' + READER_ID)
        self.assertEqual(response.json['role'], 258)

    def test_missing_malformed_or_similar_groups_never_grant_admin(self):
        self.options['admin_users'] = []
        client = self.make_app().test_client()
        for value in ('', 'admin', 'System-Admin', 'my-system-admin',
                      'system-administrator', '["system-admin"]',
                      'system-admin system-users', 'system-admin,,system-users',
                      'system-admin,invalid group', 'system-admin,'):
            with self.subTest(groups=value):
                response = client.get('/', headers=self.headers(
                    **{'X-Remote-User-Groups': value}))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json['role'], 258)

    def test_ha_role_revocation_and_promotion_apply_to_next_request(self):
        self.options['admin_users'] = []
        client = self.make_app().test_client()
        admin_headers = self.headers(ADMIN_ID, **{'X-Remote-User-Groups': 'system-admin'})
        self.assertEqual(client.get('/', headers=admin_headers).json['name'], 'admin')
        with client.session_transaction() as state:
            state['_user_id'] = '1'
        reader = client.get('/', headers=self.headers(ADMIN_ID)).json
        self.assertEqual(reader['name'], 'ha_' + ADMIN_ID)
        self.assertEqual(reader['role'], 258)
        self.assertEqual(client.get('/', headers=admin_headers).json['name'], 'admin')
        self.assertEqual(client.get('/', headers=self.headers(ADMIN_ID)).json['name'], reader['name'])

    def test_explicit_id_list_preserves_existing_selection(self):
        client = self.make_app().test_client()
        # Existing configurations keep working without group headers.
        self.assertEqual(client.get('/', headers=self.headers(ADMIN_ID)).json['name'], 'admin')
        headers = self.headers(READER_ID, **{'X-Remote-User-Groups': 'system-admin'})
        self.assertEqual(client.get('/', headers=headers).json['role'], 258)

    def test_automatic_admin_role_still_requires_trusted_identity(self):
        self.options['admin_users'] = []
        client = self.make_app().test_client()
        for headers in ({'X-Remote-User-Groups': 'system-admin'},
                        {'X-CWA-Ingress': '1', 'X-Remote-User-Groups': 'system-admin'},
                        {'X-Remote-User-Id': ADMIN_ID, 'X-Remote-User-Groups': 'system-admin'}):
            self.assertEqual(client.get('/', headers=headers).status_code, 403)

    def test_automatic_mapping_validates_admin_target_at_startup(self):
        self.options['admin_users'] = []
        self.options['admin_account'] = 'missing'
        with self.assertRaises(ValueError):
            self.make_app()

    def test_invalid_admin_target_fails_startup(self):
        for name in ('missing', 'reader'):
            if name == 'reader':
                self.db.add(User(name=name, role=258, email='reader@localhost'))
                self.db.commit()
            self.options['admin_account'] = name
            with self.assertRaises(ValueError):
                self.make_app()

    def test_basic_auth_cannot_override_ingress_user(self):
        client = self.make_app().test_client()
        headers = self.headers(Authorization='Basic YWRtaW46cGFzc3dvcmQ=')
        self.assertEqual(client.get('/opds', headers=headers).json['name'], 'ha_' + READER_ID)
        self.assertEqual(client.get('/opds', headers=self.headers()).json['name'], 'ha_' + READER_ID)
        self.assertEqual(client.get('/opds', headers={'Authorization': headers['Authorization']}).status_code, 403)

    def test_csrf_protection_and_token_survive(self):
        client = self.make_app().test_client()
        token = client.get('/', headers=self.headers()).json['csrf']
        self.assertEqual(client.post('/write', headers=self.headers()).status_code, 400)
        headers = self.headers(**{'X-CSRFToken': token})
        self.assertEqual(client.post('/write', headers=headers).status_code, 200)

    def test_alternate_authentication_routes_are_blocked(self):
        client = self.make_app().test_client()
        for path in ('/login/generic/authorized', '/kosync/users/auth'):
            self.assertEqual(client.get(path, headers=self.headers()).status_code, 403)
        self.assertEqual(client.post('/login', headers=self.headers()).status_code, 403)

    def test_config_is_unchanged_for_rollback(self):
        before = vars(self.config).copy()
        self.make_app().test_client().get('/', headers=self.headers())
        self.assertEqual(vars(self.config), before)


class OptionsTest(unittest.TestCase):
    def test_upgrade_defaults_disable_sso(self):
        self.assertFalse(read_options({})['enabled'])
        config = yaml.safe_load((ADDON / 'config.yaml').read_text())
        self.assertFalse(config['options']['sso']['enabled'])
        self.assertIsNone(config['ports']['8083/tcp'])

    def test_invalid_options_fail_closed(self):
        for value in ({'enabled': 'false'}, {'admin_users': ['admin']},
                      {'admin_users': ADMIN_ID}, {'admin_account': ''},
                      {'auto_create_users': 1}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                read_options({'sso': value})


if __name__ == '__main__':
    unittest.main()
