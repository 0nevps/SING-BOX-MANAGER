import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


class ReleaseWorkflowTests(unittest.TestCase):
    def run_publish(self, exists=True, upload_status=0):
        source = (Path(__file__).resolve().parents[1] / '.github/workflows/release.yml').read_text()
        step = source.split('      - name: Create prerelease for deployment validation\n', 1)[1]
        command = step.split('        run: ', 1)[1]
        if command.startswith('|\n'):
            command = textwrap.dedent(command[2:])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'dist').mkdir()
            for name in ('sbmanager-v0.1.0.tar.gz', 'SHA256SUMS'):
                (root / 'dist' / name).touch()
            executable = root / 'gh'
            executable.write_text(
                '#!/bin/bash\n'
                'printf "%s\\n" "$*" >> "$CALL_LOG"\n'
                'case "$1 $2" in\n'
                '  "release view") exit "$VIEW_STATUS" ;;\n'
                '  "release upload") exit "$UPLOAD_STATUS" ;;\n'
                '  "release create") exit 0 ;;\n'
                '  *) exit 99 ;;\n'
                'esac\n')
            executable.chmod(0o700)
            log = root / 'calls'
            environment = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                               CALL_LOG=str(log), VIEW_STATUS='0' if exists else '1',
                               UPLOAD_STATUS=str(upload_status), GITHUB_REF_NAME='v0.1.0')
            result = subprocess.run(['bash', '-e', '-c', command], cwd=root, env=environment,
                                    capture_output=True, text=True, timeout=10)
            return result, log.read_text().splitlines()

    def test_existing_release_replaces_only_expected_assets(self):
        result, calls = self.run_publish()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(calls[0].startswith('release view v0.1.0'))
        self.assertEqual('release upload v0.1.0 dist/sbmanager-v0.1.0.tar.gz dist/SHA256SUMS --clobber', calls[1])
        self.assertEqual(2, len(calls))

    def test_new_release_is_verified_prerelease(self):
        result, calls = self.run_publish(exists=False)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(calls[0].startswith('release view v0.1.0'))
        self.assertTrue(calls[1].startswith('release create v0.1.0 '))
        self.assertIn('--verify-tag', calls[1])
        self.assertIn('--prerelease', calls[1])
        self.assertEqual(2, len(calls))

    def test_upload_failure_is_not_hidden_by_creating_release(self):
        result, calls = self.run_publish(upload_status=7)
        self.assertEqual(7, result.returncode)
        self.assertEqual(2, len(calls))
        self.assertTrue(calls[1].startswith('release upload '))
