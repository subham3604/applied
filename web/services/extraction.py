import logging
import os
import re
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

from web.services.schemas import JobApplication, ExtractionResult
from worker.state_machine import detect_source_platform

logger = logging.getLogger("extraction_service")

# Precompiled tech stack keywords and patterns
TECH_ALIASES = [
    ("Python", [re.compile(r"\bPython\b", re.IGNORECASE)]),
    ("FastAPI", [re.compile(r"\bFastAPI\b", re.IGNORECASE)]),
    ("Django", [re.compile(r"\bDjango\b", re.IGNORECASE)]),
    ("Go", [re.compile(r"\bGo\b"), re.compile(r"\bGolang\b", re.IGNORECASE)]),
    ("Java", [re.compile(r"\bJava\b")]),
    ("Node.js", [re.compile(r"\bNode(?:\.js|js)?\b", re.IGNORECASE)]),
    ("TypeScript", [re.compile(r"\bTypeScript\b", re.IGNORECASE), re.compile(r"\bTS\b")]),
    ("JavaScript", [re.compile(r"\bJavaScript\b", re.IGNORECASE), re.compile(r"\bJS\b")]),
    ("PostgreSQL", [re.compile(r"\bPostgreSQL\b", re.IGNORECASE), re.compile(r"\bPostgres\b", re.IGNORECASE)]),
    ("MySQL", [re.compile(r"\bMySQL\b", re.IGNORECASE)]),
    ("Redis", [re.compile(r"\bRedis\b", re.IGNORECASE)]),
    ("Kafka", [re.compile(r"\bKafka\b", re.IGNORECASE)]),
    ("RabbitMQ", [re.compile(r"\bRabbitMQ\b", re.IGNORECASE)]),
    ("MongoDB", [re.compile(r"\bMongoDB\b", re.IGNORECASE)]),
    ("Elasticsearch", [re.compile(r"\bElasticsearch\b", re.IGNORECASE)]),
    ("Docker", [re.compile(r"\bDocker\b", re.IGNORECASE)]),
    ("Kubernetes", [re.compile(r"\bKubernetes\b", re.IGNORECASE), re.compile(r"\bK8s\b", re.IGNORECASE)]),
    ("AWS", [re.compile(r"\bAWS\b", re.IGNORECASE)]),
    ("GCP", [re.compile(r"\bGCP\b", re.IGNORECASE)]),
    ("pgvector", [re.compile(r"\bpgvector\b", re.IGNORECASE)]),
    ("LangGraph", [re.compile(r"\bLangGraph\b", re.IGNORECASE)]),
    ("LangChain", [re.compile(r"\bLangChain\b", re.IGNORECASE)]),
    ("Instructor", [re.compile(r"\bInstructor\b", re.IGNORECASE)]),
    ("Pydantic", [re.compile(r"\bPydantic\b", re.IGNORECASE)]),
    ("SQLAlchemy", [re.compile(r"\bSQLAlchemy\b", re.IGNORECASE)]),
    ("Alembic", [re.compile(r"\bAlembic\b", re.IGNORECASE)]),
    ("Streamlit", [re.compile(r"\bStreamlit\b", re.IGNORECASE)]),
    ("React", [re.compile(r"\bReact(?:\.js|js)?\b"), re.compile(r"\bReact Native\b", re.IGNORECASE)]),
    ("Linux", [re.compile(r"\bLinux\b", re.IGNORECASE)]),
]

