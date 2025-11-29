# ===================== NPS HR SYSTEM – FULL APP (WITH FIXES + ACCOUNTING SYNC) =====================
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
    from reportlab.lib.pagesizes import A4, A5
    from reportlab.lib.units import mm

    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

# ---------- Branding ----------
BRAND_RED = "#ff2b4d"
BRAND_DARK_BLUE = "#003388"
BRAND_LIGHT_BLUE = "#0ea5e9"
BRAND_BG = "#00a6df"  # light blue sidebar background

# ---------- Paths (local default: OneDrive) ----------
USER_HOME = os.path.expanduser("~")
# Default shared folder: C:\Users\<username>\OneDrive\NPS_HR_DATA
DEFAULT_DATA_DIR = os.path.join(USER_HOME, "OneDrive", "NPS_HR_DATA")

DATA_DIR = DEFAULT_DATA_DIR
PHOTOS_DIR = os.path.join(DATA_DIR, "photos")
DB_PATH = os.path.join(DATA_DIR, "hr.db")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PHOTOS_DIR, exist_ok=True)

TODAY = date.today()

# ---------- Payroll Policy ----------
STANDARD_DAILY_HOURS = 9
OVERTIME_MULTIPLIER = 1.0  # OT x1


def do_rerun():
    """Safe rerun wrapper for modern Streamlit."""
    try:
        st.rerun()
    except Exception:
        pass


# ===================== DB HELPERS =====================
def get_connection():
    return sqlite3.connect(DB_PATH)


