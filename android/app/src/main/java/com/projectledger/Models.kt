package com.projectledger

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.math.BigDecimal
import java.time.LocalDate
import java.util.UUID

val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }
fun newId() = UUID.randomUUID().toString()
const val MAX_MONEY = 1_000_000_000_000_000L
fun parseMoney(raw: String): Long {
    var value = raw.trim().lowercase().replace("₹", "").replace("inr", "").replace(",", "").trim()
    var multiplier = BigDecimal.ONE
    listOf("crore" to 10000000, "lakh" to 100000, "lac" to 100000).firstOrNull { value.endsWith(it.first) }?.let {
        value = value.removeSuffix(it.first).trim(); multiplier = BigDecimal(it.second)
    }
    val minor = BigDecimal(value).multiply(multiplier).movePointRight(2).longValueExact()
    require(minor in 1..MAX_MONEY) { "Enter a positive amount with at most two decimal places" }
    return minor
}
fun money(value: Long): String = "₹" + java.text.DecimalFormat("#,##0.00").format(BigDecimal.valueOf(value, 2))

@Serializable data class Expense(
    val id: String = newId(), val project_id: String, val amount_minor: Long, val currency: String = "INR",
    val category: String, val description: String, val expense_date: String, val vendor: String = "",
    val payment_method: String = "unknown", val kind: String = "expense", val source_proposal_id: String? = null
)
@Serializable data class ServerExpense(
    val id: String, val project_id: String, val amount_minor: Long, val currency: String = "INR",
    val category: String, val description: String, val expense_date: String, val vendor: String = "",
    val payment_method: String = "unknown", val kind: String = "expense", val source_proposal_id: String? = null,
    val version: Int, val owner_id: String, val created_at: String, val updated_at: String, val voided: Boolean
) {
    fun expense() = Expense(id, project_id, amount_minor, currency, category, description, expense_date, vendor, payment_method, kind, source_proposal_id)
}
@Serializable data class Mutation(val operation_id: String = newId(), val action: String, val expense: Expense,
    val base_version: Int, val reason: String = "", val allow_duplicate: Boolean = false)
@Serializable data class Acknowledgment(val record: ServerExpense, val revision: Long, val workbook_status: String)
@Serializable data class ProjectData(val id: String, val name: String, val budget_minor: Long?,
    val categories: List<String>, val archived: Boolean = false, val version: Int = 1, val role: String = "administrator")
@Serializable data class WorkbookStatus(val project_id: String, val status: String, val error: String? = null, val version: Int)
@Serializable data class Pull(val epoch: String, val cursor: Long, val has_more: Boolean, val changes: List<ServerExpense>,
    val snapshot: List<ServerExpense>, val projects: List<ProjectData>, val workbooks: List<WorkbookStatus>,
    val synced_at: String, val session_expires_at: String)
@Serializable data class Session(val token: String, val user_id: String, val username: String, val administrator: Boolean, val expires_at: String)
@Serializable data class LoginBody(val username: String, val password: String)
@Serializable data class AIRequest(val id: String, val text: String, val reference_date: String, val timezone: String = "Asia/Kolkata")
@Serializable data class Proposal(val id: String, val amount_minor: Long?, val category: String?, val vendor: String?,
    val description: String, val expense_date: String?, val payment_method: String, val kind: String)
@Serializable data class Interpretation(val proposals: List<Proposal>, val warnings: List<String>, val needs_clarification: Boolean,
    val state: String, val original_text: String, val generated_at: String)

data class Totals(val total: Long, val remaining: Long?, val categories: Map<String, Long>, val months: Map<String, Long>, val vendors: Map<String, Long>)
fun totals(records: List<Expense>, budget: Long?): Totals {
    val categories = mutableMapOf<String, Long>(); val months = mutableMapOf<String, Long>(); val vendors = mutableMapOf<String, Long>()
    var sum = 0L
    records.forEach {
        val amount = if (it.kind == "refund") -it.amount_minor else it.amount_minor
        sum = Math.addExact(sum, amount)
        listOf(categories to it.category, months to it.expense_date.take(7), vendors to it.vendor.ifBlank { "Unknown" }).forEach { (map, key) ->
            map[key] = Math.addExact(map[key] ?: 0L, amount)
        }
    }
    return Totals(sum, budget?.let { Math.subtractExact(it, sum) }, categories, months, vendors)
}
val constructionCategories = listOf("Cement", "Steel", "Sand and aggregates", "Labour", "Transportation", "Electrical", "Plumbing", "Interior design", "Equipment", "Software", "Professional services", "Miscellaneous")
