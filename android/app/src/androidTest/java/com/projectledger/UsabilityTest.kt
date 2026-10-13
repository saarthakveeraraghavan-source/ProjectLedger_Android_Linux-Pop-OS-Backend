package com.projectledger

import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.WorkManager
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import kotlinx.serialization.encodeToString
import kotlinx.serialization.decodeFromString
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.time.Instant
import java.util.concurrent.atomic.AtomicReference

@RunWith(AndroidJUnit4::class)
class UsabilityTest {
    private fun node(root: AccessibilityNodeInfo?, predicate: (AccessibilityNodeInfo) -> Boolean): AccessibilityNodeInfo? {
        if (root == null) return null
        if (predicate(root)) return root
        for (index in 0 until root.childCount) node(root.getChild(index), predicate)?.let { return it }
        return null
    }
    private fun click(predicate: (AccessibilityNodeInfo) -> Boolean) {
        val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
        repeat(50) {
            val found = node(automation.rootInActiveWindow, predicate)
            if (found != null) {
                assertEquals("com.projectledger", automation.rootInActiveWindow.packageName.toString())
                val bounds = android.graphics.Rect()
                found.getBoundsInScreen(bounds)
                assertFalse(bounds.isEmpty)
                val now = android.os.SystemClock.uptimeMillis()
                val down = android.view.MotionEvent.obtain(now, now, android.view.MotionEvent.ACTION_DOWN, bounds.exactCenterX(), bounds.exactCenterY(), 0)
                val up = android.view.MotionEvent.obtain(now, now + 60, android.view.MotionEvent.ACTION_UP, bounds.exactCenterX(), bounds.exactCenterY(), 0)
                try { assertTrue(automation.injectInputEvent(down, true)); assertTrue(automation.injectInputEvent(up, true)) }
                finally { down.recycle(); up.recycle() }
                InstrumentationRegistry.getInstrumentation().waitForIdleSync()
                Thread.sleep(250)
                return
            }
            Thread.sleep(100)
        }
        val root = automation.rootInActiveWindow
        fun labels(value: AccessibilityNodeInfo?): List<String> {
            if (value == null || value.packageName?.toString()?.startsWith("com.projectledger") != true) return emptyList()
            return listOfNotNull(value.text?.toString(), value.contentDescription?.toString()) + (0 until value.childCount).flatMap { labels(value.getChild(it)) }
        }
        fail("Calendar control not found; synthetic test labels: ${labels(root)}; foreground package: ${root?.packageName}")
    }
    @Test fun calendarSelectsExpenseDateOnDevice() {
        val chosen = AtomicReference<String>()
        ActivityScenario.launch(VerificationActivity::class.java).use { scenario ->
            scenario.onActivity { activity -> activity.setContent { MaterialTheme { ExpenseDateField("2026-10-13") { chosen.set(it) } } } }
            click { it.contentDescription?.toString()?.contains("Choose expense date") == true }
            click { "${it.text} ${it.contentDescription}".contains("20 October") }
            click { it.text?.toString() == "Select date" && (it.isClickable || it.parent?.isClickable == true) }
            repeat(50) { if (chosen.get() == null) Thread.sleep(100) }
            assertEquals("2026-10-20", chosen.get())
        }
    }
    @Test fun descriptionSaveRequestsImmediateDurableSync(): Unit = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val vault = Vault(context)
        val previousAuto = vault.get("auto_sync")
        vault.put("auto_sync", "true")
        val user = newId(); val id = newId(); val base = "https://ledger-usability-test.example"
        val database = LedgerDatabase.open(context, user, vault, base)
        try {
            val repository = Repository(database, vault, Session("synthetic", user, "fixture", true, Instant.now().plusSeconds(3600).toString()), base)
            repository.dao.saveProject(LocalProject(id, json.encodeToString(ProjectData(id, "No budget", null, emptyList()))))
            val manager = WorkManager.getInstance(context)
            val before = withContext(Dispatchers.IO) { manager.getWorkInfosForUniqueWork("ledger-sync-now").get().map { it.id }.toSet() }
            val requested = async(start = CoroutineStart.UNDISPATCHED) { withTimeout(5000) { repository.syncRequests.first() } }
            repository.queueAI(id, "Paid ₹100 for site security today")
            requested.await()
            val after = withContext(Dispatchers.IO) { manager.getWorkInfosForUniqueWork("ledger-sync-now").get() }
            assertTrue(after.any { it.id !in before })
            assertEquals("Paid ₹100 for site security today", repository.dao.pending().single().text)
            repository.saveExpense(Expense(project_id=id, amount_minor=10000, category="Site security", description="Guard payment", expense_date="2026-10-13"), false)
            assertEquals(10000L, totals(repository.dao.observeExpenses().first().map { json.decodeFromString<Expense>(it.payload) }, null).total)
            assertTrue(json.decodeFromString<ProjectData>(repository.dao.project(id)!!.payload).categories.contains("Site security"))
        } finally {
            val name = java.io.File(requireNotNull(database.openHelper.writableDatabase.path)).name
            database.close(); context.deleteDatabase(name)
            if (previousAuto == null) vault.remove("auto_sync") else vault.put("auto_sync", previousAuto)
        }
    }
}
