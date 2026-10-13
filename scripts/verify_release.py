"""Verify the actual release APK without reading private signing material."""
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
apk = root/'android/app/build/outputs/apk/release/app-release.apk'
buildtools = root/'.tools/sdk/build-tools/35.0.0'
environment = dict(os.environ, PATH=str(root/'.tools/jdk/bin')+os.pathsep+os.environ['PATH'])
signature = subprocess.run([str(buildtools/'apksigner'), 'verify', '--verbose', '--print-certs', str(apk)],
                           env=environment, check=True, capture_output=True, text=True).stdout
badging = subprocess.run([str(buildtools/'aapt'), 'dump', 'badging', str(apk)],
                        check=True, capture_output=True, text=True).stdout
manifest = subprocess.run([str(buildtools/'aapt'), 'dump', 'xmltree', str(apk), 'AndroidManifest.xml'],
                         check=True, capture_output=True, text=True).stdout
assert "name='com.projectledger.production'" in badging
assert 'application-debuggable' not in badging
assert 'VerificationActivity' not in manifest
assert 'Verified using v2 scheme (APK Signature Scheme v2): true' in signature
assert 'CN=Project Ledger, OU=Local Deployment' in signature
certificate = re.search(r'certificate SHA-256 digest: ([0-9a-f]+)', signature).group(1)
version = re.search(r"versionName='([^']+)'", badging).group(1)
version_code = int(re.search(r"versionCode='(\d+)'", badging).group(1))
with apk.open('rb') as handle:
    digest = hashlib.file_digest(handle, 'sha256').hexdigest()
report = {
    'verified_at': datetime.now(timezone.utc).isoformat(),
    'package': 'com.projectledger.production', 'version': version, 'version_code': version_code,
    'sha256': digest, 'bytes': apk.stat().st_size,
    'signature_scheme_v2': 'passed', 'signer_certificate_sha256': certificate,
    'debuggable': False, 'test_activity_in_release': False,
    'private_signing_material': 'excluded; protected in operator encrypted vault',
}
report_path = root/'docs/release-verification.json'
if report_path.exists():
    previous = json.loads(report_path.read_text())
    if {k: v for k, v in previous.items() if k != 'verified_at'} == {k: v for k, v in report.items() if k != 'verified_at'}:
        report['verified_at'] = previous['verified_at']
report_path.write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