def init_db():
    """Create tables & sample data if empty, and add missing columns."""
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
            photo_file TEXT,
            phone TEXT
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
    if "signed_in" not in cols:
        c.execute("ALTER TABLE attendance ADD COLUMN signed_in INTEGER DEFAULT 0")
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
    if "phone" not in wcols:
        c.execute("ALTER TABLE workers ADD COLUMN phone TEXT")

    # Seed sample data if empty
    c.execute("SELECT COUNT(*) FROM workers")
    if c.fetchone()[0] == 0:
        sample_workers = [
            ("NPS-W0001", "Ahmed Ali", "Technician", "HVAC", 5000, "2026-01-01", None, "0770xxxxxx1"),
            ("NPS-W0002", "Mohamed Hassan", "Engineer", "Plumbing", 7000, "2025-12-15", None, "0770xxxxxx2"),
            ("NPS-W0003", "Fatima Salem", "Helper", "Fire", 3000, "2025-11-30", None, "0770xxxxxx3"),
            ("NPS-W0004", "Omar Khalid", "Supervisor", "HVAC", 6000, "2026-02-01", None, "0770xxxxxx4"),
            ("NPS-W0005", "Layla Nour", "Technician", "Plumbing", 4500, "2025-12-20", None, "0770xxxxxx5"),
            ("NPS-W0006", "Sara Ahmed", "Accountant", "Admin", 5500, "2026-03-01", None, "0770xxxxxx6"),
            ("NPS-W0007", "Ali Driver", "Driver", "Logistics", 4000, "2025-10-15", None, "0770xxxxxx7"),
        ]
        c.executemany(
            """
            INSERT INTO workers (worker_code, name, role, trade, salary, visa_expiry, photo_file, phone)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
    """Return (color, label) for project based on held flag and today's attendance."""
    conn = get_connection()
    c = conn.cursor()

    # 1) Held check
    c.execute("SELECT held FROM projects WHERE id=?", (project_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return "gray", "Unknown project"
    held = row[0]
    if held:
        conn.close()
        return "red", "Held"

    # 2) Assigned workers count
    c.execute("SELECT COUNT(*) FROM project_workers WHERE project_id=?", (project_id,))
    assigned_row = c.fetchone()
    assigned = assigned_row[0] if assigned_row and assigned_row[0] is not None else 0

    # 3) Attendance today (all workers, even if not assigned)
    c.execute(
        """
        SELECT COUNT(DISTINCT worker_id)
        FROM attendance
        WHERE project_id=? AND att_date=? AND signed_in=1
        """,
        (project_id, TODAY.isoformat()),
    )
    present_row = c.fetchone()
    present = present_row[0] if present_row and present_row[0] is not None else 0

    conn.close()

    if present > 0:
        return "green", "Active (Attendance Today)"
    if assigned > 0:
        return "yellow", "No Attendance Today"
    return "yellow", "No Workers"


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


# ============= FIXED PAYROLL FUNCTION (PRO-RATED BASE + OT) =============
def generate_monthly_payroll(year, month, project_id=None):
    """
    Payroll logic:

    - For ALL projects:
        base_earned = salary * (days_present / days_in_month)
        net_pay     = base_earned + overtime_pay

    - For single PROJECT:
        1) First compute total base_earned_total for the worker (all projects)
           using the same rule as above.
        2) Then allocate that base_earned_total to this project according to
           the share of working hours in this project.

           base_share = base_earned_total * (proj_hours / total_hours_all)

        net_pay = base_share + overtime_pay_for_this_project
    """
    month_start = date(year, month, 1)
    if month == 12:
        month_end = date(year + 1, 1, 1)
    else:
        month_end = date(year, month + 1, 1)
    days_in_month = (month_end - month_start).days

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

    # No attendance at all → show zeros
    if att.empty:
        df = workers.copy()
        df["days_in_month"] = days_in_month
        df["days_present"] = 0
        df["total_hours"] = 0.0
        df["overtime_hours"] = 0.0
        df["hourly_rate"] = df["salary"] / (days_in_month * STANDARD_DAILY_HOURS)
        df["overtime_pay"] = 0.0
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
                "net_pay",
            ]
        ]

    # Prepare attendance summaries
    att["hours"] = att.apply(lambda r: _hours_between(r["time_in"], r["time_out"]), axis=1)
    att["ot_hours"] = att["hours"].apply(lambda h: max(h - STANDARD_DAILY_HOURS, 0.0))

    # All-project summary per worker
    summary_all = att.groupby("worker_id").agg(
        days_present_all=("att_date", "nunique"),
        total_hours_all=("hours", "sum"),
        overtime_hours_all=("ot_hours", "sum"),
    ).reset_index()

    # ---------- A) GLOBAL PAYROLL (ALL PROJECTS) ----------
    if project_id is None:
        df = workers.merge(summary_all, left_on="id", right_on="worker_id", how="left")
        df[["days_present_all", "total_hours_all", "overtime_hours_all"]] = df[
            ["days_present_all", "total_hours_all", "overtime_hours_all"]
        ].fillna(0)

        df["days_in_month"] = days_in_month
        df["days_present"] = df["days_present_all"].astype(int)

        # Hourly rate based on full month
        df["hourly_rate"] = df["salary"] / (days_in_month * STANDARD_DAILY_HOURS)

        # Base salary actually earned = salary × (days_present / days_in_month)
        df["base_earned"] = df["salary"] * (df["days_present"] / df["days_in_month"])

        # Overtime pay for all projects
        df["overtime_pay"] = (
            df["hourly_rate"] * df["overtime_hours_all"] * OVERTIME_MULTIPLIER
        )

        df["net_pay"] = df["base_earned"] + df["overtime_pay"]

        # Rounding for display
        df["total_hours"] = df["total_hours_all"].round(2)
        df["overtime_hours"] = df["overtime_hours_all"].round(2)
        df["hourly_rate"] = df["hourly_rate"].round(2)
        df["overtime_pay"] = df["overtime_pay"].round(2)
        df["net_pay"] = df["net_pay"].round(2)

        return df[
            [
                "worker_code",
                "name",
                "role",
                "trade",
                "salary",        # full monthly salary (for info)
                "days_in_month",
                "days_present",
                "total_hours",
                "overtime_hours",
                "hourly_rate",
                "overtime_pay",
                "net_pay",
            ]
        ]

    # ---------- B) PER-PROJECT PAYROLL ----------
    att_proj = att[att["project_id"] == project_id].copy()
    if att_proj.empty:
        return pd.DataFrame()

    summary_proj = att_proj.groupby("worker_id").agg(
        days_present=("att_date", "nunique"),
        total_hours=("hours", "sum"),
        overtime_hours=("ot_hours", "sum"),
    ).reset_index()

    # Merge project summary + overall summary
    df = workers.merge(summary_proj, left_on="id", right_on="worker_id", how="inner")
    df = df.merge(
        summary_all[["worker_id", "days_present_all", "total_hours_all"]],
        on="worker_id",
        how="left",
    )
    df[["days_present_all", "total_hours_all"]] = df[
        ["days_present_all", "total_hours_all"]
    ].fillna(0)

    df["days_in_month"] = days_in_month
    df["hourly_rate"] = df["salary"] / (days_in_month * STANDARD_DAILY_HOURS)

    # Total base salary earned for the month across all projects
    df["base_earned_total"] = df["salary"] * (
        df["days_present_all"] / df["days_in_month"]
    )

    # Avoid divide-by-zero
    def _base_share(row):
        if row["total_hours_all"] <= 0:
            return 0.0
        return row["base_earned_total"] * (row["total_hours"] / row["total_hours_all"])

    df["base_share"] = df.apply(_base_share, axis=1)

    # Overtime pay only for this project
    df["overtime_pay"] = (
        df["hourly_rate"] * df["overtime_hours"] * OVERTIME_MULTIPLIER
    )

    df["net_pay"] = df["base_share"] + df["overtime_pay"]

    # Rounding
    df["total_hours"] = df["total_hours"].round(2)
    df["overtime_hours"] = df["overtime_hours"].round(2)
    df["hourly_rate"] = df["hourly_rate"].round(2)
    df["base_share"] = df["base_share"].round(2)
    df["overtime_pay"] = df["overtime_pay"].round(2)
    df["net_pay"] = df["net_pay"].round(2)

    return df[
        [
            "worker_code",
            "name",
            "role",
            "trade",
            "salary",            # full monthly salary (for info)
            "days_in_month",
            "days_present",      # days present in THIS project
            "total_hours",
            "overtime_hours",
            "hourly_rate",
            "base_share",        # base earned allocated to this project
            "overtime_pay",
            "net_pay",
        ]
    ]


# ===================== ID CARD & PAYSLIP PDFs =====================
def render_id_card(worker_row):
    worker_code = worker_row["worker_code"] or f"NPS-W{worker_row['id']:04d}"
    name = worker_row["name"]
    role = worker_row.get("role") or ""
    trade = worker_row.get("trade") or ""
    visa = worker_row.get("visa_expiry") or ""
    phone = worker_row.get("phone") or ""

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
            Nile Projects Service Company
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
          <p style="margin:4px 0;"><strong>Phone:</strong> {phone}</p>
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
    phone = worker_row.get("phone") or ""

    buf = io.BytesIO()
    width, height = 85.6 * mm, 54 * mm
    c_pdf = canvas.Canvas(buf, pagesize=(width, height))

    c_pdf.setLineWidth(1)
    c_pdf.rect(2 * mm, 2 * mm, width - 4 * mm, height - 4 * mm)

    c_pdf.setFont("Helvetica-Bold", 10)
    c_pdf.setFillColorRGB(0, 0.2, 0.5)
    c_pdf.drawString(5 * mm, height - 10 * mm, "Nile Projects Service Company")
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
    c_pdf.drawString(5 * mm, y, f"Phone: {phone}")
    y -= 4 * mm
    c_pdf.drawString(5 * mm, y, f"Visa Expiry: {visa}")

    c_pdf.setFont("Helvetica", 6)
    c_pdf.setFillColorRGB(0.2, 0.2, 0.2)
    c_pdf.drawString(5 * mm, 4 * mm, "www.nileps.com")

    c_pdf.showPage()
    c_pdf.save()
    buf.seek(0)
    return buf.getvalue()


def _draw_payslip_a5_page(c_pdf, row, year, month):
    w, h = A5
    month_name = calendar.month_name[month]

    c_pdf.setFont("Helvetica-Bold", 14)
    c_pdf.setFillColorRGB(0, 0.2, 0.5)
    c_pdf.drawString(30, h - 40, "Nile Projects Service Company")
    c_pdf.setFont("Helvetica", 9)
    c_pdf.setFillColorRGB(0.3, 0.3, 0.3)
    c_pdf.drawString(30, h - 55, "MEP Contracting – Monthly Salary Slip")
    c_pdf.drawString(30, h - 70, f"Month: {month_name} {year}")

    c_pdf.rect(25, h - 150, w - 50, 65)
    c_pdf.setFont("Helvetica", 8)
    c_pdf.setFillColorRGB(0, 0, 0)

    c_pdf.drawString(35, h - 95, f"Employee ID : {row.get('worker_code','')}")
    c_pdf.drawString(35, h - 110, f"Name        : {row.get('name','')}")
    c_pdf.drawString(35, h - 125, f"Role        : {row.get('role','')}")
    c_pdf.drawString(35, h - 140, f"Trade       : {row.get('trade','')}")

    c_pdf.rect(25, h - 290, w - 50, 120)
    salary = float(row.get("salary", 0) or 0)
    days_in_month = int(row.get("days_in_month", 0) or 0)
    days_present = int(row.get("days_present", 0) or 0)
    total_hours = float(row.get("total_hours", 0) or 0)
    ot_hours = float(row.get("overtime_hours", 0) or 0)
    hourly_rate = float(row.get("hourly_rate", 0) or 0)
    ot_pay = float(row.get("overtime_pay", 0) or 0)
    net_pay = float(row.get("net_pay", 0) or 0)

    y = h - 165
    c_pdf.setFont("Helvetica-Bold", 9)
    c_pdf.drawString(35, y, "Payroll Summary")
    c_pdf.setFont("Helvetica", 8)
    y -= 15
    c_pdf.drawString(35, y, f"Basic Salary (Monthly)   : {salary:,.2f}")
    y -= 13
    c_pdf.drawString(35, y, f"Days in Month            : {days_in_month}")
    y -= 13
    c_pdf.drawString(35, y, f"Days Present             : {days_present}")
    y -= 13
    c_pdf.drawString(35, y, f"Total Working Hours      : {total_hours:,.2f}")
    y -= 13
    c_pdf.drawString(35, y, f"Overtime Hours (> {STANDARD_DAILY_HOURS}h) : {ot_hours:,.2f}")
    y -= 13
    c_pdf.drawString(35, y, f"Hourly Rate              : {hourly_rate:,.2f}")
    y -= 13
    c_pdf.drawString(35, y, f"Overtime Pay             : {ot_pay:,.2f}")
    y -= 16
    c_pdf.setFont("Helvetica-Bold", 10)
    c_pdf.drawString(35, y, f"Net Pay                  : {net_pay:,.2f}")

    c_pdf.setFont("Helvetica", 7)
    c_pdf.setFillColorRGB(0.3, 0.3, 0.3)
    c_pdf.drawString(30, 25, "System-generated payslip from NPS HR. No signature required.")
    c_pdf.drawString(30, 14, "www.nileps.com")


def generate_payslip_pdf(row, year, month):
    if not REPORTLAB_AVAILABLE:
        return None
    buf = io.BytesIO()
    c_pdf = canvas.Canvas(buf, pagesize=A5)
    _draw_payslip_a5_page(c_pdf, row, year, month)
    c_pdf.showPage()
    c_pdf.save()
    buf.seek(0)
    return buf.getvalue()


def generate_payslips_batch_pdf(rows, year, month):
    if not REPORTLAB_AVAILABLE:
        return None
    buf = io.BytesIO()
    c_pdf = canvas.Canvas(buf, pagesize=A5)
    for row in rows:
        _draw_payslip_a5_page(c_pdf, row, year, month)
        c_pdf.showPage()
    c_pdf.save()
    buf.seek(0)
    return buf.getvalue()


# ===================== PAGES =====================

# ---------- Dashboard (enhanced with visa stats) ----------
def dashboard_page():
    st.header("📊 HR & Project Dashboard – Nile Projects Service Company")

    total_workers, present, absent, active_projects, held_projects = get_global_today_stats()

    # Visa stats
    conn = get_connection()
    visa_raw = pd.read_sql("SELECT visa_expiry FROM workers", conn)
    conn.close()

    expiring_soon = 0
    expired = 0
    if not visa_raw.empty:
        for v in visa_raw["visa_expiry"]:
            if not v:
                continue
            try:
                d = date.fromisoformat(str(v))
            except Exception:
                continue
            if d < TODAY:
                expired += 1
            elif d <= TODAY + relativedelta(days=30):
                expiring_soon += 1

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Total Workers", total_workers)
    c2.metric("Present Today", present)
    c3.metric("Absent Today", absent)
    c4.metric("Active Projects", active_projects)
    c5.metric("Held Projects", held_projects)
    c6.metric("Visa Expiring ≤30 days", expiring_soon)

    if expired > 0:
        st.warning(f"⚠ يوجد عدد {expired} موظف/عامل فيزتهم منتهية بالفعل – راجع صفحة الموظفين فوراً.")

    conn = get_connection()
    projects = pd.read_sql("SELECT * FROM projects", conn)

    proj_stats = pd.read_sql(
        """
        SELECT
          p.id,
          p.name,
          p.held,
          COUNT(DISTINCT pw.worker_id) AS assigned_workers,
          COUNT(DISTINCT CASE WHEN a.signed_in=1 THEN a.worker_id END) AS present_today
        FROM projects p
        LEFT JOIN project_workers pw
          ON p.id = pw.project_id
        LEFT JOIN attendance a
          ON a.project_id = p.id
         AND a.att_date = ?
        GROUP BY p.id, p.name, p.held
        """,
        conn,
        params=(TODAY.isoformat(),),
    )

    if projects.empty:
        conn.close()
        st.info("No projects yet. Use sidebar to add a project.")
        return

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
        st.session_state["show_workers_map"] = {}

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
                do_rerun()

        if st.button("Workers PRESENT today", key=f"view_{pid}"):
            st.session_state["show_workers_map"][pid] = not st.session_state["show_workers_map"].get(
                pid, False
            )
            do_rerun()

        if st.session_state["show_workers_map"].get(pid, False):
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


def projects_page():
    st.header("🏗 Projects – Add / Edit")

    conn = get_connection()
    df = pd.read_sql("SELECT id, name, held FROM projects ORDER BY id", conn)

    st.caption("Edit project names and held flag. Add new rows at bottom if needed.")
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        key="projects_editor",
    )

    if st.button("💾 Save Projects"):
        try:
            cur = conn.cursor()
            # Update existing / insert new
            for _, row in edited.iterrows():
                name = str(row["name"]).strip() if pd.notna(row["name"]) else ""
                if not name:
                    continue
                held = int(row.get("held", 0) or 0)
                pid = row.get("id")
                if pd.isna(pid):
                    cur.execute("INSERT INTO projects (name, held) VALUES (?, ?)", (name, held))
                else:
                    cur.execute(
                        "UPDATE projects SET name=?, held=? WHERE id=?",
                        (name, held, int(pid)),
                    )
            conn.commit()
            st.success("Projects saved.")
            do_rerun()
        except Exception as e:
            st.error(f"Error saving projects: {e}")
        finally:
            conn.close()
    else:
        conn.close()


