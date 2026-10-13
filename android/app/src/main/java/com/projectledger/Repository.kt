package com.projectledger

import android.app.Application
import android.content.Context
import androidx.room.withTransaction
import androidx.work.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.encodeToString
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.time.Instant
import java.util.concurrent.TimeUnit

class ApiError(val status: Int, val body: String) : Exception(when(status) {
    401 -> "Session expired or account revoked. Log in again; local changes are retained."
    403 -> "Your project permission changed. Local changes are retained for recovery."
    409 -> "This record needs review before synchronization."
    503 -> "Local AI is unavailable. Your text remains safely queued."
    422 -> "Please check your input. ${validationMessage(body)}"
    else -> "Server request failed ($status). ${validationMessage(body)}"
})
fun validationMessage(body: String): String = runCatching {
    when (val detail = json.parseToJsonElement(body).jsonObject["detail"]) {
        is JsonPrimitive -> detail.content.take(250)
        is JsonArray -> detail.take(3).joinToString("; ") { item ->
            val data = item.jsonObject
            val field = data["loc"]?.jsonArray?.drop(1)?.joinToString(".") { it.jsonPrimitive.content }.orEmpty()
            "$field: ${data["msg"]?.jsonPrimitive?.content ?: "Invalid value"}"
        }
        else -> "Try again; saved records are retained."
    }
}.getOrDefault("Try again; saved records are retained.")
class Api(val base: String, val token: String) {
    private val client = OkHttpClient.Builder().protocols(listOf(okhttp3.Protocol.HTTP_1_1)).connectTimeout(10, TimeUnit.SECONDS).readTimeout(25, TimeUnit.SECONDS).callTimeout(35, TimeUnit.SECONDS).build()
    init {
        val url = java.net.URI(base)
        require(url.scheme == "https" && url.host != null && url.userInfo == null && url.query == null && url.fragment == null) { "Use your private Tailscale HTTPS address" }
    }
    fun request(path: String, method: String = "GET", value: String? = null): String {
        val builder = Request.Builder().url(base.trimEnd('/') + path)
        if (token.isNotBlank()) builder.header("Authorization", "Bearer $token")
        if (method != "GET") builder.method(method, (value ?: "{}").toRequestBody("application/json".toMediaType()))
        val transport = if (path.contains("/ai/")) client.newBuilder().readTimeout(150, TimeUnit.SECONDS).callTimeout(180, TimeUnit.SECONDS).build() else client
        transport.newCall(builder.build()).execute().use { response ->
            val body = response.body?.string() ?: ""
            if (!response.isSuccessful) throw ApiError(response.code, body)
            return body
        }
    }
    fun upload(bytes: ByteArray): String {
        val body = okhttp3.MultipartBody.Builder().setType(okhttp3.MultipartBody.FORM)
            .addFormDataPart("file", "import.xlsx", bytes.toRequestBody("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet".toMediaType())).build()
        val request = Request.Builder().url(base.trimEnd('/') + "/workbooks/inspect").header("Authorization", "Bearer $token").post(body).build()
        client.newCall(request).execute().use { r ->
            val text = r.body?.string() ?: ""
            if (!r.isSuccessful) throw ApiError(r.code, text)
            return text
        }
    }
}

