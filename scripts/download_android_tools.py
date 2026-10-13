"""Download tools only inside this repository. SDK licensing is a separate explicit step."""
import hashlib
import json
import os
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
tools = root / '.tools'
tools.mkdir(exist_ok=True)


def fetch(url, destination, expected=None):
    if not destination.exists():
        print('Downloading', destination.name, flush=True)
        urllib.request.urlretrieve(url, destination)
    if expected and hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
        raise RuntimeError('Checksum mismatch: ' + destination.name)


# Retrieve authoritative checksum for the previously downloaded JDK before extraction.
if not (tools / 'jdk-metadata.json').exists():
    subprocess.run(['curl', '-fsSL', '--retry', '2', '-o', str(tools / 'jdk-metadata.json'), 'https://api.adoptium.net/v3/assets/latest/21/hotspot?architecture=x64&image_type=jdk&os=linux'], check=True)
metadata = json.loads((tools / 'jdk-metadata.json').read_text())[0]['binary']['package']
fetch(metadata['link'], tools / 'jdk.tar.gz', metadata['checksum'])
if not (tools / 'jdk').exists():
    with tarfile.open(tools / 'jdk.tar.gz') as archive:
        base = archive.getmembers()[0].name.split('/')[0]
        archive.extractall(tools, filter='data')
        (tools / base).rename(tools / 'jdk')
# Pin known compatible SDK tools rather than a moving IDE release.
url = 'https://dl.google.com/android/repository/commandlinetools-linux-13114758_latest.zip'
fetch(url, tools / 'sdk-tools.zip')
# SDK package versions/checksums are also validated by sdkmanager for component installs.
if not (tools / 'sdk/cmdline-tools/latest').exists():
    with zipfile.ZipFile(tools / 'sdk-tools.zip') as archive:
        archive.extractall(tools / 'sdk/cmdline-tools')
    (tools / 'sdk/cmdline-tools/cmdline-tools').rename(tools / 'sdk/cmdline-tools/latest')
    for file in (tools / 'sdk/cmdline-tools/latest/bin').iterdir():
        file.chmod(0o755)
checksum = urllib.request.urlopen('https://services.gradle.org/distributions/gradle-8.13-bin.zip.sha256').read().decode().strip()
fetch('https://services.gradle.org/distributions/gradle-8.13-bin.zip', tools / 'gradle.zip', checksum)
if not (tools / 'gradle-8.13').exists():
    with zipfile.ZipFile(tools / 'gradle.zip') as archive:
        archive.extractall(tools)
    (tools / 'gradle-8.13/bin/gradle').chmod(0o755)
print('Tools downloaded. Run sdkmanager --licenses after reviewing Android SDK license terms.', flush=True)