def employees_page():
    st.header("👥 Employees – List & ID Cards")

    conn = get_connection()
    df = pd.read_sql(
        """
        SELECT id, worker_code, name, role, trade, salary, visa_expiry, phone, photo_file
        FROM workers
        ORDER BY worker_code
        """,
        conn,
    )
    conn.close()

    if df.empty:
        st.info("No employees yet. Use sidebar to add employee.")
        return

    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("Employees Table")
        st.dataframe(
            df[
                [
                    "worker_code",
                    "name",
                    "role",
                    "trade",
                    "salary",
                    "visa_expiry",
                    "phone",
                ]
            ],
            use_container_width=True,
            height=400,
        )

    with col2:
        st.subheader("ID Card Preview")
        selected_code = st.selectbox(
            "Select Employee",
            df["worker_code"].tolist(),
        )
        worker_row = df[df["worker_code"] == selected_code].iloc[0]
        render_id_card(worker_row)

        if REPORTLAB_AVAILABLE:
            pdf_bytes = generate_id_card_pdf(worker_row)
            if pdf_bytes:
                st.download_button(
                    "⬇️ Download ID Card PDF",
                    data=pdf_bytes,
                    file_name=f"{worker_row['worker_code']}_id_card.pdf",
                    mime="application/pdf",
                )
        else:
            st.info("To enable ID card PDF export: `pip install reportlab`")


