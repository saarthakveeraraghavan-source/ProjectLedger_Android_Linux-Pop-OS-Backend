package com.projectledger

import kotlinx.serialization.json.*

/** Human-readable answers; all financial amounts are supplied by deterministic server queries. */
fun formatFinanceAnswer(response: JsonObject, acrossProjects: Boolean): String {
    val plan = response["interpretation"]!!.jsonObject
    val operation = plan["operation"]!!.jsonPrimitive.content
    fun filter(name: String) = plan[name]?.jsonPrimitive?.contentOrNull
    val start = filter("start"); val end = filter("end")
    val period = when {
        start == null && end == null -> "All dates"
        start != null && end != null -> "$start to $end"
        start != null -> "From $start"
        else -> "Through $end"
    }
    val scope = listOf(period, filter("category")?.let { "Category: $it" }, filter("vendor")?.let { "Vendor: $it" }).filterNotNull().joinToString(" • ")
    fun transaction(entry: JsonElement): String {
        val record = entry.jsonObject
        val amount = record["amount_minor"]!!.jsonPrimitive.long * if (record["kind"]?.jsonPrimitive?.content == "refund") -1 else 1
        val vendor = record["vendor"]?.jsonPrimitive?.contentOrNull?.takeIf { it.isNotBlank() }?.let { " • $it" }.orEmpty()
        return "${money(amount)} — ${record["description"]!!.jsonPrimitive.content}\n${record["expense_date"]!!.jsonPrimitive.content} • ${record["category"]!!.jsonPrimitive.content}$vendor"
    }
    fun result(data: JsonObject): String {
        val sources = data[if (operation == "budget") "budget_source_ids" else "source_ids"]?.jsonArray?.size ?: 0
        return when (operation) {
            "budget" -> data["remaining_minor"]?.jsonPrimitive?.longOrNull?.let { "Remaining budget: ${money(it)}" } ?: "No budget is set for this project."
            "largest" -> {
                val largest = data["largest_transactions"]?.jsonArray ?: JsonArray(emptyList())
                if (largest.isEmpty()) "No matching confirmed expenses were found."
                else "Largest expense${if (largest.size > 1) "s (tied)" else ""}:\n" + largest.take(10).joinToString("\n\n") { transaction(it) }
            }
            "transactions" -> {
                val records = data["transactions"]!!.jsonArray
                if (records.isEmpty()) "No matching confirmed transactions were found."
                else records.take(20).joinToString("\n\n") { transaction(it) } + if (records.size > 20) "\nShowing 20 of ${records.size}. Use History to view the rest." else ""
            }
            "categories", "months", "vendors" -> {
                val groups = data[operation]!!.jsonObject
                if (groups.isEmpty()) "No matching confirmed transactions were found."
                else groups.entries.joinToString("\n") { (label, value) -> "$label: ${money(value.jsonPrimitive.long)}" }
            }
            else -> "Recorded expenditure: ${money(data["total_minor"]!!.jsonPrimitive.long)}"
        } + "\nBased on $sources confirmed server transaction${if (sources == 1) "" else "s"}."
    }
    val answer = if (!acrossProjects) result(response["calculation"]!!.jsonObject) else if (operation == "largest") {
        val largest = response["largest_transactions"]!!.jsonArray
        if (largest.isEmpty()) "No matching confirmed expenses were found."
        else "Largest expense across your projects:\n" + largest.take(10).joinToString("\n\n") { entry ->
            val projectId = entry.jsonObject["project_id"]!!.jsonPrimitive.content
            val project = response["projects"]!!.jsonArray.first { it.jsonObject["project_id"]!!.jsonPrimitive.content == projectId }
            "${project.jsonObject["project_name"]!!.jsonPrimitive.content}\n${transaction(entry)}"
        }
    } else {
        val projects = response["projects"]!!.jsonArray
        if (projects.isEmpty()) "No authorized projects are available."
        else projects.joinToString("\n\n") { "${it.jsonObject["project_name"]!!.jsonPrimitive.content}\n${result(it.jsonObject)}" }
    }
    return "$answer\n\n$scope\nCalculated from synchronized server records."
}
