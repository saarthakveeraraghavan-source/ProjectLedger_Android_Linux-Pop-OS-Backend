# Engineering decisions and synchronization protocol

## Decisions

SQLite WAL with FULL synchronous commits is appropriate for a small team and one backend process. BEGIN IMMEDIATE serializes mutations. Exact signed expenditure is computed in Python integers and Kotlin Long; expenses store positive paise with an explicit expense/refund direction. No financial calculation uses a binary float. Charts convert ratios to floating point only to draw bar lengths. Currency is INR in this release; mixed-currency totals are deliberately rejected rather than combined without exchange rates.

The Android repository owns an encrypted Room database for each server/account pair. SQLCipher keys are random, wrapped in an Android Keystore AES-GCM key, and kept in private encrypted preferences. Tokens are protected by the same vault. No destructive Room migration fallback is configured. Database schema v1 is exported. Manual local saves and queue insertions share a Room transaction.

Dependencies are constructed through a small application/repository composition rather than a DI framework. OkHttp and Kotlin serialization are used for networking and explicit integer JSON. HTTPS uses HTTP/1.1; repeated HTTP/2 stream stalls were observed during the actual phone/Tailscale test, so protocol compatibility is being verified with the simpler backend-matching transport. TLS/certificate verification remains enabled. This keeps the application small while preserving repository/lifecycle separation. Background sync uses WorkManager with a network constraint and a 15-minute periodic schedule; the user can turn it off and use the Sync button. It is not a promise of immediate background execution, since Android power policies control scheduling.

Inference is an interchangeable structured provider protocol. This deployment accepts only HTTP Ollama URLs on loopback. JSON schemas and semantic guards validate proposals. Inference has no database/file/shell capability. The configured IANA expense time zone is saved with each pending description, preserving relative-date context after a preference change. Questions become bounded filter plans; all numbers come from deterministic records, with source IDs. Cross-project answers use only memberships held by the authenticated user.

## Records and permissions

Project membership grants administrator/editor/viewer access. System administration alone does not grant financial access to every project. Editors may edit transactions within an authorized project, with original ownership retained and the acting editor logged. Administrators configure membership, category suggestions, optional budgets, and workbooks. Editors can create a category with a reviewed expense; it is added and audited only on commit. AI proposals do not change categories. Archiving makes a project read only. Historical categories remain usable when editing records.

Expenses distinguish expense_date (ISO local date), created_at and updated_at (UTC ISO timestamps), server version, owner, and sync time. Refunds reduce expenditure. Voids require a reason, retain the original record, carry zero financial impact, and create a versioned audit event. The UI calls this reversal; it is a void, not a silently deleted row. Drafts can be deleted before confirmation and never count toward totals.

## Durable synchronization

1. Android creates an immutable operation UUID and stores its exact payload in Room alongside the local record.
2. Edits made before reconnection remain separate ordered operations; base versions account for preceding local operations.
3. Sync fetches current permissions and the server epoch before transmitting changes. A restored epoch pauses all writes.
4. Project operations are committed/retried with stable operation IDs before related expenses.
5. Server authentication, project authorization, schema checks, base-version checks, duplicate warnings, data mutation, revision event, audit event, workbook job, and idempotency response are enforced transactionally.
6. Android deletes a queued operation only after receiving a committed response with a record/version/revision. Financial requests have bounded network deadlines; inference requests have a longer deadline. A timeout keeps the original UUID and payload, making an uncertain acknowledgment safe to retry.
7. Pull returns revisioned changes, project roles, workbook status, and authorized snapshots. Snapshots also supply historical records when membership is granted after the device's cursor has advanced. The small-team implementation currently includes full authorized snapshots on each pull; it is not optimized for very large datasets.
8. Queued/conflicting local payloads are never overwritten by a pull. Unchanged synchronized records are refreshed. Removed-project data is hidden and pending operations retained for an explicit protected recovery export.

Per-process sync mutex serialization prevents foreground and background sync from applying stale acknowledgments to the same local account. SQLite/Room transactions protect state updates; server idempotency protects network retries.

## Conflicts and duplicates

An outdated base version returns HTTP 409 with the current authorized record. The client retains the local payload and every queued intent. Review allows choosing the server version or submitting the local version against the reviewed server version. Every discarded queue is archived in the encrypted metadata table before an explicit choice. A second concurrent edit can conflict again; there is no last-write-wins policy.

Possible duplicates compare amount/date/vendor/description/direction within a project. They are warnings rather than automatic deduplication of legitimate separate payments. The user must explicitly confirm a separate expense to override the warning; the override is audited. Exact repeated operation IDs return the prior commit instead of creating another expense. Reusing an ID for a different payload is rejected.

Project configuration changes also have base versions, durable operation IDs, and explicit conflict review. Project creation works locally for a cached system administrator and is queued before expense writes. New accounts and membership changes require the server; an offline device cannot grant authoritative permissions.

## State meanings

| State | Counted in local totals | Server change | Workbook change |
|---|---:|---|---|
| Draft | No | None | None |
| Pending AI | No | Interpretation only after sync | None |
| Awaiting confirmation | No | Stored proposal only | None |
| Confirmed local | Yes | Durable queue | None until server commit |
| Synchronized | Yes | Committed version/revision | Independently queued/synced/blocked |
| Conflict | Local reviewed intent remains visible | Preserved server version | Only committed server data |
| Voided | No | Audited version update when synced | Zero amount with retained identity/status |

Every local dashboard marks team totals provisional and shows the last successful sync. A local confirmed expense is durable without being a verified current team-wide fact.
