import pytest
from pathlib import Path
from pydantic import ValidationError

from web.services.schemas import JobApplication, normalize_company_name
from web.services.extraction import parse_job_description

DATA_DIR = Path(__file__).parent / "data"


def test_job_application_schema_valid():
    """Test valid JobApplication creation and property calculation."""
    app = JobApplication(
        company_name="Swiggy Technologies Pvt Ltd",
        role_title="Senior Backend Engineer (SDE-2)",
        primary_tech_stack=["Python", "FastAPI", "PostgreSQL", "python", "Redis"],
        experience_required_yrs=3.5,
        location="Bengaluru, India",
        source_platform="Naukri",
    )
    assert app.company_name == "Swiggy Technologies Pvt Ltd"
    assert app.canonical_company_name == "swiggy"
    # Verify deduplication in tech stack (Python vs python)
    assert len(app.primary_tech_stack) == 4
    assert "FastAPI" in app.primary_tech_stack
    assert app.experience_required_yrs == 3.5


def test_job_application_schema_invalid():
    """Test validation errors for empty role_title or negative experience."""
    with pytest.raises(ValidationError):
        JobApplication(
            company_name="Acme Corp",
            role_title="",  # Must not be empty
            primary_tech_stack=["Python"],
        )

    with pytest.raises(ValidationError):
        JobApplication(
            company_name="Acme Corp",
            role_title="Software Engineer",
            experience_required_yrs=-2.0,  # Must be >= 0.0
        )


def test_normalize_company_name():
    """Verify company name normalization stripping legal entities."""
    test_cases = [
        ("Bundl Technologies Pvt Ltd", "bundl"),
        ("Zomato Media Private Limited", "zomato"),
        ("PhonePe India Tech Solutions Pvt. Ltd.", "phonepe"),
        ("Amazon Development Centre (India) Pvt Ltd", "amazon development centre"),
        ("Google Inc.", "google"),
        ("Swiggy", "swiggy"),
    ]
    for raw, expected in test_cases:
        assert normalize_company_name(raw) == expected, f"Failed for {raw}"


def test_parse_job_description_naukri_backend():
    """Test parsing a real Naukri backend JD dump."""
    jd_text = (DATA_DIR / "jd_naukri_backend.txt").read_text(encoding="utf-8")
    app = parse_job_description(jd_text, force_fallback=True)

    assert "bundl" in app.canonical_company_name or "swiggy" in app.canonical_company_name
    assert "Backend" in app.role_title
    assert app.source_platform == "Naukri"
    assert app.experience_required_yrs == 3.0
    assert any(tech in app.primary_tech_stack for tech in ["Python", "FastAPI", "PostgreSQL", "Kafka", "Redis"])


def test_parse_job_description_naukri_ai():
    """Test parsing a real Naukri AI systems JD dump."""
    jd_text = (DATA_DIR / "jd_naukri_ai.txt").read_text(encoding="utf-8")
    app = parse_job_description(jd_text, force_fallback=True)

    assert app.canonical_company_name == "zomato"
    assert "AI Systems Engineer" in app.role_title
    assert app.source_platform == "Naukri"
    assert app.experience_required_yrs == 2.0
    assert any(tech in app.primary_tech_stack for tech in ["pgvector", "LangGraph", "FastAPI", "PostgreSQL"])


def test_parse_job_description_linkedin_fullstack():
    """Test parsing a real LinkedIn full stack JD dump."""
    jd_text = (DATA_DIR / "jd_linkedin_fullstack.txt").read_text(encoding="utf-8")
    app = parse_job_description(jd_text, force_fallback=True)

    assert app.canonical_company_name == "phonepe"
    assert "Full Stack" in app.role_title
    assert app.source_platform == "LinkedIn"
    assert app.experience_required_yrs is not None
    assert any(tech in app.primary_tech_stack for tech in ["Python", "FastAPI", "TypeScript", "PostgreSQL", "Docker"])


def test_parse_empty_text_raises_value_error():
    """Assert empty or whitespace JD text raises ValueError."""
    with pytest.raises(ValueError):
        parse_job_description("")
    with pytest.raises(ValueError):
        parse_job_description("   \n\t  ")
