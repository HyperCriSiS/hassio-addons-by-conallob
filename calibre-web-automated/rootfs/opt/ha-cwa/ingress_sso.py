"""Add-on authentication boundary; no changes to upstream CWA sources/settings."""

import re

USER_ID = re.compile(r'[0-9a-f]{32}', re.ASCII)


def read_options(options):
    sso = options.get('sso', {})
    if not isinstance(sso, dict):
        raise ValueError('sso must be an object')
    result = dict(enabled=False, admin_users=[], admin_account='admin',
                  auto_create_users=False)
    result.update(sso)
    for field in ('enabled', 'auto_create_users'):
        if not isinstance(result[field], bool):
            raise ValueError(f'sso.{field} must be a boolean')
    if (not isinstance(result['admin_users'], list)
            or any(not isinstance(value, str) or not USER_ID.fullmatch(value)
                   for value in result['admin_users'])):
        raise ValueError('sso.admin_users must contain Home Assistant user IDs')
    if not isinstance(result['admin_account'], str) or not result['admin_account'].strip():
        raise ValueError('sso.admin_account must be a CWA account name')
    return result


def install(app, config, constants, ub, usermanagement, options):
    from flask import abort, g, request, session
    from sqlalchemy import Column, Integer, MetaData, String, Table, select
    from sqlalchemy.exc import IntegrityError

    # Store ID-based bindings in app.db so renames cannot transfer accounts.
    bindings = Table('ha_ingress_users', MetaData(),
                     Column('ha_id', String(32), primary_key=True),
                     Column('user_id', Integer, nullable=False, unique=True))
    bindings.create(ub.session.get_bind(), checkfirst=True)
    admin = ub.session.query(ub.User).filter_by(name=options['admin_account']).first()
    if options['admin_users'] and (admin is None or not admin.role_admin()
                                   or admin.role_anonymous()):
        raise ValueError('sso.admin_account must identify an existing CWA administrator')
    admin_id = admin.id if admin is not None else None

    def resolve_user(ha_id):
        if ha_id in options['admin_users']:
            user = ub.session.get(ub.User, admin_id)
            if user is None or not user.role_admin() or user.role_anonymous():
                abort(403)
            return user
        user_id = ub.session.execute(
            select(bindings.c.user_id).where(bindings.c.ha_id == ha_id)).scalar()
        if user_id is not None:
            user = ub.session.get(ub.User, user_id)
            # Admin rights are granted exclusively through the explicit allowlist.
            if user is None or user.role_admin() or user.role_anonymous():
                abort(403)
            return user
        if not options['auto_create_users']:
            abort(403)
        # A reserved namespace avoids linking an HA login to a local namesake.
        name = 'ha_' + ha_id
        if ub.session.query(ub.User).filter_by(name=name).first() is not None:
            abort(403)
        user = ub.User()
        user.name = name
        user.email = name + '@localhost'
        user.password = ''
        user.role = constants.ROLE_DOWNLOAD | constants.ROLE_VIEWER
        user.sidebar_view = config.config_default_show
        user.locale = config.config_default_locale
        user.default_language = config.config_default_language
        for field in ('allowed_tags', 'denied_tags', 'allowed_column_value',
                      'denied_column_value'):
            setattr(user, field, getattr(config, 'config_' + field, ''))
        user.theme = 1
        user.kobo_only_shelves_sync = 0
        try:
            ub.session.add(user)
            ub.session.flush()
            ub.session.execute(bindings.insert().values(ha_id=ha_id, user_id=user.id))
            ub.session.commit()
        except IntegrityError:
            # A parallel first request may have provisioned this ID already.
            ub.session.rollback()
            abort(409)
        return user

    def require_ingress_identity():
        # nginx admits only the Supervisor, then overwrites this marker.
        # CWA itself binds to loopback; forwarded peer addresses are not trusted.
        if request.headers.get('X-CWA-Ingress') != '1':
            abort(403)
        ha_id = request.headers.get('X-Remote-User-Id', '')
        if not USER_ID.fullmatch(ha_id):
            abort(403)
        # These protocols carry their own identities/tokens. They cannot be
        # combined with a mode in which HA is the sole authentication source.
        if (request.blueprint in ('oauth', 'remotelogin', 'kobo', 'kobo_auth', 'kosync')
                or request.path.startswith('/login/')
                or (request.path == '/login' and request.method == 'POST')):
            abort(403)
        user = resolve_user(ha_id)
        # Keep CSRF tokens and UI state; remove only local login credentials.
        for key in ('_user_id', '_id', '_random', '_remember_seconds'):
            session.pop(key, None)
        session['_remember'] = 'clear'
        session['_fresh'] = True
        g.ha_ingress_user = user
        g.flask_httpauth_user = user
        app.login_manager._update_request_context_with_user(user)

    # Route upstream's alternate authentication paths (OPDS/Basic and native
    # proxy login) to the same verified identity. No password/header aliases
    # can change it, regardless of the saved CWA authentication settings.
    usermanagement.load_user_from_reverse_proxy_header = lambda req: g.ha_ingress_user
    usermanagement.auth.verify_password(lambda username, password: g.ha_ingress_user)

    # Run before CWA's hooks and blueprint authentication on every request,
    # including static files and APIs. No cookie/password fallback is permitted.
    app.before_request_funcs.setdefault(None, []).insert(0, require_ingress_identity)
