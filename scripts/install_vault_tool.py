"""Download and signature-verify the pinned encryption tool without touching system keyrings."""
import hashlib
import json
import subprocess
import tarfile
from pathlib import Path

root=Path(__file__).resolve().parents[1]
directory=root/'.tools/gocryptfs';directory.mkdir(parents=True,exist_ok=True)
keyhome=directory/'gnupg';keyhome.mkdir(mode=0o700,exist_ok=True);keyhome.chmod(0o700)
fingerprint='FFF3E01444FED7C316A3545A895F5BC123A02740'
files={
 'binary.tar.gz':'https://github.com/rfjakob/gocryptfs/releases/download/v2.6.1/gocryptfs_v2.6.1_linux-static_amd64.tar.gz',
 'binary.tar.gz.asc':'https://github.com/rfjakob/gocryptfs/releases/download/v2.6.1/gocryptfs_v2.6.1_linux-static_amd64.tar.gz.asc',
 'signing-key.pub':'https://nuetzlich.net/gocryptfs-signing-key.pub'}
for name,url in files.items():
 if not (directory/name).exists():subprocess.run(['curl','-fsSL','--retry','3','--retry-all-errors','--max-time','120','-o',str(directory/name),url],check=True)
keyinfo=subprocess.check_output(['gpg','--homedir',str(keyhome),'--no-autostart','--batch','--with-colons','--show-keys',str(directory/'signing-key.pub')],text=True)
if fingerprint not in keyinfo:raise RuntimeError('Signing key fingerprint mismatch')
keyring=directory/'trustedkeys.gpg'
if not keyring.exists():subprocess.run(['gpg','--homedir',str(keyhome),'--no-autostart','--batch','--dearmor','--output',str(keyring),str(directory/'signing-key.pub')],check=True)
verified=subprocess.run(['gpgv','--homedir',str(keyhome),'--keyring',str(keyring),'--status-fd','1',str(directory/'binary.tar.gz.asc'),str(directory/'binary.tar.gz')],capture_output=True,text=True,check=True)
if 'VALIDSIG '+fingerprint not in verified.stdout:raise RuntimeError('Release signature signer mismatch')
with tarfile.open(directory/'binary.tar.gz') as archive:archive.extractall(directory,filter='data')
(directory/'gocryptfs').chmod(0o755)
(root/'docs/vault-tool-verification.json').write_text(json.dumps({'tool':'gocryptfs','version':'2.6.1','signature':'valid','signer_fingerprint':fingerprint,'source':'https://github.com/rfjakob/gocryptfs/releases/tag/v2.6.1','sha256':hashlib.sha256((directory/'binary.tar.gz').read_bytes()).hexdigest()},indent=2))
print('Official gocryptfs signature and pinned signer verified.')
