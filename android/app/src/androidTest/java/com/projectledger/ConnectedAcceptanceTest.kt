package com.projectledger

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.flow.first
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ConnectedAcceptanceTest {
    @Test fun privateNetworkFinancialLifecycle(): Unit = runBlocking {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val arguments = InstrumentationRegistry.getArguments()
        val base = arguments.getString("ledgerBase")
        assumeTrue("Pass a private synthetic test backend via instrumentation arguments", base != null)
        fun progress(message: String) {
            instrumentation.sendStatus(0, android.os.Bundle().apply { putString(android.app.Instrumentation.REPORT_KEY_STREAMRESULT, "\nSTEP: $message\n") })
        }
        suspend fun synchronize(repository: Repository) {
            repeat(3) { attempt ->
                try { repository.sync(); return } catch (e: java.io.IOException) {
                    progress("Network interrupted (${e.javaClass.simpleName}); durable queue retained; retry ${attempt + 1}")
                    if (attempt == 2) throw e
                    kotlinx.coroutines.delay(500)
                }
            }
        }
        val context = instrumentation.targetContext
        val awake = ActivityScenario.launch(VerificationActivity::class.java)
        check(!(context.getSystemService(android.content.Context.KEYGUARD_SERVICE) as android.app.KeyguardManager).isDeviceLocked) { "Unlock the test phone before running verification" }
        val vault = Vault(context)
        val session = json.decodeFromString<Session>(Api(base!!, "").request("/auth/login", "POST", json.encodeToString(LoginBody(arguments.getString("ledgerUsername")!!, arguments.getString("ledgerPassword")!!))))
        val databases = mutableListOf<LedgerDatabase>()
        fun repository(s: Session): Repository {
            val database = LedgerDatabase.open(context, s.user_id, vault, base)
            databases.add(database); return Repository(database, vault, s, base)
        }
        val first = repository(session)
        val project = ProjectData(newId(), "Android acceptance ${newId().take(8)}", 100000000, constructionCategories)
        try {
            progress("Create project and synchronize offline project queue")
            first.saveProject(project); synchronize(first)
            val expense = Expense(project_id=project.id,amount_minor=300000,category="Transportation",description="Cement delivery from Chennai",expense_date="2026-10-12",vendor="Transport contractor")
            // These writes are offline code paths: no request is made until sync().
            first.saveExpense(expense,false); first.saveExpense(expense.copy(amount_minor=325001),false)
            first.saveExpense(expense.copy(id=newId(),description="Unconfirmed draft"),true)
            first.queueAI(project.id,"Paid Rajesh ₹15,000 for electrical work yesterday.")
            assertEquals(2,first.dao.queue().size)
            assertEquals(325001L,totals(first.dao.observeExpenses().first().filter { it.state!="draft" }.map { json.decodeFromString<Expense>(it.payload) },project.budget_minor).total)
            synchronize(first)
            assertTrue(first.dao.queue().isEmpty())
            progress("Manual offline edits synchronized; deferred AI proposal received")
            val pending = first.dao.observeAI().first().single()
            assertEquals("review",pending.state)
            val proposal=json.decodeFromString<Interpretation>(pending.result!!).proposals.single()
            assertEquals(1500000L,proposal.amount_minor)
            // Explicit confirmation simulates the reviewed UI action; sync itself never does this.
            val reviewed=Expense(project_id=project.id,amount_minor=proposal.amount_minor!!,category="Electrical",description=proposal.description,expense_date=proposal.expense_date!!,vendor="Rajesh",kind=proposal.kind,source_proposal_id=proposal.id)
            first.saveExpense(reviewed,false,pending.id);synchronize(first)
            assertEquals("confirmed",first.dao.ai(pending.id)!!.state)
            progress("Explicit AI confirmation synchronized")
            val inspect=json.parseToJsonElement(first.api.upload(instrumentation.context.assets.open("empty-workbook.xlsx").use { it.readBytes() })).jsonObject
            val mapping=buildJsonObject {
                put("upload_id",inspect["upload_id"]!!);put("sheet","Expenses");put("header_row",1);put("import_rows",false)
                put("columns",buildJsonObject { put("expense_date","A");put("category","B");put("amount_minor","C");put("description","D");put("vendor","E");put("payment_method","F");put("kind","G") })
            }
            first.api.request("/projects/${project.id}/workbook/link","POST",mapping.toString())
            var workbookSynced=false
            repeat(20) {
                val pulled=json.decodeFromString<Pull>(first.api.request("/sync/pull"))
                if (pulled.workbooks.any { it.project_id==project.id && it.status=="synced" }) workbookSynced=true
                if (!workbookSynced) Thread.sleep(100)
            }
            assertTrue("Workbook job should publish",workbookSynced)
            progress("Workbook linked and publication verified")
            fun provision(name:String): Pair<String,String> {
                val password=newId()+newId()
                val body=buildJsonObject { put("username",name);put("password",password) }
                val result=json.parseToJsonElement(first.api.request("/users","POST",body.toString())).jsonObject
                return result["id"]!!.jsonPrimitive.content to password
            }
            val editorName="editor-${newId().take(8)}"; val (editorId,editorPassword)=provision(editorName)
            val membership=buildJsonObject { put("user_id",editorId);put("role","editor") }
            first.api.request("/projects/${project.id}/members","PUT",membership.toString())
            val secondSession=json.decodeFromString<Session>(Api(base,"").request("/auth/login","POST",json.encodeToString(LoginBody(editorName,editorPassword))))
            val second=repository(secondSession);synchronize(second)
            progress("Second user authenticated; begin concurrent offline edits")
            first.saveExpense(expense.copy(amount_minor=330001),false)
            second.saveExpense(expense.copy(amount_minor=340001),false)
            synchronize(first);synchronize(second)
            assertTrue(second.dao.queue().single().conflict!!.contains("version_conflict"))
            second.resolveConflict(expense.id,true);synchronize(second);synchronize(first)
            assertEquals(340001L,json.decodeFromString<Expense>(first.dao.expense(expense.id)!!.payload).amount_minor)
            progress("Conflict detected, reviewed, and resolved without losing edits")
            val labour=Expense(project_id=project.id,amount_minor=750000,category="Labour",description="Additional site labour",expense_date="2026-10-12",vendor="Rajesh")
            second.saveExpense(labour,false);synchronize(second);synchronize(first)
            val summary=json.parseToJsonElement(first.api.request("/projects/${project.id}/analytics")).jsonObject
            assertEquals(2590001L,summary["total_minor"]!!.jsonPrimitive.long)
            assertEquals(3,summary["source_ids"]!!.jsonArray.size)
            progress("Independent second-user expense retained; exact total verified")
            val viewerName="viewer-${newId().take(8)}";val (viewerId,viewerPassword)=provision(viewerName)
            first.api.request("/projects/${project.id}/members","PUT",buildJsonObject { put("user_id",viewerId);put("role","viewer") }.toString())
            val viewerSession=json.decodeFromString<Session>(Api(base,"").request("/auth/login","POST",json.encodeToString(LoginBody(viewerName,viewerPassword))))
            val viewer=repository(viewerSession);synchronize(viewer)
            try { viewer.saveExpense(labour.copy(id=newId()),false);fail("Viewer must not write offline") } catch (_:IllegalArgumentException) { }
            second.saveExpense(labour.copy(id=newId(),description="Pending before revocation",amount_minor=100),false)
            first.api.request("/users/$editorId/revoke","POST")
            try { synchronize(second);fail("Revoked account must not synchronize") } catch (e:ApiError) { assertEquals(401,e.status) }
            assertEquals(1,second.dao.queue().size)
            progress("Viewer denied offline write; revoked editor denied sync with queue preserved")
            first.saveExpense(labour.copy(id=newId(),amount_minor=100000,description="Labour refund",kind="refund"),false);synchronize(first)
            assertEquals(2490001L,json.parseToJsonElement(first.api.request("/projects/${project.id}/analytics")).jsonObject["total_minor"]!!.jsonPrimitive.long)
            first.voidExpense(labour.id,"Synthetic acceptance reversal");synchronize(first)
            assertEquals(1740001L,json.parseToJsonElement(first.api.request("/projects/${project.id}/analytics")).jsonObject["total_minor"]!!.jsonPrimitive.long)
            progress("Refund and audited reversal totals verified")
            val query=buildJsonObject { put("text","How much did we spend on Transportation?");put("reference_date","2026-10-12") }
            val answer=json.parseToJsonElement(first.api.request("/projects/${project.id}/ai/question","POST",query.toString())).jsonObject
            progress("Deterministic financial question answered from source records")
            assertEquals(340001L,answer["calculation"]!!.jsonObject["total_minor"]!!.jsonPrimitive.long)
        } finally {
            databases.forEach { db -> val name=java.io.File(requireNotNull(db.openHelper.writableDatabase.path)).name; db.close();context.deleteDatabase(name) }
            awake.close()
        }
    }
}
