"""
Monim - Dev Queries
Ad-hoc DB investigation queries used during development.

These are NOT automated tests (no assertions, no pass/fail), they are manual, one-off queries kept 
as a record of debugging/investigation sessions against real data patterns encountered while building the system.

Usage:
    python scripts/dev_queries.py <query_name>

Available queries:
    buildings   - Inspect usage_type per address for a specific street/period
                  (investigated a shared-consumption grouping edge case)
    names       - Search customer addresses containing a given substring,
                  with a fallback period if nothing found in the first
    clients     - List all clients currently in the DB (quick sanity check)
    shared      - Run SharedConsumptionService.calculate() for a period and
                  print the result summary
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from database.connection import Database
from src.services.shared_consumption_service import SharedConsumptionService


def check_buildings(period_id=18, address_pattern='ביאליק 6%'):
    """
    Inspect usage_type per customer/address for a given street pattern.
    Originally used to investigate how shared_consumption should group apartments within the same building.
    """
    db = Database()
    rows = db.execute_query("""
        SELECT customer_name, address, raw_data->>'usage_type' as usage_type
        FROM period_meters
        WHERE period_id = %s
        AND address LIKE %s
        ORDER BY address
    """, (period_id, address_pattern), fetch="all")

    print(f"Building/address check: period_id={period_id}, pattern='{address_pattern}'")
    for r in rows:
        print(f"  {r['usage_type']} | {r['customer_name'][:20]} | {r['address']}")
    print(f"  Total: {len(rows)} rows")

def check_names(period_id=1, name_pattern='%רמב%', fallback_period_id=2):
    """
    Search customer addresses containing a given substring, showing
    meter_id / usage_type / customer_name / address. Falls back to a
    second period if nothing is found in the first.
    """
    db = Database()
    rows = db.execute_query("""
        SELECT raw_data->>'meter_id' as meter_id,
               raw_data->>'usage_type' as usage_type,
               customer_name, address
        FROM period_meters
        WHERE period_id = %s
        AND address LIKE %s
        ORDER BY walk_order
        LIMIT 30
    """, (period_id, name_pattern), fetch="all")

    print(f"Name/address check : period_id={period_id}, pattern='{name_pattern}'")
    print(f"  Found {len(rows)} rows:")
    for r in rows:
        print(f"    {r['meter_id']} | type={r['usage_type']} | {r['customer_name']} | {repr(r['address'])}")

    if not rows and fallback_period_id is not None:
        print(f"\n  Nothing in period_id={period_id}, trying period_id={fallback_period_id}...")
        check_names(period_id=fallback_period_id, name_pattern=name_pattern, fallback_period_id=None)

def check_clients():
    """List all clients currently in the DB, quick sanity check."""
    db = Database()
    rows = db.execute_query("SELECT * FROM clients;", fetch="all")

    print("לקוחות במערכת:")
    for row in rows:
        print(f"  {row['client_id']}: {row['name']} ({row['corporation_number']})")
    print(f"\nסה\"כ: {len(rows)} לקוחות")

def check_shared_consumption(period_id=18):
    """Run SharedConsumptionService.calculate() for a period and print the summary."""
    service = SharedConsumptionService()
    result = service.calculate(period_id=period_id,include_details=True)

    print(f"Shared consumption : period_id={period_id}")
    print(f"  בניינים שעובדו:  {result['buildings']}")
    print(f"  דירות שעודכנו:   {result['apartments_updated']}")
    print(f"  חריגים:          {result['exceptions']}")
    print(f"  דולגו:           {result['skipped']}")

    if result.get('skipped_details'):
        print(f"\n  --- פירוט בניינים שדולגו ({len(result['skipped_details'])}) ---")
        for item in result['skipped_details']:
            print(f"    {item['address']} - {item['reason']}")

    if result.get('exception_details'):
        print(f"\n  --- פירוט חריגים ({len(result['exception_details'])}) ---")
        for item in result['exception_details']:
            print(f"    {item['address']} - צריכה: {item['shared_consumption']}")

QUERIES = {
    'buildings': check_buildings,
    'names': check_names,
    'clients': check_clients,
    'shared': check_shared_consumption,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in QUERIES:
        print(__doc__)
        return

    QUERIES[sys.argv[1]]()


if __name__ == "__main__":
    main()