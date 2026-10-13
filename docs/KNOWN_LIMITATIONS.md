# Known limitations and remaining acceptance work

This is an implemented verification build. Do not label the entire supplied production-v1 specification complete until the remaining deployment/device acceptance checks are executed and defects are resolved.

- INR only. Configurable categories and independent projects are supported; multi-currency conversion is not.
- Only conservative plain XLSX layouts are supported. Advanced Excel features are rejected; no formula evaluation engine or arbitrary bidirectional merge is included.
- Full authorized record snapshots accompany incremental revisions for small-team correctness; very large project histories need pagination/snapshot optimization and scale tests.
- The operator-owned signed release is built, signature-verified, and installed beside the debug app. Signing material is protected inside the initialized encrypted vault. Remaining device/deployment acceptance gates still apply.
- The Linux encrypted vault is initialized, filesystem-tested, and used by the running backend. It requires manual unlock after reboot. Encryption does not defend against a compromised unlocked account or replace whole-host security.
- Server-restore epochs pause device synchronization safely. Device recovery currently uses explicit protected exports and reviewed reconciliation/fresh cache; there is no automated disaster-rebase wizard or recovery-file import UI.
- Android recovery JSON/CSV exports are unencrypted portable artifacts. There is no encrypted portable phone-backup restore UI. Keystore loss requires server or separately protected exported recovery data.
- Immediate offline revocation is impossible; cached sessions expire after seven days and current permissions are enforced after reconnection. A continuous session also expires in the UI.
- Local AI evaluation covers seven synthetic English cases on one installed model. The suite validates schemas and guards, but Hindi quality, diverse ambiguities, model comparisons, sustained throughput, and adversarial robustness beyond the fixtures remain unverified.
- Authentication/provisioning/reset/revocation are implemented. Audit logs are transactional but not independently tamper-proof against a filesystem administrator.
- Real spreadsheet lock behavior is advisory. Compatibility checks and interrupted-write tests do not certify physical power-loss behavior or every vendor-specific workbook format.
- Physical low-storage/device reboot/app-termination and server power-loss drills still need execution, beyond transaction/unit fault-injection tests.
- Native phone-to-private-Tailscale-to-desktop acceptance passed, including local AI, workbook publication, multi-user conflicts, exact calculations, and backup/restore. Human screen usability, two-physical-device operation, reboot/low-storage/power-loss drills, and operator disaster recovery are still release gates.
