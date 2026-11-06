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


class TagInstallationTests(unittest.TestCase):
    def run_download(self, tags, reference=None, annotated=None, archive=None, version=''):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures = root / 'fixtures'
            fixtures.mkdir()
            work = root / 'download'
            work.mkdir()
            (fixtures / 'tags.json').write_text(json.dumps(tags))
            reference = reference or {'object': {'type': 'commit', 'sha': 'a' * 40}}
            (fixtures / 'ref.json').write_text(json.dumps(reference))
            (fixtures / 'tag.json').write_text(json.dumps(annotated or {}))
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
                        */git/matching-refs/tags/v) cp "$FIXTURES/tags.json" "$2" ;;
                        */git/ref/tags/*) cp "$FIXTURES/ref.json" "$2" ;;
                        */git/tags/*) cp "$FIXTURES/tag.json" "$2" ;;
                        https://codeload.github.com/*/tar.gz/*) cp "$FIXTURES/source.tar.gz" "$2" ;;
                        *) return 90 ;;
                    esac
                }
            '''
            environment = dict(os.environ, FIXTURES=str(fixtures), tmp=str(work),
                               repo='owner/project', version=version)
            script = textwrap.dedent(fetch) + '\ndownload_source() {\n' + command + '\n}\ndownload_source\n'
            result = subprocess.run(['bash', '-eu', '-c', script],
                                    env=environment, capture_output=True, text=True, timeout=10)
            calls = (fixtures / 'calls').read_text().splitlines() if (fixtures / 'calls').exists() else []
            return result, calls, (work / 'package' / 'main.py').exists()

    def test_latest_semantic_tag_downloads_pinned_commit(self):
        tags = [{'ref': f'refs/tags/{name}'} for name in ('v0.9.0', 'v0.10.0', 'v0.10.0-rc1', 'other')]
        result, calls, extracted = self.run_download(tags)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('https://api.github.com/repos/owner/project/git/ref/tags/v0.10.0', calls)
        self.assertEqual('https://codeload.github.com/owner/project/tar.gz/' + 'a' * 40, calls[-1])
        self.assertTrue(extracted)

    def test_explicit_annotated_tag_resolves_to_commit(self):
        result, calls, extracted = self.run_download(
            [], reference={'object': {'type': 'tag', 'sha': 'b' * 40}},
            annotated={'object': {'type': 'commit', 'sha': 'c' * 40}}, version='v0.1.0')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(any('matching-refs' in url for url in calls))
        self.assertIn('https://api.github.com/repos/owner/project/git/tags/' + 'b' * 40, calls)
        self.assertEqual('https://codeload.github.com/owner/project/tar.gz/' + 'c' * 40, calls[-1])
        self.assertTrue(extracted)

    def test_missing_tags_and_invalid_versions_fail_closed(self):
        for version in ('', 'main', '../v0.1.0'):
            with self.subTest(version=version):
                result, _, extracted = self.run_download([], version=version)
                self.assertNotEqual(0, result.returncode)
                self.assertFalse(extracted)

    def test_invalid_reference_and_tag_cycle_fail_closed(self):
        for reference in ({'object': {'type': 'commit', 'sha': '../invalid'}},
                          {'object': {'type': 'tree', 'sha': 'a' * 40}},
                          {'object': {'type': 'tag', 'sha': 'b' * 40}}):
            with self.subTest(reference=reference):
                result, calls, extracted = self.run_download(
                    [], reference=reference, annotated=reference, version='v0.1.0')
                self.assertNotEqual(0, result.returncode)
                self.assertFalse(any('codeload' in url for url in calls))
                self.assertFalse(extracted)

    def test_unsafe_or_incomplete_archive_is_rejected(self):
        for archive in ([('../escape', 'file')], [('repo/link', 'symlink')],
                        [('/absolute', 'file')], [('one/main.py', 'file'), ('two/install.sh', 'file')],
                        [('repo/main.py', 'file')]):
            with self.subTest(archive=archive):
                result, _, extracted = self.run_download([], version='v0.1.0', archive=archive)
                self.assertNotEqual(0, result.returncode)
                self.assertFalse(extracted)

    def test_workflow_only_tests_and_never_publishes(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/checks.yml').read_text()
        self.assertIn("tags: ['v*']", workflow)
        self.assertIn('python -m unittest discover', workflow)
        self.assertNotIn('gh release', workflow)
        self.assertNotIn('contents: write', workflow)
        self.assertNotIn('scripts/package.py', workflow)
