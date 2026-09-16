import argparse
import hashlib
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv()

from db.models import MasterExperienceVault, VaultCategory
from db.session import SessionLocal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("seed_vault")


from web.services.rag_engine import embed_text


def seed_vault(json_path: Path, clear_existing: bool = False):
    if not json_path.exists():
        logger.error("Seed file not found: %s", json_path)
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        bullets_data = json.load(f)

    api_key = os.getenv("OPENAI_API_KEY")
    db = SessionLocal()

    try:
        if clear_existing:
            deleted = db.query(MasterExperienceVault).delete()
            db.commit()
            logger.info("Cleared %d existing vault records.", deleted)

        # Check existing count
        existing_count = db.query(MasterExperienceVault).count()
        if existing_count > 0 and not clear_existing:
            logger.info(
                "Vault already contains %d records. Use --clear to overwrite or add new entries.",
                existing_count
            )

        inserted = 0
        for item in bullets_data:
            category_str = item.get("category", "WORK_EXPERIENCE")
            title = item.get("title", "Experience")
            bullet_point = item.get("bullet_point", "")
            tech_tags = item.get("tech_tags", [])

            # Validate category
            try:
                category = VaultCategory(category_str).value
            except ValueError:
                logger.warning("Invalid category '%s', defaulting to WORK_EXPERIENCE", category_str)
                category = VaultCategory.WORK_EXPERIENCE.value

            text_to_embed = f"{title}: {bullet_point} {' '.join(tech_tags)}"
            embedding = embed_text(text_to_embed)

            vault_entry = MasterExperienceVault(
                id=uuid.uuid4(),
                category=category,
                title=title,
                bullet_point=bullet_point,
                tech_tags=tech_tags,
                embedding=embedding,
            )
            db.add(vault_entry)
            inserted += 1

        db.commit()
        logger.info("Successfully inserted %d experience bullets into master_experience_vault!", inserted)

        # Verification query
        total_count = db.query(MasterExperienceVault).count()
        logger.info("Total records in master_experience_vault: %d", total_count)

    except Exception as exc:
        db.rollback()
        logger.error("Failed to seed vault: %s", exc, exc_info=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed master_experience_vault with embeddings.")
    parser.add_argument(
        "--file",
        type=Path,
        default=PROJECT_ROOT / "data" / "master_vault.json",
        help="Path to JSON file containing master vault items",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing entries before seeding",
    )
    args = parser.parse_args()

    seed_vault(args.file, clear_existing=args.clear)
