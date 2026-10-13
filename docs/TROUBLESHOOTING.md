# Troubleshooting

**Cannot sign in:** verify backend `/health` locally, Tailscale on both devices, Serve's HTTPS address/port, certificate provisioning, and the account. Use terminal `recover-account` for authorized local recovery. Do not paste passwords into logs or chat. Eight bad login attempts from a client/username are throttled for 15 minutes.

**Saved entry not in workbook:** check Android's queued changes, last sync, and workbook status separately. Server commit does not imply Excel publication. A blocked workbook retains the expense and reports its error; close Excel/LibreOffice, restore storage space, or reconcile external edits before retrying.

**Workbook rejected:** only conservative plain XLSX is supported. Move summary formulas out of mapped transaction cells, remove unsupported advanced features in a separate reviewed copy, and confirm categories/mapping before import. Preserve the original. Macros, charts, images, pivots, external links, extensions, merged transaction cells, and embedded table totals are not round-tripped.

**AI amount/date/vendor missing:** that is a review state, not a lost transaction. Correct the proposal manually. Invalid or unsupported generated facts are removed. Pending descriptions and proposals do not count toward spending.

**Conflict cannot be resolved:** version conflicts support explicit keep-local/use-server review. Validation, unavailable identities, changed permissions, and restored epochs require administrator review; use protected recovery export rather than modifying queued UUIDs. An archived project is read only.

**Background sync delayed:** Android/WorkManager controls periodic execution and power constraints; open the app and use Sync. Ensure Automatic synchronization and queued AI processing preferences match your intent. Connectivity to the internet does not guarantee connectivity to the desktop.

**Keystore/Room cannot open:** do not clear application storage before exporting/recovering available data. Uninstalling, factory reset, or device/Keystore changes can destroy access to encrypted local keys. Reinstall only after confirming server synchronization or protected recovery exports. Hardware/device recovery is not equivalent to a server database restore.

**Android build fails in sandbox:** Gradle uses local sockets for locking and requires Maven access. Run in an approved host build context. Use the pinned JDK/Gradle/SDK combination. Missing release signing configuration is expected until the operator supplies a production key. No network interception/certificate checks should be disabled for production.

**Emulator cannot run:** hardware acceleration requires `/dev/kvm` and suitable host permissions. This host initially has no `/dev/kvm`; software emulation can be slow or unsupported for an image. A compiled test APK is not evidence of tests passing on Android. Use an attached test device if emulator execution fails.
