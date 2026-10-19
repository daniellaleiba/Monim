"""  
Period Meter Repository - Data Access Layer


Data access for period_meters: the core, highest-traffic table in the system. 
Handles bulk creation from parsed files, folder assignment (single + bulk), work-status transitions, current-state updates after
readings, shared-consumption writes, and the aggregate status-count query used by the dashboard/meters screen.
"""
 
from database.connection import Database
from typing import List, Optional, Dict, Any
from psycopg2.extras import Json
 
 
class PeriodMeterRepository:
    """
    Data Access Layer for period_meters table.
 
    This is the CORE entity of the system - one meter row inside a specific period.
 
    Responsibilities:
        - bulk insert of meters (from parsed source file)
        - get by id / period / folder / meter_number
        - update folder assignment
        - update work status
        - update current state fields (after reading)
        - filtering queries (unassigned, exceptions, by status)
        - counting queries
 
    Note: PeriodMeter holds the CURRENT state of a meter in a period.
          Reading history is stored in the readings table.
          This repository does not manage readings - ReadingRepository does.
 
    Relevant indexes:
        - idx_period_meters_status (period_id, work_status)
        - idx_period_meters_walk_order (walk_order)
        - idx_period_meters_folder (folder_id)
    """
    def __init__(self):
        self.db = Database()
    
    # --- CREATE:
 
    def bulk_create(self, period_id: int, source_file_id: int, rows: List[dict]) -> int:
        """
        Insert multiple period meters from parsed source file rows.
        Uses get_cursor for efficient bulk insert.
 
        Args:
            period_id: Reading period ID
            source_file_id: Source file these rows came from
            rows: List of normalized dicts from parser. Each dict should contain:
                  row_number, meter_number, customer_number, customer_name,
                  address, walk_order, previous_reading, installation_date, raw_data.
                  Optional: work_status (defaults to 'new' if not set, the parser sets it to 'missing_info' upstream when required fields are absent)
 
        Returns: Number of rows inserted
        """
        if not rows:
            return 0
 
        with self.db.get_cursor(commit=True) as cur:
            for row in rows:
                cur.execute("""
                    INSERT INTO period_meters
                        (period_id, source_file_id, row_number, meter_number,
                         customer_number, customer_name, address, walk_order,
                         previous_reading, installation_date, raw_data, work_status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    period_id,
                    source_file_id,
                    row.get('row_number'),
                    row.get('meter_number'),
                    row.get('customer_number'),
                    row.get('customer_name'),
                    row.get('address'),
                    row.get('walk_order'),
                    row.get('previous_reading'),
                    row.get('installation_date'),
                    # raw_data (JSONB): wrap in Json() for psycopg2, or None if not provided
                    Json(row.get('raw_data')) if row.get('raw_data') else None,
                    row.get('work_status', 'new')
                ))
 
            return len(rows)
 
    # --- READ: Single record
 
    def get_by_id(self, period_meter_id: int) -> Optional[dict]:
        """Get single period meter by ID, or None if not found"""
        return self.db.execute_query(
            "SELECT * FROM period_meters WHERE period_meter_id = %s",
            (period_meter_id,), fetch="one")
    
    def get_by_ids(self, period_meter_ids: List[int]) -> List[dict]:
        """
        Get multiple period meters by their IDs in a single query.
        Silently omits any IDs that don't exist.
        """
        if not period_meter_ids:
            return []
        return self.db.execute_query( "SELECT * FROM period_meters WHERE period_meter_id = ANY(%s)",
            (period_meter_ids,), fetch="all")
    
    def get_by_period_and_meter_number(self, period_id: int, meter_number: str) -> Optional[dict]:
        """
        Get meter by period + meter number (business identity).
        UNIQUE(period_id, meter_number) guarantees at most one result.
        """
        return self.db.execute_query("""
            SELECT * FROM period_meters
            WHERE period_id = %s AND meter_number = %s
        """, (period_id, meter_number), fetch="one")

    # --- READ: Lists
 
    def list_by_period(self, period_id: int) -> List[dict]:
        """
        Get all meters for a period, ordered by walk_order.
        Uses index: idx_period_meters_status (covers period_id queries via composite)
        """
        return self.db.execute_query("""
            SELECT * FROM period_meters
            WHERE period_id = %s
            ORDER BY walk_order, meter_number
        """, (period_id,), fetch="all")
    
    def list_by_folder(self, folder_id: int) -> List[dict]:
        """
        Get all meters assigned to a specific work folder.
        Uses index: idx_period_meters_folder
        """
        return self.db.execute_query("""
            SELECT * FROM period_meters
            WHERE folder_id = %s
            ORDER BY walk_order, meter_number
        """, (folder_id,), fetch="all")
    
    def list_unassigned_by_period(self, period_id: int) -> List[dict]:
        """
        Get all meters in a period that are NOT assigned to any folder yet.
        folder_id is NULL until assignment.
        """
        return self.db.execute_query("""
            SELECT * FROM period_meters
            WHERE period_id = %s AND folder_id IS NULL
            ORDER BY walk_order, meter_number
        """, (period_id,), fetch="all")
 
    def list_by_work_status(self, period_id: int, work_status: str) -> List[dict]:
        """
        Get all meters in a period with a specific work status.
        Uses index: idx_period_meters_status
        """
        return self.db.execute_query("""
            SELECT * FROM period_meters
            WHERE period_id = %s AND work_status = %s
            ORDER BY walk_order, meter_number
        """, (period_id, work_status), fetch="all")
    
    def list_exceptions_by_period(self, period_id: int) -> List[dict]:
        """
        Get all meters in exception status for a period.
        Shorthand for list_by_work_status with 'exception'.
        """
        return self.list_by_work_status(period_id, 'exception')
    
    def list_meters_for_shared_consumption(self, period_id: int, folder_id: int = None) -> List[dict]:
        """
        Get all meters relevant for shared consumption calculation.
        Returns main meters (usage_type='1') and apartment meters (usage_type='5').
        
        Used by SharedConsumptionService to build building groups.
        Single query for efficiency - grouping is done in the service layer.

        Args:
            period_id: Reading period ID
            folder_id: Optional - restrict to a specific folder

        Returns: List of meter rows ordered by address, then usage_type
        """
        base = """
            SELECT * FROM period_meters
            WHERE period_id = %s
            AND raw_data->>'usage_type' IN ('1', '5')
        """
        params = [period_id]
        if folder_id:
            base += " AND folder_id = %s"
            params.append(folder_id)
        base += " ORDER BY address, raw_data->>'usage_type'"
        return self.db.execute_query(base, params, fetch="all")

    # --- UPDATE: Folder assignment
 
    def update_folder_assignment(self, period_meter_id: int, folder_id: int) -> bool:
        """
        Assign a meter to a work folder.
        Note: Service must verify folder belongs to same period as meter.
 
        Returns: True if updated
        """
        rows = self.db.execute_query("""
            UPDATE period_meters
            SET folder_id = %s, updated_at = CURRENT_TIMESTAMP
            WHERE period_meter_id = %s
        """, (folder_id, period_meter_id), commit=True)
        return rows > 0
 
    def bulk_update_folder_assignment(self, period_meter_ids: List[int], folder_id: int) -> int:
        """
        Assign multiple meters to a work folder in one transaction.
        More efficient than calling update_folder_assignment in a loop.
 
        Returns: Number of rows updated
        """
        if not period_meter_ids:
            return 0
 
        with self.db.get_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE period_meters
                SET folder_id = %s, updated_at = CURRENT_TIMESTAMP
                WHERE period_meter_id = ANY(%s)
            """, (folder_id, period_meter_ids))
            return cur.rowcount
 
    def clear_folder_assignment(self, period_meter_id: int) -> bool:
        """
        Remove meter from its work folder (set folder_id to NULL).
        
           Note: currently unused, superseded by release_folder_meters(), which also resets work_status appropriately. 
            Kept for potential direct use (e.g. moving a single meter between folders without a full release)

        Returns: True if updated
        """
        rows = self.db.execute_query("""
            UPDATE period_meters
            SET folder_id = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE period_meter_id = %s
        """, (period_meter_id,), commit=True)
        return rows > 0
    
    def release_folder_meters(self, folder_id: int) -> int:
        """
        Release all meters from a folder back to unassigned state.
        Sets folder_id = NULL and work_status = 'new' (except meters already 'completed', which keep their status).
        Called before deleting a work folder.

        Returns: Number of meters released
        Uses index: idx_period_meters_folder
        """
        return self.db.execute_query("""
            UPDATE period_meters
            SET folder_id   = NULL,
                work_status = CASE 
                WHEN work_status = 'completed' THEN 'completed'
                ELSE 'new'
                END,
                updated_at  = CURRENT_TIMESTAMP
            WHERE folder_id = %s
        """, (folder_id,), commit=True)
 
    # --- UPDATE: Work status

    def update_work_status(self, period_meter_id: int, work_status: str) -> bool:
        """
        Update work status of a meter.
        Valid statuses: 'new', 'assigned_to_folder', 'assigned_to_reader', 'in_progress', 'completed', 'exception', 'missing_info'
        (validation of allowed transitions is done by Service)
 
        Returns: True if updated
        """
        rows = self.db.execute_query("""
            UPDATE period_meters
            SET work_status = %s, updated_at = CURRENT_TIMESTAMP
            WHERE period_meter_id = %s
        """, (work_status, period_meter_id), commit=True)
        return rows > 0
    
    def update_fault_code(self, period_meter_id: int, fault_code: str | None):
        """
        Update the current fault code for a meter. Pass None to clear it.

            Note: unlike update_current_state(), a None value here is meaningful: it explicitly writes NULL to current_fault_code. update_current_state()
                treats None as "field not provided" and skips it entirely. Use this method when you specifically want to clear the fault code; use
                update_current_state() when updating other fields without touching the fault code.

        Returns: True if updated
        """
        sql = """
            UPDATE period_meters
            SET current_fault_code = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE period_meter_id = %s
        """
        rows = self.db.execute_query(sql, (fault_code, period_meter_id), commit=True)
        return rows > 0

    def update_manager_notes(self, period_meter_id: int, manager_notes: str | None) -> bool:
        """
        Update the manager notes for a meter. Pass None to clear them.

            Note: like update_fault_code(), a None value here is meaningful: it explicitly
                writes NULL to manager_notes. update_current_state() treats None as
                "field not provided" and skips it.

        Returns: True if updated
        """
        rows = self.db.execute_query("""
            UPDATE period_meters
            SET manager_notes = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE period_meter_id = %s
        """, (manager_notes, period_meter_id), commit=True)
        return rows > 0

    # --- UPDATE: Current state (after reading) 
 
    def update_current_state(self, period_meter_id: int, fault_code: str = None, manager_notes: str = None, current_reading: float = None, consumption: float = None, addon: float = None, reading_time=None,  is_estimated: bool = None) -> bool:
        """
        Update the current operational state of a meter.
        Called after a new reading is received, or by manager review.
        Only updates fields that are not None, None means "leave this field unchanged", not "clear it".

        Note: to explicitly clear fault_code (set it to NULL), use update_fault_code() instead, it treats None as a real value to write.

        Returns: True if updated
        """
        updates = []
        params = []
 
        if fault_code is not None:
            updates.append("current_fault_code = %s")
            params.append(fault_code)
 
        if manager_notes is not None:
            updates.append("manager_notes = %s")
            params.append(manager_notes)
        
        if current_reading is not None:
            updates.append("current_reading = %s")
            params.append(current_reading)

        if consumption is not None:
            updates.append("consumption = %s")
            params.append(consumption)

        if addon is not None:
            updates.append("addon = %s")
            params.append(addon)

        if reading_time is not None:
            updates.append("reading_time = %s")
            params.append(reading_time)
        
        if is_estimated is not None:
            updates.append("is_estimated = %s")
            params.append(is_estimated)

        if not updates:
            return False
 
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(period_meter_id)
 
        query = f"""
            UPDATE period_meters
            SET {', '.join(updates)}
            WHERE period_meter_id = %s
        """
        rows = self.db.execute_query(query, params, commit=True)
        return rows > 0
    
    def bulk_update_estimated(self, updates: list) -> int:
        """
        Bulk update current_reading, consumption, addon and is_estimated=True
        for multiple meters in a single transaction.
        
        Args:
            updates: list of dicts, each with required keys period_meter_id,
             current_reading, consumption, and optional key addon (missing addon is treated as NULL)
        
        Returns: number of meters updated
        """
        if not updates:
            return 0
        
        with self.db.get_cursor(commit=True) as cur:
            for u in updates:
                cur.execute("""
                    UPDATE period_meters
                    SET current_reading = %s,
                        consumption     = %s,
                        addon           = %s,
                        is_estimated    = TRUE,
                        updated_at      = CURRENT_TIMESTAMP
                    WHERE period_meter_id = %s
                """, ( u['current_reading'], u['consumption'], u.get('addon'),u['period_meter_id'],))
            return len(updates)

    def reset_shared_consumption_by_prefix(self, period_id: int, building_key: str) -> None:
        """
        Reset shared_consumption to NULL for all meters in a building.
        Building = first N digits of meter_id (the building_key).
        """
        self.db.execute_query("""
            UPDATE period_meters
            SET shared_consumption = NULL
            WHERE period_id = %s
            AND raw_data->>'meter_id' LIKE %s
        """, (period_id, building_key + '%'), commit=True)
        
    def bulk_update_shared_consumption(self, updates: list) -> int:
        """
        Bulk update shared_consumption for multiple meters in one transaction.
        Called by SharedConsumptionService after calculating per-building shared value.

        Args:
            updates: list of dicts with keys: period_meter_id, shared_consumption

        Returns: Number of meters updated
        """
        if not updates:
            return 0

        with self.db.get_cursor(commit=True) as cur:
            for u in updates:
                cur.execute("""
                    UPDATE period_meters
                    SET shared_consumption = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE period_meter_id = %s
                """, (u['shared_consumption'], u['period_meter_id']))
            return len(updates)

    # --- COUNTS: 
 
    def count_by_period(self, period_id: int) -> int:
        """Count total meters in a period"""
        result = self.db.execute_query(
            "SELECT COUNT(*) as count FROM period_meters WHERE period_id = %s",(period_id,),fetch="one")
        return result['count']
 
    def count_by_folder(self, folder_id: int) -> int:
        """Count meters in a specific folder"""
        result = self.db.execute_query(
            "SELECT COUNT(*) as count FROM period_meters WHERE folder_id = %s",(folder_id,),fetch="one")
        return result['count']
 
    def count_unassigned_by_period(self, period_id: int) -> int:
        """Count meters in a period that are not assigned to any folder"""
        result = self.db.execute_query(""" SELECT COUNT(*) as count FROM period_meters
            WHERE period_id = %s AND folder_id IS NULL""", (period_id,), fetch="one")
        return result['count']
 
    def count_by_work_status_and_folder(self, folder_id: int, work_status: str) -> int:
        """
        Count meters in a folder by work status.
        Used to calculate folder progress (e.g. how many are 'completed').

        Returns: Count of matching meters (0 if none found)
        Uses index: idx_period_meters_folder (folder_id)
        """
        result = self.db.execute_query("""SELECT COUNT(*) as cnt FROM period_meters 
            WHERE folder_id = %s AND work_status = %s""",(folder_id, work_status), fetch="one")
        return result['cnt'] if result else 0

    def get_status_summary(self, period_id: int) -> dict:
        """
        Get all status counts for a period in a single query.
        Replaces 9 separate COUNT calls in get_period_status_summary().
        """
        rows = self.db.execute_query(""" SELECT 
                work_status,
                COUNT(*) as cnt,
                SUM(CASE WHEN folder_id IS NULL THEN 1 ELSE 0 END) as unassigned_cnt
            FROM period_meters
            WHERE period_id = %s
            GROUP BY work_status""", (period_id,), fetch="all")

        summary = {'total': 0, 'unassigned': 0, 'new': 0, 'assigned_to_folder': 0, 
            'assigned_to_reader': 0, 'in_progress': 0, 'completed': 0, 'exception': 0, 'missing_info': 0}
        for row in rows:
            status = row['work_status']
            cnt = row['cnt']
            summary['total'] += cnt
            summary['unassigned'] += row['unassigned_cnt']
            if status in summary:
                summary[status] = cnt

        return summary

    # --- DELETE:
 
    def delete_by_source_file(self, source_file_id: int) -> int:
        """
        Delete all meters created from a specific source file.
        Used when replacing a file or retrying failed processing.
 
        Returns: Number of deleted meters
        """
        return self.db.execute_query(
            "DELETE FROM period_meters WHERE source_file_id = %s",
            (source_file_id,), commit=True)
 
