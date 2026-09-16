import hashlib
import logging
import math
import os
from typing import Any, List, Optional
from uuid import UUID

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

load_dotenv()

from db.models import MasterExperienceVault
from db.session import SessionLocal

logger = logging.getLogger("rag_engine")

DEFAULT_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMENSION = 1536


class RetrievedBullet(BaseModel):
    """Structured representation of a bullet retrieved from master_experience_vault."""
    id: str = Field(..., description="UUID of the vault entry")
    category: str = Field(..., description="Category: WORK_EXPERIENCE, PROJECT, SKILL, EDUCATION")
    title: str = Field(..., description="Project or employer title")
    bullet_point: str = Field(..., description="Exact bullet point text")
    tech_tags: List[str] = Field(default_factory=list, description="Associated technologies")
    similarity_score: float = Field(..., description="Cosine similarity score (0.0 to 1.0)")


class ProjectMatch(BaseModel):
    """A coherent project selected by aggregating relevant bullet scores."""
    project_title: str = Field(..., description="Project name")
    aggregate_score: float = Field(..., description="Aggregated relevance score")
    bullets: List[RetrievedBullet] = Field(default_factory=list, description="Top-matching bullets for this project")
    tech_tags: List[str] = Field(default_factory=list, description="Consolidated unique tech tags")



STOP_WORDS = {
    "and", "or", "the", "in", "with", "a", "an", "to", "for", "of",
    "on", "at", "by", "from", "using", "under", "over", "is", "are",
}


def _get_mock_embedding(text: str, dim: int = EMBEDDING_DIMENSION) -> List[float]:
    """
    Deterministic pseudo-embedding for testing when OpenAI API key is unavailable.
    Projects semantic word tokens into a 1536-dimensional unit vector using md5/sha256 hashing.
    Preserves cosine similarity between texts sharing technical terms and keywords.
    """
    import re

    tokens = re.findall(r"[a-z0-9_\-\+]+", text.lower())
    vector = [0.0] * dim

    # Subtle base noise derived from full text hash to prevent zero vectors
    base_hash = hashlib.sha256(text.encode("utf-8")).digest()
    for i in range(dim):
        vector[i] = ((base_hash[(i * 7) % len(base_hash)] / 255.0) - 0.5) * 0.05

    # Project tokens into dimension coordinates
    for token in tokens:
        weight = 0.2 if token in STOP_WORDS else 1.0
        for seed in range(16):
            slot = int(hashlib.md5(f"{token}_{seed}".encode("utf-8")).hexdigest(), 16) % dim
            vector[slot] += weight

    # Normalize to L2 unit vector (sum(x^2) == 1.0)
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def embed_text(
    text: str,
    model: Optional[str] = None,
    client: Optional[Any] = None,
) -> List[float]:
    """
    Generate a 1536-dimensional embedding vector for input text.
    Uses OpenAI text-embedding-3-small by default, or configurable via EMBEDDING_MODEL.
    Falls back to deterministic mock embedding for offline tests.
    """
    if not text or not text.strip():
        raise ValueError("Text to embed cannot be empty or whitespace.")

    model_name = model or DEFAULT_EMBEDDING_MODEL
    raw_key = os.getenv("OPENAI_API_KEY")
    api_key = raw_key.strip().strip('"\'') if raw_key else None

    if api_key and api_key.startswith("sk-") and not api_key.startswith("sk-proj-placeholder"):
        try:
            if client is None:
                from openai import OpenAI
                client = OpenAI(api_key=api_key)

            # Support matryoshka dimension constraint if using text-embedding-3-large
            kwargs = {"input": text, "model": model_name}
            if model_name == "text-embedding-3-large":
                kwargs["dimensions"] = EMBEDDING_DIMENSION

            response = client.embeddings.create(**kwargs)
            raw_vec = response.data[0].embedding
            norm = math.sqrt(sum(x * x for x in raw_vec)) or 1.0
            return [x / norm for x in raw_vec]
        except Exception as exc:
            logger.warning("OpenAI embedding API failed (%s). Using fallback embedding.", exc)
            return _get_mock_embedding(text)
    else:
        return _get_mock_embedding(text)


