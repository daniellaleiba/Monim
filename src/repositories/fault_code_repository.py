"""
FaultCode Repository - Data Access Layer

Thin read-only wrapper around the fault_codes table: a static seed-data lookup (see schema.sql INSERT block) with no write operations.
"""
from database.connection import Database
from typing import List

class FaultCodeRepository:
    """Provides read access to the fixed fault-codes list."""

    def __init__(self):
        self.db = Database()

    def list_active(self) -> List[dict]:
        """
        Get all active fault codes, ordered numerically by code.

        Note: code is stored as VARCHAR (schema.sql), so ORDER BY code alone would sort as text ('10' before '2'),
        code::int casts to integer first for correct numeric order.

        Returns: list of {code, description} dicts
        """

        return self.db.execute_query("SELECT code, description FROM fault_codes WHERE active = TRUE ORDER BY code::int", fetch="all")