def workers_page():
    st.header("👷 Workers – Quick Editor")

    conn = get_connection()
    df = pd.read_sql(
        "SELECT id, worker_code, name, role, trade, salary, visa_expiry, phone FROM workers ORDER BY id",
        conn,
    )

    edited = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        key="workers_editor",
    )

    if st.button("💾 Save Workers"):
        try:
            cur = conn.cursor()
            for _, row in edited.iterrows():
                name = str(row["name"]).strip() if pd.notna(row["name"]) else ""
                if not name:
                    continue
                worker_code = (
                    str(row["worker_code"]).strip()
                    if pd.notna(row["worker_code"])
                    else None
                )
                if not worker_code:
                    worker_code = generate_next_worker_code()
                role = str(row.get("role", "") or "")
                trade = str(row.get("trade", "") or "")
                phone = str(row.get("phone", "") or "")
                salary_val = float(row.get("salary", 0) or 0)
                visa_val = None
                if pd.notna(row.get("visa_expiry")):
                    visa_val = str(row["visa_expiry"])[:10]

                wid = row.get("id")
                if pd.isna(wid):
                    cur.execute(
                        """
                        INSERT INTO workers (worker_code, name, role, trade, salary, visa_expiry, phone)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (worker_code, name, role, trade, salary_val, visa_val, phone),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE workers
                           SET worker_code=?,
                               name=?,
                               role=?,
                               trade=?,
                               salary=?,
                               visa_expiry=?,
                               phone=?
                         WHERE id=?
                        """,
                        (worker_code, name, role, trade, salary_val, visa_val, phone, int(wid)),
                    )
            conn.commit()
            st.success("Workers saved.")
            do_rerun()
        except Exception as e:
            st.error(f"Error saving workers: {e}")
        finally:
            conn.close()
    else:
        conn.close()


