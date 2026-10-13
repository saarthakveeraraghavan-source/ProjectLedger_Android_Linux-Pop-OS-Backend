from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_MONEY = 1_000_000_000_000_000


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def minor_units(value: str) -> int:
    """Exact INR parser; rejects rounding, nonfinite values and negative expenses."""
    value = value.strip().lower().replace("₹", "").replace("inr", "").replace(",", "").strip()
    multiplier = Decimal(1)
    for suffix, scale in (("crore", 10_000_000), ("lakh", 100_000), ("lac", 100_000)):
        if value.endswith(suffix):
            value = value[:-len(suffix)].strip()
            multiplier = Decimal(scale)
            break
    try:
        amount = Decimal(value) * multiplier * 100
        if not amount.is_finite() or amount != amount.to_integral_value() or not 0 < amount <= MAX_MONEY:
            raise ValueError("Amount must be positive with at most two decimal places")
        return int(amount)
    except InvalidOperation as exc:
        raise ValueError("Invalid amount") from exc


class Expense(StrictModel):
    id: UUID
    project_id: UUID
    amount_minor: int = Field(strict=True, gt=0, le=MAX_MONEY)
    currency: Literal["INR"] = "INR"
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2000)
    expense_date: date
    vendor: str = Field(default="", max_length=200)
    payment_method: Literal["unknown", "cash", "upi", "bank", "card", "cheque"] = "unknown"
    kind: Literal["expense", "refund"] = "expense"
    source_proposal_id: UUID | None = None

    @field_validator("category", "description")
    @classmethod
    def nonblank(cls, v):
        if not v.strip():
            raise ValueError("Cannot be blank")
        return v.strip()


class Mutation(StrictModel):
    operation_id: UUID
    action: Literal["create", "update", "void"]
    expense: Expense
    base_version: int = Field(ge=0)
    reason: str = Field(default="", max_length=500)
    allow_duplicate: bool = False


class Login(StrictModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class UserCreate(StrictModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9_.-]{3,80}$")
    password: str = Field(min_length=12, max_length=256)
    administrator: bool = False


class Project(StrictModel):
    operation_id: UUID | None = None
    id: UUID
    name: str = Field(min_length=1, max_length=150)
    budget_minor: int | None = Field(default=None, strict=True, ge=0, le=MAX_MONEY)
    categories: list[str] = Field(default_factory=list, max_length=100)
    archived: bool = False
    base_version: int = Field(default=0, ge=0)

    @field_validator("categories")
    @classmethod
    def valid_categories(cls, v):
        if any(not c.strip() or len(c) > 100 for c in v) or len(set(v)) != len(v):
            raise ValueError("Categories must be unique nonempty names")
        return v


class Membership(StrictModel):
    user_id: UUID
    role: Literal["administrator", "editor", "viewer", "removed"]


class AIRequest(StrictModel):
    id: UUID
    text: str = Field(min_length=1, max_length=4000)
    reference_date: date
    timezone: str = "Asia/Kolkata"


class AIExpense(StrictModel):
    amount: str | None
    category: str | None = Field(max_length=100)
    vendor: str | None
    description: str = Field(min_length=1, max_length=2000)
    expense_date: date | None
    payment_method: Literal["unknown", "cash", "upi", "bank", "card", "cheque"] = "unknown"
    kind: Literal["expense", "refund"]


class Extraction(StrictModel):
    expenses: list[AIExpense] = Field(max_length=20)
    warnings: list[str] = Field(max_length=30)
    needs_clarification: bool


class QueryPlan(StrictModel):
    operation: Literal["total", "categories", "months", "vendors", "budget", "transactions", "largest"]
    category: str | None = None
    vendor: str | None = None
    start: date | None = None
    end: date | None = None

    @model_validator(mode='after')
    def valid_range(self):
        if self.start and self.end and self.start > self.end:
            raise ValueError('Date range is reversed')
        return self


class WorkbookMapping(StrictModel):
    upload_id: UUID
    sheet: str
    header_row: int = Field(ge=1, le=100)
    columns: dict[str, str]
    import_rows: bool = True
