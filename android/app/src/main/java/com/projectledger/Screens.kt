package com.projectledger

import android.content.Intent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import java.time.Instant
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.*
import java.math.BigDecimal
import java.time.LocalDate
import java.time.ZoneOffset
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CalendarMonth

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun ExpenseDateField(value: String, onChange: (String) -> Unit) {
    var showCalendar by remember { mutableStateOf(false) }
    OutlinedTextField(value, onChange, label = { Text("Expense date") }, singleLine = true,
        trailingIcon = { IconButton(onClick = { showCalendar = true }) { Icon(Icons.Default.CalendarMonth, "Choose expense date") } },
        modifier = Modifier.fillMaxWidth())
    if (showCalendar) {
        val initial = runCatching { LocalDate.parse(value).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli() }.getOrNull()
        val state = rememberDatePickerState(initialSelectedDateMillis = initial)
        DatePickerDialog(onDismissRequest = { showCalendar = false }, confirmButton = {
            TextButton(onClick = {
                state.selectedDateMillis?.let { onChange(Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate().toString()) }
                showCalendar = false
            }, enabled = state.selectedDateMillis != null) { Text("Select date") }
        }, dismissButton = { TextButton(onClick = { showCalendar = false }) { Text("Cancel") } }) { DatePicker(state) }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun CategoryField(value: String, choices: List<String>, onChange: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(expanded, { expanded = !expanded }) {
        OutlinedTextField(value, onChange, label = { Text("Category") }, singleLine = true,
            supportingText = { Text("Choose a suggestion or type a new category.") },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) },
            modifier = Modifier.menuAnchor(MenuAnchorType.PrimaryEditable).fillMaxWidth())
        if (choices.isNotEmpty()) ExposedDropdownMenu(expanded, { expanded = false }) {
            choices.forEach { category -> DropdownMenuItem(text = { Text(category) }, onClick = { onChange(category); expanded = false }) }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun Choice(label: String, value: String, choices: List<String>, onChange: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(expanded, { expanded = !expanded }) {
        OutlinedTextField(value, {}, label = { Text(label) }, readOnly = true,
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) }, modifier = Modifier.menuAnchor(MenuAnchorType.PrimaryNotEditable).fillMaxWidth())
        ExposedDropdownMenu(expanded, { expanded = false }) { choices.forEach { option -> DropdownMenuItem(text = { Text(option) }, onClick = { onChange(option); expanded = false }) } }
    }
}
@Composable fun ExpenseEditor(initialProject: ProjectData, projects: List<ProjectData>, original: Expense?, aiReview: Boolean, referenceDate: String, onDismiss: () -> Unit, save: (Expense, Boolean) -> Unit) {
    var projectId by remember { mutableStateOf(initialProject.id) }
    val project = projects.firstOrNull { it.id == projectId } ?: initialProject
    var amount by remember(original?.id) { mutableStateOf(original?.amount_minor?.takeIf { it > 0 }?.let { BigDecimal.valueOf(it, 2).toPlainString() } ?: "") }
    var category by remember { mutableStateOf(original?.category ?: project.categories.firstOrNull().orEmpty()) }
    var description by remember { mutableStateOf(original?.description ?: "") }
    var day by remember { mutableStateOf(original?.expense_date ?: referenceDate) }
    var vendor by remember { mutableStateOf(original?.vendor ?: "") }
    var method by remember { mutableStateOf(original?.payment_method ?: "unknown") }
    var kind by remember { mutableStateOf(original?.kind ?: "expense") }
    var error by remember { mutableStateOf("") }
    fun submit(draft: Boolean) {
        try {
            val minor = parseMoney(amount); LocalDate.parse(day)
            require(description.isNotBlank()) { "Enter a description" }
            require(category.isNotBlank() && category.trim().length <= 100) { "Enter a category of up to 100 characters" }
            save(Expense(original?.id ?: newId(), project.id, minor, category = category.trim(), description = description.trim(),
                expense_date = day, vendor = vendor, payment_method = method, kind = kind, source_proposal_id = original?.source_proposal_id), draft)
        } catch (e: Exception) { error = e.message ?: "Check the amount and date" }
    }
    AlertDialog(onDismissRequest = onDismiss, title = { Text(if (aiReview) "Review AI proposal" else if (original == null) "New expense" else "Edit expense") },
        text = {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                item { Text(project.name, fontWeight = FontWeight.Bold) }
                if (original == null || aiReview) item {
                    Choice("Project", project.name, projects.map { it.name }) { name ->
                        projects.first { it.name == name }.let { projectId = it.id }
                    }
                }
                if (aiReview) item { Text("Check every field. This proposal is excluded from spending until you confirm it.") }
                item { OutlinedTextField(amount, { amount = it }, label = { Text("Amount in rupees") }, singleLine = true, modifier = Modifier.fillMaxWidth()) }
                item { CategoryField(category, project.categories) { category = it } }
                item { OutlinedTextField(description, { description = it }, label = { Text("Description") }, modifier = Modifier.fillMaxWidth()) }
                item { ExpenseDateField(day) { day = it } }
                item { OutlinedTextField(vendor, { vendor = it }, label = { Text("Vendor / recipient (optional)") }, modifier = Modifier.fillMaxWidth()) }
                item { Choice("Payment method", method, listOf("unknown", "cash", "upi", "bank", "card", "cheque")) { method = it } }
                item { Choice("Transaction type", kind, listOf("expense", "refund")) { kind = it } }
                if (error.isNotBlank()) item { Text(error, color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = { Button(onClick = { submit(false) }) { Text(if (aiReview) "Confirm reviewed expense" else "Save expense") } },
        dismissButton = { Column { TextButton(onClick = onDismiss) { Text("Cancel") }; if (!aiReview) TextButton(onClick = { submit(true) }) { Text("Save as draft") } } })
}
@Composable fun ProjectEditor(original: ProjectData?, onDismiss: () -> Unit, save: (ProjectData) -> Unit) {
    var name by remember { mutableStateOf(original?.name ?: "") }
    var budget by remember { mutableStateOf(original?.budget_minor?.let { BigDecimal.valueOf(it, 2).toPlainString() } ?: "") }
    var hasBudget by remember { mutableStateOf(original?.budget_minor != null) }
    var categories by remember { mutableStateOf((original?.categories ?: emptyList()).joinToString(", ")) }
    var archived by remember { mutableStateOf(original?.archived ?: false) }
    var error by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = onDismiss, title = { Text(if (original == null) "Create project" else "Project and budget") }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedTextField(name, { name = it }, label = { Text("Project name") })
            Row { Checkbox(hasBudget, { hasBudget = it }); Text("Set a project budget") }
            if (hasBudget) OutlinedTextField(budget, { budget = it }, label = { Text("Budget in rupees") })
            OutlinedTextField(categories, { categories = it }, label = { Text("Category suggestions (optional)") }, supportingText = { Text("Separate with commas. You and AI can add categories as expenses are reviewed.") }, maxLines = 3)
            Row { Checkbox(archived, { archived = it }); Text("Archive project (read only)") }
            if (error.isNotBlank()) Text(error, color = MaterialTheme.colorScheme.error)
        }
    }, confirmButton = { Button(onClick = {
        try {
            require(name.isNotBlank()) { "Enter a project name" }
            val value = if (!hasBudget) null else if (BigDecimal(budget).compareTo(BigDecimal.ZERO) == 0) 0L else parseMoney(budget)
            val list = categories.split(',').map { it.trim() }.filter { it.isNotBlank() }.distinct()
            save(ProjectData(original?.id ?: newId(), name.trim(), value, list, archived, original?.version ?: 0))
        } catch (e: Exception) { error = e.message ?: "Check project details" }
    }) { Text("Save project") } }, dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } })
}
@Composable fun HistoryScreen(rows: List<LocalExpense>, categories: List<String>, writable: Boolean, queue: List<Outbox>, repo: Repository, vm: LedgerViewModel, edit: (Expense) -> Unit) {
    var search by remember { mutableStateOf("") }; var category by remember { mutableStateOf("All") }
    var start by remember { mutableStateOf("") }; var end by remember { mutableStateOf("") }
    var detail by remember { mutableStateOf<LocalExpense?>(null) }
    val displayed = rows.filter { row ->
        val expense = json.decodeFromString<Expense>(row.payload)
        (category == "All" || expense.category == category) && (start.isBlank() || expense.expense_date >= start) && (end.isBlank() || expense.expense_date <= end) &&
            (search.isBlank() || (expense.description + " " + expense.vendor).contains(search, ignoreCase = true))
    }.sortedByDescending { json.decodeFromString<Expense>(it.payload).expense_date }
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { OutlinedTextField(search, { search = it }, label = { Text("Search descriptions and vendors") }, modifier = Modifier.fillMaxWidth().padding(top = 12.dp)) }
        item { Choice("Category", category, listOf("All") + categories) { category = it } }
        item { Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(start, { start = it }, label = { Text("From YYYY-MM-DD") }, modifier = Modifier.weight(1f))
            OutlinedTextField(end, { end = it }, label = { Text("To YYYY-MM-DD") }, modifier = Modifier.weight(1f))
        } }
        item { Text("${displayed.size} records", style = MaterialTheme.typography.labelLarge) }
        items(displayed, key = { it.id }) { row ->
            val expense = json.decodeFromString<Expense>(row.payload)
            Card(onClick = { detail = row }, modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(expense.category, color = MaterialTheme.colorScheme.primary)
                        Text(money(if (expense.kind == "refund") -expense.amount_minor else expense.amount_minor), fontWeight = FontWeight.Bold)
                    }
                    Text(expense.description, style = MaterialTheme.typography.titleMedium)
                    Text("${expense.expense_date} • ${expense.vendor.ifBlank { "Vendor unknown" }}", style = MaterialTheme.typography.bodySmall)
                    Text(if (row.voided) "Reversed" else when(row.state) { "synced" -> "Saved on server"; "draft" -> "Draft — excluded from totals"; "conflict" -> "Needs conflict review"; else -> "Saved locally — waiting to sync" }, style = MaterialTheme.typography.labelSmall)
                }
            }
        }
        item { Spacer(Modifier.height(90.dp)) }
    }
    detail?.let { row ->
        val expense = json.decodeFromString<Expense>(row.payload)
        var reason by remember(row.id) { mutableStateOf("") }
        val conflict = queue.firstOrNull { it.expenseId == row.id && it.conflict != null }
        AlertDialog(onDismissRequest = { detail = null }, title = { Text(expense.description) }, text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("${money(expense.amount_minor)} • ${expense.category}\nDate: ${expense.expense_date}\nVendor: ${expense.vendor}\nPayment: ${expense.payment_method}\nType: ${expense.kind}\nOwner: ${row.owner}\nCreated: ${row.createdAt}\nUpdated: ${row.updatedAt}\nServer version: ${row.serverVersion}")
                if (conflict != null) {
                    Text("Both versions are retained. Review the server response before choosing.")
                    Text(conflict.conflict!!, style = MaterialTheme.typography.bodySmall)
                    OutlinedButton(onClick = { vm.action { repo.resolveConflict(row.id, false); detail = null } }) { Text("Use server version") }
                    Button(onClick = { vm.action { repo.resolveConflict(row.id, true, conflict.conflict.contains("possible_duplicate")); detail = null } }) { Text(if (conflict.conflict.contains("possible_duplicate")) "Confirm this is a separate expense" else "Keep my version, retry against server version") }
                } else if (writable && !row.voided && row.state != "draft") {
                    OutlinedTextField(reason, { reason = it }, label = { Text("Reason for reversal") })
                    TextButton(onClick = { vm.action { repo.voidExpense(row.id, reason); detail = null } }) { Text("Reverse this record") }
                }
            }
        }, confirmButton = { if (writable && !row.voided && conflict == null) Button(onClick = { detail = null; edit(expense) }) { Text("Edit") } }, dismissButton = {
            Column { TextButton(onClick = { detail = null }) { Text("Close") }; if (row.state == "draft") TextButton(onClick = { vm.action { repo.dao.removeDraft(row.id); detail = null } }) { Text("Delete draft") } }
        })
    }
}
@Composable fun PendingScreen(project: ProjectData, entries: List<PendingAI>, repo: Repository, vm: LedgerViewModel, writable: Boolean, review: (PendingAI, Proposal) -> Unit) {
    var text by remember { mutableStateOf("") }
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { Text("Describe an expense", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(top = 16.dp)) }
        item { Text("Your original text is stored on this device. Local AI prepares proposals after reconnection. Nothing counts as spending until you confirm.") }
        if (writable) item {
            OutlinedTextField(text, { text = it }, label = { Text("e.g. Paid Rajesh ₹15,000 yesterday for wiring") }, minLines = 3, modifier = Modifier.fillMaxWidth())
            Button(onClick = { vm.action { repo.queueAI(project.id, text); text = "" } }) { Text("Save for AI interpretation") }
        }
        items(entries, key = { it.id }) { entry ->
            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(entry.text, style = MaterialTheme.typography.titleMedium)
                Text(when(entry.state) { "pending" -> "Waiting for local AI"; "review" -> "Review required"; "confirmed" -> "Confirmed — see transaction history"; else -> "Cancelled — original text retained" }, color = MaterialTheme.colorScheme.primary)
                entry.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                entry.result?.let { encoded ->
                    val result = json.decodeFromString<Interpretation>(encoded)
                    result.warnings.forEach { Text(it, color = MaterialTheme.colorScheme.error) }
                    result.proposals.filter { it.id !in entry.confirmed.split(',') }.forEach { proposal ->
                        if (entry.state == "review" && writable) OutlinedButton(onClick = { review(entry, proposal) }) { Text("Review ${proposal.amount_minor?.let { money(it) } ?: "missing amount"} • ${proposal.description}") }
                    }
                    if (result.proposals.isEmpty()) Text("AI could not identify a transaction. Keep this text and use manual entry.")
                }
                if (writable && entry.state in listOf("pending", "review")) TextButton(onClick = { vm.action { repo.dao.saveAI(entry.copy(state = "cancelled")) } }) { Text("Cancel processing — retain original text") }
            } }
        }
        item { Spacer(Modifier.height(90.dp)) }
    }
}
@Composable fun SettingsScreen(project: ProjectData, repo: Repository, vm: LedgerViewModel, meta: Map<String, String>, editProject: () -> Unit) {
    val context = LocalContext.current
    var autoSync by remember { mutableStateOf(repo.vault.get("auto_sync") != "false") }
    var autoAI by remember(meta["auto_ai"]) { mutableStateOf(meta["auto_ai"] != "false") }
    var zone by remember(meta["timezone"]) { mutableStateOf(meta["timezone"] ?: "Asia/Kolkata") }
    var page by remember { mutableStateOf("settings") }
    if (page == "workbook") { WorkbookScreen(project, repo, vm) { page = "settings" }; return }
    if (page == "team") { TeamScreen(project, repo, vm) { page = "settings" }; return }
    val report = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/csv")) { uri ->
        if (uri != null) vm.action {
            val rows = repo.dao.observeExpenses().first().filter { it.project == project.id && it.state !in listOf("draft", "access_removed") }
            fun csv(raw: String): String {
                val safe = if (raw.trimStart().firstOrNull() in listOf('=', '+', '-', '@', '\t', '\r')) "'" + raw else raw
                return "\"" + safe.replace("\"", "\"\"") + "\""
            }
            val lines = mutableListOf("id,project,amount_inr,currency,kind,expense_date,category,vendor,description,payment_method,status,version,owner,created_at,updated_at")
            rows.forEach { row ->
                val e = json.decodeFromString<Expense>(row.payload)
                val value = if (row.voided) 0L else if (e.kind == "refund") -e.amount_minor else e.amount_minor
                val fields = listOf(e.id, project.name, BigDecimal.valueOf(value, 2).toPlainString(), "INR", e.kind, e.expense_date, e.category, e.vendor, e.description, e.payment_method, row.state, row.serverVersion.toString(), row.owner, row.createdAt, row.updatedAt)
                lines.add(fields.mapIndexed { index, field -> if (index == 2 || index == 11) field else csv(field) }.joinToString(","))
            }
            withContext(Dispatchers.IO) { context.contentResolver.openOutputStream(uri)?.use { it.write(lines.joinToString("\r\n").toByteArray()) } ?: error("Cannot write report") }
        }
    }
    val export = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri ->
        if (uri != null) vm.action {
            val rows = withContext(Dispatchers.IO) { repo.dao.observeExpenses().first() }
            val queue = repo.dao.queue()
            val pending = withContext(Dispatchers.IO) { repo.dao.observeAI().first() }
            val projects = repo.dao.observeProjects().first()
            val metadata = repo.dao.observeMeta().first()
            val payload = buildJsonObject {
                put("projects", JsonArray(projects.map { json.parseToJsonElement(it.payload) }))
                put("metadata", JsonObject(metadata.associate { it.key to JsonPrimitive(it.value) }))
                put("format", "ledger-device-recovery-v1"); put("exported_at", Instant.now().toString())
                put("records", json.encodeToJsonElement(rows)); put("queue", json.encodeToJsonElement(queue)); put("pending_ai", json.encodeToJsonElement(pending))
            }
            withContext(Dispatchers.IO) { context.contentResolver.openOutputStream(uri)?.use { it.write(payload.toString().toByteArray()) } ?: error("Cannot write export") }
        }
    }
    LazyColumn(Modifier.fillMaxSize().padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item { Text("Project settings", style = MaterialTheme.typography.headlineSmall) }
        if (meta["project_conflict"].orEmpty().isNotBlank()) item {
            Text("Project settings changed on another device. Review both versions before retrying.")
            Text(meta["project_conflict"]!!, style = MaterialTheme.typography.bodySmall)
            OutlinedButton(onClick = { vm.action { repo.resolveProjectConflict(project.id, false) } }) { Text("Use server project settings") }
            Button(onClick = { vm.action { repo.resolveProjectConflict(project.id, true) } }) { Text("Keep my settings against reviewed server version") }
        }
        item { Text("Signed in as ${repo.session.username}\nServer: ${repo.base}\nOffline session expires: ${repo.session.expires_at}") }
        if (project.role == "administrator") item { Button(onClick = editProject) { Text("Project, categories and budget") } }
        item { OutlinedTextField(zone, { zone = it }, label = { Text("Expense time zone (e.g. Asia/Kolkata)") })
            TextButton(onClick = { vm.action { java.time.ZoneId.of(zone); repo.dao.saveMeta(Meta("timezone", zone)) } }) { Text("Save time zone") }
        }
        item { Row { Switch(autoSync, { autoSync = it; repo.vault.put("auto_sync", it.toString()) }); Text("Automatic synchronization", Modifier.padding(12.dp)) } }
        item { Row { Switch(autoAI, { autoAI = it; vm.action { repo.dao.saveMeta(Meta("auto_ai", it.toString())) } }); Text("Process queued AI descriptions", Modifier.padding(12.dp)) } }
        item { OutlinedButton(onClick = { page = "workbook" }) { Text("Workbook mapping and status") } }
        if (project.role == "administrator") item { OutlinedButton(onClick = { page = "team" }) { Text("Team and accounts") } }
        item { OutlinedButton(onClick = { report.launch("project-ledger-local-records.csv") }) { Text("Export local financial report (CSV)") } }
        item { Text("Recovery export contains sensitive unencrypted data. Choose protected local storage.", style = MaterialTheme.typography.bodySmall) }
        item { OutlinedButton(onClick = { export.launch("ledger-device-recovery.json") }) { Text("Export device records and pending changes") } }
        item { Text("Offline totals include confirmed local entries and may differ from the team. Removed access takes effect after reconnecting; disconnected sessions expire after seven days.") }
        item { TextButton(onClick = { vm.logout() }) { Text("Log out") } }
    }
}
@Composable fun WorkbookScreen(project: ProjectData, repo: Repository, vm: LedgerViewModel, back: () -> Unit) {
    val context = LocalContext.current
    var inspection by remember { mutableStateOf<JsonObject?>(null) }
    var sheet by remember { mutableStateOf("") }; var header by remember { mutableStateOf("1") }
    var amount by remember { mutableStateOf("C") }; var category by remember { mutableStateOf("B") }
    var description by remember { mutableStateOf("D") }; var date by remember { mutableStateOf("A") }
    var vendor by remember { mutableStateOf("E") }; var paymentColumn by remember { mutableStateOf("F") }; var kindColumn by remember { mutableStateOf("G") }; var reviewedHash by remember { mutableStateOf("") }; var status by remember { mutableStateOf("") }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) vm.action {
            val bytes = withContext(Dispatchers.IO) { context.contentResolver.openInputStream(uri)?.use { input ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(65536)
                while (true) {
                    val count = input.read(buffer); if (count < 0) break
                    require(output.size() + count <= 20 * 1024 * 1024) { "Workbook exceeds 20 MiB" }
                    output.write(buffer, 0, count)
                }
                output.toByteArray()
            } ?: error("Workbook cannot be opened") }
            val response = withContext(Dispatchers.IO) { repo.api.upload(bytes) }
            inspection = json.parseToJsonElement(response).jsonObject
            sheet = inspection!!["sheets"]!!.jsonArray.first().jsonObject["name"]!!.jsonPrimitive.content
        }
    }
    LazyColumn(Modifier.fillMaxSize().padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { TextButton(onClick = back) { Text("Back to settings") }; Text("Excel workbook", style = MaterialTheme.typography.headlineSmall) }
        item { Text("Supported plain XLSX only. Original files are backed up. Formulas are preserved, but calculated values are refreshed by Excel or LibreOffice when opened.") }
        if (project.role == "administrator") item { Button(onClick = { picker.launch(arrayOf("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")) }) { Text("Select and inspect workbook") } }
        inspection?.let { data ->
            item { Text(data["sheets"].toString(), style = MaterialTheme.typography.bodySmall) }
            item { Choice("Worksheet", sheet, data["sheets"]!!.jsonArray.map { it.jsonObject["name"]!!.jsonPrimitive.content }) { sheet = it } }
            item { OutlinedTextField(header, { header = it }, label = { Text("Header row") }) }
            item { OutlinedTextField(amount, { amount = it }, label = { Text("Amount column (Excel letter)") }) }
            item { OutlinedTextField(category, { category = it }, label = { Text("Category column") }) }
            item { OutlinedTextField(description, { description = it }, label = { Text("Description column") }) }
            item { OutlinedTextField(date, { date = it }, label = { Text("Date column") }) }
            item { OutlinedTextField(vendor, { vendor = it }, label = { Text("Vendor column (blank to skip)") }) }
            item { OutlinedTextField(paymentColumn, { paymentColumn = it }, label = { Text("Payment method column (blank to skip)") }) }
            item { OutlinedTextField(kindColumn, { kindColumn = it }, label = { Text("Expense/refund kind column (blank to skip)") }) }
            item { Button(onClick = { vm.action {
                val payload = buildJsonObject {
                    put("upload_id", data["upload_id"]!!); put("sheet", sheet); put("header_row", header.toInt()); put("import_rows", true)
                    put("columns", buildJsonObject { put("amount_minor", amount); put("category", category); put("description", description); put("expense_date", date); if (vendor.isNotBlank()) put("vendor", vendor); if (paymentColumn.isNotBlank()) put("payment_method", paymentColumn); if (kindColumn.isNotBlank()) put("kind", kindColumn) })
                }
                status = withContext(Dispatchers.IO) { repo.api.request("/projects/${project.id}/workbook/link", "POST", payload.toString()) }
                repo.sync(); inspection = null
            } }) { Text("Confirm mapping, import and link") } }
        }
        item { OutlinedButton(onClick = { vm.action { status = withContext(Dispatchers.IO) { repo.api.request("/projects/${project.id}/workbook/retry", "POST") } } }) { Text("Check status and retry updates") } }
        item { Text(status) }
        if (project.role == "administrator") {
            item { OutlinedButton(onClick = { vm.action {
                val response = withContext(Dispatchers.IO) { repo.api.request("/projects/${project.id}/workbook/inspect-current") }
                val data = json.parseToJsonElement(response).jsonObject
                reviewedHash = data["sha256"]!!.jsonPrimitive.content
                status = response
            } }) { Text("Inspect external workbook changes") } }
            if (reviewedHash.isNotBlank()) item { Button(onClick = { vm.action {
                val body = buildJsonObject { put("reviewed_sha256", reviewedHash); put("confirmed", true) }
                status = withContext(Dispatchers.IO) { repo.api.request("/projects/${project.id}/workbook/reconcile", "POST", body.toString()) }
                reviewedHash = ""; repo.sync()
            } }) { Text("Confirm reviewed workbook; verify financial cells and adopt") } }
        }
        item { Text("External workbook edits block automatic updates. Keep the external copy, review differences, and reconcile with the administrator before retrying.") }
    }
}
@Composable fun TeamScreen(project: ProjectData, repo: Repository, vm: LedgerViewModel, back: () -> Unit) {
    var members by remember { mutableStateOf<JsonArray>(JsonArray(emptyList())) }
    var users by remember { mutableStateOf<JsonArray>(JsonArray(emptyList())) }
    var username by remember { mutableStateOf("") }; var password by remember { mutableStateOf("") }
    var identifier by remember { mutableStateOf("") }; var role by remember { mutableStateOf("editor") }
    fun refresh() { vm.action {
        members = withContext(Dispatchers.IO) { json.parseToJsonElement(repo.api.request("/projects/${project.id}/members")).jsonArray }
        if (repo.session.administrator) users = withContext(Dispatchers.IO) { json.parseToJsonElement(repo.api.request("/users")).jsonArray }
    } }
    LaunchedEffect(project.id) { refresh() }
    LazyColumn(Modifier.fillMaxSize().padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { TextButton(onClick = back) { Text("Back to settings") }; Text("Team access", style = MaterialTheme.typography.headlineSmall) }
        items(members) { member -> val value = member.jsonObject; Text("${value["username"]!!.jsonPrimitive.content} • ${value["role"]!!.jsonPrimitive.content}\n${value["id"]!!.jsonPrimitive.content}") }
        item { OutlinedTextField(identifier, { identifier = it }, label = { Text("User ID to add or modify") }) }
        item { Choice("Role", role, listOf("administrator", "editor", "viewer", "removed")) { role = it } }
        item { Button(onClick = { vm.action {
            val body = buildJsonObject { put("user_id", identifier); put("role", role) }
            withContext(Dispatchers.IO) { repo.api.request("/projects/${project.id}/members", "PUT", body.toString()) }; refresh()
        } }) { Text("Apply project permission") } }
        if (repo.session.administrator) {
            item { Text("System accounts", style = MaterialTheme.typography.titleLarge); Text(users.toString(), style = MaterialTheme.typography.bodySmall) }
            item { OutlinedTextField(username, { username = it }, label = { Text("New username") }) }
            item { OutlinedTextField(password, { password = it }, label = { Text("Password (12+ characters)") }, visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation()) }
            item { Button(onClick = { vm.action {
                val body = buildJsonObject { put("username", username); put("password", password) }
                withContext(Dispatchers.IO) { repo.api.request("/users", "POST", body.toString()) }; password = ""; refresh()
            } }) { Text("Provision account") } }
            item { OutlinedButton(onClick = { vm.action { withContext(Dispatchers.IO) { repo.api.request("/users/$identifier/revoke", "POST") }; refresh() } }) { Text("Revoke selected user account") } }
            item { OutlinedButton(onClick = { vm.action {
                val body = buildJsonObject { put("password", password) }
                withContext(Dispatchers.IO) { repo.api.request("/users/$identifier/reset-password", "POST", body.toString()) }; password = ""; refresh()
            } }) { Text("Reset selected user password") } }
        }
    }
}
