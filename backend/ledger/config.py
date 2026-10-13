import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


def verify_vault(path: Path):
    path = path.resolve()
    mountinfo = Path('/proc/self/mountinfo').read_text()
    for line in mountinfo.splitlines():
        left, right = line.split(' - ', 1)
        mounted = left.split()[4].replace('\\040', ' ').replace('\\134', '\\')
        if mounted == str(path) and right.split()[0] == 'fuse.gocryptfs':
            return
    raise RuntimeError('Encrypted vault is locked or not a gocryptfs mount. Unlock it before accessing financial data.')


def verify_vault_destination(destination: Path, vault_mount: Path | None):
    if vault_mount:
        if not destination.resolve().is_relative_to(vault_mount.resolve()):
            raise RuntimeError('Financial data must be inside the configured encrypted vault')
        verify_vault(vault_mount)


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.environ.get("LEDGER_DATA_DIR", "data")).resolve()
    ollama_url: str = os.environ.get("LEDGER_OLLAMA_URL", "http://127.0.0.1:11434")
    model: str = os.environ.get("LEDGER_MODEL", "qwen2.5:14b")
    vault_mount: Path | None = Path(os.environ["LEDGER_VAULT_MOUNT"]).resolve() if os.environ.get("LEDGER_VAULT_MOUNT") else None
    session_hours: int = 168
    upload_limit: int = 20 * 1024 * 1024

    def __post_init__(self):
        url = urlparse(self.ollama_url)
        if url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1", "localhost"} or url.username or url.password:
            raise ValueError("Inference must use a loopback Ollama endpoint")
        if 'cloud' in self.model.casefold():
            raise ValueError('Cloud Ollama model names are disabled for this deployment')
        self.verify_storage()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.data_dir.chmod(0o700)

    def verify_storage(self):
        verify_vault_destination(self.data_dir, self.vault_mount)

    @property
    def database(self):
        return self.data_dir / "ledger.db"
