import re
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


def normalize_company_name(name: str) -> str:
    """
    Normalize company names for entity resolution and deduplication.
    Strips legal suffixes, punctuation, and common generic qualifiers.
    Example: 'Bundl Technologies Pvt Ltd' -> 'bundl'
             'Zomato Media Private Limited' -> 'zomato'
             'Swiggy' -> 'swiggy'
    """
    if not name:
        return ""
    
    # Lowercase and clean whitespace
    normalized = name.lower().strip()
    
    # Remove content in parentheses e.g. "Google (Alphabet)" -> "Google"
    normalized = re.sub(r"\(.*?\)", "", normalized).strip()

    # Normalize punctuation and dots to space first: e.g. "Pvt. Ltd." -> "pvt ltd"
    normalized = re.sub(r"[,\.\-_/]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    # Common legal and corporate qualifiers
    suffixes = [
        "private limited", "pvt ltd", "pvt", "ltd",
        "technologies", "technology", "tech", "solutions", "services",
        "media", "corporation", "corp", "incorporated", "inc",
        "enterprises", "group", "holdings", "india", "global", "labs"
    ]
    
    # Sort suffixes by length descending so longer phrases match first
    suffixes.sort(key=len, reverse=True)
    
    for suffix in suffixes:
        pattern = rf"\b{re.escape(suffix)}\b"
        normalized = re.sub(pattern, "", normalized).strip()
    
    # Clean up residual multiple spaces
    normalized = re.sub(r"\s+", " ", normalized).strip()
    
    return normalized or name.lower().strip()


class JobApplication(BaseModel):
    """
    Pydantic schema for structured job application data extracted from raw JDs.
    Enforces clean schema compliance for the applications database table.
    """
    company_name: str = Field(
        ...,
        description="The recognizable brand or hiring company name (e.g., 'Swiggy', 'Zomato', 'Microsoft'). Do not include legal entity suffixes like 'Pvt Ltd' unless it is integral to the brand name.",
        min_length=1,
    )
    role_title: str = Field(
        ...,
        description="The explicit job title (e.g., 'Senior Backend Engineer', 'SDE-1', 'AI Systems Engineer'). Must NOT be inferred or generic if not explicitly named.",
        min_length=2,
    )
    primary_tech_stack: List[str] = Field(
        default_factory=list,
        description="List of primary programming languages, frameworks, databases, and key technologies mentioned in requirements (e.g., ['Python', 'PostgreSQL', 'Redis', 'Kafka', 'Docker']).",
    )
    experience_required_yrs: Optional[float] = Field(
        default=None,
        description="Minimum years of professional experience required as a decimal number (e.g., 2.0, 3.5, 5.0). Null if not specified or for freshers.",
        ge=0.0,
        le=30.0,
    )
    location: Optional[str] = Field(
        default=None,
        description="Job location or work model (e.g., 'Bengaluru, India', 'Remote', 'Hybrid - Pune').",
    )
    source_platform: str = Field(
        default="Direct",
        description="Source platform identified from text, headers, or links: 'Naukri', 'LinkedIn', 'Indeed', 'Wellfound', or 'Direct'.",
    )

    @property
    def canonical_company_name(self) -> str:
        """Helper property returning the normalized company deduplication key."""
        return normalize_company_name(self.company_name)

    @field_validator("primary_tech_stack", mode="before")
    @classmethod
    def clean_tech_stack(cls, v):
        if isinstance(v, list):
            # Clean and deduplicate while preserving order
            cleaned = []
            seen = set()
            for item in v:
                if isinstance(item, str):
                    s = item.strip()
                    if s and s.lower() not in seen:
                        seen.add(s.lower())
                        cleaned.append(s)
            return cleaned
        return v or []

    @field_validator("company_name")
    @classmethod
    def validate_company_name(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
            forbidden = {
                "direct", "unknown", "n/a", "none", "not specified", "unspecified",
                "not provided", "not mentioned", "employer", "company", "confidential",
                "hiring company", "direct employer"
            }
            if not v or v.lower() in forbidden or v.lower().startswith("not "):
                raise ValueError(f"'{v}' is not a valid company name. The company name must be explicitly stated in the text.")
        return v

    @field_validator("role_title")
    @classmethod
    def validate_role_title(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
            forbidden = {"unknown", "n/a", "none", "not specified", "unspecified", "role", "job"}
            if not v or v.lower() in forbidden:
                raise ValueError(f"'{v}' is not a valid role title. The role title must be explicitly stated in the text.")
        return v


class ExtractionResult(BaseModel):
    """
    Structured outcome of the extraction pipeline with circuit breaker status.
    Guarantees callers receive a typed result without unhandled exceptions.
    """
    success: bool
    data: Optional[JobApplication] = None
    error: Optional[str] = None
    retry_count: int = 0
    circuit_broken: bool = False


class JobEvent(BaseModel):
    """
    Structured career pipeline event parsed from candidate-pasted status update text.
    """
    event_type: str = Field(
        ...,
        description="Type of pipeline event: OA_RECEIVED, INTERVIEW_INVITE, OFFER, REJECTED, APPLICATION_RECEIVED, or STATUS_UPDATE."
    )
    detected_deadline: Optional[str] = Field(
        default=None,
        description="ISO 8601 formatted date/time string if a deadline or event time is detected."
    )
    confidence: str = Field(
        default="HIGH",
        description="Confidence level of classification ('HIGH', 'MEDIUM', 'LOW')."
    )
    notes: Optional[str] = Field(
        default=None,
        description="Summary or details extracted from update text."
    )


