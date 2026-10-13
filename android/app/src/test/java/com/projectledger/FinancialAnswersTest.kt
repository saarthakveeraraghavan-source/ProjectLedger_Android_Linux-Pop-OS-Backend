package com.projectledger

import kotlinx.serialization.json.jsonObject
import org.junit.Assert.*
import org.junit.Test

class FinancialAnswersTest {
    private fun response(operation: String, fields: String) = json.parseToJsonElement("""{"interpretation":{"operation":"$operation","category":null,"vendor":null,"start":null,"end":null},"calculation":{"source_ids":["private-record-id"],"budget_source_ids":["private-record-id"],$fields}}""").jsonObject
    @Test fun largestExpenseIsReadableWithoutRawFiltersOrIds() {
        val data = response("largest", """"largest_transactions":[{"amount_minor":20000,"description":"Steel delivery","expense_date":"2026-10-12","category":"Steel","vendor":"Rajesh","kind":"expense"}]""")
        val answer = formatFinanceAnswer(data, false)
        assertTrue(answer.contains("₹200.00 — Steel delivery"))
        assertTrue(answer.contains("2026-10-12 • Steel • Rajesh"))
        assertTrue(answer.contains("All dates"))
        assertFalse(answer.contains("private-record-id")); assertFalse(answer.contains("{"))
    }
    @Test fun noMatchingExpenseHasClearMessage() {
        assertTrue(formatFinanceAnswer(response("largest", """"largest_transactions":[]"""), false).contains("No matching confirmed expenses"))
    }
    @Test fun noBudgetHasNoInventedRemainingAmount() {
        val answer = formatFinanceAnswer(response("budget", """"remaining_minor":null"""), false)
        assertTrue(answer.contains("No budget is set")); assertFalse(answer.contains("₹"))
    }
    @Test fun refundShownAsNegativeTransaction() {
        val answer = formatFinanceAnswer(response("transactions", """"transactions":[{"amount_minor":5000,"description":"Returned cement","expense_date":"2026-10-12","category":"Cement","vendor":"","kind":"refund"}]"""), false)
        assertTrue(answer.contains("₹-50.00"))
    }
    @Test fun validationErrorNamesFieldWithoutEchoingSensitiveInput() {
        val error = ApiError(422, """{"detail":[{"loc":["body","text"],"msg":"String should have at least 1 character","input":"private input"}]}""")
        assertTrue(error.message!!.contains("text:")); assertFalse(error.message!!.contains("private input"))
    }
}
