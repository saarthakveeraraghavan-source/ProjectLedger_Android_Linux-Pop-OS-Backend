"""Generate operator-owned signing material only inside the unlocked encrypted vault."""
import os
import secrets
import subprocess
from pathlib import Path

from ledger.config import verify_vault

root=Path(__file__).resolve().parents[1]
plain=root/'.vault/plain'
verify_vault(plain)
signing=plain/'signing';signing.mkdir(mode=0o700,exist_ok=True)
keystore=signing/'project-ledger-release.p12'
properties=signing/'signing.properties'
passwordfile=signing/'keystore-password'
if any(p.exists() for p in (keystore,properties,passwordfile)):
    raise SystemExit('Signing material already exists; never overwrite it. Use the protected existing key.')
os.umask(0o077)
passwordfile.write_text(secrets.token_urlsafe(48)+'\n')
subprocess.run([str(root/'.tools/jdk/bin/keytool'),'-genkeypair','-alias','project-ledger','-keyalg','RSA','-keysize','3072','-validity','10000','-storetype','PKCS12','-keystore',str(keystore),'-storepass:file',str(passwordfile),'-dname','CN=Project Ledger, OU=Local Deployment'],check=True)
password=passwordfile.read_text().strip()
def escape(value):return value.replace('\\','\\\\').replace('\n','\\n').replace('\r','\\r').replace('=','\\=')
properties.write_text('\n'.join([f'storeFile={escape(str(keystore))}',f'storePassword={escape(password)}','keyAlias=project-ledger',f'keyPassword={escape(password)}'])+'\n')
for file in (keystore,properties,passwordfile):file.chmod(0o600)
print('Release key generated inside the encrypted vault. Back up the entire vault; no password was printed.')