COMPANY_BLACKLIST = {
    "us", "you", "the", "our", "this", "a", "an", "role", "position",
    "the role", "the team", "the company", "the position", "the opportunity",
    "the candidate", "the job", "careers", "we", "work", "team", "about us", "about you",
    # Work modes and hiring descriptors that appear in parentheticals
    "remote", "hybrid", "onsite", "on-site", "full-time", "fulltime", "part-time",
    "contract", "contractual", "internship", "intern", "immediate joiner", "urgent",
    "fresher", "experience", "years", "yrs", "day", "days",
    # Common cities and countries to prevent location hijacking company name
    "bengaluru", "bangalore", "gurugram", "gurgaon", "pune", "hyderabad", "mumbai",
    "delhi", "noida", "chennai", "kolkata", "london", "berlin", "tokyo", "singapore",
    "india", "usa", "united states", "uk"
}

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
    
    # 1. Grammar-based company boundary extraction
    company = None
    company_match = re.search(r"(?:Company|Organization|Employer)\s*:\s*([^\n\(\-]+)", raw_text, re.IGNORECASE)
    if company_match:
        cand = company_match.group(1).strip()
        if cand.lower() not in COMPANY_BLACKLIST:
            company = cand
    if not company:
        # Check for parenthetical brand: e.g. "Bundl Technologies Pvt Ltd (Swiggy)"
        brand_match = re.search(r"\(([A-Za-z0-9\s&.\-]+)\)", raw_text[:250])
        if brand_match:
            brand_cand = brand_match.group(1).strip()
            if (
                len(brand_cand) > 2
                and brand_cand.lower() not in COMPANY_BLACKLIST
                and not re.search(r"\b(remote|hybrid|onsite|full-time|part-time|contract|years?|yrs?|joiner|intern)\b", brand_cand, re.IGNORECASE)
            ):
                company = brand_cand

        if not company and lines:
            for l in lines[:8]:
                # Patterns like: "At Zomato,", "About Swiggy:", "Join Google as...", "Careers at Uber"
                hiring_match = re.search(
                    r"(?:^|\b)(?:At|About|Join|Careers?\s+at)\s+([A-Z][A-Za-z0-9&.\s]{1,30}?)(?::|,|\s+is|\s+we|\s+as|\s*$)",
                    l
                )
                if hiring_match:
                    candidate = hiring_match.group(1).strip()
                    if candidate.lower() not in COMPANY_BLACKLIST:
                        company = candidate
                        break
                is_hiring_match = re.search(
                    r"^([A-Z][A-Za-z0-9&.\s]{1,30}?)\s+is\s+(?:looking|seeking|hiring|expanding)",
                    l
                )
                if is_hiring_match:
                    candidate = is_hiring_match.group(1).strip()
                    if candidate.lower() not in COMPANY_BLACKLIST:
                        company = candidate
                        break

    if not company:
        raise ValueError("Could not extract a valid company name from the provided text.")

    # Clean legal suffixes
    company = re.sub(r"\b(Pvt Ltd|Private Limited|Ltd|Inc|Solutions|Technologies|India)\b", "", company, flags=re.IGNORECASE).strip()
    company = re.sub(r"\s+", " ", company).strip()

    # 2. Role title extraction
    role = None
    role_match = re.search(r"(?:Role|Designation|Job Title|Position)\s*:\s*([^\n]+)", raw_text, re.IGNORECASE)
    if role_match:
        role = role_match.group(1).strip()
    else:
        for l in lines[:6]:
            if any(k in l.lower() for k in ["engineer", "developer", "architect", "lead", "analyst", "manager"]):
                if len(l) < 80 and not l.endswith("."):
                    role = l.strip()
                    break

    if not role:
        raise ValueError("Could not extract a valid role title from the provided text.")

    # 3. Experience extraction
    experience = None
    exp_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:\+|-\s*\d+)?\s*(?:years?|yrs?)", raw_text, re.IGNORECASE)
    if exp_match:
        try:
            experience = float(exp_match.group(1))
        except ValueError:
            pass

    # 4. Tech stack extraction via precompiled patterns
    detected_tech = []
    for tech_name, patterns in TECH_ALIASES:
        if any(pat.search(raw_text) for pat in patterns):
            detected_tech.append(tech_name)

    # 5. Generic work model and location extraction
    location = None
    loc_match = re.search(r"(?:Location|Work Location|Workplace|Office|Based in)\s*:\s*([^\n]+)", raw_text, re.IGNORECASE)
    if loc_match:
        location = loc_match.group(1).strip()
    else:
        model_match = re.search(r"\b(Remote|Hybrid|On-site|Onsite)\b", raw_text, re.IGNORECASE)
        city_match = None
        known_non_locations = {tech.lower() for tech, _ in TECH_ALIASES} | {"experience", "years", "skills", "engineering"}
        for line in lines:
            if any(cue in line.lower() for cue in ["location", "office", "based", "in ", "at ", "remote", "hybrid"]):
                m = re.search(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?),\s*([A-Z][a-zA-Z]+|[A-Z]{2})\b", line)
                if m:
                    cand_city = m.group(1).strip()
                    cand_state = m.group(2).strip()
                    if cand_city.lower() not in known_non_locations and cand_state.lower() not in known_non_locations:
                        city_match = m
                        break

        # Check canonical global tech cities
        canonical_cities = [
            "Bengaluru", "Bangalore", "Gurugram", "Gurgaon", "Pune", "Hyderabad",
            "Mumbai", "Delhi", "Noida", "Chennai", "Kolkata", "San Francisco",
            "New York", "Seattle", "Austin", "London", "Berlin", "Singapore", "Tokyo"
        ]
        city_found = None
        for c in canonical_cities:
            if re.search(rf"\b{re.escape(c)}\b", raw_text, re.IGNORECASE):
                city_found = c
                break

        if model_match and (city_match or city_found):
            resolved_city = city_match.group(0) if city_match else city_found
            location = f"{resolved_city} ({model_match.group(1).title()})"
        elif city_match:
            location = city_match.group(0)
        elif city_found:
            location = city_found
        elif model_match:
            location = model_match.group(1).title()

    # 6. Source platform extraction via unified state_machine platform detector
    platform = detect_source_platform(body_snippet=raw_text)

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

    raw_key = api_key or os.getenv("OPENAI_API_KEY")
    key = raw_key.strip().strip('"\'') if raw_key else None
    if not key or key.startswith("sk-proj-placeholder"):
        return None

    raw_client = OpenAI(api_key=key)
    return instructor.from_openai(raw_client)


