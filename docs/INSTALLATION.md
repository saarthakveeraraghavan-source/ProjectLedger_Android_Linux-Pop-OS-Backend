# Installation and operations

## Verified host environment

Inspected on 12 October 2026: Pop!_OS 24.04 LTS, Python 3.12.3; NVIDIA RTX 5060 Ti 16 GB, driver 580.173.02; working local Ollama and Tailscale. About 131 GB was free at initial inspection. Java, Android SDK, Gradle, and backend libraries were initially absent. Tooling was installed only in this workspace (`.venv` and `ledger/.tools`). Sandbox-only checks initially failed to see host services; approved host checks confirmed them. Existing services, models, Docker deployments, and tailnet configuration were not changed.

Existing models include Qwen 2.5 14B, Qwen 2.5 Coder 14B, Llama 3.2 3B, Gemma 4, and larger Qwen 3.6 variants. The configured Qwen 2.5 14B model was evaluated with synthetic examples; no new model was downloaded. Other models were inventoried but not benchmarked.

## Fresh checkout

Use Python 3.12+ in a virtual environment, then install `backend/requirements.lock`. The lock includes the tested development/audit environment; application dependencies are separately specified in `backend/pyproject.toml`. `PYTHONPATH=backend python -m ledger.cli` works without installing the package. Packaging with `pip install ./backend` is also supported by its setuptools build configuration.

This deployment uses the isolated gocryptfs vault described in [VAULT.md](VAULT.md). The operator initialized it and bootstrapped the administrator privately. Its decrypted mount is `ledger/.vault/plain`; database/workbooks are under `plain/data`, backups under `plain/backups`, and release signing material under `plain/signing`. The secure launcher verifies the actual FUSE mount before creating/accessing data, so a locked vault cannot silently fall back to plaintext. Storage must remain local, outside NFS/SMB and cloud synchronization. The SQLite file itself is not separately encrypted; the mounted filesystem supplies encryption.

Bootstrap one administrator with the terminal CLI. No default password exists. Recover an account from the console with `recover-account USERNAME`; it resets the password, revokes sessions, and writes an audit entry. Provision other accounts through the authenticated API or Android Team screen. A system administrator can create projects and accounts; project access still requires explicit membership, including for system administrators.

Run `scripts/vault.sh run` in a terminal. It binds loopback port 18766, matching the existing private 8443 route; the unrelated service on 8765 is preserved. It runs one worker, with restrictive umask and no HTTP access logging. The API starts its workbook retry loop on application startup. The backend was started in a controlled terminal for this deployment; no startup service was installed. Stop it with Ctrl+C, then use `vault.sh lock`. After reboot, unlock the vault privately and run the backend again. For a service, adapt `ledger.service.example` and review encrypted-volume availability before enabling it.

## Private Android connectivity

1. Sign desktop and phone into the intended Tailscale network.
2. Inspect `tailscale serve status`; choose an unused HTTPS port so unrelated services are preserved.
3. Start the backend on loopback.
4. Enable private Serve forwarding, for example `tailscale serve --bg --https=8443 http://127.0.0.1:18766`. The operator already created this rule on this host; do not recreate unrelated forwarding rules.
5. Restrict access in the tailnet policy to approved team identities and the selected port; retain application authentication.
6. Enter the returned `https://HOST.TAILNET.ts.net:8443` address in Android.
7. Sign in online, select/create projects, and synchronize before taking the device offline.

HTTPS certificate provisioning may require the tailnet HTTPS setting and operator privileges. The implementation does not disable certificate verification or allow cleartext Android traffic. If HTTPS is not yet configured, fix the tailnet/service certificate rather than modifying Android to accept insecure connections. Never use Tailscale Funnel for this deployment.

[Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve) exposes the backend privately and can provision HTTPS. Tailscale also uses coordination infrastructure and may relay encrypted traffic. [Tailscale's security explanation](https://tailscale.com/security) describes the network metadata it receives. For infrastructure independence, evaluate self-hosted Headscale plus self-hosted DERP, or manually managed WireGuard with your own certificate infrastructure. Those alternatives are not installed or verified here.

## Android installation and release signing

Install the debug APK on a test device using Android's normal package installer, or `adb install -r APK_PATH` after enabling USB debugging. A secure PIN/password/pattern is required by the app. The UI asks for the device credential on entering the application. Screen capture is blocked for sensitive views. Android backup and device transfer rules exclude application data; recovery exports are explicit user actions.

The signed release APK is `artifacts/ProjectLedger-signed.apk`, version 0.2.0, package `com.projectledger.production`. It was installed beside the debug package `com.projectledger`, retaining its separate test data. The operator-owned RSA-3072 signing key and private properties are inside the encrypted vault, excluded from Git and delivery archives. APK Signature Scheme v2 verification passed. Protect and back up the entire vault, including signing material; losing the key prevents updates to existing installations. The separate debug APK uses Gradle's development key.

Rebuild a release with the vault unlocked using `scripts/build_release.sh`. For a fresh deployment only, generate its own key with `PYTHONPATH=backend ../.venv/bin/python scripts/prepare_release_key.py`; this refuses to overwrite existing keys. Never distribute the keystore or private properties. The signed build still requires the remaining acceptance checks in [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).

## Toolchain reproduction

`download_android_tools.py` downloads an isolated Temurin JDK, pinned SDK command-line tools, and Gradle 8.13. On this machine the JDK's official API metadata was fetched with curl because Python's request was rejected; metadata is verified before extraction. Accept only the Android SDK license needed for the selected packages; unrelated TV/XR/preview licenses are not needed. Install `platforms;android-35`, `build-tools;35.0.0`, and `platform-tools` with sdkmanager. Set `LEDGER_JAVA_HOME` and `LEDGER_ANDROID_HOME` to use an existing toolchain instead. No global Java/SDK settings are required.

The Android Gradle plugin, Kotlin/Compose plugin, and libraries are pinned to a compatible tested combination rather than dynamic versions. Gradle SHA-256 artifact metadata lives in `android/gradle/verification-metadata.xml`. Version warnings alone are not vulnerability findings; perform advisory checks before updates.