def get_relevant_bullets(
    jd_text: str,
    top_k: int = 5,
    category: Optional[str] = None,
    db: Optional[Session] = None,
    model: Optional[str] = None,
    client: Optional[Any] = None,
) -> List[RetrievedBullet]:
    """
    Retrieve top-k most relevant bullets from master_experience_vault using pgvector cosine distance.
    
    Args:
        jd_text: Unstructured job description requirements or keywords.
        top_k: Number of bullets to retrieve (default: 5).
        category: Optional category filter (e.g. 'WORK_EXPERIENCE', 'PROJECT').
        db: Optional SQLAlchemy session. If None, a new session is managed.
        model: Optional embedding model name override.
        client: Optional OpenAI client.
        
    Returns:
        List of RetrievedBullet objects sorted in descending order of semantic similarity.
    """
    if not jd_text or not jd_text.strip():
        raise ValueError("Job description text cannot be empty or whitespace.")

    if top_k <= 0:
        raise ValueError(f"top_k must be a positive integer greater than 0, got {top_k}.")

    managed_session = False
    if db is None:
        db = SessionLocal()
        managed_session = True

    try:
        # 1. Embed query text into 1536-dim vector
        query_vector = embed_text(jd_text, model=model, client=client)

        # 2. Query pgvector using cosine_distance operator (<=>)
        # In pgvector: cosine_distance = 1 - cosine_similarity
        distance_expr = MasterExperienceVault.embedding.cosine_distance(query_vector).label("distance")

        query = db.query(MasterExperienceVault, distance_expr)
        if category:
            query = query.filter(MasterExperienceVault.category == category)

        # Order by distance ascending (nearest neighbor first)
        results = query.order_by(distance_expr.asc()).limit(top_k).all()

        retrieved: List[RetrievedBullet] = []
        for vault_row, distance in results:
            dist_val = float(distance) if distance is not None else 1.0
            similarity = round(1.0 - dist_val, 4)

            retrieved.append(
                RetrievedBullet(
                    id=str(vault_row.id),
                    category=vault_row.category,
                    title=vault_row.title,
                    bullet_point=vault_row.bullet_point,
                    tech_tags=vault_row.tech_tags or [],
                    similarity_score=similarity,
                )
            )

        return retrieved

    finally:
        if managed_session:
            db.close()


def get_tailored_projects(
    jd_text: str,
    top_n_projects: int = 2,
    bullets_per_project: int = 3,
    db: Optional[Session] = None,
    model: Optional[str] = None,
    client: Optional[Any] = None,
) -> List[ProjectMatch]:
    """
    Select cohesive projects based on aggregate bullet relevance with hybrid tag boosting.
    
    1. Retrieves candidate PROJECT bullets using pgvector cosine retrieval.
    2. Applies an exact-match boost for JD tech/umbrella terms present in tech_tags.
    3. Groups bullets by project title and computes aggregate score (mean of top-2 bullets).
    4. Returns the top_n_projects, each containing its top bullets_per_project bullets.
    """
    if not jd_text or not jd_text.strip():
        raise ValueError("Job description text cannot be empty or whitespace.")

    if top_n_projects <= 0:
        raise ValueError(f"top_n_projects must be greater than 0, got {top_n_projects}.")

    # Fetch all project bullets
    raw_bullets = get_relevant_bullets(
        jd_text=jd_text,
        top_k=50,
        category="PROJECT",
        db=db,
        model=model,
        client=client,
    )

    jd_lower = jd_text.lower()
    project_groups: dict[str, List[RetrievedBullet]] = {}

    for bullet in raw_bullets:
        # Hybrid exact-tag boost: +0.02 per matching tag, capped at +0.08
        tag_hits = sum(1 for tag in bullet.tech_tags if tag.lower() in jd_lower)
        boost = min(0.08, tag_hits * 0.02)
        boosted_score = round(min(1.0, bullet.similarity_score + boost), 4)

        updated_bullet = bullet.model_copy(update={"similarity_score": boosted_score})
        project_groups.setdefault(bullet.title, []).append(updated_bullet)

    ranked_projects: List[ProjectMatch] = []
    for title, bullets in project_groups.items():
        # Sort project bullets by similarity descending
        sorted_bullets = sorted(bullets, key=lambda b: b.similarity_score, reverse=True)

        # Aggregate score: mean of top 2 bullets (or top 1 if only 1 available)
        top_scores = [b.similarity_score for b in sorted_bullets[:2]]
        agg_score = round(sum(top_scores) / len(top_scores), 4)

        # Deduplicate tags while preserving order
        unique_tags = []
        seen = set()
        for b in sorted_bullets:
            for t in b.tech_tags:
                if t.lower() not in seen:
                    seen.add(t.lower())
                    unique_tags.append(t)

        ranked_projects.append(
            ProjectMatch(
                project_title=title,
                aggregate_score=agg_score,
                bullets=sorted_bullets[:bullets_per_project],
                tech_tags=unique_tags,
            )
        )

    # Sort projects by aggregate score descending
    ranked_projects.sort(key=lambda p: p.aggregate_score, reverse=True)
    return ranked_projects[:top_n_projects]


def get_tailored_skills(
    jd_text: str,
    db: Optional[Session] = None,
    model: Optional[str] = None,
    client: Optional[Any] = None,
) -> List[RetrievedBullet]:
    """
    Retrieve skill categories ranked by relevance to target job description.
    """
    return get_relevant_bullets(
        jd_text=jd_text,
        top_k=10,
        category="SKILL",
        db=db,
        model=model,
        client=client,
    )

