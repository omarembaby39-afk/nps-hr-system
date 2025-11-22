# ===================== NPS HR SYSTEM – PART 1 =====================
import streamlit as st
import sqlite3
import pandas as pd
from datetime import date, datetime, timedelta, time
from dateutil.relativedelta import relativedelta
import io
import os
import base64
import calendar

# Optional PDF support
try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm

    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

# ---------- Branding ----------
BRAND_RED = "#ff2b4d"
BRAND_DARK_BLUE = "#003388"
BRAND_LIGHT_BLUE = "#00a6df"
BRAND_BG = "#0b1020"  # dark sidebar background

# ---------- Paths ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PHOTOS_DIR = os.path.join(DATA_DIR, "photos")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PHOTOS_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "hr.db")
TODAY = date.today()

# ---------- Payroll Policy ----------
STANDARD_DAILY_HOURS = 9
OVERTIME_MULTIPLIER = 1.0  # OT x1


# ===================== DB HELPERS =====================
def get_connection():
    return sqlite3.connect(DB_PATH)


def init_db():
    """Create tables & sample data if empty."""
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_code TEXT,
            name TEXT NOT NULL,
            role TEXT,
            trade TEXT,
            salary REAL,
            visa_expiry DATE,
            photo_file TEXT
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            held INTEGER DEFAULT 0
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS project_workers (
            project_id INTEGER,
            worker_id INTEGER,
            PRIMARY KEY (project_id, worker_id),
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (worker_id) REFERENCES workers(id)
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id INTEGER,
            project_id INTEGER,
            att_date DATE,
            signed_in INTEGER DEFAULT 0,
            time_in TEXT,
            time_out TEXT,
            FOREIGN KEY (worker_id) REFERENCES workers(id),
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )
        """
    )

    # Add missing columns if DB existed before
    c.execute("PRAGMA table_info(attendance)")
    cols = [r[1] for r in c.fetchall()]
    if "time_in" not in cols:
        c.execute("ALTER TABLE attendance ADD COLUMN time_in TEXT")
    if "time_out" not in cols:
        c.execute("ALTER TABLE attendance ADD COLUMN time_out TEXT")

    c.execute("PRAGMA table_info(workers)")
    wcols = [r[1] for r in c.fetchall()]
    if "worker_code" not in wcols:
        c.execute("ALTER TABLE workers ADD COLUMN worker_code TEXT")
    if "photo_file" not in wcols:
        c.execute("ALTER TABLE workers ADD COLUMN photo_file TEXT")

    # Seed sample data
    c.execute("SELECT COUNT(*) FROM workers")
    if c.fetchone()[0] == 0:
        sample_workers = [
            ("NPS-W0001", "Ahmed Ali", "Technician", "HVAC", 5000, "2026-01-01", None),
            ("NPS-W0002", "Mohamed Hassan", "Engineer", "Plumbing", 7000, "2025-12-15", None),
            ("NPS-W0003", "Fatima Salem", "Helper", "Fire", 3000, "2025-11-30", None),
            ("NPS-W0004", "Omar Khalid", "Supervisor", "HVAC", 6000, "2026-02-01", None),
            ("NPS-W0005", "Layla Nour", "Technician", "Plumbing", 4500, "2025-12-20", None),
            ("NPS-W0006", "Sara Ahmed", "Accountant", "Admin", 5500, "2026-03-01", None),
            ("NPS-W0007", "Ali Driver", "Driver", "Logistics", 4000, "2025-10-15", None),
        ]
        c.executemany(
            """
            INSERT INTO workers (worker_code, name, role, trade, salary, visa_expiry, photo_file)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            sample_workers,
        )

        sample_projects = [
            ("MEP Install - Bldg A", 0),
            ("Fire System Upgrade - Site B", 1),
            ("HVAC Retrofit - Office C", 0),
        ]
        c.executemany("INSERT INTO projects (name, held) VALUES (?, ?)", sample_projects)

        assignments = [
            (1, 1),
            (1, 2),
            (1, 3),
            (1, 4),
            (1, 5),
            (1, 6),
            (2, 3),
            (2, 5),
            (2, 7),
            (3, 1),
            (3, 2),
            (3, 4),
            (3, 6),
        ]
        c.executemany(
            "INSERT OR IGNORE INTO project_workers (project_id, worker_id) VALUES (?, ?)",
            assignments,
        )

        # Sample attendance last week
        today = TODAY
        for i in range(7):
            d = (today - timedelta(days=i)).isoformat()
            rows = [
                (1, 1, d, 1, "07:00", "16:30"),
                (2, 1, d, 1, "07:30", "17:15"),
                (3, 3, d, 1 if i != 3 else 0, "08:00", "18:00"),
            ]
            c.executemany(
                """
                INSERT INTO attendance (worker_id, project_id, att_date, signed_in, time_in, time_out)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    conn.commit()
    conn.close()


# ===================== HR / PAYROLL UTILITIES =====================
def generate_next_worker_code():
    conn = get_connection()
    df = pd.read_sql("SELECT worker_code FROM workers WHERE worker_code IS NOT NULL", conn)
    conn.close()
    if df.empty:
        return "NPS-W0001"
    max_num = 0
    for code in df["worker_code"].dropna():
        if code.startswith("NPS-W"):
            try:
                num = int(code.replace("NPS-W", ""))
                max_num = max(max_num, num)
            except ValueError:
                continue
    return f"NPS-W{max_num + 1:04d}"


def get_visa_status(expiry_str):
    if not expiry_str:
        return "gray", "No Visa", "⚪"
    try:
        expiry = date.fromisoformat(expiry_str)
        if expiry > TODAY + relativedelta(months=1):
            return "green", "Valid (>1 month)", "🟢"
        else:
            return "red", "Expiring ≤1 month", "🔴"
    except Exception:
        return "gray", "Invalid Date", "⚪"


def _hours_between(t_in, t_out):
    """Return hours between HH:MM strings. If invalid, 0.0"""
    if not t_in or not t_out:
        return 0.0
    try:
        ti = datetime.strptime(t_in, "%H:%M").time()
        to = datetime.strptime(t_out, "%H:%M").time()
        dt1 = datetime.combine(date.today(), ti)
        dt2 = datetime.combine(date.today(), to)
        h = (dt2 - dt1).total_seconds() / 3600.0
        return max(h, 0.0)
    except Exception:
        return 0.0


def toggle_attendance(worker_id, project_id, att_date, present, time_in=None, time_out=None):
    """Only one row per worker/date. If present=0 → delete."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM attendance WHERE worker_id=? AND att_date=?", (worker_id, att_date))
    if present:
        c.execute(
            """
            INSERT INTO attendance (worker_id, project_id, att_date, signed_in, time_in, time_out)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (worker_id, project_id, att_date, time_in, time_out),
        )
    conn.commit()
    conn.close()


def assign_worker_to_project(project_id, worker_id, assign=True):
    conn = get_connection()
    c = conn.cursor()
    if assign:
        c.execute(
            "INSERT OR IGNORE INTO project_workers (project_id, worker_id) VALUES (?, ?)",
            (project_id, worker_id),
        )
    else:
        c.execute(
            "DELETE FROM project_workers WHERE project_id=? AND worker_id=?",
            (project_id, worker_id),
        )
    conn.commit()
    conn.close()


def get_today_attendance(worker_id, project_id):
    conn = get_connection()
    df = pd.read_sql(
        """
        SELECT signed_in FROM attendance
        WHERE worker_id=? AND project_id=? AND att_date=?
        ORDER BY id DESC LIMIT 1
        """,
        conn,
        params=(worker_id, project_id, TODAY.isoformat()),
    )
    conn.close()
    if df.empty:
        return 0
    return int(df["signed_in"].iloc[0])


def get_project_status(project_id: int):
    """Return (color, label) for project (Held / Active / No workers / No attendance)."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT held FROM projects WHERE id=?", (project_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return "gray", "Unknown"
    held = row[0]
    if held:
        conn.close()
        return "red", "Held"

    c.execute("SELECT worker_id FROM project_workers WHERE project_id=?", (project_id,))
    workers = [r[0] for r in c.fetchall()]
    if not workers:
        conn.close()
        return "yellow", "No Workers"

    placeholders = ",".join(["?"] * len(workers))
    params = [project_id, TODAY.isoformat()] + workers
    c.execute(
        f"""
        SELECT signed_in FROM attendance
        WHERE project_id=? AND att_date=? AND worker_id IN ({placeholders})
        """,
        params,
    )
    rows = c.fetchall()
    conn.close()
    has_sign_in = any(r[0] for r in rows)
    if has_sign_in:
        return "green", "Active (Attendance Today)"
    return "yellow", "No Attendance Today"


def get_global_today_stats():
    conn = get_connection()
    w = pd.read_sql("SELECT COUNT(*) AS total FROM workers", conn)
    p = pd.read_sql(
        "SELECT COUNT(DISTINCT worker_id) AS present FROM attendance WHERE att_date=? AND signed_in=1",
        conn,
        params=(TODAY.isoformat(),),
    )
    proj = pd.read_sql(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN held=1 THEN 1 ELSE 0 END) AS held FROM projects",
        conn,
    )
    conn.close()

    total_workers = int(w["total"].iloc[0]) if not w.empty else 0
    present = int(p["present"].iloc[0]) if not p.empty else 0
    absent = max(total_workers - present, 0)

    total_projects = int(proj["total"].iloc[0]) if not proj.empty else 0
    held = int(proj["held"].iloc[0]) if not proj.empty and proj["held"].iloc[0] is not None else 0
    active = max(total_projects - held, 0)
    return total_workers, present, absent, active, held



def generate_monthly_payroll(year, month, project_id=None):
    """Company-wide or per-project payroll.

    Rules (as per NPS requirement):
    - Fixed month length = 30 days (Fridays already included in monthly salary).
    - Base pay is pro-rated by days PRESENT in the month:
        daily_rate   = salary / 30
        base_earned  = daily_rate * days_present
    - Standard daily hours = STANDARD_DAILY_HOURS (9h).
        hourly_rate  = daily_rate / STANDARD_DAILY_HOURS
    - Overtime = hours above STANDARD_DAILY_HOURS in a day:
        overtime_pay = hourly_rate * overtime_hours * OVERTIME_MULTIPLIER
    - Net pay:
        net_pay      = base_earned + overtime_pay - deductions
      (currently deductions = 0, can be extended later).
    """
    days_in_month = 30

    # Month range
    month_start = date(year, month, 1)
    if month == 12:
        month_end = date(year + 1, 1, 1)
    else:
        month_end = date(year, month + 1, 1)

    conn = get_connection()
    workers = pd.read_sql(
        "SELECT id, worker_code, name, role, trade, salary FROM workers",
        conn,
    )
    att = pd.read_sql(
        """
        SELECT worker_id, project_id, att_date, signed_in, time_in, time_out
        FROM attendance
        WHERE att_date>=? AND att_date<? AND signed_in=1
        """,
        conn,
        params=(month_start.isoformat(), month_end.isoformat()),
    )
    conn.close()

    if workers.empty:
        return None

    if att.empty:
        # No attendance records: zero earned/OT
        df = workers.copy()
        df["days_in_month"] = days_in_month
        df["days_present"] = 0
        df["total_hours"] = 0.0
        df["overtime_hours"] = 0.0
        df["daily_rate"] = df["salary"] / days_in_month
        df["hourly_rate"] = df["daily_rate"] / STANDARD_DAILY_HOURS
        df["overtime_pay"] = 0.0
        df["deductions"] = 0.0
        df["net_pay"] = 0.0
        return df[
            [
                "worker_code",
                "name",
                "role",
                "trade",
                "salary",
                "days_in_month",
                "days_present",
                "total_hours",
                "overtime_hours",
                "hourly_rate",
                "overtime_pay",
                "deductions",
                "net_pay",
            ]
        ]

    # Compute hours and overtime per row
    att["hours"] = att.apply(
        lambda r: _hours_between(r["time_in"], r["time_out"]), axis=1
    )
    att["ot_hours"] = att["hours"].apply(
        lambda h: max(h - STANDARD_DAILY_HOURS, 0.0)
    )

    # Summary across all projects for each worker
    summary_all = att.groupby("worker_id").agg(
        days_present_all=("att_date", "nunique"),
        total_hours_all=("hours", "sum"),
        overtime_hours_all=("ot_hours", "sum"),
    ).reset_index()

    # === Company‑wide payroll (all projects) ===
    if project_id is None:
        df = workers.merge(
            summary_all, left_on="id", right_on="worker_id", how="left"
        )
        df[["days_present_all", "total_hours_all", "overtime_hours_all"]] = df[
            ["days_present_all", "total_hours_all", "overtime_hours_all"]
        ].fillna(0)

        df["days_in_month"] = days_in_month
        df["days_present"] = df["days_present_all"]

        # Base + OT
        df["daily_rate"] = df["salary"] / days_in_month
        df["base_earned"] = df["daily_rate"] * df["days_present"]
        df["hourly_rate"] = df["daily_rate"] / STANDARD_DAILY_HOURS
        df["overtime_pay"] = (
            df["hourly_rate"] * df["overtime_hours_all"] * OVERTIME_MULTIPLIER
        )
        df["deductions"] = 0.0
        df["net_pay"] = (df["base_earned"] + df["overtime_pay"] - df["deductions"]).round(2)

        df["total_hours"] = df["total_hours_all"].round(2)
        df["overtime_hours"] = df["overtime_hours_all"].round(2)
        df["hourly_rate"] = df["hourly_rate"].round(2)
        df["overtime_pay"] = df["overtime_pay"].round(2)

        return df[
            [
                "worker_code",
                "name",
                "role",
                "trade",
                "salary",
                "days_in_month",
                "days_present",
                "total_hours",
                "overtime_hours",
                "hourly_rate",
                "overtime_pay",
                "deductions",
                "net_pay",
            ]
        ]

    # === Per‑project payroll (share of base per project) ===
    att_proj = att[att["project_id"] == project_id].copy()
    if att_proj.empty:
        return pd.DataFrame()

    summary_proj = att_proj.groupby("worker_id").agg(
        days_present=("att_date", "nunique"),
        total_hours=("hours", "sum"),
        overtime_hours=("ot_hours", "sum"),
    ).reset_index()

    df = workers.merge(summary_proj, left_on="id", right_on="worker_id", how="inner")
    df = df.merge(
        summary_all[["worker_id", "total_hours_all", "days_present_all"]],
        on="worker_id",
        how="left",
    )
    df[["total_hours_all", "days_present_all"]] = df[
        ["total_hours_all", "days_present_all"]
    ].fillna(0)

    df["days_in_month"] = days_in_month
    df["daily_rate"] = df["salary"] / days_in_month
    # Total base this month based on all attendance
    df["base_earned_total"] = df["daily_rate"] * df["days_present_all"]

    def _base_share(row):
        if row["total_hours_all"] <= 0:
            return 0.0
        return row["base_earned_total"] * (row["total_hours"] / row["total_hours_all"])

    df["base_share"] = df.apply(_base_share, axis=1)
    df["hourly_rate"] = df["daily_rate"] / STANDARD_DAILY_HOURS
    df["overtime_pay"] = (
        df["hourly_rate"] * df["overtime_hours"] * OVERTIME_MULTIPLIER
    )
    df["deductions"] = 0.0
    df["net_pay"] = (df["base_share"] + df["overtime_pay"] - df["deductions"]).round(2)

    df["total_hours"] = df["total_hours"].round(2)
    df["overtime_hours"] = df["overtime_hours"].round(2)
    df["hourly_rate"] = df["hourly_rate"].round(2)
    df["base_share"] = df["base_share"].round(2)
    df["overtime_pay"] = df["overtime_pay"].round(2)

    return df[
        [
            "worker_code",
            "name",
            "role",
            "trade",
            "salary",
            "days_in_month",
            "days_present",
            "total_hours",
            "overtime_hours",
            "hourly_rate",
            "base_share",
            "overtime_pay",
            "deductions",
            "net_pay",
        ]
    ]
# ===================== ID CARD & PAYSLIP PDFs =====================
def render_id_card(worker_row):
    """HTML preview ID card."""
    worker_code = worker_row["worker_code"] or f"NPS-W{worker_row['id']:04d}"
    name = worker_row["name"]
    role = worker_row.get("role") or ""
    trade = worker_row.get("trade") or ""
    visa = worker_row.get("visa_expiry") or ""

    photo_html = ""
    photo_file = worker_row.get("photo_file")
    if photo_file:
        path = os.path.join(PHOTOS_DIR, photo_file)
        if os.path.exists(path):
            with open(path, "rb") as f:
                b = base64.b64encode(f.read()).decode("utf-8")
            photo_html = (
                '<div style="text-align:center;margin-left:8px;">'
                f'<img src="data:image/png;base64,{b}" '
                'style="width:90px;height:110px;object-fit:cover;'
                'border-radius:8px;border:1px solid #e5e7eb;" />'
                '<div style="font-size:9px;color:#6b7280;margin-top:4px;">Employee Photo</div>'
                "</div>"
            )

    card_html = f"""
    <div style="width:350px;border:2px solid {BRAND_DARK_BLUE};border-radius:14px;
                padding:10px 12px;font-family:Arial, sans-serif;background-color:white;
                box-shadow:0 2px 8px rgba(0,0,0,0.2);">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
          <div style="font-weight:bold;color:{BRAND_DARK_BLUE};font-size:18px;">
            Nile Projects Sevice
          </div>
          <div style="font-size:11px;color:#4b5563;">
            MEP Contracting – Employee ID
          </div>
        </div>
      </div>
      <hr style="border:0;border-top:1px solid #e5e7eb;margin:8px 0;" />
      <div style="display:flex;justify-content:space-between;">
        <div style="font-size:12px;">
          <p style="margin:4px 0;"><strong>ID:</strong> {worker_code}</p>
          <p style="margin:4px 0;"><strong>Name:</strong> {name}</p>
          <p style="margin:4px 0;"><strong>Role:</strong> {role}</p>
          <p style="margin:4px 0;"><strong>Trade:</strong> {trade}</p>
          <p style="margin:4px 0;font-size:11px;">
             <strong>Visa Expiry:</strong> {visa}
          </p>
        </div>
        {photo_html}
      </div>
      <hr style="border:0;border-top:1px solid #e5e7eb;margin:8px 0;" />
      <div style="font-size:10px;color:#6b7280;display:flex;justify-content:space-between;">
        <span>Authorized Signature</span>
        <span>www.nileps.com</span>
      </div>
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)


def generate_id_card_pdf(worker_row):
    if not REPORTLAB_AVAILABLE:
        return None

    worker_code = worker_row["worker_code"] or f"NPS-W{worker_row['id']:04d}"
    name = worker_row["name"]
    role = worker_row.get("role") or ""
    trade = worker_row.get("trade") or ""
    visa = worker_row.get("visa_expiry") or ""

    buf = io.BytesIO()
    width, height = 85.6 * mm, 54 * mm
    c_pdf = canvas.Canvas(buf, pagesize=(width, height))

    c_pdf.setLineWidth(1)
    c_pdf.rect(2 * mm, 2 * mm, width - 4 * mm, height - 4 * mm)

    c_pdf.setFont("Helvetica-Bold", 10)
    c_pdf.setFillColorRGB(0, 0.2, 0.5)
    c_pdf.drawString(5 * mm, height - 10 * mm, "Nile Projects Sevice")
    c_pdf.setFont("Helvetica", 7)
    c_pdf.setFillColorRGB(0.3, 0.3, 0.3)
    c_pdf.drawString(5 * mm, height - 14 * mm, "MEP Contracting – Employee ID")

    c_pdf.setFont("Helvetica", 7)
    c_pdf.setFillColorRGB(0, 0, 0)
    y = height - 22 * mm
    c_pdf.drawString(5 * mm, y, f"ID: {worker_code}")
    y -= 4 * mm
    c_pdf.drawString(5 * mm, y, f"Name: {name}")
    y -= 4 * mm
    c_pdf.drawString(5 * mm, y, f"Role: {role}")
    y -= 4 * mm
    c_pdf.drawString(5 * mm, y, f"Trade: {trade}")
    y -= 4 * mm
    c_pdf.drawString(5 * mm, y, f"Visa Expiry: {visa}")

    c_pdf.setFont("Helvetica", 6)
    c_pdf.setFillColorRGB(0.2, 0.2, 0.2)
    c_pdf.drawString(5 * mm, 4 * mm, "www.nileps.com")

    c_pdf.showPage()
    c_pdf.save()
    buf.seek(0)
    return buf.getvalue()


def generate_payslip_pdf(row, year, month):
    if not REPORTLAB_AVAILABLE:
        return None

    buf = io.BytesIO()
    c_pdf = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    month_name = calendar.month_name[month]

    c_pdf.setFont("Helvetica-Bold", 16)
    c_pdf.setFillColorRGB(0, 0.2, 0.5)
    c_pdf.drawString(40, h - 60, "Nile Projects Sevice")
    c_pdf.setFont("Helvetica", 10)
    c_pdf.setFillColorRGB(0.3, 0.3, 0.3)
    c_pdf.drawString(40, h - 80, "MEP Contracting – Monthly Salary Slip")
    c_pdf.drawString(40, h - 100, f"Month: {month_name} {year}")

    c_pdf.rect(35, h - 190, w - 70, 70)
    c_pdf.setFont("Helvetica", 9)
    c_pdf.setFillColorRGB(0, 0, 0)

    c_pdf.drawString(45, h - 130, f"Employee ID : {row.get('worker_code','')}")
    c_pdf.drawString(45, h - 145, f"Name        : {row.get('name','')}")
    c_pdf.drawString(45, h - 160, f"Role        : {row.get('role','')}")
    c_pdf.drawString(45, h - 175, f"Trade       : {row.get('trade','')}")

    c_pdf.rect(35, h - 360, w - 70, 150)
    salary = float(row.get("salary", 0) or 0)
    days_in_month = int(row.get("days_in_month", 0) or 0)
    days_present = int(row.get("days_present", 0) or 0)
    total_hours = float(row.get("total_hours", 0) or 0)
    ot_hours = float(row.get("overtime_hours", 0) or 0)
    hourly_rate = float(row.get("hourly_rate", 0) or 0)
    ot_pay = float(row.get("overtime_pay", 0) or 0)
    net_pay = float(row.get("net_pay", 0) or 0)

    y = h - 210
    c_pdf.setFont("Helvetica-Bold", 10)
    c_pdf.drawString(45, y, "Payroll Summary")
    c_pdf.setFont("Helvetica", 9)
    y -= 20
    c_pdf.drawString(45, y, f"Basic Salary (Monthly)   : {salary:,.2f}")
    y -= 15
    c_pdf.drawString(45, y, f"Days in Month            : {days_in_month}")
    y -= 15
    c_pdf.drawString(45, y, f"Days Present             : {days_present}")
    y -= 15
    c_pdf.drawString(45, y, f"Total Working Hours      : {total_hours:,.2f}")
    y -= 15
    c_pdf.drawString(45, y, f"Overtime Hours (> {STANDARD_DAILY_HOURS}h) : {ot_hours:,.2f}")
    y -= 15
    c_pdf.drawString(45, y, f"Hourly Rate              : {hourly_rate:,.2f}")
    y -= 15
    c_pdf.drawString(45, y, f"Overtime Pay             : {ot_pay:,.2f}")
    y -= 20
    c_pdf.setFont("Helvetica-Bold", 11)
    c_pdf.drawString(45, y, f"Net Pay                  : {net_pay:,.2f}")

    c_pdf.setFont("Helvetica", 8)
    c_pdf.setFillColorRGB(0.3, 0.3, 0.3)
    c_pdf.drawString(40, 60, "System-generated payslip from NPS HR. No signature required.")
    c_pdf.drawString(40, 45, "www.nileps.com")

    c_pdf.showPage()
    c_pdf.save()
    buf.seek(0)
    return buf.getvalue()
# ===================== PAGES – DASHBOARD & EMPLOYEES =====================
def dashboard_page():
    st.header("📊 HR & Project Dashboard – Nile Projects Service")

    total_workers, present, absent, active_projects, held_projects = get_global_today_stats()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Workers", total_workers)
    c2.metric("Present Today", present)
    c3.metric("Absent Today", absent)
    c4.metric("Active Projects", active_projects)
    c5.metric("Held Projects", held_projects)

    # Projects overview
    conn = get_connection()
    projects = pd.read_sql("SELECT * FROM projects", conn)
    proj_stats = pd.read_sql(
        """
        SELECT
          p.id, p.name, p.held,
          COUNT(DISTINCT pw.worker_id) AS assigned_workers,
          COUNT(DISTINCT CASE WHEN a.signed_in=1 AND a.att_date=? THEN a.worker_id END)
            AS present_today
        FROM projects p
        LEFT JOIN project_workers pw ON p.id = pw.project_id
        LEFT JOIN attendance a
          ON a.project_id=p.id AND a.worker_id=pw.worker_id
        GROUP BY p.id, p.name, p.held
        """,
        conn,
        params=(TODAY.isoformat(),),
    )
    conn.close()

    if projects.empty:
        st.info("No projects yet. Use sidebar to add a project.")
        return

    # KPI table
    table_df = proj_stats.copy()
    table_df["StatusColor"] = table_df["id"].apply(lambda pid: get_project_status(pid)[0])
    table_df["StatusIcon"] = table_df["StatusColor"].map(
        {"green": "🟢", "yellow": "🟡", "red": "🔴"}
    )
    table_df["Status"] = table_df["id"].apply(lambda pid: get_project_status(pid)[1])
    table_df["assigned_workers"] = table_df["assigned_workers"].fillna(0).astype(int)
    table_df["present_today"] = table_df["present_today"].fillna(0).astype(int)

    table_df = table_df[
        ["StatusIcon", "name", "present_today", "assigned_workers", "held", "Status"]
    ]
    table_df = table_df.rename(
        columns={
            "StatusIcon": " ",
            "name": "Project",
            "present_today": "Present Today",
            "assigned_workers": "Assigned Workers",
            "held": "Held (1=yes)",
        }
    )

    st.subheader("📋 Project Manpower Overview")
    st.dataframe(table_df, use_container_width=True, height=260)

    st.subheader("🔍 Project Details & Workers Today")

    if "show_workers_map" not in st.session_state:
        st.session_state.show_workers_map = {}

    conn = get_connection()
    for _, row in projects.iterrows():
        pid = int(row["id"])
        pstats = proj_stats[proj_stats["id"] == pid].iloc[0]
        assigned = int(pstats["assigned_workers"] or 0)
        present_p = int(pstats["present_today"] or 0)

        col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
        with col1:
            st.markdown(f"**{row['name']}**")
        with col2:
            color, label = get_project_status(pid)
            icon = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(color, "⚪")
            st.markdown(f"{icon} {label}")
        with col3:
            st.metric("Present / Assigned", f"{present_p} / {assigned}")
        with col4:
            held_now = bool(row["held"])
            new_held = st.checkbox("Held", value=held_now, key=f"held_{pid}")
            if new_held != held_now:
                conn2 = get_connection()
                conn2.execute("UPDATE projects SET held=? WHERE id=?", (int(new_held), pid))
                conn2.commit()
                conn2.close()
                st.success("Project held status updated.")
                st.experimental_rerun()

        if st.button("Workers PRESENT today", key=f"view_{pid}"):
            st.session_state.show_workers_map[pid] = not st.session_state.show_workers_map.get(
                pid, False
            )
            st.experimental_rerun()

        if st.session_state.show_workers_map.get(pid, False):
            w_today = pd.read_sql(
                """
                SELECT DISTINCT w.worker_code, w.name, w.role, w.trade,
                       a.time_in, a.time_out
                FROM workers w
                JOIN attendance a ON w.id=a.worker_id
                WHERE a.project_id=? AND a.att_date=? AND a.signed_in=1
                ORDER BY w.name
                """,
                conn,
                params=(pid, TODAY.isoformat()),
            )
            if w_today.empty:
                st.info("No workers marked PRESENT today in this project.")
            else:
                st.dataframe(w_today, use_container_width=True)

    conn.close()


def employees_page():
    st.header("👤 Employees – Master Data & ID Cards")
    conn = get_connection()
    workers = pd.read_sql("SELECT * FROM workers ORDER BY name", conn)
    conn.close()

    if workers.empty:
        st.info("No employees yet. Use sidebar ➕ Add Employee.")
        return

    left, right = st.columns([1.7, 1.3])

    with left:
        df = workers[["worker_code", "name", "role", "trade", "salary", "visa_expiry"]].copy()
        df = df.rename(
            columns={
                "worker_code": "Worker ID",
                "name": "Name",
                "role": "Role",
                "trade": "Trade",
                "salary": "Salary",
                "visa_expiry": "Visa Expiry",
            }
        )
        st.subheader("Employee List")
        st.dataframe(df, use_container_width=True, height=400)

        options = []
        id_map = {}
        for _, r in workers.iterrows():
            code = r["worker_code"] or f"NPS-W{r['id']:04d}"
            label = f"{code} – {r['name']}"
            options.append(label)
            id_map[label] = int(r["id"])

        selected_label = st.selectbox("Select employee to edit / ID card", options)
        selected_id = id_map[selected_label]

    with right:
        worker_row = workers[workers["id"] == selected_id].iloc[0]
        st.subheader("ID Card Preview")
        render_id_card(worker_row)

        if REPORTLAB_AVAILABLE:
            pdf_bytes = generate_id_card_pdf(worker_row)
            st.download_button(
                "📄 Download ID Card PDF",
                data=pdf_bytes,
                file_name=f"{worker_row['worker_code'] or 'ID'}.pdf",
                mime="application/pdf",
            )
        else:
            st.info("To export ID card to PDF: `pip install reportlab`")

        st.markdown("---")
        st.subheader("Edit Employee")

        with st.form(f"edit_emp_{selected_id}"):
            name = st.text_input("Name", worker_row["name"])
            role = st.text_input("Role", worker_row.get("role") or "")
            trade = st.text_input("Trade", worker_row.get("trade") or "")
            salary = float(worker_row.get("salary") or 0)
            salary = st.number_input("Basic Salary (QAR)", value=salary, min_value=0.0, step=100.0)

            try:
                visa_default = (
                    date.fromisoformat(worker_row["visa_expiry"])
                    if worker_row.get("visa_expiry")
                    else TODAY
                )
            except Exception:
                visa_default = TODAY
            visa = st.date_input("Visa Expiry", value=visa_default)

            photo = st.file_uploader(
                "Replace Photo (optional)", type=["png", "jpg", "jpeg"], key=f"photo_{selected_id}"
            )

            submitted = st.form_submit_button("Save Changes")

        if submitted:
            photo_file = worker_row.get("photo_file")
            if photo is not None:
                if photo_file:
                    old = os.path.join(PHOTOS_DIR, photo_file)
                    if os.path.exists(old):
                        try:
                            os.remove(old)
                        except Exception:
                            pass
                code = worker_row["worker_code"] or f"NPS-W{worker_row['id']:04d}"
                _, ext = os.path.splitext(photo.name)
                if ext.lower() not in [".png", ".jpg", ".jpeg"]:
                    ext = ".png"
                photo_file = f"{code}{ext}"
                with open(os.path.join(PHOTOS_DIR, photo_file), "wb") as f:
                    f.write(photo.getbuffer())

            conn = get_connection()
            conn.execute(
                """
                UPDATE workers
                SET name=?, role=?, trade=?, salary=?, visa_expiry=?, photo_file=?
                WHERE id=?
                """,
                (name.strip(), role.strip(), trade.strip(), salary, visa.isoformat(), photo_file, selected_id),
            )
            conn.commit()
            conn.close()
            st.success("Employee updated.")
            st.experimental_rerun()


# ===================== WORKERS / ASSIGNMENTS / ATTENDANCE =====================
def workers_page():
    st.header("👷 Workers by Project")

    conn = get_connection()
    projects = pd.read_sql("SELECT id, name FROM projects ORDER BY name", conn)
    conn.close()
    if projects.empty:
        st.info("No projects. Use sidebar ➕ Add Project.")
        return

    proj_name = st.selectbox("Select project", projects["name"].tolist())
    proj_id = int(projects[projects["name"] == proj_name]["id"].iloc[0])

    conn = get_connection()
    workers = pd.read_sql(
        """
        SELECT w.id, w.worker_code, w.name, w.role, w.trade, w.salary, w.visa_expiry
        FROM workers w
        JOIN project_workers pw ON w.id=pw.worker_id
        WHERE pw.project_id=?
        ORDER BY w.name
        """,
        conn,
        params=(proj_id,),
    )
    conn.close()

    if workers.empty:
        st.info("No workers assigned to this project yet.")
        return

    workers["today_att"] = workers["id"].apply(lambda wid: get_today_attendance(wid, proj_id))

    search = st.text_input("Search (ID / Name / Role / Trade)")
    if search:
        m = workers["worker_code"].fillna("").str.contains(search, case=False)
        m |= workers["name"].str.contains(search, case=False)
        m |= workers["role"].str.contains(search, case=False)
        m |= workers["trade"].str.contains(search, case=False)
        workers = workers[m]

    with st.form("proj_att_form"):
        for _, w in workers.iterrows():
            c1, c2, c3, c4, c5 = st.columns([1.2, 2, 1.5, 1.5, 1])
            with c1:
                st.write(w.get("worker_code") or f"#{w['id']}")
            with c2:
                st.write(f"**{w['name']}**")
            with c3:
                st.write(w["role"])
            with c4:
                vcolor, vlabel, vicon = get_visa_status(w["visa_expiry"])
                st.write(f"{vicon} {vlabel}")
            with c5:
                st.checkbox(
                    "Present",
                    value=bool(w["today_att"]),
                    key=f"proj_{proj_id}_w_{w['id']}",
                )
        if st.form_submit_button("Save Attendance (Present only)"):
            for _, w in workers.iterrows():
                present = st.session_state[f"proj_{proj_id}_w_{w['id']}"]
                toggle_attendance(
                    w["id"], proj_id, TODAY.isoformat(), int(present), time_in="07:00", time_out="16:00"
                )
            st.success("Attendance saved for this project.")
            st.experimental_rerun()


def assignments_page():
    st.header("🔗 Worker–Project Assignments")

    conn = get_connection()
    workers = pd.read_sql("SELECT id, worker_code, name, role, trade FROM workers", conn)
    projects = pd.read_sql("SELECT id, name FROM projects ORDER BY name", conn)
    assigned = pd.read_sql("SELECT * FROM project_workers", conn)
    conn.close()

    if workers.empty or projects.empty:
        st.info("Need both employees and projects first.")
        return

    assigned_map = {(r["project_id"], r["worker_id"]): True for _, r in assigned.iterrows()}
    rows = []
    for _, w in workers.iterrows():
        code = w["worker_code"] or f"#{w['id']}"
        row = {"Worker": f"{code} – {w['name']} ({w['role']}, {w['trade']})"}
        for _, p in projects.iterrows():
            row[p["name"]] = assigned_map.get((p["id"], w["id"]), False)
        rows.append(row)

    df = pd.DataFrame(rows)
    st.caption("Tick the projects for each worker, then click Save.")

    edited = st.data_editor(
        df,
        use_container_width=True,
        column_config={
            p["name"]: st.column_config.CheckboxColumn("Assigned", default=False)
            for _, p in projects.iterrows()
        },
        key="assign_editor",
    )

    if st.button("Save Assignments", key="save_assignments_btn"):
        conn = get_connection()
        conn.execute("DELETE FROM project_workers")
        for _, row in edited.iterrows():
            label = row["Worker"]
            # worker name is part after " – "
            try:
                name_part = label.split(" – ", 1)[1]
                worker_name = name_part.split(" (")[0]
            except Exception:
                continue
            wid_df = workers[workers["name"] == worker_name]
            if wid_df.empty:
                continue
            wid = int(wid_df["id"].iloc[0])
            for _, p in projects.iterrows():
                if bool(row[p["name"]]):
                    conn.execute(
                        "INSERT INTO project_workers (project_id, worker_id) VALUES (?, ?)",
                        (int(p["id"]), wid),
                    )
        conn.commit()
        conn.close()
        st.success("Assignments saved.")
        st.experimental_rerun()


def attendance_page():
    st.header("📅 Global Attendance – Today (with Time In / Out)")

    conn = get_connection()
    workers = pd.read_sql("SELECT * FROM workers ORDER BY name", conn)
    projects = pd.read_sql("SELECT id, name FROM projects ORDER BY name", conn)
    conn.close()

    if workers.empty or projects.empty:
        st.info("Need employees and projects first.")
        return

    project_names = projects["name"].tolist()

    with st.form("global_att_form"):
        for _, w in workers.iterrows():
            c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
            with c1:
                code = w.get("worker_code") or f"#{w['id']}"
                st.write(f"{code} – {w['name']} ({w['trade']} / {w['role']})")

            conn = get_connection()
            last = pd.read_sql(
                """
                SELECT project_id, signed_in, time_in, time_out
                FROM attendance
                WHERE worker_id=? AND att_date=?
                ORDER BY id DESC LIMIT 1
                """,
                conn,
                params=(w["id"], TODAY.isoformat()),
            )
            conn.close()

            if last.empty:
                default_proj_id = int(projects["id"].iloc[0])
                default_present = False
                default_in = time(7, 0)
                default_out = time(16, 0)
            else:
                default_proj_id = int(last["project_id"].iloc[0])
                default_present = bool(last["signed_in"].iloc[0])
                ti = last["time_in"].iloc[0]
                to = last["time_out"].iloc[0]
                try:
                    default_in = datetime.strptime(ti, "%H:%M").time() if ti else time(7, 0)
                except Exception:
                    default_in = time(7, 0)
                try:
                    default_out = datetime.strptime(to, "%H:%M").time() if to else time(16, 0)
                except Exception:
                    default_out = time(16, 0)

            if default_proj_id not in projects["id"].tolist():
                default_proj_id = int(projects["id"].iloc[0])

            default_proj_name = projects[projects["id"] == default_proj_id]["name"].iloc[0]
            idx = project_names.index(default_proj_name)

            with c2:
                proj_name = st.selectbox(
                    "Project",
                    project_names,
                    index=idx,
                    key=f"proj_{w['id']}",
                )
            with c3:
                t_in = st.time_input("Time In", value=default_in, key=f"ti_{w['id']}")
                t_out = st.time_input("Time Out", value=default_out, key=f"to_{w['id']}")
            with c4:
                st.checkbox("Present", value=default_present, key=f"pre_{w['id']}")

        submitted = st.form_submit_button("Save All")

    if submitted:
        for _, w in workers.iterrows():
            proj_name = st.session_state[f"proj_{w['id']}"]
            proj_id = int(projects[projects["name"] == proj_name]["id"].iloc[0])
            present = bool(st.session_state[f"pre_{w['id']}"])
            t_in = st.session_state[f"ti_{w['id']}"]
            t_out = st.session_state[f"to_{w['id']}"]
            toggle_attendance(
                w["id"],
                proj_id,
                TODAY.isoformat(),
                int(present),
                t_in.strftime("%H:%M"),
                t_out.strftime("%H:%M"),
            )
        st.success("Attendance saved.")
        st.experimental_rerun()


# ===================== REPORTS & HELP =====================
def reports_page():
    st.header("📈 Reports & Payroll")

    choice = st.selectbox(
        "Select report type",
        ["Attendance Summary", "Payroll (by Month)", "Visa Compliance"],
    )

    # ----- Attendance Summary -----
    if choice == "Attendance Summary":
        c1, c2 = st.columns(2)
        with c1:
            year = int(
                st.number_input("Year", min_value=2000, max_value=2100, value=TODAY.year)
            )
        with c2:
            month = int(st.number_input("Month", min_value=1, max_value=12, value=TODAY.month))

        month_start = date(year, month, 1)
        month_end = date(year + (month // 12), (month % 12) + 1, 1)

        conn = get_connection()
        att = pd.read_sql(
            """
            SELECT w.worker_code, w.name, w.trade, p.name AS project,
                   a.att_date, a.signed_in, a.time_in, a.time_out
            FROM workers w
            JOIN attendance a ON w.id=a.worker_id
            LEFT JOIN projects p ON a.project_id=p.id
            WHERE a.att_date>=? AND a.att_date<?
            ORDER BY a.att_date DESC, w.name
            """,
            conn,
            params=(month_start.isoformat(), month_end.isoformat()),
        )
        conn.close()

        if att.empty:
            st.info("No attendance for this month.")
            return

        att["hours"] = att.apply(lambda r: _hours_between(r["time_in"], r["time_out"]), axis=1)
        att["ot_hours"] = att["hours"].apply(lambda h: max(h - STANDARD_DAILY_HOURS, 0.0))
        att["Status"] = att["signed_in"].map({1: "Present", 0: "Absent"})

        tab1, tab2 = st.tabs(["Daily Records", "Monthly Summary by Worker"])
        with tab1:
            ddf = att.rename(
                columns={
                    "worker_code": "Worker ID",
                    "name": "Name",
                    "trade": "Trade",
                    "project": "Project",
                    "att_date": "Date",
                    "time_in": "Time In",
                    "time_out": "Time Out",
                    "hours": "Hours",
                    "ot_hours": "Overtime (hrs)",
                }
            )[
                [
                    "Worker ID",
                    "Name",
                    "Trade",
                    "Project",
                    "Date",
                    "Status",
                    "Time In",
                    "Time Out",
                    "Hours",
                    "Overtime (hrs)",
                ]
            ]
            st.dataframe(ddf, use_container_width=True)
            st.download_button(
                "Download Daily CSV",
                data=ddf.to_csv(index=False),
                file_name=f"attendance_daily_{year}_{month:02d}.csv",
                mime="text/csv",
            )

        with tab2:
            payroll_df = generate_monthly_payroll(year, month)
            if payroll_df is None or payroll_df.empty:
                st.info("No payroll data.")
            else:
                st.dataframe(payroll_df, use_container_width=True)
                st.metric(
                    "Total Company Payroll (Net)",
                    f"{payroll_df['net_pay'].sum():,.2f} QAR",
                )
                st.download_button(
                    "Download Monthly Summary CSV",
                    data=payroll_df.to_csv(index=False),
                    file_name=f"attendance_summary_{year}_{month:02d}.csv",
                    mime="text/csv",
                )

                if REPORTLAB_AVAILABLE:
                    codes = payroll_df["worker_code"].tolist()
                    labels = [
                        f"{c} – {n}"
                        for c, n in zip(payroll_df["worker_code"], payroll_df["name"])
                    ]
                    sel = st.selectbox("Print salary slip", labels)
                    sel_code = sel.split(" – ", 1)[0]
                    sel_row_df = payroll_df[payroll_df["worker_code"] == sel_code]
                    if not sel_row_df.empty:
                        sel_row = sel_row_df.iloc[0]
                        pdf = generate_payslip_pdf(sel_row, year, month)
                        st.download_button(
                            "Download Payslip PDF",
                            data=pdf,
                            file_name=f"payslip_{sel_code}_{year}_{month:02d}.pdf",
                            mime="application/pdf",
                        )
                else:
                    st.info("To export payslip PDFs: `pip install reportlab`")

    # ----- Payroll (by Month) -----
    elif choice == "Payroll (by Month)":
        c1, c2 = st.columns(2)
        with c1:
            year = int(
                st.number_input(
                    "Year",
                    min_value=2000,
                    max_value=2100,
                    value=TODAY.year,
                    key="pay_year",
                )
            )
        with c2:
            month = int(
                st.number_input(
                    "Month",
                    min_value=1,
                    max_value=12,
                    value=TODAY.month,
                    key="pay_month",
                )
            )

        conn = get_connection()
        projects = pd.read_sql("SELECT id, name FROM projects ORDER BY name", conn)
        conn.close()
        options = ["All Projects"]
        id_map = {"All Projects": None}
        for _, p in projects.iterrows():
            options.append(p["name"])
            id_map[p["name"]] = int(p["id"])

        scope = st.selectbox("Scope", options)
        project_id = id_map[scope]

        if st.button("Generate Payroll", key="btn_gen_payroll"):
            payroll_df = generate_monthly_payroll(year, month, project_id=project_id)
            if payroll_df is None or payroll_df.empty:
                st.info("No payroll for this period / project.")
            else:
                st.dataframe(payroll_df, use_container_width=True)
                total_net = payroll_df["net_pay"].sum()
                label = "All Projects" if project_id is None else scope
                st.metric(f"Total Net Payroll – {label}", f"{total_net:,.2f} QAR")

                scope_tag = "all" if project_id is None else f"proj_{project_id}"
                st.download_button(
                    "Download Payroll CSV",
                    data=payroll_df.to_csv(index=False),
                    file_name=f"payroll_{year}_{month:02d}_{scope_tag}.csv",
                    mime="text/csv",
                )

                if REPORTLAB_AVAILABLE:
                    codes = payroll_df["worker_code"].tolist()
                    labels = [
                        f"{c} – {n}"
                        for c, n in zip(payroll_df["worker_code"], payroll_df["name"])
                    ]
                    sel = st.selectbox("Print salary slip", labels, key="payroll_slip_sel")
                    sel_code = sel.split(" – ", 1)[0]
                    sel_row_df = payroll_df[payroll_df["worker_code"] == sel_code]
                    if not sel_row_df.empty:
                        sel_row = sel_row_df.iloc[0]
                        pdf = generate_payslip_pdf(sel_row, year, month)
                        st.download_button(
                            "Download Payslip PDF",
                            data=pdf,
                            file_name=f"payslip_{sel_code}_{year}_{month:02d}.pdf",
                            mime="application/pdf",
                        )

    # ----- Visa Compliance -----
    else:
        conn = get_connection()
        visa_df = pd.read_sql(
            "SELECT worker_code, name, role, trade, visa_expiry FROM workers", conn
        )
        conn.close()
        visa_df["Visa Status"] = visa_df["visa_expiry"].apply(lambda x: get_visa_status(x)[1])
        visa_df = visa_df.rename(
            columns={
                "worker_code": "Worker ID",
                "name": "Name",
                "role": "Role",
                "trade": "Trade",
                "visa_expiry": "Visa Expiry",
            }
        )
        st.dataframe(visa_df, use_container_width=True)
        st.download_button(
            "Download Visa CSV",
            data=visa_df.to_csv(index=False),
            file_name="visa_compliance.csv",
            mime="text/csv",
        )


def help_page():
    st.header("ℹ️ Help / About – NPS HR")

    st.markdown(
        """
### Overview
This system is built for **Nile Projects Service – MEP Contracting** to manage:

- Employee master data & ID cards  
- Project list & worker assignments  
- Daily attendance with **Time In / Out**  
- Automatic overtime calculation (> 9 hours/day)  
- Monthly payroll & salary slips  
- Visa expiry tracking  

### Daily Use – Site HR / Timekeeper

1. **Add employees** from left sidebar ➕ Add Employee.  
2. **Assign workers to projects** from *Assignments* page.  
3. **Mark attendance** each day on *Attendance* page  
   - Choose project  
   - Enter Time In / Time Out  
   - Tick “Present”.  
4. **Monitor manpower** on *Dashboard* (workers present by project).

### Monthly Use – Accounts / HR

- Go to **Reports** → *Attendance Summary* or *Payroll (by Month)*  
- Select **year & month**  
- Export CSV / Excel  
- Print **payslips (PDF)** for any employee (if `reportlab` is installed).

### Technical Notes

- Database & photos are stored under the `data` folder next to `app.py`.  
- To enable PDF exports:  
  - `pip install reportlab`  
- Optional Excel export uses pandas built-ins.  

Official website: **www.nileps.com**
"""
    )


# ===================== MAIN APP & SIDEBAR =====================
def main():
    st.set_page_config(page_title="NPS HR System", layout="wide")

    # Global CSS
    st.markdown(
        f"""
        <style>
        .main {{
            background-color: #0f172a;
            color: #e5e7eb;
        }}
        [data-testid="stSidebar"] {{
            background-color: {BRAND_BG};
        }}
        .nps-header {{
            color: {BRAND_RED};
            font-size: 2rem;
            font-weight: 800;
            margin-bottom: 0.2rem;
        }}
        .nps-subtitle {{
            color: {BRAND_LIGHT_BLUE};
            font-size: 0.9rem;
            margin-bottom: 0.8rem;
        }}
        .nps-footer {{
            color: #9ca3af;
            font-size: 0.8rem;
            text-align: center;
            padding: 10px;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="nps-header">Nile Projects Sevice – MEP HR System</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="nps-subtitle">MEP Contracting · HR, Attendance & Payroll</div>',
        unsafe_allow_html=True,
    )

    # Logo if available
    for logo_name in ["nps.png", "logo.png"]:
        logo_path = os.path.join(BASE_DIR, logo_name)
        if os.path.exists(logo_path):
            st.image(logo_path, width=260)
            break

    # Ensure DB ready
    init_db()

    # ----- SIDEBAR NAV -----
    st.sidebar.title("NPS HR Navigation")

    pages = [
        "Dashboard",
        "Employees",
        "Workers",
        "Assignments",
        "Attendance",
        "Reports",
        "Help / About",
    ]
    page = st.sidebar.radio("Main Menu", pages)

    # Quick actions
    st.sidebar.markdown("### Quick Actions")
    qa1, qa2 = st.sidebar.columns(2)
    with qa1:
        if st.button("🏠 Dash", key="qa_dash"):
            page = "Dashboard"
    with qa2:
        if st.button("📅 Att", key="qa_att"):
            page = "Attendance"
    qa3, qa4 = st.sidebar.columns(2)
    with qa3:
        if st.button("👤 Emp", key="qa_emp"):
            page = "Employees"
    with qa4:
        if st.button("📈 Pay", key="qa_pay"):
            page = "Reports"

    # Add master data
    st.sidebar.markdown("### Add Master Data")

    st.sidebar.markdown("**➕ Add Project**")
    proj_name = st.sidebar.text_input("Project Name", key="sb_proj_name")
    held = st.sidebar.checkbox("Held (on hold)", key="sb_proj_held")
    if st.sidebar.button("Save Project", key="sb_proj_save"):
        if proj_name.strip():
            conn = get_connection()
            conn.execute(
                "INSERT INTO projects (name, held) VALUES (?, ?)",
                (proj_name.strip(), int(held)),
            )
            conn.commit()
            conn.close()
            st.sidebar.success("Project added.")
            st.experimental_rerun()
        else:
            st.sidebar.warning("Enter project name.")

    st.sidebar.markdown("---")
    st.sidebar.markdown("**➕ Add Employee**")
    w_name = st.sidebar.text_input("Full Name", key="sb_emp_name")
    w_role = st.sidebar.selectbox(
        "Role",
        ["Technician", "Engineer", "Supervisor", "Helper", "Accountant", "Driver", "HR", "Other"],
        key="sb_emp_role",
    )
    w_trade = st.sidebar.selectbox(
        "Trade",
        ["HVAC", "Plumbing", "Fire", "Electrical", "Logistics", "Admin", "Other"],
        key="sb_emp_trade",
    )
    w_salary = st.sidebar.number_input(
        "Basic Salary (QAR)", min_value=0.0, step=100.0, key="sb_emp_salary"
    )
    w_visa = st.sidebar.date_input("Visa Expiry", key="sb_emp_visa")
    w_photo = st.sidebar.file_uploader(
        "Photo (optional)", type=["png", "jpg", "jpeg"], key="sb_emp_photo"
    )

    if st.sidebar.button("Save Employee", key="sb_emp_save"):
        if not w_name.strip():
            st.sidebar.warning("Enter employee name.")
        else:
            code = generate_next_worker_code()
            photo_file = None
            if w_photo is not None:
                _, ext = os.path.splitext(w_photo.name)
                if ext.lower() not in [".png", ".jpg", ".jpeg"]:
                    ext = ".png"
                photo_file = f"{code}{ext}"
                with open(os.path.join(PHOTOS_DIR, photo_file), "wb") as f:
                    f.write(w_photo.getbuffer())

            conn = get_connection()
            conn.execute(
                """
                INSERT INTO workers (worker_code, name, role, trade, salary, visa_expiry, photo_file)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code,
                    w_name.strip(),
                    w_role,
                    w_trade,
                    w_salary,
                    w_visa.isoformat(),
                    photo_file,
                ),
            )
            conn.commit()
            conn.close()
            st.sidebar.success(f"Employee added with ID: {code}")
            st.experimental_rerun()

    # ----- ROUTING -----
    if page == "Dashboard":
        dashboard_page()
    elif page == "Employees":
        employees_page()
    elif page == "Workers":
        workers_page()
    elif page == "Assignments":
        assignments_page()
    elif page == "Attendance":
        attendance_page()
    elif page == "Reports":
        reports_page()
    elif page == "Help / About":
        help_page()

    st.markdown(
        '<div class="nps-footer">© 2025 Nile Projects Service | www.nileps.com</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
