"""Package only source/docs/examples and verified build outputs; exclude tools/data/secrets."""
import hashlib
import json
import tarfile
import shutil
import subprocess
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[1]
out=root/'artifacts'
out.mkdir(exist_ok=True)
apk=root/'android/app/build/outputs/apk/debug/app-debug.apk'
if not apk.exists(): raise RuntimeError('Build the Android APK first')
shutil.copy2(apk,out/'ProjectLedger-debug.apk')
release=root/'android/app/build/outputs/apk/release/app-release.apk'
if release.exists():
    subprocess.run([sys.executable, str(root/'scripts/verify_release.py')], check=True, capture_output=True)
    shutil.copy2(release,out/'ProjectLedger-signed.apk')
test=root/'android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk'
if test.exists(): shutil.copy2(test,out/'ProjectLedger-tests.apk')
allowed={'README.md','.env.example','.gitignore','backend','android','docs','scripts','examples'}
excluded={'.git','.tools','.vault','.secrets','.venv','.gradle','build','__pycache__','.pytest_cache','data','backups','artifacts'}
with tarfile.open(out/'ProjectLedger-source.tar.gz','w:gz') as archive:
    for path in sorted(root.rglob('*')):
        relative=path.relative_to(root)
        if relative.parts[0] not in allowed or any(part in excluded for part in relative.parts): continue
        if path.is_file() and path.name not in {'local.properties','signing.properties','keystore-password'} and not path.name.endswith(('.jks','.keystore','.p12','.pyc')):
            archive.add(path,arcname='project-ledger/'+str(relative),recursive=False)
manifest={}
for file in out.iterdir():
    if file.name!='SHA256SUMS.json' and file.is_file():
        with file.open('rb') as handle: manifest[file.name]={'bytes':file.stat().st_size,'sha256':hashlib.file_digest(handle,'sha256').hexdigest()}
(out/'SHA256SUMS.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps(manifest,indent=2))
