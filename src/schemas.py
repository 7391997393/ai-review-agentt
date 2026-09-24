from typing import Literal
 
from pydantic import BaseModel, Field
 
 
Severity = Literal["critical", "high", "medium", "low", "info"]
Category = Literal["security", "standards", "tests", "performance"]
 
 
class Finding(BaseModel):
    """One code-review finding produced by the LLM."""
 
    category: Category
    severity: Severity
    file: str
    line: int | None = Field(default=None, ge=1)
    title: str
    description: str
    recommendation: str
    confidence: float = Field(default=0.8, ge=0, le=1)
 
 
class ReviewResult(BaseModel):
    """Validated result of one review stage."""
 
    findings: list[Finding] = Field(default_factory=list)