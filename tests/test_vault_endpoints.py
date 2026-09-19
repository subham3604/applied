"""
tests/test_vault_endpoints.py
==============================
Unit tests for Master Experience Vault management endpoints in FastAPI:
- GET /api/vault (list, category filter, keyword search)
- POST /api/vault (create with 1536-d embedding)
- PATCH /api/vault/{id} (update metadata, recompute embedding on text edit)
- DELETE /api/vault/{id} (delete entry)
- Validation constraints and error handling
"""

import uuid
import pytest
from fastapi.testclient import TestClient

from db.models import MasterExperienceVault
from db.session import SessionLocal
from web.main import app

client = TestClient(app)


def test_get_vault_bullets():
    """Verifies listing vault bullets and category/search filtering."""
    response = client.get("/api/vault")
    assert response.status_code == 200
    bullets = response.json()
    assert isinstance(bullets, list)
    assert len(bullets) >= 20

    # Test category filter
    proj_resp = client.get("/api/vault?category=PROJECT")
    assert proj_resp.status_code == 200
    proj_bullets = proj_resp.json()
    assert all(b["category"] == "PROJECT" for b in proj_bullets)

    # Test search filter
    search_resp = client.get("/api/vault?search=Ropar")
    assert search_resp.status_code == 200
    found = search_resp.json()
    assert len(found) > 0
    assert any("ropar" in f["title"].lower() or "ropar" in f["bullet_point"].lower() for f in found)


def test_create_vault_bullet_success():
    """Verifies creating a new bullet with automatic 1536-dim vector embedding."""
    payload = {
        "category": "PROJECT",
        "title": "Autonomous Career Pipeline Engine",
        "bullet_point": "Engineered event-driven career pipeline with pgvector semantic similarity search and LangGraph worker.",
        "tech_tags": ["Python", "FastAPI", "PostgreSQL", "pgvector", "LangGraph"],
    }
    response = client.post("/api/vault", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["category"] == "PROJECT"
    assert data["title"] == payload["title"]
    assert data["bullet_point"] == payload["bullet_point"]
    assert "FastAPI" in data["tech_tags"]
    bullet_id = data["id"]

    # Verify in DB that embedding vector was generated
    with SessionLocal() as db:
        record = db.query(MasterExperienceVault).filter(MasterExperienceVault.id == uuid.UUID(bullet_id)).first()
        assert record is not None
        assert record.embedding is not None
        assert len(record.embedding) == 1536

    # Clean up test bullet
    del_resp = client.delete(f"/api/vault/{bullet_id}")
    assert del_resp.status_code == 200


def test_create_vault_bullet_validation_errors():
    """Verifies validation failure on invalid category, empty title, or empty text."""
    # Empty title
    resp = client.post(
        "/api/vault",
        json={"category": "SKILL", "title": "   ", "bullet_point": "Proficient in Python.", "tech_tags": []},
    )
    assert resp.status_code == 422

    # Empty bullet text
    resp = client.post(
        "/api/vault",
        json={"category": "SKILL", "title": "Languages", "bullet_point": "  ", "tech_tags": []},
    )
    assert resp.status_code == 422

    # Invalid category
    resp = client.post(
        "/api/vault",
        json={"category": "INVALID_CAT", "title": "Languages", "bullet_point": "Python", "tech_tags": []},
    )
    assert resp.status_code == 422


def test_update_vault_bullet_success():
    """Verifies updating bullet metadata and re-embedding on text change."""
    # Create test bullet
    create_resp = client.post(
        "/api/vault",
        json={
            "category": "SKILL",
            "title": "Temporary Skill Entry",
            "bullet_point": "Initial text for testing updates.",
            "tech_tags": ["Test"],
        },
    )
    assert create_resp.status_code == 200
    bullet_id = create_resp.json()["id"]

    try:
        # Update metadata (title and tags) without changing text
        patch_resp = client.patch(
            f"/api/vault/{bullet_id}",
            json={"title": "Updated Skill Title", "tech_tags": ["Test", "Updated"]},
        )
        assert patch_resp.status_code == 200
        patched = patch_resp.json()
        assert patched["title"] == "Updated Skill Title"
        assert "Updated" in patched["tech_tags"]

        # Update bullet text (triggers re-embedding)
        new_text = "Completely revised bullet text focusing on high-throughput asynchronous Python microservices."
        patch_text_resp = client.patch(
            f"/api/vault/{bullet_id}",
            json={"bullet_point": new_text},
        )
        assert patch_text_resp.status_code == 200
        assert patch_text_resp.json()["bullet_point"] == new_text

        # Verify DB reflects updated text and valid embedding
        with SessionLocal() as db:
            record = db.query(MasterExperienceVault).filter(MasterExperienceVault.id == uuid.UUID(bullet_id)).first()
            assert record.bullet_point == new_text
            assert record.embedding is not None
            assert len(record.embedding) == 1536
    finally:
        client.delete(f"/api/vault/{bullet_id}")


def test_delete_vault_bullet():
    """Verifies deletion and 404 on subsequent queries."""
    # Create bullet
    create_resp = client.post(
        "/api/vault",
        json={
            "category": "EDUCATION",
            "title": "Coursework to delete",
            "bullet_point": "Operating Systems & Networking.",
            "tech_tags": ["Linux"],
        },
    )
    bullet_id = create_resp.json()["id"]

    # Delete
    del_resp = client.delete(f"/api/vault/{bullet_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True

    # Subsequent delete should 404
    del_again = client.delete(f"/api/vault/{bullet_id}")
    assert del_again.status_code == 404

    # Subsequent update should 404
    patch_resp = client.patch(f"/api/vault/{bullet_id}", json={"title": "Doesn't exist"})
    assert patch_resp.status_code == 404
