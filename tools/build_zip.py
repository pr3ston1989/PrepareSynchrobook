"""Package only reviewed source/assets. Never include models, projects or secrets."""
import hashlib
import zipfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from prepare_synchrobook import __version__
FILES = ['README.md', 'requirements.txt', 'Start_PrepareSynchrobook.bat', 'Zainstaluj_skrot_na_pulpicie.bat']
for folder in ['prepare_synchrobook', 'tools', 'assets', 'tests', 'docs']:
    FILES.extend(str(p.relative_to(ROOT)) for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
destination = ROOT / 'dist' / f'PrepareSynchrobook-{__version__}-Windows.zip'
destination.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in sorted(FILES):
        archive.write(ROOT / name, 'PrepareSynchrobook/' + name.replace('\\', '/'))
digest = hashlib.sha256(destination.read_bytes()).hexdigest()
destination.with_suffix('.zip.sha256').write_text(digest + '  ' + destination.name + '\n', encoding='ascii')
print(destination)
print(digest)
