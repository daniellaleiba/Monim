"""
Monim V2 : Shared Test Helpers
Common functions used across all test files.

All tests run on monim_v2_test DB ::: never on the real DB.
"""
import os

# IMPORTANT: Override DB_NAME before any Database import
# This ensures all tests run on the test DB, not the real one
os.environ['DB_NAME'] = 'monim_v2_test'

passed = 0
failed = 0


def report(test_name, success, detail=""):
    """Print test result and update counters"""
    global passed, failed
    if success:
        passed += 1
        print(f"  PASS - {test_name}")
    else:
        failed += 1
        print(f"  FAIL - {test_name}: {detail}")


def print_summary():
    """Print final test results"""
    global passed, failed
    total = passed + failed
    print(f"\n  תוצאות: {passed}/{total} עברו")
    if failed > 0:
        print(f"  ⚠ {failed} בדיקות נכשלו!")
    else:
        print("  כל הבדיקות עברו בהצלחה! ✓")


def reset_counters():
    """Reset pass/fail counters"""
    global passed, failed
    passed = 0
    failed = 0


def cleanup():
    """Reset DB to clean state after tests"""
    from database.connection import Database
    db = Database()
    schema_path = os.path.join(os.path.dirname(__file__), '..', 'database', 'schema.sql')
    db.execute_script(schema_path)
    print("\n  DB reset to clean state ✓")