def assignments_page():
    st.header("🔗 Assign Workers to Projects")

    conn = get_connection()
    projects = pd.read_sql("SELECT id, name FROM projects ORDER BY name", conn)
    workers = pd.read_sql(
        "SELECT id, worker_code, name, trade FROM workers ORDER BY worker_code",
        conn,
    )

    if projects.empty or workers.empty:
        conn.close()
        st.info("Need at least one project and one worker to assign.")
        return

    project_name = st.selectbox("Select Project", projects["name"].tolist())
    project_id = int(projects[projects["name"] == project_name]["id"].iloc[0])

    assigned_df = pd.read_sql(
        """
        SELECT w.id, w.worker_code, w.name, w.trade
        FROM workers w
        JOIN project_workers pw ON w.id = pw.worker_id
        WHERE pw.project_id=?
        ORDER BY w.worker_code
        """,
        conn,
        params=(project_id,),
    )

    assigned_ids = set(assigned_df["id"].tolist())

    all_labels = [
        f"{row.worker_code} - {row.name} ({row.trade})"
        for _, row in workers.iterrows()
    ]
    id_by_label = {
        f"{row.worker_code} - {row.name} ({row.trade})": int(row.id)
        for _, row in workers.iterrows()
    }

    preselect = [
        label for label, wid in id_by_label.items() if wid in assigned_ids
    ]

    selected_labels = st.multiselect(
        "Select workers assigned to this project",
        all_labels,
        default=preselect,
    )

    if st.button("💾 Save Assignments"):
        try:
            cur = conn.cursor()
            # Clear existing
            cur.execute("DELETE FROM project_workers WHERE project_id=?", (project_id,))
            # Insert new
            for label in selected_labels:
                wid = id_by_label[label]
                cur.execute(
                    "INSERT OR IGNORE INTO project_workers (project_id, worker_id) VALUES (?, ?)",
                    (project_id, wid),
                )
            conn.commit()
            st.success("Assignments updated.")
            do_rerun()
        except Exception as e:
            st.error(f"Error saving assignments: {e}")
        finally:
            conn.close()
    else:
        conn.close()


def attendance_page():
    st.header("🕒 Attendance – Today")

    conn = get_connection()
    projects = pd.read_sql("SELECT id, name FROM projects ORDER BY name", conn)
    workers = pd.read_sql(
        "SELECT id, worker_code, name, role, trade FROM workers ORDER BY worker_code",
        conn,
    )

    if projects.empty or workers.empty:
        conn.close()
        st.info("Need at least one project and one worker.")
        return

    project_name = st.selectbox("Project", projects["name"].tolist())
    project_id = int(projects[projects["name"] == project_name]["id"].iloc[0])

    # Workers assigned to this project
    assigned = pd.read_sql(
        """
        SELECT w.id, w.worker_code, w.name, w.role, w.trade
        FROM workers w
        JOIN project_workers pw ON w.id = pw.worker_id
        WHERE pw.project_id=?
        ORDER BY w.worker_code
        """,
        conn,
        params=(project_id,),
    )

    if assigned.empty:
        st.info("No workers assigned to this project. Use Assignments page.")
        return

    st.caption(f"Date: {TODAY.isoformat()}")

    for _, row in assigned.iterrows():
        wid = int(row["id"])
        current = get_today_attendance(wid, project_id)
        col1, col2, col3, col4 = st.columns([4, 1.5, 1.5, 2])
        with col1:
            st.markdown(
                f"**{row['worker_code']} – {row['name']}** ({row['trade']}, {row['role']})"
            )
        with col2:
            present = st.checkbox(
                "Present",
                value=bool(current),
                key=f"att_{wid}",
            )
        with col3:
            t_in = st.text_input(
                "Time In", value="07:00", key=f"tin_{wid}"
            )
        with col4:
            t_out = st.text_input(
                "Time Out", value="17:00", key=f"tout_{wid}"
            )

        if st.button("Save", key=f"save_att_{wid}"):
            toggle_attendance(
                worker_id=wid,
                project_id=project_id,
                att_date=TODAY.isoformat(),
                present=present,
                time_in=t_in if present else None,
                time_out=t_out if present else None,
            )
            st.success("Attendance updated.")
            do_rerun()

    conn.close()


