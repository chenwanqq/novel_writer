"""Shared wire models. Free-form prose retains meaning alongside structured fields."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SourceRef(Model):
    source_id: str
    locator: str
    excerpt: str = ""


class Record(Model):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$", max_length=100)
    kind: Literal["entity", "fact", "event", "relationship", "hypothesis", "inference",
                  "decision", "question", "constraint", "map", "place", "route", "region"]
    nature: Literal["fictional", "reference", "inference", "author_decision"] = "fictional"
    status: Literal["candidate", "accepted", "rejected", "deprecated"] = "candidate"
    name: str = Field(min_length=1)
    text: str = ""
    tags: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    refs: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    supersedes: list[str] = Field(default_factory=list)
    valid_from: float | None = None
    valid_to: float | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def time_range(self):
        if self.valid_from is not None and self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be greater than valid_from; intervals are [from,to)")
        return self


class Change(Model):
    action: Literal["put", "delete"]
    id: str
    record: Record | None = None

    @model_validator(mode="after")
    def matching(self):
        if self.action == "put" and (self.record is None or self.record.id != self.id):
            raise ValueError("put requires a record with the same id")
        if self.action == "delete" and self.record is not None:
            raise ValueError("delete does not accept a record")
        return self