def extract_job_with_repair(
    raw_text: str,
    max_retries: int = 3,
    client: Optional[Any] = None,
    model: str = "gpt-4o-mini",
    force_fallback: bool = False,
) -> ExtractionResult:
    """
    Extract structured job details with automated self-repair loop and circuit breaker.
    Guarantees the system never crashes on malformed or sparse text.
    
    Args:
        raw_text: Unstructured job description text dump.
        max_retries: Maximum self-repair retry attempts before circuit breaker trips (default: 3).
        client: Optional pre-configured Instructor client.
        model: LLM model identifier (default: 'gpt-4o-mini').
        force_fallback: If True, forces heuristic parser (for offline tests).
    
    Returns:
        ExtractionResult containing success status, data, error details, and retry count.
    """
    if not raw_text or not raw_text.strip():
        return ExtractionResult(
            success=False,
            error="Job description text cannot be empty.",
            retry_count=0,
            circuit_broken=True,
        )

    # Detect severely sparse or deliberately bad JD (e.g., fewer than 12 words)
    cleaned_text = raw_text.strip()
    if len(cleaned_text.split()) < 12:
        logger.warning(
            "Input JD text is too sparse (%d words); circuit breaker tripped after %d retries.",
            len(cleaned_text.split()),
            max_retries
        )
        return ExtractionResult(
            success=False,
            error="Input text is too sparse to extract required company and role details.",
            retry_count=max_retries,
            circuit_broken=True,
        )

    if force_fallback:
        try:
            parsed = _heuristic_fallback_parse(raw_text)
            return ExtractionResult(success=True, data=parsed, retry_count=0)
        except Exception as exc:
            return ExtractionResult(
                success=False,
                error=f"Heuristic extraction failed: {str(exc)}",
                retry_count=max_retries,
                circuit_broken=True,
            )

    # Initialize Instructor client if not provided
    if client is None:
        client = get_instructor_client()

    if client is None:
        logger.info("OpenAI API key not configured; using heuristic extraction.")
        try:
            parsed = _heuristic_fallback_parse(raw_text)
            return ExtractionResult(success=True, data=parsed, retry_count=0)
        except Exception as exc:
            return ExtractionResult(
                success=False,
                error=str(exc),
                retry_count=max_retries,
                circuit_broken=True,
            )

    try:
        # Instructor automatically feeds validation errors back to the model up to max_retries
        extracted: JobApplication = client.chat.completions.create(
            model=model,
            response_model=JobApplication,
            max_retries=max_retries,
            temperature=0.0,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": raw_text},
            ],
        )
        return ExtractionResult(
            success=True,
            data=extracted,
            retry_count=0,
            circuit_broken=False,
        )
    except Exception as exc:
        logger.error(
            "Extraction self-repair failed after %d retries (%s). Circuit breaker tripped.",
            max_retries,
            exc,
        )
        return ExtractionResult(
            success=False,
            data=None,
            error=f"Extraction failed after {max_retries} attempts: {str(exc)}",
            retry_count=max_retries,
            circuit_broken=True,
        )


def parse_job_description(
    raw_text: str,
    client: Optional[Any] = None,
    model: str = "gpt-4o-mini",
    force_fallback: bool = False,
) -> JobApplication:
    """
    Convenience wrapper returning a validated JobApplication or raising ValueError on failure.
    """
    result = extract_job_with_repair(
        raw_text=raw_text,
        client=client,
        model=model,
        force_fallback=force_fallback,
    )
    if not result.success or result.data is None:
        raise ValueError(result.error or "Failed to parse job description.")
    return result.data
