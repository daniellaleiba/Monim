"""  
Client Repository - Data Access Layer

Enforces uniqueness lookups (name, corporation number) at the query level, backing ClientService's validation.
"""

from database.connection import Database
from typing import List, Dict, Optional, Any
 
class ClientRepository:
    """
    Data Access Layer for clients table.
 
    Responsibilities:
        - insert / update / select of clients
        - search by business identifiers
        - existence checks
        - list queries
 
    Note: Client is master data, not an operational entity.
          This repository does NOT handle periods, meters, or folders.
    """
 
    def __init__(self):
        self.db = Database()

    # --- EXISTENCE CHECKS:
 
    def exists(self, client_id: int) -> bool:
        """Check if client exists by ID"""
        result = self.db.execute_query(
            "SELECT 1 FROM clients WHERE client_id = %s",
            (client_id,), fetch="one")
        
        return result is not None
 
    def name_exists(self, name: str, exclude_client_id: int = None) -> bool:
        """
        Check if client name already exists.
        Args:
            name: Client name to check
            exclude_client_id: Exclude this client from check (useful for updates)
        """
        if exclude_client_id:
            # Update case: check if name exists on a DIFFERENT client (ignore self)
            result = self.db.execute_query( "SELECT 1 FROM clients WHERE name = %s AND client_id != %s",
                (name, exclude_client_id), fetch="one")
        else:
            # Create case: check if name exists at all
            result = self.db.execute_query( "SELECT 1 FROM clients WHERE name = %s",
                (name,), fetch="one")
            
        return result is not None
 
    def corporation_number_exists(self, corp_num: str, exclude_client_id: int = None) -> bool:
        """
        Check if corporation number already exists.
        
        Args:
            corp_num: Corporation number to check
            exclude_client_id: Exclude this client from check (useful for updates)
        """
        if exclude_client_id:
            # Update case: check if corp number exists on a DIFFERENT client (ignore self)
            result = self.db.execute_query( "SELECT 1 FROM clients WHERE corporation_number = %s AND client_id != %s",
                (corp_num, exclude_client_id), fetch="one")
        else:
            result = self.db.execute_query( "SELECT 1 FROM clients WHERE corporation_number = %s",
                (corp_num,), fetch="one")
            
        return result is not None
 
    # --- CREATE:
 
    def create(self, name: str, corporation_number: str, city: str = None) -> Dict:
        """
        Insert new client.
        
        Returns: Full client record (client_id, name, corporation_number, created_at)
        """
        return self.db.execute_query("""
            INSERT INTO clients (name, corporation_number, city)
            VALUES (%s, %s, %s)
            RETURNING *
        """, (name, corporation_number, city), fetch="one", commit=True)
    
    # --- READ:
 
    def get_by_id(self, client_id: int) -> Optional[Dict]:
        """Get single client by ID, or None if not found"""
        return self.db.execute_query( "SELECT * FROM clients WHERE client_id = %s",
            (client_id,), fetch="one")
 
    def get_by_name(self, name: str) -> Optional[Dict]:
        """Get single client by exact name, or None if not found"""
        return self.db.execute_query( "SELECT * FROM clients WHERE name = %s", (name,), fetch="one")
 
    def get_by_corporation_number(self, corp_num: str) -> Optional[Dict]:
        """Get single client by corporation number, or None if not found"""
        return self.db.execute_query( "SELECT * FROM clients WHERE corporation_number = %s", (corp_num,), fetch="one")
 
    def list_all(self) -> List[Dict]:
        """Get all clients, ordered by name"""
        return self.db.execute_query( "SELECT * FROM clients ORDER BY name", fetch="all")
    
    def search(self, search_pattern: str) -> List[Dict]:
        """
        Find clients by exact name or corporation number (case-insensitive).
        Intentionally NOT a substring search, client identity should be matched precisely.
        
        Args: search_pattern: SQL LIKE pattern (e.g., "%נתניה%")
        """
        return self.db.execute_query("""
            SELECT * FROM clients
            WHERE name ILIKE %s OR corporation_number ILIKE %s
            ORDER BY name
        """, (search_pattern, search_pattern), fetch="all")
    
    # --- UPDATE:
 
    def update(self, client_id: int, updates: Dict[str, Any]) -> bool:
        """
        Update client fields dynamically.
        
        Args:
            client_id: Client ID
            updates: Dict of fields to update, e.g. {'name': 'New Name'}
            
        Returns: True if a row was updated (False otherwise)
        """
        if not updates:
            return False
 
        set_clauses = []
        params = []
 
        for field, value in updates.items():
            set_clauses.append(f"{field} = %s")
            params.append(value)
 
        params.append(client_id)
        query = f"UPDATE clients SET {', '.join(set_clauses)} WHERE client_id = %s"
 
        rows = self.db.execute_query(query, params, commit=True)
        return rows > 0
    
    # --- DELETE:
 
    def delete(self, client_id: int) -> bool:
        """
        Delete client by ID.
        
        Returns: True if a row was deleted (False otherwise)
        """
        rows = self.db.execute_query(
            "DELETE FROM clients WHERE client_id = %s",
            (client_id,), commit=True)
        return rows > 0