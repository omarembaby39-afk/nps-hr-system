
import streamlit as st
import psycopg2
import pandas as pd
import bcrypt


def get_conn():
    try:
        conn_str = st.secrets["postgres"]["conn"]
        return psycopg2.connect(conn_str)
    except Exception:
        st.error("Database connection failed. Check Streamlit Secrets.")
        st.stop()


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS workers (
            id BIGSERIAL PRIMARY KEY,
            worker_code TEXT,
            name TEXT NOT NULL,
            role TEXT,
            trade TEXT,
            salary NUMERIC,
            visa_expiry DATE,
            photo_url TEXT,
            phone TEXT
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            held INTEGER DEFAULT 0
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS project_workers (
            project_id BIGINT REFERENCES projects(id) ON DELETE CASCADE,
            worker_id BIGINT REFERENCES workers(id) ON DELETE CASCADE,
            PRIMARY KEY (project_id, worker_id)
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance (
            id BIGSERIAL PRIMARY KEY,
            worker_id BIGINT REFERENCES workers(id) ON DELETE CASCADE,
            project_id BIGINT REFERENCES projects(id) ON DELETE CASCADE,
            att_date DATE,
            signed_in INTEGER DEFAULT 0,
            time_in TEXT,
            time_out TEXT
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL
        );
        """
    )

    conn.commit()
    conn.close()


def add_worker(worker_code, name, role, trade, salary, visa_expiry, phone, photo_url):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO workers
            (worker_code, name, role, trade, salary, visa_expiry, phone, photo_url)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (worker_code, name, role, trade, salary, visa_expiry, phone, photo_url),
    )
    conn.commit()
    conn.close()


def get_workers():
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM workers ORDER BY name", conn)
    conn.close()
    return df


def update_worker(worker_id, name, role, trade, salary, visa_expiry, phone, photo_url):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE workers
        SET name=%s, role=%s, trade=%s, salary=%s,
            visa_expiry=%s, phone=%s, photo_url=%s
        WHERE id=%s
        """,
        (name, role, trade, salary, visa_expiry, phone, photo_url, worker_id),
    )
    conn.commit()
    conn.close()


def delete_worker(worker_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM workers WHERE id=%s", (worker_id,))
    conn.commit()
    conn.close()


def add_project(name, held):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO projects (name, held) VALUES (%s,%s)", (name, held))
    conn.commit()
    conn.close()


def get_projects():
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM projects ORDER BY id", conn)
    conn.close()
    return df


def update_project(project_id, name, held):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE projects SET name=%s, held=%s WHERE id=%s",
        (name, held, project_id),
    )
    conn.commit()
    conn.close()


def delete_project(project_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM projects WHERE id=%s", (project_id,))
    conn.commit()
    conn.close()


def assign_worker_to_project(project_id, worker_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO project_workers (project_id, worker_id)
        VALUES (%s,%s)
        ON CONFLICT DO NOTHING
        """,
        (project_id, worker_id),
    )
    conn.commit()
    conn.close()


def unassign_worker(project_id, worker_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM project_workers WHERE project_id=%s AND worker_id=%s",
        (project_id, worker_id),
    )
    conn.commit()
    conn.close()


def get_assignments():
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM project_workers", conn)
    conn.close()
    return df


def mark_attendance(worker_id, project_id, date_str, present, time_in, time_out):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM attendance WHERE worker_id=%s AND att_date=%s",
        (worker_id, date_str),
    )
    if present:
        cur.execute(
            """
            INSERT INTO attendance
                (worker_id, project_id, att_date, signed_in, time_in, time_out)
            VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (worker_id, project_id, date_str, 1, time_in, time_out),
        )
    conn.commit()
    conn.close()


def get_attendance(date_str):
    conn = get_conn()
    df = pd.read_sql(
        "SELECT * FROM attendance WHERE att_date=%s",
        conn,
        params=(date_str,),
    )
    conn.close()
    return df


def get_attendance_range(start, end):
    conn = get_conn()
    df = pd.read_sql(
        """
        SELECT * FROM attendance
        WHERE att_date >= %s AND att_date < %s AND signed_in=1
        """,
        conn,
        params=(start, end),
    )
    conn.close()
    return df


def create_user(username, password, role):
    conn = get_conn()
    cur = conn.cursor()
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    cur.execute(
        """
        INSERT INTO users (username, password_hash, role)
        VALUES (%s,%s,%s)
        ON CONFLICT (username) DO NOTHING
        """,
        (username, hashed, role),
    )
    conn.commit()
    conn.close()


def get_user(username):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=%s", (username,))
    row = cur.fetchone()
    conn.close()
    return row


def check_password(username, password):
    user = get_user(username)
    if not user:
        return False, None
    stored_hash = user[2]
    try:
        if bcrypt.checkpw(password.encode(), stored_hash.encode()):
            return True, user
    except Exception:
        return False, None
    return False, None
