import math
import pytest
from sqlalchemy.orm import Session

from db.session import SessionLocal
from db.models import MasterExperienceVault
from web.services.rag_engine import (
    embed_text,
    get_relevant_bullets,
    RetrievedBullet,
    EMBEDDING_DIMENSION,
)


@pytest.fixture(scope="module")
def db():
    session = SessionLocal()
    yield session
    session.close()


# ==============================================================================
# Positive Test Cases
# ==============================================================================

def test_embed_text_dimension_and_unit_norm():
    """Verify that embed_text returns a 1536-dim vector with unit L2 norm."""
    text = "Building asynchronous microservices with FastAPI and PostgreSQL"
    vector = embed_text(text)

    assert isinstance(vector, list)
    assert len(vector) == EMBEDDING_DIMENSION

    # Verify L2 norm is 1.0
    l2_norm = math.sqrt(sum(x * x for x in vector))
    assert math.isclose(l2_norm, 1.0, rel_tol=1e-4)


def test_get_relevant_bullets_backend_query(db: Session):
    """Verify that a backend-focused JD retrieves backend-related bullets."""
    jd = "Python, PostgreSQL, Redis, microservices, 2 years"
    bullets = get_relevant_bullets(jd, top_k=5, db=db)

    assert len(bullets) == 5
    assert all(isinstance(b, RetrievedBullet) for b in bullets)

    # Verify top bullets relate to backend engineering
    top_titles = [b.title.lower() for b in bullets[:3]]
    assert any("backend" in t or "task queue" in t or "pipeline" in t for t in top_titles)


def test_get_relevant_bullets_ai_query(db: Session):
    """Verify that an AI / RAG query retrieves AI Systems Engineer bullets."""
    jd = "Experience with LangGraph, pgvector, RAG architectures, and prompt orchestration"
    bullets = get_relevant_bullets(jd, top_k=3, db=db)

    assert len(bullets) >= 1
    # Check that AI/RAG bullet or project is surfaced in top results
    all_text = " ".join(b.bullet_point for b in bullets)
    assert any(k in all_text.lower() for k in ["rag", "langgraph", "vector", "openai", "embeddings"])


def test_get_relevant_bullets_category_filter(db: Session):
    """Verify filtering by category (e.g., 'PROJECT') returns ONLY project bullets."""
    bullets = get_relevant_bullets("system design and pipelines", top_k=4, category="PROJECT", db=db)

    assert len(bullets) >= 1
    for b in bullets:
        assert b.category == "PROJECT"


def test_similarity_score_monotonicity(db: Session):
    """Verify that retrieved bullets are sorted in strictly descending order of similarity."""
    bullets = get_relevant_bullets("FastAPI, PostgreSQL, Redis", top_k=5, db=db)

    for i in range(len(bullets) - 1):
        assert bullets[i].similarity_score >= bullets[i + 1].similarity_score, (
            f"Ordering violation: {bullets[i].similarity_score} < {bullets[i+1].similarity_score}"
        )


def test_configurable_model_support():
    """Verify model parameter accepts text-embedding-3-large configuration."""
    vector_small = embed_text("Hello world", model="text-embedding-3-small")
    vector_large = embed_text("Hello world", model="text-embedding-3-large")

    assert len(vector_small) == 1536
    assert len(vector_large) == 1536


# ==============================================================================
# Negative and Boundary Test Cases
# ==============================================================================

def test_empty_query_raises_value_error(db: Session):
    """Empty string or whitespace-only query must raise ValueError."""
    with pytest.raises(ValueError, match="cannot be empty"):
        get_relevant_bullets("", top_k=5, db=db)

    with pytest.raises(ValueError, match="cannot be empty"):
        get_relevant_bullets("    \n\t  ", top_k=5, db=db)


def test_invalid_top_k_raises_value_error(db: Session):
    """top_k <= 0 must raise ValueError."""
    with pytest.raises(ValueError, match="top_k must be a positive integer"):
        get_relevant_bullets("Python developer", top_k=0, db=db)

    with pytest.raises(ValueError, match="top_k must be a positive integer"):
        get_relevant_bullets("Python developer", top_k=-3, db=db)


def test_excessive_top_k_handles_gracefully(db: Session):
    """Requesting top_k greater than vault size must return all items without index error."""
    vault_total = db.query(MasterExperienceVault).count()
    assert vault_total > 0

    bullets = get_relevant_bullets("Software Engineer", top_k=100, db=db)

    # Should return all available bullets without crash
    assert len(bullets) == vault_total


