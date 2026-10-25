"""Run the pinned CWA release with optional Home Assistant ingress SSO."""

import json
import os
import sys

from ingress_sso import install, read_options


def main():
    with open('/data/options.json', encoding='utf-8') as handle:
        options = read_options(json.load(handle))
    sys.path.insert(0, '/app/calibre-web-automated')
    # Match cps.py's import/working-directory behavior.
    os.chdir('/app/calibre-web-automated')
    if options['enabled']:
        # CLI binding overrides CWA defaults. Never expose the trusted backend.
        sys.argv = [sys.argv[0], '-i', '127.0.0.1']
        os.environ['CWA_PORT_OVERRIDE'] = '8083'
        # Disable systemd socket activation, which otherwise bypasses -i.
        os.environ.pop('LISTEN_FDS', None)
        os.environ.pop('LISTEN_PID', None)
        os.environ.pop('CALIBRE_UNIX_SOCKET', None)
    import cps.main
    if options['enabled']:
        create_app = cps.main.create_app

        def create_ingress_app():
            app = create_app()
            from cps import config, constants, ub, usermanagement, web_server
            install(app, config, constants, ub, usermanagement, options)
            # The ingress proxy talks HTTP on this fixed loopback port.
            web_server.listen_address = '127.0.0.1'
            web_server.listen_port = 8083
            web_server.ssl_args = None
            return app

        cps.main.create_app = create_ingress_app
    cps.main.main()


if __name__ == '__main__':
    main()
