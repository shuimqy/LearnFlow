from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Explanation = Annotated[str, Field(min_length=1, max_length=1000)]


class ReviewEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_key: str = Field(min_length=1, max_length=40)
    observation: str = Field(min_length=1, max_length=1000)


class ProposalReview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    verdict: Literal["approve", "revise", "reject", "needs_evidence"]
    basis: Literal["source", "reasoning", "insufficient"]
    opinion: str = Field(min_length=1, max_length=5000)
    reasons: list[Explanation] = Field(min_length=1, max_length=12)
    changes: list[Explanation] = Field(max_length=12)
    warnings: list[Explanation] = Field(max_length=12)
    evidence: list[ReviewEvidence] = Field(max_length=12)
    title: str = Field(max_length=200)
    summary: str = Field(max_length=2000)
    content: str = Field(max_length=100000)

    @model_validator(mode="after")
    def applicable_content(self):
        if self.verdict in {"approve", "revise"} and (
            not self.title.strip() or not self.content.strip() or self.basis == "insufficient"
        ):
            raise ValueError("An applicable revision needs content and a stated basis")
        if self.basis == "source" and not self.evidence:
            raise ValueError("Source-based opinions require evidence")
        return self
