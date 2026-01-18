#!/usr/bin/env python
"""Recreate validation_checklist table and populate with seed data"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, Table, Column, Integer, String, Float, Boolean, Text, MetaData

# Add app to path
sys.path.insert(0, '/Users/venkatreddy/Desktop/AgenticAITest/compliance-backend')

# Load environment variables
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

# Get database connection details
POSTGRES_SERVER = os.getenv('POSTGRES_SERVER', 'localhost')
POSTGRES_USER = os.getenv('POSTGRES_USER', 'postgres')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD')
POSTGRES_DB = os.getenv('POSTGRES_DB', 'compliance_db')

# Build database URL
DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_SERVER}/{POSTGRES_DB}"

engine = create_engine(DATABASE_URL)

# Import seed data
from app.data.validation_checklist_seed import VALIDATION_CHECKS

with engine.connect() as conn:
    # Drop table if exists
    conn.execute(text("DROP TABLE IF EXISTS validation_checklist CASCADE"))
    conn.commit()
    
    # Create table
    conn.execute(text("""
        CREATE TABLE validation_checklist (
            id SERIAL PRIMARY KEY,
            check_code VARCHAR(20) NOT NULL UNIQUE,
            check_name VARCHAR(200) NOT NULL,
            category VARCHAR(50) NOT NULL,
            subcategory VARCHAR(50),
            description TEXT NOT NULL,
            validation_logic TEXT,
            error_message VARCHAR(500),
            complexity VARCHAR(20) NOT NULL,
            complexity_score INTEGER NOT NULL,
            weight FLOAT DEFAULT 1.0,
            is_automated BOOLEAN DEFAULT TRUE,
            requires_api_call BOOLEAN DEFAULT FALSE,
            api_endpoint VARCHAR(200),
            auto_reject BOOLEAN DEFAULT FALSE,
            requires_manual_review BOOLEAN DEFAULT FALSE,
            is_active BOOLEAN DEFAULT TRUE,
            effective_from VARCHAR(10),
            effective_to VARCHAR(10),
            reference_document VARCHAR(200)
        )
    """))
    conn.commit()
    
    # Create indexes
    conn.execute(text("CREATE INDEX ix_validation_checklist_check_code ON validation_checklist(check_code)"))
    conn.execute(text("CREATE INDEX ix_validation_checklist_category ON validation_checklist(category)"))
    conn.commit()
    
    # Insert seed data
    for check in VALIDATION_CHECKS:
        # Add defaults for missing fields
        check.setdefault('requires_api_call', False)
        check.setdefault('api_endpoint', None)
        check.setdefault('auto_reject', False)
        check.setdefault('requires_manual_review', False)
        check.setdefault('is_active', True)
        check.setdefault('effective_from', None)
        check.setdefault('effective_to', None)
        check.setdefault('reference_document', None)
        check.setdefault('subcategory', None)
        check.setdefault('validation_logic', None)
        check.setdefault('error_message', None)
        
        conn.execute(text("""
            INSERT INTO validation_checklist (
                check_code, check_name, category, subcategory, description,
                validation_logic, error_message, complexity, complexity_score, weight,
                is_automated, requires_api_call, api_endpoint, auto_reject,
                requires_manual_review, is_active, effective_from, effective_to, reference_document
            ) VALUES (
                :check_code, :check_name, :category, :subcategory, :description,
                :validation_logic, :error_message, :complexity, :complexity_score, :weight,
                :is_automated, :requires_api_call, :api_endpoint, :auto_reject,
                :requires_manual_review, :is_active, :effective_from, :effective_to, :reference_document
            )
        """), check)
    conn.commit()
    
    # Verify
    result = conn.execute(text("SELECT COUNT(*) FROM validation_checklist"))
    count = result.scalar()
    
    print(f"✅ Successfully created validation_checklist table and inserted {count} validation rules!")
