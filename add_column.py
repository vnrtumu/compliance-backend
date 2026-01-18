#!/usr/bin/env python
"""Add processing_start_time column to database"""

import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load environment variables
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

# Get database connection details from environment
POSTGRES_SERVER = os.getenv('POSTGRES_SERVER', 'localhost')
POSTGRES_USER = os.getenv('POSTGRES_USER', 'postgres')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD')
POSTGRES_DB = os.getenv('POSTGRES_DB', 'compliance_db')

# Build database URL
DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_SERVER}/{POSTGRES_DB}"

engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    try:
        result = conn.execute(text(
            "ALTER TABLE uploads ADD COLUMN IF NOT EXISTS processing_start_time TIMESTAMP WITH TIME ZONE"
        ))
        conn.commit()
        print("✅ Column processing_start_time added successfully!")
    except Exception as e:
        print(f"❌ Error: {e}")
