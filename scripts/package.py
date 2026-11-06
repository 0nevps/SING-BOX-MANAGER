"""Build a reproducible source release without credentials or local state."""
import argparse
import gzip
import hashlib
import io
from pathlib import Path
import re
import tarfile

parser = argparse.ArgumentParser()
parser.add_argument('version')
parser.add_argument('--output', default='dist')
args = parser.parse_args()
if not re.fullmatch(r'v\d+\.\d+\.\d+', args.version):
    parser.error('version must be vMAJOR.MINOR.PATCH')
root = Path(__file__).resolve().parents[1]
output = Path(args.output)
output.mkdir(parents=True, exist_ok=True)
archive = output / f'sbmanager-{args.version}.tar.gz'
paths = [root / p for p in ('main.py', 'install.sh', 'README.md', 'AGENTS.md', 'Sing-Box Manager.md')]
paths += sorted((root / 'sbmanager').rglob('*.py'))
paths += sorted((root / 'docs').glob('*.md'))
with archive.open('wb') as raw:
    with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as bundle:
            for path in paths:
                info = bundle.gettarinfo(str(path), arcname=str(path.relative_to(root)))
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ''
                info.mode = 0o644
                bundle.addfile(info, io.BytesIO(path.read_bytes()))
(output / 'SHA256SUMS').write_text(f'{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n')
print(archive)