class Repository(val db: LedgerDatabase, val vault: Vault, val session: Session, val base: String) {
    companion object { private val syncMutex = Mutex() }
    val dao = db.dao()
    val api = Api(base, session.token)
    val syncRequests = kotlinx.coroutines.flow.MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    private fun requireSession() { require(Instant.now().isBefore(Instant.parse(session.expires_at))) { "Offline session expired. Reconnect and log in; records are retained." } }
    private suspend fun requireWrite(projectId: String) {
        requireSession()
        val project = dao.project(projectId)?.let { json.decodeFromString<ProjectData>(it.payload) } ?: error("Project unavailable")
        require(project.role != "viewer" && !project.archived) { "This project is read only" }
    }
    suspend fun saveExpense(expense: Expense, draft: Boolean, aiId: String? = null) {
        requireWrite(expense.project_id)
        require(expense.amount_minor in 1..MAX_MONEY && expense.description.isNotBlank() && expense.category.isNotBlank())
        java.time.LocalDate.parse(expense.expense_date)
        db.withTransaction {
            val old = dao.expense(expense.id)
            val queue = dao.queued(expense.id)
            require(queue.none { it.conflict != null }) { "Resolve the conflict before editing" }
            val timestamp = Instant.now().toString()
            if (draft) {
                require(old == null || old.state == "draft") { "Confirmed expenses cannot become drafts" }
                dao.save(LocalExpense(expense.id, expense.project_id, json.encodeToString(expense), state = "draft",
                    owner = session.user_id, createdAt = old?.createdAt ?: timestamp, updatedAt = timestamp))
            } else {
                val action = if ((old?.serverVersion ?: 0) == 0 && queue.isEmpty()) "create" else "update"
                val baseVersion = (old?.serverVersion ?: 0) + queue.size
                val mutation = Mutation(action = action, expense = expense, base_version = baseVersion)
                dao.enqueue(Outbox(mutation.operation_id, expense.id, json.encodeToString(mutation), nextQueueTime(queue)))
                dao.save(LocalExpense(expense.id, expense.project_id, json.encodeToString(expense), old?.serverVersion ?: 0,
                    state = "local", owner = old?.owner ?: session.user_id, createdAt = old?.createdAt ?: timestamp, updatedAt = timestamp))
                val project = json.decodeFromString<ProjectData>(dao.project(expense.project_id)!!.payload)
                if (expense.category !in project.categories) {
                    dao.saveProject(LocalProject(project.id, json.encodeToString(project.copy(categories = project.categories + expense.category))))
                }
                if (aiId != null) {
                    val ai = dao.ai(aiId) ?: error("AI entry missing")
                    val confirmed = ai.confirmed.split(',').filter { it.isNotBlank() }.toSet() + (expense.source_proposal_id ?: error("Proposal identity missing"))
                    val interpretation = json.decodeFromString<Interpretation>(ai.result!!)
                    dao.saveAI(ai.copy(confirmed = confirmed.joinToString(","), state = if (interpretation.proposals.all { it.id in confirmed }) "confirmed" else "review"))
                }
            }
        }
        if (!draft) requestAutomaticSync()
    }
    private fun nextQueueTime(queue: List<Outbox>) = maxOf(System.currentTimeMillis(), (queue.maxOfOrNull { it.created } ?: 0) + 1)
    suspend fun voidExpense(id: String, reason: String) {
        require(reason.isNotBlank()) { "Enter a reason for the reversal" }
        db.withTransaction {
            val old = dao.expense(id) ?: error("Record unavailable")
            requireWrite(old.project)
            require(old.state != "draft" && !old.voided) { "This record cannot be reversed" }
            val queue = dao.queued(id)
            require(queue.none { it.conflict != null }) { "Resolve the conflict first" }
            val mutation = Mutation(action = "void", expense = json.decodeFromString(old.payload), base_version = old.serverVersion + queue.size, reason = reason)
            dao.enqueue(Outbox(mutation.operation_id, id, json.encodeToString(mutation), nextQueueTime(queue)))
            dao.save(old.copy(voided = true, state = "local"))
        }
        requestAutomaticSync()
    }
    suspend fun queueAI(project: String, text: String) {
        requireWrite(project)
        require(text.isNotBlank() && text.length <= 4000)
        val zone = dao.meta("timezone") ?: "Asia/Kolkata"
        val id = newId()
        db.withTransaction {
            dao.saveAI(PendingAI(id, project, text, java.time.LocalDate.now(java.time.ZoneId.of(zone)).toString()))
            dao.saveMeta(Meta("ai-timezone-$id", zone))
        }
        requestAutomaticSync()
    }
    suspend fun saveProject(project: ProjectData) {
        requireSession()
        val old = dao.project(project.id)?.let { json.decodeFromString<ProjectData>(it.payload) }
        require(if (old == null) session.administrator else old.role == "administrator") { "Administrator permission required" }
        val operation = buildJsonObject {
            put("operation_id", newId()); put("id", project.id); put("name", project.name); put("budget_minor", project.budget_minor)
            put("categories", json.encodeToJsonElement(project.categories)); put("archived", project.archived)
            put("base_version", old?.version ?: 0)
        }
        db.withTransaction {
            dao.saveMeta(Meta("project-change-${System.currentTimeMillis()}-${newId()}", operation.toString()))
            dao.saveProject(LocalProject(project.id, json.encodeToString(project.copy(version = (old?.version ?: 0) + 1))))
        }
        requestAutomaticSync()
    }
    private fun requestAutomaticSync() {
        if (vault.get("auto_sync") == "false") return
        syncRequests.tryEmit(Unit)
        WorkManager.getInstance(vault.appContext)
            .enqueueUniqueWork("ledger-sync-now", ExistingWorkPolicy.APPEND_OR_REPLACE,
                OneTimeWorkRequestBuilder<SyncWorker>()
                    .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                    .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.SECONDS).build())
    }
    suspend fun sync() = syncMutex.withLock { withContext(Dispatchers.IO) {
        requireSession()
        try {
            // Always fetch current authorization/epoch BEFORE sending queued financial writes.
            val initial = json.decodeFromString<Pull>(api.request("/sync/pull?cursor=0"))
            val knownEpoch = dao.meta("epoch")
            if (knownEpoch != null && knownEpoch != initial.epoch) {
                dao.saveMeta(Meta("restore_epoch", initial.epoch))
                error("The server was restored. Synchronization is paused; export local records and reconcile them with the administrator.")
            }
            for (change in dao.projectChanges()) {
                val payload = json.parseToJsonElement(change.value).jsonObject
                val projectId = payload["id"]!!.jsonPrimitive.content
                try {
                    api.request("/projects/$projectId", "PUT", change.value)
                    dao.removeMeta(change.key)
                } catch (e: ApiError) {
                    dao.saveMeta(Meta("project_conflict", e.body))
                    throw e
                }
            }
            val authorized = json.decodeFromString<Pull>(api.request("/sync/pull?cursor=0"))
            val allowed = authorized.projects.associateBy { it.id }
            db.withTransaction {
                val pendingIds = dao.projectChanges().map { json.parseToJsonElement(it.value).jsonObject["id"]!!.jsonPrimitive.content }.toSet()
                authorized.projects.filter { it.id !in pendingIds }.forEach { dao.saveProject(LocalProject(it.id, json.encodeToString(it))) }
                val retained = (allowed.keys + pendingIds).toList()
                dao.removeUnauthorizedProjects(retained)
                dao.hideUnauthorized(retained)
            }
            val blockedRecords = mutableSetOf<String>()
            for (operation in dao.queue()) {
                if (operation.expenseId in blockedRecords || operation.conflict != null) continue
                val mutation = json.decodeFromString<Mutation>(operation.payload)
                if (allowed[mutation.expense.project_id]?.role !in listOf("editor", "administrator")) continue
                try {
                    val ack = json.decodeFromString<Acknowledgment>(api.request("/sync/mutate", "POST", operation.payload))
                    db.withTransaction {
                        dao.acknowledge(operation.id)
                        val local = dao.expense(operation.expenseId)
                        if (dao.queued(operation.expenseId).isEmpty()) saveServer(ack.record)
                        else if (local != null) dao.save(local.copy(serverVersion = ack.record.version, owner = ack.record.owner_id))
                    }
                } catch (e: ApiError) {
                    if (e.status == 409 || e.status == 422 || e.status == 403) {
                        dao.enqueue(operation.copy(conflict = e.body))
                        dao.expense(operation.expenseId)?.let { dao.save(it.copy(state = "conflict")) }
                        blockedRecords.add(operation.expenseId)
                    } else throw e
                }
            }
            if (dao.meta("auto_ai") != "false") {
                for (pending in dao.pending()) {
                    if (allowed[pending.project]?.role !in listOf("editor", "administrator")) continue
                    try {
                        val request = AIRequest(pending.id, pending.text, pending.referenceDate, dao.meta("ai-timezone-${pending.id}") ?: "Asia/Kolkata")
                        val result = api.request("/projects/${pending.project}/ai/interpret", "POST", json.encodeToString(request))
                        json.decodeFromString<Interpretation>(result)
                        dao.saveAI(pending.copy(state = "review", result = result, error = null))
                    } catch (e: Exception) {
                        dao.saveAI(pending.copy(error = e.message ?: "Interpretation failed. Original text retained."))
                    }
                }
            }
            val cursor = dao.meta("cursor")?.toLongOrNull() ?: 0
            val pull = json.decodeFromString<Pull>(api.request("/sync/pull?cursor=$cursor&epoch=${initial.epoch}"))
            db.withTransaction {
                pull.snapshot.forEach { server ->
                    if (dao.queued(server.id).isEmpty()) saveServer(server)
                }
                dao.saveMeta(Meta("epoch", pull.epoch)); dao.saveMeta(Meta("cursor", pull.cursor.toString()))
                dao.saveMeta(Meta("last_sync", pull.synced_at))
                dao.saveMeta(Meta("workbooks", json.encodeToString(pull.workbooks)))
                dao.saveMeta(Meta("sync_error", ""))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            dao.saveMeta(Meta("sync_error", e.message ?: "Connection failed. Saved changes will retry."))
            throw e
        }
    }
    }
    private suspend fun saveServer(server: ServerExpense) {
        dao.save(LocalExpense(server.id, server.project_id, json.encodeToString(server.expense()), server.version, "synced",
            server.voided, server.owner_id, server.created_at, server.updated_at))
    }
    suspend fun resolveProjectConflict(projectId: String, keepLocal: Boolean) {
        requireSession()
        val raw = dao.meta("project_conflict") ?: error("No project conflict")
        val detail = json.parseToJsonElement(raw).jsonObject["detail"]?.jsonObject ?: error("Administrator review required")
        require(detail["code"]?.jsonPrimitive?.content == "project_version_conflict") { "This error requires administrator review" }
        val current = detail["current"]!!.jsonObject
        require(current["id"]!!.jsonPrimitive.content == projectId) { "Conflict belongs to another project" }
        val local = dao.project(projectId)?.let { json.decodeFromString<ProjectData>(it.payload) } ?: error("Project missing")
        db.withTransaction {
            val changes = dao.projectChanges().filter { json.parseToJsonElement(it.value).jsonObject["id"]!!.jsonPrimitive.content == projectId }
            dao.saveMeta(Meta("project-conflict-archive-${newId()}", changes.joinToString("\n") { it.value }))
            changes.forEach { dao.removeMeta(it.key) }
            val server = ProjectData(projectId, current["name"]!!.jsonPrimitive.content,
                if (current["budget_set"]?.jsonPrimitive?.int == 0) null else current["budget_minor"]!!.jsonPrimitive.long, json.decodeFromString(current["categories"]!!.jsonPrimitive.content),
                current["archived"]!!.jsonPrimitive.int != 0, current["version"]!!.jsonPrimitive.int, local.role)
            dao.saveProject(LocalProject(projectId, json.encodeToString(server)))
            if (keepLocal) saveProject(local)
            dao.saveMeta(Meta("project_conflict", ""))
        }
    }
    suspend fun resolveConflict(id: String, useLocal: Boolean, duplicateApproved: Boolean = false) {
        requireSession()
        db.withTransaction {
            val local = dao.expense(id) ?: error("Local record missing")
            val queued = dao.queued(id)
            val conflicting = queued.firstOrNull { it.conflict != null } ?: error("No conflict")
            val detail = json.parseToJsonElement(conflicting.conflict!!).jsonObject["detail"]!!.jsonObject
            val code = detail["code"]!!.jsonPrimitive.content
            val current = detail["current"]?.takeIf { it !is JsonNull }?.let { json.decodeFromJsonElement<ServerExpense>(it) }
            if (code == "possible_duplicate") {
                require(useLocal && duplicateApproved) { "Explicitly approve the possible duplicate or review the original" }
                val old = json.decodeFromString<Mutation>(conflicting.payload)
                val revised = old.copy(operation_id = newId(), allow_duplicate = true)
                // Preserve later local operations and their predicted versions.
                dao.acknowledge(conflicting.id)
                dao.enqueue(conflicting.copy(id = revised.operation_id, payload = json.encodeToString(revised), conflict = null))
                dao.save(local.copy(state = "local"))
            } else {
                require(code == "version_conflict" && current != null) { "This error requires administrator review; export the local record" }
                // Archive every queued intent before an explicit user choice replaces the queue.
                dao.saveMeta(Meta("conflict-archive-${newId()}", json.encodeToString(queued)))
                dao.clearQueue(id)
                if (!useLocal) saveServer(current)
                else {
                    require(!current.voided) { "The server record was reversed. Create a new reviewed expense instead." }
                    val action = if (local.voided) "void" else "update"
                    val revised = Mutation(action = action, expense = json.decodeFromString(local.payload), base_version = current.version,
                        reason = if (action == "void") "User resolved conflicting reversal" else "")
                    dao.enqueue(Outbox(revised.operation_id, id, json.encodeToString(revised), System.currentTimeMillis()))
                    dao.save(local.copy(serverVersion = current.version, state = "local"))
                }
            }
        }
    }
}
class LedgerApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork("ledger-sync", ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build())
    }
}
class SyncWorker(context: Context, parameters: WorkerParameters) : CoroutineWorker(context, parameters) {
    override suspend fun doWork(): Result {
        var db: LedgerDatabase? = null
        return try {
            val vault = Vault(applicationContext)
            if (vault.get("auto_sync") == "false") return Result.success()
            val session = vault.get("session")?.let { json.decodeFromString<Session>(it) } ?: return Result.success()
            if (!Instant.now().isBefore(Instant.parse(session.expires_at))) return Result.success()
            val base = vault.get("base") ?: return Result.success()
            db = LedgerDatabase.open(applicationContext, session.user_id, vault, base)
            Repository(db, vault, session, base).sync()
            Result.success()
        } catch (_: Exception) { Result.retry() } finally { db?.close() }
    }
}
