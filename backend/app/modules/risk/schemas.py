from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class RiskProfileOut(BaseModel):
    capital_allocation_inr: str
    max_risk_inr: str
    max_quantity: int | None
    max_exposure_inr: str | None
    allowed_products: list[str]


class RiskProfileUpdate(BaseModel):
    capital_allocation_inr: Decimal = Field(gt=0, le=Decimal("100000000"))
    max_risk_inr: Decimal = Field(gt=0, le=Decimal("10000000"))
    max_quantity: int | None = Field(default=None, gt=0, le=1_000_000)
    max_exposure_inr: Decimal | None = Field(default=None, gt=0)
    allowed_products: list[Literal["MIS", "CNC"]] = Field(min_length=1)

    @model_validator(mode="after")
    def risk_stays_within_capital(self) -> "RiskProfileUpdate":
        if self.max_risk_inr > self.capital_allocation_inr:
            raise ValueError("Maximum rupee risk cannot exceed the capital allocated to the trade.")
        if len(set(self.allowed_products)) != len(self.allowed_products):
            raise ValueError("Products must be unique.")
        return self
