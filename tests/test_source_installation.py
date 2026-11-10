import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import textwrap
import unittest


SOURCE = (Path(__file__).resolve().parents[1] / 'install.sh').read_text()


class SourceInstallationTests(unittest.TestCase):
    def run_download(self, reference=None, archive=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures = root / 'fixtures'
            fixtures.mkdir()
            work = root / 'download'
            work.mkdir()
            reference = reference if reference is not None else {'object': {'type': 'commit', 'sha': 'a' * 40}}
            (fixtures / 'ref.json').write_text(json.dumps(reference))
            with tarfile.open(fixtures / 'source.tar.gz', 'w:gz') as bundle:
                for name, kind in archive or [('repo-commit/main.py', 'file'),
                                              ('repo-commit/install.sh', 'file'),
                                              ('repo-commit/sbmanager/app.py', 'file')]:
                    member = tarfile.TarInfo(name)
                    if kind == 'symlink':
                        member.type = tarfile.SYMTYPE
                        member.linkname = '/etc/passwd'
                        bundle.addfile(member)
                    else:
                        content = b'# source\n'
                        member.size = len(content)
                        bundle.addfile(member, io.BytesIO(content))
            command = SOURCE.split('download_source() {\n', 1)[1].split('\n}\n', 1)[0]
            fetch = '''
                fetch() {
                    printf '%s\\n' "$1" >> "$FIXTURES/calls"
                    case "$1" in
                        */git/ref/heads/main) cp "$FIXTURES/ref.json" "$2" ;;
                        https://codeload.github.com/*/tar.gz/*) cp "$FIXTURES/source.tar.gz" "$2" ;;
                        *) return 90 ;;
                    esac
                }
            '''
            environment = dict(os.environ, FIXTURES=str(fixtures), tmp=str(work), repo='owner/project')
            script = textwrap.dedent(fetch) + '\ndownload_source() {\n' + command + '\n}\ndownload_source\n'
            result = subprocess.run(['bash', '-eu', '-c', script],
                                    env=environment, capture_output=True, text=True, timeout=10)
            calls = (fixtures / 'calls').read_text().splitlines() if (fixtures / 'calls').exists() else []
            return result, calls, (work / 'package' / 'main.py').exists()

    def test_installer_accepts_supported_system_versions_including_debian11(self):
        guard = SOURCE.split('case "$ID:$VERSION_ID" in ', 1)[1].split('\n', 1)[0]
        script = 'case "$ID:$VERSION_ID" in ' + guard
        for system, version in (('debian', '11'), ('debian', '12'), ('debian', '13'),
                                ('ubuntu', '22.04'), ('ubuntu', '24.04')):
            with self.subTest(system=system, version=version):
                result = subprocess.run(
                    ['bash', '-eu', '-c', script],
                    env=dict(os.environ, ID=system, VERSION_ID=version),
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_installer_still_rejects_unsupported_system_versions(self):
        guard = SOURCE.split('case "$ID:$VERSION_ID" in ', 1)[1].split('\n', 1)[0]
        script = 'case "$ID:$VERSION_ID" in ' + guard
        for system, version in (('debian', '10'), ('ubuntu', '20.04'), ('alpine', '3.20')):
            with self.subTest(system=system, version=version):
                result = subprocess.run(
                    ['bash', '-eu', '-c', script],
                    env=dict(os.environ, ID=system, VERSION_ID=version),
                    capture_output=True, text=True, timeout=10)
                self.assertNotEqual(0, result.returncode)
                self.assertIn('Debian 11/12/13', result.stderr)

    def test_main_downloads_complete_source_from_pinned_commit(self):
        result, calls, extracted = self.run_download()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(['https://api.github.com/repos/owner/project/git/ref/heads/main',
                          'https://codeload.github.com/owner/project/tar.gz/' + 'a' * 40], calls)
        self.assertTrue(extracted)

    def test_main_update_resolves_new_commit(self):
        for commit in ('a' * 40, 'b' * 40):
            with self.subTest(commit=commit):
                result, calls, extracted = self.run_download({'object': {'type': 'commit', 'sha': commit}})
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual('https://codeload.github.com/owner/project/tar.gz/' + commit, calls[-1])
                self.assertTrue(extracted)

    def test_invalid_main_reference_fails_closed(self):
        for reference in ({'object': {'type': 'commit', 'sha': '../invalid'}},
                          {'object': {'type': 'tree', 'sha': 'a' * 40}},
                          {'object': {'type': 'tag', 'sha': 'b' * 40}}, {}):
            with self.subTest(reference=reference):
                result, calls, extracted = self.run_download(reference)
                self.assertNotEqual(0, result.returncode)
                self.assertFalse(any('codeload' in url for url in calls))
                self.assertFalse(extracted)

    def test_unsafe_or_incomplete_archive_is_rejected(self):
        for archive in ([('../escape', 'file')], [('repo/link', 'symlink')],
                        [('/absolute', 'file')], [('one/main.py', 'file'), ('two/install.sh', 'file')],
                        [('repo/main.py', 'file')]):
            with self.subTest(archive=archive):
                result, _, extracted = self.run_download(archive=archive)
                self.assertNotEqual(0, result.returncode)
                self.assertFalse(extracted)

    def test_repository_is_only_installer_argument(self):
        prefix = SOURCE.split('[[ $(uname -s)', 1)[0]
        result = subprocess.run(['bash', '-c', prefix, 'install.sh', 'owner/project', 'v0.1.0'],
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(0, result.returncode)
        self.assertIn('用法', result.stderr)

    def test_repeat_update_creates_fresh_source_directory(self):
        self.assertNotIn('/opt/sbmanager/releases', SOURCE)
        self.assertNotIn('无需重复安装', SOURCE)
        self.assertIn('mktemp -d "/opt/sbmanager/builds/', SOURCE)
        self.assertIn('cp -R "$tmp/package/." "$install_dir/"', SOURCE)
        self.assertIn('ln -s "$install_dir" /opt/sbmanager/current.new', SOURCE)

    def test_source_switch_preserves_previous_build_and_business_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program = root / 'opt' / 'sbmanager'
            (program / 'builds').mkdir(parents=True)
            work = root / 'download'
            (work / 'package').mkdir(parents=True)
            (work / 'sing-box').write_text('#!/bin/sh\nexit 0\n')
            state = root / 'state.json'
            state.write_text('{"users": {"alice": {}}}')
            command = SOURCE.split('install_dir=$(mktemp -d ', 1)[1].split("\ncat > /usr/local/bin/sbmanager", 1)[0]
            command = 'install_dir=$(mktemp -d ' + command
            command = command.replace('/opt/sbmanager', str(program))
            # Emulate GNU mv's atomic replacement on macOS as well as Linux.
            move = '''
                mv() {
                    python3 -I -c 'import os,sys; os.replace(sys.argv[1], sys.argv[2])' "$2" "$3"
                }
            '''
            directories = []
            for commit in ('a' * 40, 'b' * 40, 'b' * 40):
                (work / 'package' / 'main.py').write_text(commit)
                result = subprocess.run(['bash', '-eu', '-c', textwrap.dedent(move) + '\n' + command],
                                        env=dict(os.environ, tmp=str(work), commit=commit, repo='owner/project'),
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(0, result.returncode, result.stderr)
                current = (program / 'current').resolve()
                self.assertEqual(commit, (current / 'main.py').read_text())
                self.assertEqual(commit + '\n', (current / '.source-commit').read_text())
                self.assertEqual('owner/project\n', (current / '.source-repository').read_text())
                self.assertTrue((current / 'sing-box').stat().st_mode & 0o100)
                directories.append(current)
            self.assertEqual(3, len(set(directories)))
            self.assertEqual('a' * 40, (directories[0] / 'main.py').read_text())
            self.assertEqual('{"users": {"alice": {}}}', state.read_text())

    def test_workflow_only_tests_main_without_tags_or_publishing(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/checks.yml').read_text()
        self.assertIn('branches: [main]', workflow)
        self.assertNotIn('tags:', workflow)
        self.assertIn('python -m unittest discover', workflow)
        self.assertNotIn('gh release', workflow)
        self.assertNotIn('contents: write', workflow)