def reports_page():
    st.header("📑 Attendance & Summary Reports")

    conn = get_connection()
    workers = pd.read_sql("SELECT id, worker_code, name FROM workers ORDER BY worker_code", conn)
    projects = pd.read_sql("SELECT id, name FROM projects ORDER BY name", conn)

    tab1, tab2 = st.tabs(["Daily Project Report", "Worker History"])

    with tab1:
        st.subheader("Daily Attendance by Project")
        date_sel = st.date_input("Date", value=TODAY, key="rep_date")
        proj_name = st.selectbox("Project", projects["name"].tolist(), key="rep_proj")
        proj_id = int(projects[projects["name"] == proj_name]["id"].iloc[0])

        df = pd.read_sql(
            """
            SELECT w.worker_code, w.name, w.role, w.trade,
                   a.time_in, a.time_out, a.signed_in
            FROM workers w
            LEFT JOIN attendance a
                 ON w.id = a.worker_id
                AND a.project_id = ?
                AND a.att_date = ?
            ORDER BY w.worker_code
            """,
            conn,
            params=(proj_id, date_sel.isoformat()),
        )
        df["Present"] = df["signed_in"].fillna(0).astype(int)
        st.dataframe(
            df[
                [
                    "worker_code",
                    "name",
                    "role",
                    "trade",
                    "time_in",
                    "time_out",
                    "Present",
                ]
            ],
            use_container_width=True,
        )

    with tab2:
        st.subheader("Worker Attendance History (last 60 days)")
        worker_label = st.selectbox(
            "Select Worker",
            [f"{row.worker_code} - {row.name}" for _, row in workers.iterrows()],
            key="rep_worker",
        )
        wid = int(
            workers[
                (
                    workers["worker_code"]
                    == worker_label.split(" - ")[0]
                )
            ]["id"].iloc[0]
        )

        since = TODAY - timedelta(days=60)
        df = pd.read_sql(
            """
            SELECT a.att_date, p.name AS project_name,
                   a.signed_in, a.time_in, a.time_out
            FROM attendance a
            LEFT JOIN projects p ON a.project_id = p.id
            WHERE a.worker_id=? AND a.att_date>=?
            ORDER BY a.att_date DESC
            """,
            conn,
            params=(wid, since.isoformat()),
        )
        if df.empty:
            st.info("No attendance in last 60 days.")
        else:
            df["Present"] = df["signed_in"].fillna(0).astype(int)
            st.dataframe(
                df[
                    ["att_date", "project_name", "time_in", "time_out", "Present"]
                ],
                use_container_width=True,
                height=400,
            )

    conn.close()


def payroll_page():
    st.header("💰 Payroll – Monthly Calculation")

    today = TODAY
    year = st.number_input("Year", min_value=2020, max_value=2100, value=today.year, step=1)
    month = st.number_input("Month", min_value=1, max_value=12, value=today.month, step=1)

    conn = get_connection()
    projects = pd.read_sql("SELECT id, name FROM projects ORDER BY name", conn)
    conn.close()

    proj_options = ["All Projects"] + projects["name"].tolist()
    proj_choice = st.selectbox("Project Scope", proj_options)

    if proj_choice == "All Projects":
        proj_id = None
    else:
        proj_id = int(projects[projects["name"] == proj_choice]["id"].iloc[0])

    if st.button("▶️ Calculate Payroll"):
        df = generate_monthly_payroll(int(year), int(month), proj_id)
        if df is None or df.empty:
            st.info("No workers or no attendance data for selected month.")
            return

        st.dataframe(df, use_container_width=True, height=400)

        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download Payroll CSV",
            data=csv_bytes,
            file_name=f"payroll_{year}_{month:02d}.csv",
            mime="text/csv",
        )

        if REPORTLAB_AVAILABLE:
            st.subheader("Payslip PDF Export")
            mode = st.radio(
                "PDF Mode",
                ["Single Employee", "Batch (select multiple)"],
            )

            if mode == "Single Employee":
                codes = df["worker_code"].tolist()
                code_sel = st.selectbox("Select Employee", codes, key="pay_pdf_single")
                row = df[df["worker_code"] == code_sel].iloc[0]
                pdf_bytes = generate_payslip_pdf(row, int(year), int(month))
                if pdf_bytes:
                    st.download_button(
                        "⬇️ Download Payslip PDF",
                        data=pdf_bytes,
                        file_name=f"payslip_{code_sel}_{year}_{month:02d}.pdf",
                        mime="application/pdf",
                    )
            else:
                codes = df["worker_code"].tolist()
                codes_sel = st.multiselect(
                    "Select Employees",
                    codes,
                    max_selections=5,
                    key="pay_pdf_multi",
                )
                if codes_sel:
                    rows = [df[df["worker_code"] == c].iloc[0] for c in codes_sel]
                    pdf_bytes = generate_payslips_batch_pdf(rows, int(year), int(month))
                    if pdf_bytes:
                        st.download_button(
                            "⬇️ Download Batch Payslips PDF (A5 pages)",
                            data=pdf_bytes,
                            file_name=f"payslips_batch_{year}_{month:02d}.pdf",
                            mime="application/pdf",
                        )
        else:
            st.info("To enable payslip PDF export: `pip install reportlab`")


