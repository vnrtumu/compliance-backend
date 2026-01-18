#!/usr/bin/env python
"""Test script to verify processing time tracking"""

import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

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

with engine.connect() as conn:
    # Get the latest upload
    result = conn.execute(text("""
        SELECT id, filename, processing_start_time, processing_time, invoice_status
        FROM uploads 
        ORDER BY id DESC 
        LIMIT 5
    """))
    
    print("\n" + "="*80)
    print("LATEST 5 UPLOADS - Processing Time Status")
    print("="*80)
    
    for row in result:
        print(f"\nUpload ID: {row[0]}")
        print(f"  Filename: {row[1]}")
        print(f"  Processing Start Time: {row[2]}")
        print(f"  Processing Time: {row[3]} seconds" if row[3] else f"  Processing Time: Not set")
        print(f"  Invoice Status: {row[4]}")
    
    print("\n" + "="*80)
    
    # Check if any uploads have processing_time set
    result2 = conn.execute(text("""
        SELECT COUNT(*) as total, 
               COUNT(processing_time) as with_time,
               COUNT(processing_start_time) as with_start
        FROM uploads
    """))
    
    stats = result2.fetchone()
    print("\nOVERALL STATISTICS:")
    print(f"  Total uploads: {stats[0]}")
    print(f"  With processing_start_time: {stats[2]}")
    print(f"  With processing_time: {stats[1]}")
    print("="*80 + "\n")
