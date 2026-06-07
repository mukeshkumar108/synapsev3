from core.db import Database
import asyncio

async def migrate():
    db = Database()
    
    print("Applying Phase 1 Provenance Migration...")
    
    # Add columns to confirmed_facts
    await db.execute("""
        ALTER TABLE confirmed_facts 
        ADD COLUMN IF NOT EXISTS claimed_by_entity_id TEXT,
        ADD COLUMN IF NOT EXISTS subject_entity_id TEXT,
        ADD COLUMN IF NOT EXISTS claim_type TEXT,
        ADD COLUMN IF NOT EXISTS interaction_mode TEXT;
    """)
    
    # Add columns to candidates
    await db.execute("""
        ALTER TABLE candidates 
        ADD COLUMN IF NOT EXISTS claimed_by_entity_id TEXT,
        ADD COLUMN IF NOT EXISTS subject_entity_id TEXT,
        ADD COLUMN IF NOT EXISTS claim_type TEXT DEFAULT 'direct',
        ADD COLUMN IF NOT EXISTS claim_status TEXT DEFAULT 'pending',
        ADD COLUMN IF NOT EXISTS interaction_mode TEXT DEFAULT 'real_life';
    """)
    
    # Create indexes
    await db.execute("CREATE INDEX IF NOT EXISTS idx_confirmed_facts_subject ON confirmed_facts(subject_entity_id);")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_confirmed_facts_claimed_by ON confirmed_facts(claimed_by_entity_id);")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_candidates_subject ON candidates(subject_entity_id);")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_candidates_claimed_by ON candidates(claimed_by_entity_id);")
    
    print("Migration complete.")
    await db.close()

if __name__ == "__main__":
    asyncio.run(migrate())
