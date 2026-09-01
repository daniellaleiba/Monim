"""  
Reader Repository - Data Access Layer

The field workers who perform meter readings.
"""

from database.connection import Database
from typing import List, Dict, Optional, Any

# Columns to return in SELECT queries (exclude password_hash for security)
READER_COLUMNS = "reader_id, name, username, phone, active, created_at"

class ReaderRepository:
    """
    Data Access Layer for readers table.
 
    Responsibilities:
        - insert / update / select of readers
        - search by id / username
        - existence checks
        - list queries
        - active status management
 
    Note: Reader represents the person, not their assignments or readings.
          Work folder assignments belong to WorkFolderRepository.
    """

    def __init__(self):
        self.db = Database()

    # --- EXISTENCE CHECKS:
 
    def exists(self, reader_id: int) -> bool:
        """Check if reader exists by ID"""
        result = self.db.execute_query(
            "SELECT 1 FROM readers WHERE reader_id = %s",
            (reader_id,), fetch="one")
        return result is not None
 
    def username_exists(self, username: str, exclude_reader_id: int = None) -> bool:
        """
        Check if username already exists.
 
        Args:
            username: Username to check
            exclude_reader_id: Exclude this reader from check (useful for updates)
        """
        if exclude_reader_id:
            # Update case: check if username exists on a DIFFERENT reader (ignore self)
            result = self.db.execute_query(
                "SELECT 1 FROM readers WHERE username = %s AND reader_id != %s",
                (username, exclude_reader_id), fetch="one")
        else:
            # Create case: check if username exists at all
            result = self.db.execute_query(
                "SELECT 1 FROM readers WHERE username = %s",
                (username,), fetch="one")
            
        return result is not None
 
    # --- CREATE:
 
    def create(self, name: str, username: str, password_hash: str, phone: str = None) -> dict:
        """
        Insert new reader.
 
        Args:
            name: Reader name (already validated by Service)
            username: Username (already validated by Service)
            password_hash: Hashed password
            phone: Phone number (optional)
 
        Returns: The created reader row (without password_hash)
        """
        result = self.db.execute_query("""
            INSERT INTO readers (name, username, password_hash, phone)
            VALUES (%s, %s, %s, %s)
            RETURNING {columns}
        """.format(columns=READER_COLUMNS),
            (name, username, password_hash, phone),
            fetch="one", commit=True)
        
        return result
    
    # --- READ: 
 
    def get_by_id(self, reader_id: int) -> Optional[dict]:
        """Get single reader by ID, or None if not found"""
        return self.db.execute_query(f"SELECT {READER_COLUMNS} FROM readers WHERE reader_id = %s",(reader_id,),fetch="one")
 
    def get_by_username(self, username: str) -> Optional[dict]:
        """Get single reader by username, or None if not found"""
        return self.db.execute_query(f"SELECT {READER_COLUMNS} FROM readers WHERE username = %s",(username,),fetch="one")
 
    def list_all(self, active_only: bool = False) -> List[dict]:
        """
        Get all readers, ordered by name.
 
        Args:
            active_only: If True, return only active readers
        """
        if active_only:
            return self.db.execute_query(f"SELECT {READER_COLUMNS} FROM readers WHERE active = TRUE ORDER BY name",fetch="all")
        
        return self.db.execute_query(f"SELECT {READER_COLUMNS} FROM readers ORDER BY name", fetch="all" )
 
    def search(self, search_pattern: str) -> List[dict]:
        """
        Search readers by name or username.
 
        Args:
            search_pattern: Search term (without %)
        """
        like_pattern = f"%{search_pattern}%"
        return self.db.execute_query(f"""
            SELECT {READER_COLUMNS} FROM readers
            WHERE name ILIKE %s OR username ILIKE %s
            ORDER BY name
        """, (like_pattern, like_pattern), fetch="all")
    
    
    # --- UPDATE:
 
    def update(self, reader_id: int, updates: Dict[str, Any]) -> bool:
        """
        Update reader fields dynamically.
 
        Args:
            reader_id: Reader ID
            updates: Dict of fields to update, e.g. {'name': 'New Name', 'phone': '050...'}
 
        Returns: True if a row was updated
        """
        if not updates:
            return False
 
        set_clauses = []
        params = []
 
        for field, value in updates.items():
            set_clauses.append(f"{field} = %s")
            params.append(value)
 
        params.append(reader_id)
        query = f"UPDATE readers SET {', '.join(set_clauses)} WHERE reader_id = %s"
 
        rows = self.db.execute_query(query, params, commit=True)
        return rows > 0
    
    def update_password(self, reader_id: int, password_hash: str) -> bool:
        """
        Update reader password (separate from general update for security).
 
        Returns: True if updated
        """
        rows = self.db.execute_query("UPDATE readers SET password_hash = %s WHERE reader_id = %s", (password_hash, reader_id), commit=True)
        
        return rows > 0
    
    def set_active_status(self, reader_id: int, is_active: bool) -> bool:
        """
        Activate or deactivate a reader.
 
        Args:
            reader_id: Reader ID
            is_active: True to activate, False to deactivate
 
        Returns: True if updated
        """
        rows = self.db.execute_query("UPDATE readers SET active = %s WHERE reader_id = %s", (is_active, reader_id), commit=True)
        return rows > 0
    
    # --- DELETE:
 
    def delete(self, reader_id: int) -> bool:
        """
        Delete reader from database.

        Note: readings.reader_id and work_folders.assigned_to are ON DELETE SET NULL,
        existing readings/folders are kept but lose their reader reference.
 
        Returns: True if a row was deleted
        """
        rows = self.db.execute_query("DELETE FROM readers WHERE reader_id = %s", (reader_id,), commit=True)
        return rows > 0