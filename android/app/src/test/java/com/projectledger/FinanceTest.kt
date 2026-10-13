package com.projectledger
import org.junit.Assert.*
import org.junit.Test
class FinanceTest {
    @Test fun indianMoney() { assertEquals(300000, parseMoney("₹3,000")); assertEquals(15000000, parseMoney("1.5 lakh")); assertEquals(1, parseMoney("0.01")) }
    @Test fun rejectsRounding() { assertThrows(ArithmeticException::class.java) { parseMoney("0.001") } }
    @Test fun rejectsOverflow() { assertThrows(Exception::class.java) { parseMoney("100000000000000000000") } }
    @Test fun refundCategoryMonthBudget() {
        val expense = Expense(project_id="p",amount_minor=100001,category="Electrical",description="Wiring",expense_date="2026-09-01",vendor="Rajesh")
        val refund = expense.copy(id=newId(),amount_minor=1,kind="refund")
        val totals=totals(listOf(expense,refund),200000)
        assertEquals(100000,totals.total); assertEquals(100000L,totals.remaining)
        assertEquals(100000L,totals.categories["Electrical"]); assertEquals(100000L,totals.months["2026-09"])
    }
    @Test fun unbudgetedProjectKeepsSpendingWithoutRemainingBudget() {
        val expense = Expense(project_id="p", amount_minor=12501, category="New category", description="Site security", expense_date="2026-10-13")
        val result = totals(listOf(expense), null)
        assertEquals(12501L, result.total); assertNull(result.remaining)
    }
}
