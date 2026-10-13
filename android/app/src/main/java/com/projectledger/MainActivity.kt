package com.projectledger

import android.app.KeyguardManager
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.isActive
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.*
import java.time.Instant
import java.time.LocalDate

class LedgerViewModel(application: android.app.Application) : AndroidViewModel(application) {
    val vault = Vault(application)
    val repo = MutableStateFlow<Repository?>(null)
    val error = MutableStateFlow("")
    val busy = MutableStateFlow(false)
    fun openCached() = action {
        val session = vault.get("session")?.let { json.decodeFromString<Session>(it) } ?: return@action
        require(Instant.now().isBefore(Instant.parse(session.expires_at))) { "Your offline session expired. Reconnect and log in. Your records are retained." }
        open(session, vault.get("base") ?: kotlin.error("Server address missing"))
    }
    private fun open(session: Session, base: String) {
        repo.value?.db?.close()
        repo.value = Repository(LedgerDatabase.open(getApplication(), session.user_id, vault, base), vault, session, base)
    }
    fun signIn(base: String, username: String, password: String) = action {
        val session = withContext(Dispatchers.IO) { json.decodeFromString<Session>(Api(base, "").request("/auth/login", "POST", json.encodeToString(LoginBody(username, password)))) }
        val previousBase = vault.get("base")
        require(previousBase == null || previousBase == base || vault.get("session") == null) { "Log out before switching servers" }
        vault.put("base", base); vault.put("session", json.encodeToString(session)); open(session, base)
        repo.value!!.sync()
    }
    fun action(block: suspend () -> Unit) {
        viewModelScope.launch {
            busy.value = true; error.value = ""
            try { block() } catch (e: Exception) { error.value = e.message ?: "Action failed. Your saved records are retained." }
            finally { busy.value = false }
        }
    }
    fun logout() = action {
        val current = repo.value
        vault.remove("session"); repo.value = null
        if (current != null) {
            runCatching { withContext(Dispatchers.IO) { current.api.request("/auth/logout", "POST") } }
            current.db.close()
        }
    }
    override fun onCleared() { repo.value?.db?.close() }
}

