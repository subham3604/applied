import logging
import os
import re
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

from web.services.schemas import JobApplication

logger = logging.getLogger("extraction_service")

EXTRACTION_SYSTEM_PROMPT = """You are an expert ATS (Applicant Tracking System) extraction engine.
Your task is to analyze unstructured job description text pasted from job portals (such as Naukri, LinkedIn, Indeed, or career pages) and extract structured fields conforming strictly to the schema.

STRICT EXTRACTION RULES:
1. company_name: Extract the primary recognizable brand or company name (e.g., 'Swiggy' instead of 'Bundl Technologies Pvt Ltd (Swiggy)', 'Zomato' instead of 'Zomato Media Private Limited'). Remove corporate suffixes like 'Pvt Ltd', 'Inc', 'Solutions'.
2. role_title: Extract the exact, explicit job title stated in the text (e.g. 'Senior Software Development Engineer - Backend (SDE-2)', 'AI Systems Engineer (LLMs & RAG)'). Do NOT hallucinate, infer, or summarize into generic titles.
3. primary_tech_stack: Extract core programming languages, frameworks, databases, and technologies explicitly mentioned in requirements or description (e.g., ['Python', 'PostgreSQL', 'Redis', 'Kafka', 'Docker']). Keep items concise.
4. experience_required_yrs: Extract the minimum required years of experience as a decimal number (e.g., '3+ years' -> 3.0, '3 - 6 years' -> 3.0, '2.0 Years' -> 2.0). Return null if unspecified.
5. location: Extract the city, country, or work model (e.g., 'Bengaluru (Hybrid)', 'Gurugram', 'Remote').
6. source_platform: Identify the source platform from text clues: 'Naukri', 'LinkedIn', 'Indeed', 'Wellfound', or 'Direct'.
"""


def _heuristic_fallback_parse(raw_text: str) -> JobApplication:
    """
    Deterministic rule-based extractor used when OpenAI API key is unavailable,
    allowing offline unit testing and development without network dependencies.
    """
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    
    # 1. Company extraction
    company = "Unknown Company"
    company_match = re.search(r"(?:Company|Organization|Employer)\s*:\s*([^\n\(\-]+)", raw_text, re.IGNORECASE)
    if company_match:
        company = company_match.group(1).strip()
    else:
        # Check for parenthetical brand: "Bundl Technologies Pvt Ltd (Swiggy)"
        brand_match = re.search(r"\(([A-Za-z0-9\s]+)\)", raw_text[:250])
        if brand_match and len(brand_match.group(1)) > 2:
            company = brand_match.group(1).strip()
        elif lines:
            for l in lines[:5]:
                if any(k in l.lower() for k in ["swiggy", "zomato", "phonepe", "amazon", "google", "microsoft"]):
                    for w in ["Swiggy", "Zomato", "PhonePe", "Amazon", "Google", "Microsoft"]:
                        if w.lower() in l.lower():
                            company = w
                            break

    # Clean legal suffixes
    company = re.sub(r"\b(Pvt Ltd|Private Limited|Ltd|Inc|Solutions|Technologies|India)\b", "", company, flags=re.IGNORECASE).strip()
    company = re.sub(r"\s+", " ", company).strip()

    # 2. Role title extraction
    role = "Software Engineer"
    role_match = re.search(r"(?:Role|Designation|Job Title|Position)\s*:\s*([^\n]+)", raw_text, re.IGNORECASE)
    if role_match:
        role = role_match.group(1).strip()
    else:
        for l in lines[:6]:
            if any(k in l.lower() for k in ["engineer", "developer", "architect", "lead"]):
                role = l.strip()
                break

    # 3. Experience extraction
    experience = None
    exp_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:\+|-\s*\d+)?\s*(?:years?|yrs?)", raw_text, re.IGNORECASE)
    if exp_match:
        try:
            experience = float(exp_match.group(1))
        except ValueError:
            pass

    # 4. Tech stack extraction
    common_tech = [
        "Python", "FastAPI", "Django", "Go", "Golang", "Java", "Node.js", "TypeScript", "JavaScript",
        "PostgreSQL", "MySQL", "Redis", "Kafka", "RabbitMQ", "MongoDB", "Elasticsearch",
        "Docker", "Kubernetes", "AWS", "GCP", "pgvector", "LangGraph", "LangChain",
        "Instructor", "Pydantic", "SQLAlchemy", "Alembic", "Streamlit", "React", "Linux"
    ]
    detected_tech = []
    for tech in common_tech:
        pattern = rf"\b{re.escape(tech)}\b"
        if re.search(pattern, raw_text, re.IGNORECASE):
            detected_tech.append(tech)

    # 5. Location extraction
    location = None
    loc_match = re.search(r"(?:Location|Work Location)\s*:\s*([^\n]+)", raw_text, re.IGNORECASE)
    if loc_match:
        location = loc_match.group(1).strip()
    else:
        for loc in ["Bengaluru", "Bangalore", "Gurugram", "Gurgaon", "Pune", "Hyderabad", "Mumbai", "Remote"]:
            if loc.lower() in raw_text.lower():
                location = loc
                break

    # 6. Source platform extraction
    platform = "Direct"
    lower_text = raw_text.lower()
    if "naukri" in lower_text:
        platform = "Naukri"
    elif "linkedin" in lower_text:
        platform = "LinkedIn"
    elif "indeed" in lower_text:
        platform = "Indeed"
    elif "wellfound" in lower_text or "angel" in lower_text:
        platform = "Wellfound"

    return JobApplication(
        company_name=company or "Direct Employer",
        role_title=role,
        primary_tech_stack=detected_tech,
        experience_required_yrs=experience,
        location=location,
        source_platform=platform,
    )


def get_instructor_client(api_key: Optional[str] = None):
    """Factory creating an Instructor-patched OpenAI client."""
    import instructor
    from openai import OpenAI

    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key or key == "sk-proj-placeholder":
        return None

    raw_client = OpenAI(api_key=key)
    return instructor.from_openai(raw_client)


def parse_job_description(
    raw_text: str,
    client: Optional[Any] = None,
    model: str = "gpt-4o-mini",
    force_fallback: bool = False,
) -> JobApplication:
    """
    Parse unstructured job description text into a structured JobApplication object.
    
    Args:
        raw_text: Unstructured raw text dump from any job portal.
        client: Optional pre-configured Instructor client.
        model: LLM model identifier (defaults to 'gpt-4o-mini').
        force_fallback: If True, forces heuristic parser (useful for offline tests).
    
    Returns:
        Validated JobApplication Pydantic v2 instance.
    """
    if not raw_text or not raw_text.strip():
        raise ValueError("Job description text cannot be empty.")

    if force_fallback:
        return _heuristic_fallback_parse(raw_text)

    # Initialize client if not injected
    if client is None:
        client = get_instructor_client()

    # If no live API client is available, gracefully use heuristic fallback
    if client is None:
        logger.info("OpenAI API key not configured or offline mode; using heuristic extractor.")
        return _heuristic_fallback_parse(raw_text)

    try:
        extracted: JobApplication = client.chat.completions.create(
            model=model,
            response_model=JobApplication,
            temperature=0.0,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": raw_text},
            ],
        )
        return extracted
    except Exception as exc:
        logger.warning("LLM extraction failed (%s). Falling back to heuristic extractor.", exc)
        return _heuristic_fallback_parse(raw_text)
