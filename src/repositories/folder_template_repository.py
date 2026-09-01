"""  
Folder Template Repository - Data Access Layer


Data access for folder_templates: the fixed walk-order configuration per client that work folders are generated from each period. 
Enforces uniqueness (folder number, name) and walk-order range overlap checks at the query level, backing FolderTemplateService's validation.
"""
 
from database.connection import Database
from typing import List, Dict, Optional, Any
 
 
class FolderTemplateRepository:
    """
    Data Access Layer for folder_templates table.
 
    Responsibilities:
        - insert / update / select / delete of templates
        - list by client
        - existence and overlap checks
        - basic range queries
 
    Note: FolderTemplate is a configuration entity, not an execution entity.
          It defines HOW work is divided — WorkFolder is the actual work.
    """
 
    def __init__(self):
        self.db = Database()

    # --- EXISTENCE CHECKS:
 
    def exists(self, template_id: int) -> bool:
        """Check if template exists by ID"""
        result = self.db.execute_query(
            "SELECT 1 FROM folder_templates WHERE template_id = %s",
            (template_id,), fetch="one")
        
        return result is not None
    
    def folder_number_exists(self, client_id: int, folder_number: int,
                             exclude_template_id: int = None) -> bool:
        """
        Check if folder number already exists for this client.
 
        Args:
            client_id: Client ID
            folder_number: Folder number to check
            exclude_template_id: Exclude this template from check (for updates)
        """
        if exclude_template_id:
            # Update case: check if folder number exists on a DIFFERENT template (ignore self)
            result = self.db.execute_query("""
                SELECT 1 FROM folder_templates
                WHERE client_id = %s AND folder_number = %s AND template_id != %s
            """, (client_id, folder_number, exclude_template_id), fetch="one")
        else:
            # Create case: check if folder number exists at all for this client
            result = self.db.execute_query("""
                SELECT 1 FROM folder_templates
                WHERE client_id = %s AND folder_number = %s
            """, (client_id, folder_number), fetch="one")
 
        return result is not None
    
    def name_exists(self, client_id: int, folder_name: str, exclude_template_id: int = None) -> bool:
        """
        Check if template name already exists for this client.
 
        Args:
            client_id: Client ID
            folder_name: Template name to check
            exclude_template_id: Exclude this template from check (for updates)
        """
        if exclude_template_id:
            result = self.db.execute_query("""
                SELECT 1 FROM folder_templates
                WHERE client_id = %s AND folder_name = %s AND template_id != %s
            """, (client_id, folder_name, exclude_template_id), fetch="one")
        else:
            result = self.db.execute_query("""
                SELECT 1 FROM folder_templates
                WHERE client_id = %s AND folder_name = %s
            """, (client_id, folder_name), fetch="one")
 
        return result is not None
    
    # EXISTENCE for: OVERLAPS
     
    def list_overlapping_templates(self, client_id: int, walk_order_start: int,
                               walk_order_end: int, exclude_template_id: int = None) -> List[dict]:
        """
        Get all templates whose walk order range overlaps with the given range.
        Returns empty list if no overlaps.

        Args:
            client_id: Client ID
            walk_order_start: Start of range
            walk_order_end: End of range
            exclude_template_id: Exclude this template from check (for updates)
        """
        if exclude_template_id:
            # Update case: ignore the template being updated
            return self.db.execute_query("""
                SELECT * FROM folder_templates
                WHERE client_id = %s
                AND template_id != %s
                AND walk_order_start <= %s AND walk_order_end >= %s
                ORDER BY walk_order_start
            """, (client_id, exclude_template_id, walk_order_end, walk_order_start),
                fetch="all")
        else:
            # Create case: check against all templates
            return self.db.execute_query("""
                SELECT * FROM folder_templates
                WHERE client_id = %s
                AND walk_order_start <= %s AND walk_order_end >= %s
                ORDER BY walk_order_start
            """, (client_id, walk_order_end, walk_order_start),
                fetch="all")
   
    # --- CREATE:
 
    def create(self, client_id: int, folder_number: int, folder_name: str,
               walk_order_start: int, walk_order_end: int) -> dict:
        """
        Insert new folder template.
 
        Args:
            client_id: Client ID (already validated by Service)
            folder_number: Folder number (already validated)
            folder_name: Display name
            walk_order_start: Start of walk order range
            walk_order_end: End of walk order range
 
        Returns: The created template row
        """
        return self.db.execute_query("""
            INSERT INTO folder_templates (client_id, folder_number, folder_name,
                                          walk_order_start, walk_order_end)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
        """, (client_id, folder_number, folder_name, walk_order_start, walk_order_end),
            fetch="one", commit=True)
    
    # --- READ: 
 
    def get_by_id(self, template_id: int) -> Optional[dict]:
        """Get single template by ID, or None if not found"""
        return self.db.execute_query(
            "SELECT * FROM folder_templates WHERE template_id = %s",
            (template_id,), fetch="one")
 
    def list_by_client(self, client_id: int) -> List[dict]:
        """Get all templates for a client, ordered by folder number"""
        return self.db.execute_query("""
            SELECT * FROM folder_templates
            WHERE client_id = %s
            ORDER BY folder_number
        """, (client_id,), fetch="all")
 
    def count_by_client(self, client_id: int) -> int:
        """Count templates for a client"""
        result = self.db.execute_query(
            "SELECT COUNT(*) as count FROM folder_templates WHERE client_id = %s",
            (client_id,),
            fetch="one"
        )
        return result['count']
    
    # --- UPDATE:
 
    def update(self, template_id: int, updates: Dict[str, Any]) -> bool:
        """
        Update template fields dynamically.
 
        Args:
            template_id: Template ID
            updates: Dict of fields to update, e.g. {'folder_name': 'תיק צפון'}
 
        Returns: True if a row was updated
        """
        if not updates:
            return False
 
        set_clauses = []
        params = []
 
        for field, value in updates.items():
            set_clauses.append(f"{field} = %s")
            params.append(value)
 
        params.append(template_id)
        query = f"UPDATE folder_templates SET {', '.join(set_clauses)} WHERE template_id = %s"
 
        rows = self.db.execute_query(query, params, commit=True)
        return rows > 0
    
    # --- DELETE:
 
    def delete(self, template_id: int) -> bool:
        """
        Delete single template.
 
        Returns: True if a row was deleted
        """
        rows = self.db.execute_query(
            "DELETE FROM folder_templates WHERE template_id = %s",
            (template_id,), commit=True)
        return rows > 0
 
    def delete_all_by_client(self, client_id: int) -> int:
        """
        Delete all templates for a client.
 
        Returns: Number of deleted templates
        """
        return self.db.execute_query(
            "DELETE FROM folder_templates WHERE client_id = %s",
            (client_id,), commit=True)