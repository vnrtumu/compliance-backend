#!/usr/bin/env python
"""Test validator agent database integration"""

import sys
sys.path.insert(0, '/Users/venkatreddy/Desktop/AgenticAITest/compliance-backend')

from app.services.validator import validator_agent

# Test fetching checks from database
checks = validator_agent._get_validation_checks_from_db()

print(f"✅ Successfully loaded {len(checks)} validation checks from database!\n")

# Group by category
by_category = {}
for check in checks:
    cat = check["category"]
    if cat not in by_category:
        by_category[cat] = []
    by_category[cat].append(check)

print("Checks by category:")
for category, cat_checks in sorted(by_category.items()):
    print(f"  {category}: {len(cat_checks)} checks")

print(f"\nSample check:")
if checks:
    sample = checks[0]
    print(f"  Code: {sample['check_code']}")
    print(f"  Name: {sample['check_name']}")
    print(f"  Category: {sample['category']}")
    print(f"  Description: {sample['description'][:80]}...")
    print(f"  Auto-reject: {sample['auto_reject']}")

# Test formatted checklist
print(f"\n{'='*80}")
print("FORMATTED CHECKLIST FOR LLM:")
print(f"{'='*80}")
formatted = validator_agent._format_validation_checklist()
print(formatted[:500] + "...")