class MainActivity : ComponentActivity() {
    private val vm by viewModels<LedgerViewModel>()
    private var unlocked by mutableStateOf(false)
    private var unlocking = false
    private var relockOnReturn = false
    private val deviceUnlock = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        unlocking = false
        unlocked = it.resultCode == RESULT_OK
        if (unlocked && vm.repo.value == null) vm.openCached()
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE)
        setContent {
            MaterialTheme(colorScheme = lightColorScheme(primary = Color(0xFF087E8B), secondary = Color(0xFFDA9B40),
                background = Color(0xFFF5F6F8), surface = Color.White, onSurface = Color(0xFF142938))) {
                Surface(Modifier.fillMaxSize()) {
                    if (!unlocked) LockScreen { unlock() } else LedgerApp(vm)
                }
            }
        }
        unlock()
    }
    override fun onStop() {
        super.onStop()
        if (!unlocking) { unlocked = false; relockOnReturn = true }
    }
    override fun onResume() {
        super.onResume()
        if (!unlocked && !unlocking && relockOnReturn) unlock()
    }
    private fun unlock() {
        if (unlocking) return
        relockOnReturn = false
        val keyguard = getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager
        if (!keyguard.isDeviceSecure) {
            vm.error.value = "Set a device screen lock in Android Settings to protect offline financial records."
            return
        }
        @Suppress("DEPRECATION")
        val intent = keyguard.createConfirmDeviceCredentialIntent("Unlock Project Ledger", "Use your device credential to access project finances")
        if (intent != null) { unlocking = true; deviceUnlock.launch(intent) }
    }
}
@Composable fun LockScreen(unlock: () -> Unit) {
    Column(Modifier.fillMaxSize().padding(32.dp), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
        Icon(Icons.Default.Lock, "Financial records locked", Modifier.size(64.dp), tint = MaterialTheme.colorScheme.primary)
        Text("Project Ledger", style = MaterialTheme.typography.headlineLarge)
        Text("Protect your finances with your Android screen lock.", Modifier.padding(vertical = 24.dp))
        Button(onClick = unlock) { Text("Unlock with device credential") }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun LedgerApp(vm: LedgerViewModel) {
    val repo by vm.repo.collectAsStateWithLifecycle()
    val error by vm.error.collectAsStateWithLifecycle()
    val busy by vm.busy.collectAsStateWithLifecycle()
    if (repo == null) { LoginScreen(vm, error, busy); return }
    val current = repo!!
    LaunchedEffect(current) {
        suspend fun synchronizeAutomatically() {
            if (current.vault.get("auto_sync") == "false") return
            try { current.sync() } catch (cancelled: kotlinx.coroutines.CancellationException) { throw cancelled } catch (_: Exception) { }
        }
        coroutineScope {
            launch { current.syncRequests.collect { synchronizeAutomatically() } }
            launch { while (isActive) { synchronizeAutomatically(); kotlinx.coroutines.delay(30_000) } }
        }
    }
    LaunchedEffect(current.session.expires_at) {
        val remaining = java.time.Duration.between(Instant.now(), Instant.parse(current.session.expires_at)).toMillis()
        if (remaining > 0) kotlinx.coroutines.delay(remaining)
        vm.logout()
    }
    val localProjects by current.dao.observeProjects().collectAsStateWithLifecycle(emptyList())
    val allRows by current.dao.observeExpenses().collectAsStateWithLifecycle(emptyList())
    val ai by current.dao.observeAI().collectAsStateWithLifecycle(emptyList())
    val queue by current.dao.observeQueue().collectAsStateWithLifecycle(emptyList())
    val metadata by current.dao.observeMeta().collectAsStateWithLifecycle(emptyList())
    val meta = metadata.associate { it.key to it.value }
    val projects = localProjects.map { json.decodeFromString<ProjectData>(it.payload) }
    var selected by remember { mutableStateOf<String?>(null) }
    var tab by remember { mutableStateOf("Overview") }
    var editing by remember { mutableStateOf<Expense?>(null) }
    var editorOpen by remember { mutableStateOf(false) }
    var reviewingAI by remember { mutableStateOf<String?>(null) }
    var projectEditor by remember { mutableStateOf(false) }
    var projectToEdit by remember { mutableStateOf<ProjectData?>(null) }
    val project = projects.firstOrNull { it.id == selected }
    val rows = allRows.filter { it.project == project?.id && it.state != "access_removed" }
    val writable = project != null && project.role != "viewer" && !project.archived
    val snack = remember { SnackbarHostState() }
    LaunchedEffect(error) { if (error.isNotBlank()) snack.showSnackbar(error, duration = SnackbarDuration.Long) }
    Scaffold(
        topBar = { TopAppBar(title = { Column { Text(project?.name ?: "Project Ledger", fontWeight = FontWeight.Bold); Text("PRIVATE • LOCAL FIRST", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary) } },
            navigationIcon = { if (project != null) IconButton(onClick = { selected = null; tab = "Overview" }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "All projects") } },
            actions = { IconButton(onClick = { vm.action { current.sync() } }, enabled = !busy) { Icon(Icons.Default.Sync, "Synchronize saved changes") } }) },
        snackbarHost = { SnackbarHost(snack) },
        bottomBar = { if (project != null) NavigationBar {
            listOf("Overview" to Icons.Default.Dashboard, "History" to Icons.AutoMirrored.Filled.List, "Pending" to Icons.Default.PendingActions, "Settings" to Icons.Default.Settings).forEach { (name, icon) ->
                NavigationBarItem(selected = tab == name, onClick = { tab = name }, icon = { Icon(icon, name) }, label = { Text(name) })
            }
        } },
        floatingActionButton = { if (writable && tab != "Settings") FloatingActionButton(onClick = { editing = null; reviewingAI = null; editorOpen = true }) { Icon(Icons.Default.Add, "Add manual expense") } }
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            SyncBanner(meta, queue.size)
            if (project == null) {
                LazyColumn(Modifier.fillMaxSize().padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    item { Text("Your projects", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.padding(vertical = 16.dp)) }
                    if (projects.isEmpty()) item { EmptyState("No projects yet", "An administrator can create a project. First login needs your Linux backend.") }
                    items(projects, key = { it.id }) { p ->
                        Card(onClick = { selected = p.id; tab = "Overview" }, modifier = Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(20.dp)) {
                                Text(p.name, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                                Text("${p.role} • ${if (p.archived) "Archived" else "Active"}", color = MaterialTheme.colorScheme.primary)
                                Text(p.budget_minor?.let { "Budget ${money(it)}" } ?: "No budget set", Modifier.padding(top = 12.dp))
                            }
                        }
                    }
                    item { if (current.session.administrator) Button(onClick = { projectToEdit = null; projectEditor = true }) { Text("Create project") } }
                    item { TextButton(onClick = { vm.logout() }) { Text("Log out — saved records remain on this device") } }
                }
            } else when(tab) {
                "Overview" -> Dashboard(project, rows, current, vm) { tab = "Pending" }
                "History" -> HistoryScreen(rows, project.categories, writable, queue, current, vm) { editing = it; reviewingAI = null; editorOpen = true }
                "Pending" -> PendingScreen(project, ai.filter { it.project == project.id }, current, vm, writable) { entry, proposal ->
                    editing = Expense(project_id = project.id, amount_minor = proposal.amount_minor ?: 0,
                        category = proposal.category ?: project.categories.firstOrNull().orEmpty(), description = proposal.description,
                        expense_date = proposal.expense_date ?: "", vendor = proposal.vendor ?: "", payment_method = proposal.payment_method,
                        kind = proposal.kind, source_proposal_id = proposal.id)
                    reviewingAI = entry.id; editorOpen = true
                }
                "Settings" -> SettingsScreen(project, current, vm, meta) { projectToEdit = project; projectEditor = true }
            }
        }
    }
    if (editorOpen && project != null) ExpenseEditor(project, projects.filter { it.role != "viewer" && !it.archived }, editing, reviewingAI != null, referenceDate = LocalDate.now(java.time.ZoneId.of(meta["timezone"] ?: "Asia/Kolkata")).toString(), onDismiss = { editorOpen = false }) { expense, draft ->
        vm.action { current.saveExpense(expense, draft, reviewingAI); editorOpen = false }
    }
    if (projectEditor) ProjectEditor(projectToEdit, onDismiss = { projectEditor = false }) { updated ->
        vm.action {
            current.saveProject(updated); projectEditor = false
        }
    }
}

