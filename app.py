import datetime
from contextlib import contextmanager

import pandas as pd
import streamlit as st
from sqlalchemy import text

# -------------------------
# Optional ReportLab Import
# -------------------------
try:
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


# -------------------------
# Streamlit Basic Config
# -------------------------
st.set_page_config(
    page_title="NPS HR Cloud",
    page_icon="👷",
    layout="wide",
)


# -------------------------
# Helpers
# -------------------------
def do_rerun():
    """Safe rerun helper (supports old & new Streamlit)."""
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


@st.cache_resource
def get_connection():
    """
    Get a Streamlit SQL connection using secrets:
    secrets.toml must contain:
    [connections.nps_db]
    url = "postgresql://..."
    """
    conn = st.connection("nps_db", type="sql")
    return conn


@contextmanager
def get_session():
    """
    Context manager returning a SQLAlchemy session
    from the Streamlit connection.
    """
    conn = get_connection()
    with conn.session as s:
        yield s


# -------------------------
# DB Initialization
# -------------------------
def init_db():
    """
    Create basic tables if they do not exist.
    Adjust schema later as needed.
    """
    with get_session() as s:
        # Employees table
        s.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS employees (
                    id SERIAL PRIMARY KEY,
                    worker_code VARCHAR(50) UNIQUE NOT NULL,
                    name VARCHAR(200) NOT NULL,
                    role VARCHAR(100),
                    project_code VARCHAR(100),
                    basic_salary NUMERIC(12, 2) DEFAULT 0,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                """
            )
        )

        # Projects table
        s.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id SERIAL PRIMARY KEY,
                    project_code VARCHAR(100) UNIQUE NOT NULL,
                    project_name VARCHAR(255) NOT NULL,
                    status VARCHAR(50) DEFAULT 'Active',
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                """
            )
        )

        # Attendance table
        s.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS attendance (
                    id SERIAL PRIMARY KEY,
                    worker_code VARCHAR(50) NOT NULL,
                    project_code VARCHAR(100),
                    att_date DATE NOT NULL,
                    status VARCHAR(20) DEFAULT 'Present', -- Present / Absent / Leave
                    overtime_hours NUMERIC(6, 2) DEFAULT 0,
                    signed_in BOOLEAN DEFAULT TRUE
                );
                """
            )
        )

        s.commit()


# -------------------------
# Data Access Functions
# -------------------------
def get_employees():
    conn = get_connection()
    df = conn.query("SELECT * FROM employees ORDER BY worker_code;")
    return df


def get_projects():
    conn = get_connection()
    df = conn.query("SELECT * FROM projects ORDER BY project_code;")
    return df


def get_attendance_range(date_from, date_to):
    conn = get_connection()
    df = conn.query(
        """
        SELECT *
        FROM attendance
        WHERE att_date >= :dfrom AND att_date <= :dto
        ORDER BY att_date DESC, worker_code;
        """,
        params={"dfrom": date_from, "dto": date_to},
    )
    return df


def add_or_update_employee(worker_code, name, role, project_code, basic_salary, is_active):
    with get_session() as s:
        s.execute(
            text(
                """
                INSERT INTO employees (worker_code, name, role, project_code, basic_salary, is_active)
                VALUES (:worker_code, :name, :role, :project_code, :basic_salary, :is_active)
                ON CONFLICT (worker_code) DO UPDATE
                    SET name = EXCLUDED.name,
                        role = EXCLUDED.role,
                        project_code = EXCLUDED.project_code,
                        basic_salary = EXCLUDED.basic_salary,
                        is_active = EXCLUDED.is_active;
                """
            ),
            {
                "worker_code": worker_code,
                "name": name,
                "role": role,
                "project_code": project_code,
                "basic_salary": basic_salary,
                "is_active": is_active,
            },
        )
        s.commit()


def add_or_update_project(project_code, project_name, status, is_active):
    with get_session() as s:
        s.execute(
            text(
                """
                INSERT INTO projects (project_code, project_name, status, is_active)
                VALUES (:project_code, :project_name, :status, :is_active)
                ON CONFLICT (project_code) DO UPDATE
                    SET project_name = EXCLUDED.project_name,
                        status = EXCLUDED.status,
                        is_active = EXCLUDED.is_active;
                """
            ),
            {
                "project_code": project_code,
                "project_name": project_name,
                "status": status,
                "is_active": is_active,
            },
        )
        s.commit()


def add_or_update_attendance(worker_code, project_code, att_date, status, overtime_hours):
    """
    Insert or update attendance for a worker on a specific date.
    This allows editing past days.
    """
    with get_session() as s:
        s.execute(
            text(
                """
                INSERT INTO attendance (worker_code, project_code, att_date, status, overtime_hours, signed_in)
                VALUES (:worker_code, :project_code, :att_date, :status, :overtime_hours, TRUE)
                ON CONFLICT (worker_code, att_date) DO UPDATE
                    SET project_code = EXCLUDED.project_code,
                        status = EXCLUDED.status,
                        overtime_hours = EXCLUDED.overtime_hours,
                        signed_in = EXCLUDED.signed_in;
                """
            ),
            {
                "worker_code": worker_code,
                "project_code": project_code,
                "att_date": att_date,
                "status": status,
                "overtime_hours": overtime_hours,
            },
        )
        s.commit()


# NOTE:
# The ON CONFLICT (worker_code, att_date) requires a unique constraint:
# Adjust DB if needed:
# ALTER TABLE attendance ADD CONSTRAINT uq_att UNIQUE (worker_code, att_date);
# You can run it manually once in psql.

# -------------------------
# ID Card Export (ReportLab)
# -------------------------
def export_id_card(row):
    """
    Export a worker ID card to PDF using ReportLab.
    `row` is a Pandas row from employees DataFrame.
    """
    if not REPORTLAB_AVAILABLE:
        st.info("To export ID card to PDF: `pip install reportlab`")
        return

    worker_code = row["worker_code"]
    name = row["name"]
    role = row.get("role", "")
    project_code = row.get("project_code", "")

    filename = f"ID_{worker_code}.pdf"
    c = canvas.Canvas(filename)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, 800, "Nile Projects Service - Worker ID")
    c.setFont("Helvetica", 12)
    c.drawString(50, 770, f"Name: {name}")
    c.drawString(50, 750, f"Code: {worker_code}")
    c.drawString(50, 730, f"Role: {role}")
    c.drawString(50, 710, f"Project: {project_code}")
    c.showPage()
    c.save()

    with open(filename, "rb") as f:
        st.download_button(
            label=f"⬇️ Download ID Card ({worker_code})",
            data=f,
            file_name=filename,
            mime="application/pdf",
        )
# -------------------------
# Pages
# -------------------------
def dashboard_page():
    st.title("👷 NPS HR – Dashboard")

    today = datetime.date.today()

    # Get today attendance & global stats
    df_att = get_attendance_range(today, today)
    df_emp = get_employees()
    df_proj = get_projects()

    total_workers = len(df_emp)
    present = len(df_att[df_att["status"] == "Present"])
    absent = len(df_att[df_att["status"] == "Absent"])
    on_leave = len(df_att[df_att["status"] == "Leave"])

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Workers", int(total_workers))
    col2.metric("Present Today", int(present))
    col3.metric("Absent Today", int(absent))
    col4.metric("On Leave", int(on_leave))

    st.markdown("---")
    st.subheader("Present by Project (Today)")

    if not df_att.empty:
        proj_counts = df_att[df_att["status"] == "Present"].groupby("project_code")[
            "worker_code"
        ].count()
        proj_df = proj_counts.reset_index().rename(columns={"worker_code": "present"})

        st.bar_chart(proj_df.set_index("project_code")["present"])
    else:
        st.info("No attendance recorded for today yet.")


def employees_page():
    st.title("👤 Employees")

    df_emp = get_employees()
    df_proj = get_projects()

    with st.expander("➕ Add / Update Employee", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            worker_code = st.text_input("Worker Code").strip()
            name = st.text_input("Name").strip()
            role = st.text_input("Role / Trade").strip()
        with col2:
            project_code = st.selectbox(
                "Default Project",
                options=[""] + df_proj["project_code"].tolist(),
                index=0,
            )
            basic_salary = st.number_input("Basic Salary", min_value=0.0, step=25.0)
            is_active = st.checkbox("Active", value=True)

        if st.button("💾 Save Employee"):
            if worker_code and name:
                add_or_update_employee(
                    worker_code=worker_code,
                    name=name,
                    role=role,
                    project_code=project_code or None,
                    basic_salary=basic_salary,
                    is_active=is_active,
                )
                st.success("Employee saved.")
                do_rerun()
            else:
                st.error("Worker Code and Name are required.")

    st.markdown("---")
    st.subheader("Employees List")

    if df_emp.empty:
        st.info("No employees found. Add new employees above.")
        return

    st.dataframe(df_emp, use_container_width=True)

    st.markdown("### ID Card Export")
    selected_code = st.selectbox(
        "Select worker to export ID card", options=[""] + df_emp["worker_code"].tolist()
    )
    if selected_code:
        row = df_emp[df_emp["worker_code"] == selected_code].iloc[0]
        export_id_card(row)


def projects_page():
    st.title("🏗 Projects")

    df_proj = get_projects()

    with st.expander("➕ Add / Update Project", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            project_code = st.text_input("Project Code (e.g., NPS-25-P612)").strip()
            project_name = st.text_input("Project Name").strip()
        with col2:
            status = st.selectbox("Status", ["Active", "On Hold", "Closed"], index=0)
            is_active = st.checkbox("Active", value=True)

        if st.button("💾 Save Project"):
            if project_code and project_name:
                add_or_update_project(
                    project_code=project_code,
                    project_name=project_name,
                    status=status,
                    is_active=is_active,
                )
                st.success("Project saved.")
                do_rerun()
            else:
                st.error("Project Code and Project Name are required.")

    st.markdown("---")
    st.subheader("Projects List")

    if df_proj.empty:
        st.info("No projects found. Add new projects above.")
        return

    st.dataframe(df_proj, use_container_width=True)


def attendance_page():
    st.title("📅 Attendance")

    df_emp = get_employees()
    df_proj = get_projects()

    if df_emp.empty:
        st.warning("No employees found. Please add employees first.")
        return

    st.subheader("➕ Add / Edit Attendance (Any Date)")

    col1, col2, col3 = st.columns(3)
    with col1:
        att_date = st.date_input("Attendance Date", value=datetime.date.today())
    with col2:
        project_code = st.selectbox(
            "Project",
            options=[""] + df_proj["project_code"].tolist(),
            index=0,
        )
    with col3:
        status = st.selectbox("Status", ["Present", "Absent", "Leave"], index=0)

    worker_code = st.selectbox(
        "Select Worker", options=df_emp["worker_code"].tolist(), index=0
    )
    overtime_hours = st.number_input("Overtime Hours", min_value=0.0, step=0.5)

    if st.button("💾 Save Attendance"):
        add_or_update_attendance(
            worker_code=worker_code,
            project_code=project_code or None,
            att_date=att_date,
            status=status,
            overtime_hours=overtime_hours,
        )
        st.success(
            f"Attendance saved for {worker_code} on {att_date.strftime('%Y-%m-%d')}."
        )

    st.markdown("---")
    st.subheader("Attendance Log")

    col_from, col_to = st.columns(2)
    with col_from:
        date_from = st.date_input(
            "From Date",
            value=datetime.date.today() - datetime.timedelta(days=7),
            key="att_from",
        )
    with col_to:
        date_to = st.date_input(
            "To Date",
            value=datetime.date.today(),
            key="att_to",
        )

    df_att = get_attendance_range(date_from, date_to)
    if df_att.empty:
        st.info("No attendance records for selected range.")
    else:
        st.dataframe(df_att, use_container_width=True)


def payroll_page():
    st.title("💰 Payroll (Basic Demo)")

    df_emp = get_employees()
    today = datetime.date.today()

    year = st.number_input("Year", min_value=2000, max_value=2100, value=today.year)
    month = st.number_input("Month", min_value=1, max_value=12, value=today.month)

    first_day = datetime.date(int(year), int(month), 1)
    if month == 12:
        last_day = datetime.date(int(year) + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        last_day = datetime.date(int(year), int(month) + 1, 1) - datetime.timedelta(
            days=1
        )

    df_att = get_attendance_range(first_day, last_day)

    if df_emp.empty:
        st.warning("No employees found.")
        return

    # Simple payroll calc: salary / 30 * days_present + overtime * fixed_rate
    OT_RATE = st.number_input("Overtime Rate per Hour", min_value=0.0, value=5.0)

    records = []
    for _, emp in df_emp.iterrows():
        wc = emp["worker_code"]
        basic_sal = float(emp.get("basic_salary", 0) or 0)
        emp_att = df_att[df_att["worker_code"] == wc]
        days_present = len(emp_att[emp_att["status"] == "Present"])
        total_ot = float(emp_att["overtime_hours"].sum() or 0)

        daily_rate = basic_sal / 30.0 if basic_sal else 0
        salary_component = daily_rate * days_present
        ot_component = total_ot * OT_RATE
        total_pay = salary_component + ot_component

        records.append(
            {
                "worker_code": wc,
                "name": emp["name"],
                "days_present": days_present,
                "total_overtime_hours": round(total_ot, 2),
                "basic_salary": basic_sal,
                "salary_component": round(salary_component, 2),
                "overtime_component": round(ot_component, 2),
                "total_pay": round(total_pay, 2),
            }
        )

    df_pay = pd.DataFrame(records)
    st.dataframe(df_pay, use_container_width=True)

    csv = df_pay.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇️ Download Payroll CSV",
        data=csv,
        file_name=f"payroll_{year}_{month}.csv",
        mime="text/csv",
    )


# -------------------------
# Main App & Navigation
# -------------------------
def main():
    # Ensure DB exists
    init_db()

    if "page" not in st.session_state:
        st.session_state["page"] = "Dashboard"

    st.sidebar.title("NPS HR Cloud")

    # Main navigation
    page = st.sidebar.radio(
        "Go to",
        [
            "Dashboard",
            "Attendance",
            "Employees",
            "Projects",
            "Payroll",
        ],
        index=[
            "Dashboard",
            "Attendance",
            "Employees",
            "Projects",
            "Payroll",
        ].index(st.session_state["page"]),
    )

    st.session_state["page"] = page

    # Quick Actions
    st.sidebar.markdown("### Quick Actions")
    qa1, qa2 = st.sidebar.columns(2)
    with qa1:
        if st.button("🏠 Dash", key="qa_dash"):
            st.session_state["page"] = "Dashboard"
            do_rerun()
    with qa2:
        if st.button("📅 Att", key="qa_att"):
            st.session_state["page"] = "Attendance"
            do_rerun()
    qa3, qa4 = st.sidebar.columns(2)
    with qa3:
        if st.button("👤 Emp", key="qa_emp"):
            st.session_state["page"] = "Employees"
            do_rerun()
    with qa4:
        if st.button("💰 Pay", key="qa_pay"):
            st.session_state["page"] = "Payroll"
            do_rerun()

    # Render selected page
    if st.session_state["page"] == "Dashboard":
        dashboard_page()
    elif st.session_state["page"] == "Attendance":
        attendance_page()
    elif st.session_state["page"] == "Employees":
        employees_page()
    elif st.session_state["page"] == "Projects":
        projects_page()
    elif st.session_state["page"] == "Payroll":
        payroll_page()
    else:
        dashboard_page()


if __name__ == "__main__":
    main()