def database_page():
    st.header("🗄 Raw Database Viewer")

    conn = get_connection()
    tabs = st.tabs(["Workers", "Projects", "Assignments", "Attendance"])

    with tabs[0]:
        df = pd.read_sql("SELECT * FROM workers", conn)
        st.dataframe(df, use_container_width=True)

    with tabs[1]:
        df = pd.read_sql("SELECT * FROM projects", conn)
        st.dataframe(df, use_container_width=True)

    with tabs[2]:
        df = pd.read_sql("SELECT * FROM project_workers", conn)
        st.dataframe(df, use_container_width=True)

    with tabs[3]:
        df = pd.read_sql("SELECT * FROM attendance", conn)
        st.dataframe(df, use_container_width=True)

    conn.close()


# ===================== ACCOUNTING SYNC PAGE =====================
def accounting_sync_page():
    st.header("📤 Accounting Sync – Export HR Master Data")

    st.markdown(
        """
هذه الصفحة مخصصة لربط نظام الـ HR مع **نظام المحاسبة**:

- تصدير ملف **الموظفين/العمّال** لاستخدامه في جدول Employees في نظام الحسابات  
- تصدير ملف **المشاريع** لاستخدامه في جدول Projects / Cost Centers  

> الملفات بصيغة CSV (تُفتح مباشرة في Excel) ويمكن رفعها لأي قاعدة بيانات محاسبية.
        """
    )

    conn = get_connection()
    workers_df = pd.read_sql(
        """
        SELECT
            id AS worker_id,
            worker_code,
            name,
            role,
            trade,
            salary,
            visa_expiry,
            phone
        FROM workers
        ORDER BY worker_code
        """,
        conn,
    )
    projects_df = pd.read_sql(
        """
        SELECT
            id AS project_id,
            name AS project_name,
            held AS held_flag
        FROM projects
        ORDER BY name
        """,
        conn,
    )
    conn.close()

    c1, c2 = st.columns(2)
    with c1:
        st.metric("Total Workers", len(workers_df))
    with c2:
        st.metric("Total Projects", len(projects_df))

    st.markdown("---")

    col1, col2 = st.columns(2)

    # ---- Workers export ----
    with col1:
        st.subheader("👷 Employees / Workers Master")
        st.caption("استخدم هذا الملف لجدول Employees في نظام المحاسبة.")
        st.dataframe(workers_df, use_container_width=True, height=300)

        workers_csv = workers_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download nps_workers_for_accounting.csv",
            data=workers_csv,
            file_name="nps_workers_for_accounting.csv",
            mime="text/csv",
        )

    # ---- Projects export ----
    with col2:
        st.subheader("🏗 Projects Master")
        st.caption("استخدم هذا الملف لجدول Projects أو Cost Centers في نظام المحاسبة.")
        st.dataframe(projects_df, use_container_width=True, height=300)

        projects_csv = projects_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download nps_projects_for_accounting.csv",
            data=projects_csv,
            file_name="nps_projects_for_accounting.csv",
            mime="text/csv",
        )

    st.info(
        """
💡 **اقتراح تطوير لاحقاً:**
يمكن لاحقاً إضافة زر "Import from Accounting" لقراءة أكواد المشاريع أو مراكز التكلفة من نظام الحسابات
وإعادة مزامنتها مع الـ HR.
        """
    )


