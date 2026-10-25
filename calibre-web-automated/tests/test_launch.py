import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'rootfs/opt/ha-cwa'))
import launch


class LaunchTest(unittest.TestCase):
    def run_launcher(self, enabled):
        cps = ModuleType('cps')
        module = ModuleType('cps.main')
        cps.main = module
        cps.web_server = SimpleNamespace(listen_address='0.0.0.0', listen_port=9000,
                                         ssl_args={'certfile': 'old'})
        for name in ('config', 'constants', 'ub', 'usermanagement'):
            setattr(cps, name, object())
        app = object()
        module.create_app = lambda: app
        module.main = lambda: module.create_app()
        environment = dict(LISTEN_FDS='1', LISTEN_PID='1', CALIBRE_UNIX_SOCKET='/tmp/old',
                           CWA_PORT_OVERRIDE='9000')
        options = launch.read_options({'sso': {'enabled': enabled}})
        with (patch.dict(sys.modules, {'cps': cps, 'cps.main': module}),
              patch.dict(os.environ, environment, clear=True),
              patch.object(sys, 'argv', ['launch.py']),
              patch.object(os, 'chdir'),
              patch.object(launch, 'load_options_and_drop_privileges', return_value=options) as load,
              patch.object(launch, 'install') as install):
            launch.main()
            load.assert_called_once_with()
            if enabled:
                self.assertEqual(sys.argv, ['launch.py', '-i', '127.0.0.1'])
                self.assertEqual(os.environ['CWA_PORT_OVERRIDE'], '8083')
                self.assertNotIn('LISTEN_FDS', os.environ)
                self.assertNotIn('CALIBRE_UNIX_SOCKET', os.environ)
                self.assertEqual(cps.web_server.listen_address, '127.0.0.1')
                self.assertEqual(cps.web_server.listen_port, 8083)
                self.assertIsNone(cps.web_server.ssl_args)
                install.assert_called_once()
            else:
                self.assertEqual(sys.argv, ['launch.py'])
                self.assertEqual(dict(os.environ), environment)
                self.assertEqual(cps.web_server.listen_address, '0.0.0.0')
                install.assert_not_called()

    def test_enabled_enforces_loopback(self):
        self.run_launcher(True)

    def test_disabled_preserves_normal_startup(self):
        self.run_launcher(False)

    def test_privileges_drop_before_cwa_import(self):
        # A failed privilege change must prevent all CWA application imports.
        with (patch.object(launch, 'load_options_and_drop_privileges',
                           side_effect=PermissionError('setuid failed')),
              patch.object(sys, 'path', []) as paths):
            with self.assertRaises(PermissionError):
                launch.main()
            self.assertEqual(paths, [])
