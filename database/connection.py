
"""
Database connection manager for the Monim system.
Purpose:
    Centralizes all PostgreSQL connection handling for the application.

Database usage guidelines:
1. Use execute_query() for most repository CRUD operations (One record / list).
2. Use get_cursor() when a single logical action includes multiple queries
   or requires a managed transaction.
3. Use get_connection() only for special low-level cases such as bulk work
   or advanced psycopg2 usage (Raw access to a connection from the pool).
4. Repositories should avoid managing raw connections unless truly needed.
    -> Repositories work primarily with execute_query()
5. commit=True is required only for INSERT / UPDATE / DELETE operations.
6. fetch="one" is used when expecting a single row.
7. fetch="all" is used when expecting multiple rows.
"""
import os
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

class Database:
    """
    Singleton database manager with connection pooling.

    Main goals:
    - Keep one shared connection pool for the app
    - Provide a safe high-level API for most repositories
    - Still allow raw connection access for special cases (bulk, advanced transactions)
    """

    _instance = None
    _pool = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Database, cls).__new__(cls)
            cls._instance._initialize_pool()
        return cls._instance
    
    def _initialize_pool(self):
        """Initialize connection pool once"""
        if self._pool is None:
            self._pool = pool.SimpleConnectionPool(
                minconn=1,
                maxconn=10,  # Maximum 10 concurrent connections
                host=os.getenv('DB_HOST'),
                port=int(os.getenv('DB_PORT')),
                database=os.getenv('DB_NAME'),
                user=os.getenv('DB_USER'),
                password=os.getenv('DB_PASSWORD')
            )
            print(f"[OK] DB Pool initialized: {os.getenv('DB_HOST')}/{os.getenv('DB_NAME')}")
    

    def get_connection(self):
        """
        Get a raw connection from the pool.
        
        Use only for special cases:
        - bulk inserts
        - complex multi-step transactions
        - low-level DB operations
        """
        return self._pool.getconn()
    
    def return_connection(self, conn):
        """Return a raw connection back to the pool"""
        if conn:
            self._pool.putconn(conn)
    
    @contextmanager
    def get_cursor(self, dict_cursor: bool = True, commit: bool = False):
        """
        Context manager for safe DB cursor usage.

        Responsibilities (Handles automatically):
        - Acquire a connection from pool
        - create a cursor
        - commit on success (if commit=True)
        - rollback on error/faliure
        - return the connection to the pool
        """
        conn = self._pool.getconn()
        cursor_factory = RealDictCursor if dict_cursor else None

        try:
            with conn.cursor(cursor_factory=cursor_factory) as cur:
                yield cur

            if commit:
                conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            self._pool.putconn(conn)
    
    def execute_query( self, query: str, params=None,
        fetch: str | None = None, commit: bool = False):
        """
        Execute a SQL query safely.

        Args:
            query: SQL statement
            params: Query parameters
            fetch:
                "one"  -> return single row
                "all"  -> return list of rows
                None   -> return affected row count
            commit: commit transaction after execution

        Returns: dict | list[dict] | int
        """
        with self.get_cursor(dict_cursor=True, commit=commit) as cur:
            cur.execute(query, params or ())

            if fetch == "one":
                return cur.fetchone()

            if fetch == "all":
                return cur.fetchall()

            return cur.rowcount
        
    def execute_script(self, filepath: str):
        """
        Execute a full SQL script file.
        Useful for schema creation or seed scripts.
        """
        conn = self._pool.getconn()
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                sql = f.read()

            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            self._pool.putconn(conn)

    def test_connection(self) -> bool:
        """Check if DB connection works."""
        try:
            result = self.execute_query("SELECT 1 AS ok;", fetch="one")
            return bool(result and result["ok"] == 1)
        except Exception:
            return False
        
    def close(self) -> None:
        """
        Close all connections in the pool.
        Usually called on app shutdown.
        """
        if self._pool:
            self._pool.closeall()
            print("[OK] DB Pool closed")
    
    @classmethod
    def shutdown(cls) -> None:
        """
        Shutdown the singleton instance and its pool.
        """
        if cls._instance and cls._instance._pool:
            cls._instance._pool.closeall()
            print("[OK] DB Pool shutdown")
            cls._instance = None
            cls._pool = None
