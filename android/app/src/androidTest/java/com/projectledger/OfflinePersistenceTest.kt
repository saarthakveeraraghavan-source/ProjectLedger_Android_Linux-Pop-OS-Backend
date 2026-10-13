package com.projectledger

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.flow.first
import kotlinx.serialization.encodeToString
import kotlinx.serialization.decodeFromString
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.time.Instant

@RunWith(AndroidJUnit4::class)
class OfflinePersistenceTest {
    @Test fun encryptedRoomSurvivesCloseAndQueuesOfflineEdits(): Unit = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val vault = Vault(context)
        val user = newId(); val projectId = newId(); val base = "https://ledger-test.example"
        val session = Session("test-token", user, "fixture-user", true, Instant.now().plusSeconds(3600).toString())
        var database = LedgerDatabase.open(context, user, vault, base)
        var repository = Repository(database, vault, session, base)
        val project = ProjectData(projectId, "Main building", 1000000, constructionCategories)
        repository.dao.saveProject(LocalProject(projectId, json.encodeToString(project)))
        val expense = Expense(project_id = projectId, amount_minor = 300001, category = "Transportation", description = "Cement delivery", expense_date = "2026-10-12")
        repository.saveExpense(expense, false)
        repository.saveExpense(expense.copy(amount_minor = 325001), false)
        repository.queueAI(projectId, "Spent ₹8500 buying cement yesterday")
        val draft = expense.copy(id = newId(), description = "Draft expense")
        repository.saveExpense(draft, true)
        assertEquals(2, repository.dao.queue().size)
        val first = json.decodeFromString<Mutation>(repository.dao.queue()[0].payload)
        val second = json.decodeFromString<Mutation>(repository.dao.queue()[1].payload)
        assertEquals("create", first.action); assertEquals(0, first.base_version)
        assertEquals("update", second.action); assertEquals(1, second.base_version)
        database.close()
        database = LedgerDatabase.open(context, user, vault, base)
        repository = Repository(database, vault, session, base)
        assertEquals(325001L, json.decodeFromString<Expense>(repository.dao.expense(expense.id)!!.payload).amount_minor)
        assertEquals("draft", repository.dao.expense(draft.id)!!.state)
        assertEquals(1, repository.dao.pending().size)
        val records = repository.dao.observeExpenses().first().filter { it.state != "draft" && !it.voided }.map { json.decodeFromString<Expense>(it.payload) }
        assertEquals(325001, totals(records, project.budget_minor).total)
        val dbfile = java.io.File(requireNotNull(database.openHelper.writableDatabase.path))
        database.close()
        assertFalse(String(dbfile.inputStream().use { input -> ByteArray(16).also { input.read(it) } }).startsWith("SQLite format 3"))
        context.deleteDatabase(dbfile.name)
    }
    @Test fun viewersCannotWriteOffline(): Unit = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val vault = Vault(context); val user = newId(); val id = newId(); val base = "https://ledger-test.example"
        val database = LedgerDatabase.open(context, user, vault, base)
        val repository = Repository(database, vault, Session("test", user, "viewer", false, Instant.now().plusSeconds(3600).toString()), base)
        repository.dao.saveProject(LocalProject(id, json.encodeToString(ProjectData(id,"Private project",0,constructionCategories,role="viewer"))))
        try {
            repository.saveExpense(Expense(project_id=id,amount_minor=1,category="Cement",description="Unauthorized",expense_date="2026-10-12"),false)
            fail("Viewer write should fail")
        } catch (_: IllegalArgumentException) { }
        assertEquals(0, repository.dao.queue().size)
        val name=java.io.File(requireNotNull(database.openHelper.writableDatabase.path)).name
        database.close(); context.deleteDatabase(name)
    }
}