# ===================== SETTINGS PAGE – DATA PATH =====================
def settings_page():
    global DATA_DIR, PHOTOS_DIR, DB_PATH

    st.header("⚙️ Settings – Data / Cloud Path")

    st.markdown(
        """
### Data Folder (OneDrive or Local)

The app stores:

- `hr.db`  → HR database (workers, projects, attendance, payroll)
- `photos` → employee photo files

**Recommended setup (OneDrive shared folder):**

1. On one PC, create folder: `C:\\Users\\<username>\\OneDrive\\NPS_HR_DATA`  
2. Put `hr.db` and `photos` in this OneDrive folder.  
3. Install this app on all HR PCs.  
4. Point all PCs to the **same** OneDrive folder.  
5. All HR users will see the same data.
        """
    )

    st.write(f"**Default OneDrive path:** `{DEFAULT_DATA_DIR}`")
    st.write(f"**Current active data path:** `{DATA_DIR}`")

    new_path = st.text_input(
        "Data folder path (for hr.db + photos)",
        value=DATA_DIR,
        help="Example: C:\\Users\\acer\\OneDrive\\NPS_HR_DATA",
    )

    if st.button("Save Data Path"):
        new_path_clean = new_path.strip()
        if not new_path_clean:
            st.warning("Please enter a valid folder path.")
        else:
            try:
                os.makedirs(new_path_clean, exist_ok=True)
                photos_dir = os.path.join(new_path_clean, "photos")
                os.makedirs(photos_dir, exist_ok=True)

                DATA_DIR = new_path_clean
                PHOTOS_DIR = photos_dir
                DB_PATH = os.path.join(new_path_clean, "hr.db")

                st.success(f"Data path updated to: {new_path_clean}")
                st.info(
                    "If hr.db and photos already exist in this folder, the app will use them. "
                    "Otherwise a new empty database will be created."
                )
                do_rerun()
            except Exception as e:
                st.error(f"Failed to use this path: {e}")

    st.markdown(
        """
### How to move existing data (step by step)

1. Close the HR app.  
2. Go to your old data folder (for example `D:\\NileHR\\app\\data`).  
3. Copy:
   - `hr.db` → into your new data folder  
   - `photos` folder → into your new data folder  
4. Open the HR app again.  
5. In **Settings**, set the data path to that folder (if not already).  
6. Confirm that employees, projects, attendance, and photos appear correctly.
        """
    )


# ===================== HELP / ABOUT =====================
def help_page():
    st.header("ℹ️ Help / About – NPS HR")

    st.markdown(
        """
### Overview
This system is built for **Nile Projects Service Company – MEP Contracting** to manage:

- Employee master data & ID cards  
- Project list & worker assignments  
- Daily attendance with **Time In / Out**  
- Automatic overtime calculation (> 9 hours/day)  
- Monthly payroll & salary slips (A5 size)  
- Visa expiry tracking  
- Shared HR database via OneDrive (or any folder you configure)

### Payroll Printing

- **Single slip:** choose employee in *Payroll* page → download A5 PDF.  
- **Batch (up to 5):** multi-select employees → download A5 PDF with several pages.  
- To print **many slips on one paper**, use your printer options:
  - “Multiple pages per sheet” → choose 4 or 6 per sheet.

### Data / Cloud

- Default data folder: `C:\\Users\\<username>\\OneDrive\\NPS_HR_DATA`  
- You can change it anytime from **Settings → Data / Cloud Path**.

### Technical Notes

- Database & photos live in the **data folder** you configure (see Settings).  
- To enable PDF exports: `pip install reportlab`  

Official website: **www.nileps.com**
"""
    )


# ===================== MAIN APP & SIDEBAR =====================
def main():
    st.set_page_config(page_title="NPS HR System", layout="wide")

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
            color: #0b1120;
            font-size: 0.8rem;
            text-align: center;
            padding: 10px;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="nps-header">Nile Projects Service Company – HR System</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="nps-subtitle">MEP Contracting · HR, Attendance & Payroll</div>',
        unsafe_allow_html=True,
    )

    if "page" not in st.session_state:
        st.session_state["page"] = "Dashboard"

    init_db()

    st.sidebar.title("NPS HR Navigation")

    pages = [
        "Dashboard",
        "Projects",
        "Employees",
        "Workers",
        "Assignments",
        "Attendance",
        "Reports",
        "Payroll",
        "Accounting Sync",   # NEW
        "Database",
        "Settings",
        "Help / About",
    ]

    selected_page = st.sidebar.radio(
        "Main Menu",
        pages,
        index=pages.index(st.session_state["page"]),
        key="main_menu",
    )
    st.session_state["page"] = selected_page

    st.sidebar.markdown("### Add Master Data")

    # Add Project (quick)
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
            do_rerun()
        else:
            st.sidebar.warning("Enter project name.")

    st.sidebar.markdown("---")
    # Add Employee (quick)
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
        "Basic Salary", min_value=0.0, step=100.0, key="sb_emp_salary"
    )
    w_phone = st.sidebar.text_input("Phone", key="sb_emp_phone")
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
                INSERT INTO workers (worker_code, name, role, trade, salary, visa_expiry, photo_file, phone)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code,
                    w_name.strip(),
                    w_role,
                    w_trade,
                    w_salary,
                    w_visa.isoformat(),
                    photo_file,
                    w_phone.strip(),
                ),
            )
            conn.commit()
            conn.close()
            st.sidebar.success(f"Employee added with ID: {code}")
            do_rerun()

    st.sidebar.markdown("---")
    st.sidebar.caption(f"Data path:\n{DATA_DIR}")

    current_page = st.session_state["page"]

    if current_page == "Dashboard":
        dashboard_page()
    elif current_page == "Projects":
        projects_page()
    elif current_page == "Employees":
        employees_page()
    elif current_page == "Workers":
        workers_page()
    elif current_page == "Assignments":
        assignments_page()
    elif current_page == "Attendance":
        attendance_page()
    elif current_page == "Reports":
        reports_page()
    elif current_page == "Payroll":
        payroll_page()
    elif current_page == "Accounting Sync":
        accounting_sync_page()
    elif current_page == "Database":
        database_page()
    elif current_page == "Settings":
        settings_page()
    elif current_page == "Help / About":
        help_page()

    st.markdown(
        '<div class="nps-footer">© 2025 Nile Projects Service Company | www.nileps.com</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
