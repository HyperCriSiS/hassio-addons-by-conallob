"""Real Linux UID/file-permission regression for Supervisor options access."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0,
                     'requires root on Linux to test a real privilege drop')
class LaunchPermissionsTest(unittest.TestCase):
    def test_read_root_only_options_then_drop_for_both_login_modes(self):
        import pwd
        account = pwd.getpwnam('nobody')
        module_path = Path(__file__).resolve().parents[1] / 'rootfs/opt/ha-cwa'
        # Each child permanently drops privileges, leaving the test runner root.
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                root.chmod(0o755)
                source = root / 'options.json'
                source.write_text(json.dumps({'sso': {'enabled': enabled}}))
                source.chmod(0o600)
                script = '''
import json, os, sys
sys.path.insert(0, sys.argv[1])
from launch import load_options_and_drop_privileges
options = load_options_and_drop_privileges(sys.argv[2], 'nobody')
assert os.getuid() == int(sys.argv[3])
assert os.getgid() == int(sys.argv[4])
assert 0 not in os.getgroups()
try:
    open(sys.argv[2]).close()
except PermissionError:
    pass
else:
    raise AssertionError('App user can still read protected Supervisor options')
print(json.dumps(options))
'''
                result = subprocess.run(
                    [sys.executable, '-c', script, str(module_path), str(source),
                     str(account.pw_uid), str(account.pw_gid)],
                    capture_output=True, text=True, check=True)
                self.assertEqual(json.loads(result.stdout)['enabled'], enabled)
                self.assertEqual(source.stat().st_mode & 0o777, 0o600)

    def test_unprivileged_launcher_reproduces_original_permission_error(self):
        import pwd
        account = pwd.getpwnam('nobody')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o755)
            source = root / 'options.json'
            source.write_text('{}')
            source.chmod(0o600)
            result = subprocess.run(
                [sys.executable, '-c', 'import sys; open(sys.argv[1])', str(source)],
                user=account.pw_uid, group=account.pw_gid, extra_groups=[],
                capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('PermissionError', result.stderr)