@Composable fun LoginScreen(vm: LedgerViewModel, error: String, busy: Boolean) {
    var base by remember { mutableStateOf("") }; var username by remember { mutableStateOf("") }; var password by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize().padding(28.dp), verticalArrangement = Arrangement.Center) {
        Icon(Icons.Default.AccountBalanceWallet, "", Modifier.size(60.dp), tint = MaterialTheme.colorScheme.primary)
        Text("Project Ledger", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 16.dp))
        Text("Every project. Every expense.\nYour records stay with your team.", Modifier.padding(vertical = 20.dp), style = MaterialTheme.typography.bodyLarge)
        OutlinedTextField(base, { base = it }, label = { Text("Tailscale HTTPS address") }, placeholder = { Text("https://desktop.tailnet.ts.net") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(username, { username = it }, label = { Text("Username") }, singleLine = true, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
        OutlinedTextField(password, { password = it }, label = { Text("Password") }, singleLine = true, visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
        Button(onClick = { vm.signIn(base.trim(), username.trim(), password); password = "" }, enabled = !busy, modifier = Modifier.fillMaxWidth().padding(top = 20.dp)) { Text("Sign in securely") }
        if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (error.isNotBlank()) Text(error, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(top = 12.dp))
        Text("First sign-in requires the desktop. Your cached session supports offline work for seven days.", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 20.dp))
    }
}
@Composable fun SyncBanner(meta: Map<String, String>, queued: Int) {
    Column(Modifier.fillMaxWidth().background(Color(0xFFE8F2F3)).padding(horizontal = 20.dp, vertical = 10.dp)) {
        Text("${if (queued == 0) "Saved on this device" else "$queued changes waiting to sync"} • Team totals are provisional", style = MaterialTheme.typography.labelMedium)
        Text("Last sync: ${meta["last_sync"] ?: "Never"}", style = MaterialTheme.typography.bodySmall)
        meta["sync_error"]?.takeIf { it.isNotBlank() }?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
    }
}
@Composable fun EmptyState(title: String, body: String) {
    Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(24.dp)) { Text(title, style = MaterialTheme.typography.titleMedium); Text(body, Modifier.padding(top = 8.dp)) } }
}
@Composable fun StatCard(label: String, value: String, modifier: Modifier = Modifier) {
    Card(modifier) { Column(Modifier.padding(20.dp)) { Text(label, style = MaterialTheme.typography.labelLarge); Text(value, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 8.dp)) } }
}
@Composable fun Breakdown(title: String, values: Map<String, Long>) {
    Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 16.dp))
    val maximum = values.values.maxOfOrNull { kotlin.math.abs(it) }?.coerceAtLeast(1) ?: 1
    values.toSortedMap().forEach { (label, amount) ->
        Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) { Text(label); Text(money(amount), fontWeight = FontWeight.Medium) }
            LinearProgressIndicator(progress = { (kotlin.math.abs(amount).toDouble() / maximum).toFloat() }, modifier = Modifier.fillMaxWidth().height(6.dp).padding(top = 2.dp))
        }
    }
}
@Composable fun Dashboard(project: ProjectData, rows: List<LocalExpense>, repo: Repository, vm: LedgerViewModel, pending: () -> Unit) {
    val valid = rows.filter { it.state != "draft" && !it.voided }.map { json.decodeFromString<Expense>(it.payload) }
    val totals = totals(valid, project.budget_minor)
    var question by remember { mutableStateOf("") }; var allProjects by remember { mutableStateOf(false) }; var answer by remember { mutableStateOf("") }
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { Spacer(Modifier.height(8.dp)); StatCard("Total recorded expenditure", money(totals.total), Modifier.fillMaxWidth()) }
        item { StatCard("Remaining budget", totals.remaining?.let { money(it) } ?: "No budget set", Modifier.fillMaxWidth()) }
        item { Text("${valid.size} confirmed records • Drafts and pending AI excluded", style = MaterialTheme.typography.bodySmall)
            val budget = project.budget_minor
            if (budget != null && budget > 0) {
                val utilization = java.math.BigDecimal.valueOf(totals.total).multiply(java.math.BigDecimal(100)).divide(java.math.BigDecimal.valueOf(budget), 1, java.math.RoundingMode.HALF_UP)
                Text("Budget used: ${utilization.toPlainString()}%")
                LinearProgressIndicator(progress = { (utilization.toFloat() / 100).coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
            }
        }
        item { Breakdown("By category", totals.categories) }
        item { Breakdown("Monthly spending", totals.months) }
        item { Breakdown("By vendor", totals.vendors) }
        item { OutlinedButton(onClick = pending) { Text("Enter a description for local AI") } }
        item {
            Text("Ask about project finances", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(question, { question = it }, label = { Text("e.g. Transportation spending this month") }, modifier = Modifier.fillMaxWidth())
            Row { Checkbox(allProjects, { allProjects = it }); Text("Compare all authorized projects", Modifier.padding(top = 12.dp)) }
            Button(enabled = question.isNotBlank() && question.length <= 2000, onClick = { vm.action {
                val questionDate = LocalDate.now(java.time.ZoneId.of(repo.dao.meta("timezone") ?: "Asia/Kolkata")).toString()
                val payload = buildJsonObject { put("text", question); put("reference_date", questionDate) }
                val response = withContext(Dispatchers.IO) { repo.api.request(if (allProjects) "/ai/question" else "/projects/${project.id}/ai/question", "POST", payload.toString()) }
                val parsed = json.parseToJsonElement(response).jsonObject
                answer = formatFinanceAnswer(parsed, allProjects)
            } }) { Text("Calculate using server records") }
            if (answer.isNotBlank()) Text(answer)
        }
        item { Spacer(Modifier.height(90.dp)) }
    }
}
