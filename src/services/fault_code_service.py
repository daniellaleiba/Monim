"""
FaultCode Service - Business Logic Layer


Thin read-only wrapper around FaultCodeRepository, exposes the fixed list of fault codes (seed data in schema.sql) for use in forms and lookups.
No validation or write operations; fault codes are static reference data.
"""
from src.repositories.fault_code_repository import FaultCodeRepository

class FaultCodeService:
    """Provides read access to fault codes for dropdowns and lookups."""
    def __init__(self):
        self.repo = FaultCodeRepository()

    def list_active(self) -> list:
        """Return all active fault codes as list of dicts."""
        return self.repo.list_active()

    def get_as_dict(self) -> dict:
        """Return fault codes as {code: description} dict."""
        return {fc['code']: fc['description'] for fc in self.repo.list_active()}