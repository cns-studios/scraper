
import os
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor, Json
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

db_pool = None

def init_db_pool():
    """Initializes the database connection pool."""
    global db_pool
    if db_pool is None:
        try:
            db_pool = psycopg2.pool.SimpleConnectionPool(1, 10, dsn=DATABASE_URL)
        except psycopg2.OperationalError as e:
            logger.error(f"Could not connect to the database: {e}", exc_info=True)
            raise

def get_db_connection():
    """Gets a connection from the pool."""
    if db_pool is None:
        init_db_pool()
    return db_pool.getconn()

def release_db_connection(conn):
    """Releases a connection back to the pool."""
    if db_pool:
        db_pool.putconn(conn)

def close_db_pool():
    """Closes all connections in the pool."""
    if db_pool:
        db_pool.closeall()

def setup_database():
    """Creates the necessary tables in the database if they don't already exist."""
    commands = (
        """
        CREATE TABLE IF NOT EXISTS runs (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            start_url TEXT NOT NULL,
            stats JSONB,
            domain_counts JSONB,
            status TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS pages (
            id SERIAL PRIMARY KEY,
            run_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            content_type TEXT,
            filepath TEXT,
            depth INTEGER,
            size INTEGER,
            domain TEXT,
            FOREIGN KEY (run_id) REFERENCES runs (id) ON DELETE CASCADE
        );
        """
    )
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        for command in commands:
            cur.execute(command)
        cur.close()
        conn.commit()
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(error)
    finally:
        if conn is not None:
            release_db_connection(conn)

def create_run(start_url, status="running"):
    """Creates a new run in the database and returns the run ID."""
    sql = """INSERT INTO runs(start_url, status) VALUES(%s, %s) RETURNING id;"""
    conn = None
    run_id = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(sql, (start_url, status))
        run_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(error)
    finally:
        if conn is not None:
            release_db_connection(conn)
    return run_id

def update_run(run_id, stats, domain_counts, status="completed"):
    """Updates a run with stats, domain_counts, and status."""
    sql = """UPDATE runs SET stats = %s, domain_counts = %s, status = %s WHERE id = %s;"""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(sql, (Json(stats), Json(domain_counts), status, run_id))
        conn.commit()
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(error)
    finally:
        if conn is not None:
            release_db_connection(conn)

def insert_page(run_id, url, content_type, filepath, depth, size, domain):
    """Inserts a new page into the database."""
    sql = """INSERT INTO pages(run_id, url, content_type, filepath, depth, size, domain)
             VALUES(%s, %s, %s, %s, %s, %s, %s);"""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(sql, (run_id, url, content_type, filepath, depth, size, domain))
        conn.commit()
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(error)
    finally:
        if conn is not None:
            release_db_connection(conn)

def get_runs_from_db():
    """Retrieves all runs from the database."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM runs ORDER BY timestamp DESC;")
        runs = cur.fetchall()
        cur.close()
        return runs
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(error)
        return []
    finally:
        if conn is not None:
            release_db_connection(conn)

def get_run_details_from_db(run_id):
    """Retrieves the details for a specific run."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM runs WHERE id = %s;", (run_id,))
        run = cur.fetchone()
        cur.close()
        return run
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(error)
        return None
    finally:
        if conn is not None:
            release_db_connection(conn)

def get_run_pages_from_db(run_id, page=1, per_page=50, search=None, domain_filter=None):
    """Retrieves pages for a specific run with pagination and filtering."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        base_query = "FROM pages WHERE run_id = %s"
        params = [run_id]

        if search:
            base_query += " AND (url ILIKE %s OR domain ILIKE %s)"
            params.extend([f"%{search}%", f"%{search}%"])

        if domain_filter:
            base_query += " AND domain = %s"
            params.append(domain_filter)

        # Get total count
        cur.execute(f"SELECT COUNT(*) {base_query}", tuple(params))
        total = cur.fetchone()['count']

        # Get paginated results
        offset = (page - 1) * per_page
        query = f"SELECT * {base_query} ORDER BY timestamp DESC LIMIT %s OFFSET %s"
        params.extend([per_page, offset])

        cur.execute(query, tuple(params))
        pages = cur.fetchall()

        cur.close()
        return pages, total
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(error)
        return [], 0
    finally:
        if conn is not None:
            release_db_connection(conn)

if __name__ == '__main__':
    init_db_pool()
    setup_database()
    close_db_pool()
    logger.info("Database setup complete.")
