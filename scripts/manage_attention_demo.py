"""
scripts/manage_attention_demo.py
================================
CLI utility to seed or clear demo attention triage items directly via database.
Usage:
    python scripts/manage_attention_demo.py --seed
    python scripts/manage_attention_demo.py --clear
"""

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.session import SessionLocal
from web.services.demo_seeder import seed_demo_attention_data, clear_demo_attention_data


def main():
    parser = argparse.ArgumentParser(description="Seed or clear demo attention triage items.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--seed", action="store_true", help="Seed realistic demo triage items.")
    group.add_argument("--clear", action="store_true", help="Clear all demo triage items.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.seed:
            res = seed_demo_attention_data(db)
            print(f"Seed Result: {res}")
        elif args.clear:
            res = clear_demo_attention_data(db)
            print(f"Clear Result: {res}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