def test_non_existent_category_returns_empty_list(db: Session):
    """Filtering by an empty or non-existent category must return empty list without crash."""
    bullets = get_relevant_bullets("Python developer", top_k=5, category="NON_EXISTENT_CATEGORY", db=db)

    assert isinstance(bullets, list)
    assert len(bullets) == 0


def test_embed_text_empty_input_raises_value_error():
    """embed_text with empty string or whitespace must raise ValueError."""
    with pytest.raises(ValueError, match="cannot be empty"):
        embed_text("")

    with pytest.raises(ValueError, match="cannot be empty"):
        embed_text("   \t\n ")


def test_get_relevant_bullets_default_session_lifecycle():
    """Verify that get_relevant_bullets manages its own session cleanly when db=None."""
    bullets = get_relevant_bullets("FastAPI developer", top_k=3, db=None)
    assert len(bullets) == 3
    assert all(isinstance(b, RetrievedBullet) for b in bullets)


def test_similarity_scores_within_normalized_bounds(db: Session):
    """Verify that similarity scores fall within valid bounds [-1.0, 1.0]."""
    bullets = get_relevant_bullets("Docker Kubernetes microservices", top_k=5, db=db)
    for b in bullets:
        assert -1.0 <= b.similarity_score <= 1.0
        assert isinstance(b.tech_tags, list)
        assert len(b.bullet_point) > 10


def test_simulated_client_exception_falls_back_gracefully(monkeypatch):
    """Verify embed_text falls back gracefully to mock embedding if OpenAI client raises an error."""
    class FaultyEmbeddings:
        def create(self, **kwargs):
            raise ConnectionError("Simulated OpenAI rate limit or network failure")

    class FaultyClient:
        embeddings = FaultyEmbeddings()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-simulated-key-for-test")
    vector = embed_text("FastAPI backend test", client=FaultyClient())
    assert isinstance(vector, list)
    assert len(vector) == EMBEDDING_DIMENSION


def test_get_tailored_projects_cloud_profile(db: Session):
    """Verify that a Kubernetes / Cloud JD ranks Genesis as the top project with coherent bullets."""
    from web.services.rag_engine import get_tailored_projects, ProjectMatch

    jd = "Cloud DevOps Engineer with Kubernetes, Docker, microservices, and reverse proxy experience"
    projects = get_tailored_projects(jd, top_n_projects=2, db=db)

    assert len(projects) == 2
    assert all(isinstance(p, ProjectMatch) for p in projects)
    # Top project must be Genesis
    assert "genesis" in projects[0].project_title.lower()
    assert len(projects[0].bullets) >= 2
    assert any("kubernetes" in t.lower() for t in projects[0].tech_tags)


def test_get_tailored_projects_graph_profile(db: Session):
    """Verify that a Python / Graph JD ranks Urban Metro as the top project."""
    from web.services.rag_engine import get_tailored_projects

    jd = "Python Engineer with experience in graph algorithms, spatial analysis, and BFS optimization"
    projects = get_tailored_projects(jd, top_n_projects=2, db=db)

    assert len(projects) == 2
    # Top project must be Urban Metro Network Finder
    assert "urban metro" in projects[0].project_title.lower()
    assert len(projects[0].bullets) >= 2
    assert any("python" in t.lower() for t in projects[0].tech_tags)


def test_get_tailored_projects_empty_input_raises_error(db: Session):
    """Empty JD must raise ValueError."""
    from web.services.rag_engine import get_tailored_projects

    with pytest.raises(ValueError, match="cannot be empty"):
        get_tailored_projects("", top_n_projects=2, db=db)


def test_get_tailored_skills_retrieval(db: Session):
    """Verify get_tailored_skills returns skill bullets ranked by relevance."""
    from web.services.rag_engine import get_tailored_skills

    jd = "Kubernetes, Docker, Linux, CI/CD, NGINX"
    skills = get_tailored_skills(jd, db=db)

    assert len(skills) >= 1
    # Cloud/DevOps or Infrastructure should be near the top
    top_titles = [s.title.lower() for s in skills[:2]]
    assert any("cloud" in t or "infrastructure" in t or "devops" in t for t in top_titles)


