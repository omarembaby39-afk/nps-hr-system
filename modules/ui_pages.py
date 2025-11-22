
import streamlit as st
from datetime import time

from modules.db import (
    get_projects,
    get_workers,
    add_project,
    update_project,
    delete_project,
    add_worker,
    update_worker,
    delete_worker,
    assign_worker_to_project,
    unassign_worker,
    get_assignments,
    mark_attendance,
    get_attendance,
    create_user,
)
from modules.core import (
    TODAY,
    get_visa_status,
    upload_photo_to_supabase,
    render_id_card,
    generate_monthly_payroll,
    generate_payslip_pdf,
    hours_between,
)


def page_dashboard():
    st.markdown("### 📊 HR & Project Dashboard")

    workers = get_workers()
    projects = get_projects()
    today_att = get_attendance(TODAY.isoformat())

    total_workers = len(workers)
    present_today = len(today_att[today_att["signed_in"] == 1]) if not today_att.empty else 0
    absent_today = max(total_workers - present_today, 0)
    active_projects = len(projects[projects["held"] == 0]) if not projects.empty else 0
    held_projects = len(projects[projects["held"] == 1]) if not projects.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Workers", total_workers)
    c2.metric("Present Today", present_today)
    c3.metric("Absent Today", absent_today)
    c4.metric("Active / Held", f"{active_projects} / {held_projects}")

    st.markdown("")
    tab1, tab2 = st.tabs(["Projects Overview", "Today Attendance"])

    with tab1:
        st.markdown("#### 🏗 Projects Status")
        if projects.empty:
            st.info("No projects found. Add projects from the Projects page.")
        else:
            df_proj = projects.rename(
                columns={"id": "ID", "name": "Project", "held": "Held (1=yes)"}
            )
            st.dataframe(df_proj, use_container_width=True)

    with tab2:
        st.markdown("#### 👷 Workers Present Today")
        if today_att.empty:
            st.info("No attendance marked for today yet.")
        else:
            att = today_att.merge(
                workers[["id", "worker_code", "name", "role", "trade"]],
                left_on="worker_id",
                right_on="id",
                how="left",
            ).merge(
                projects[["id", "name"]],
                left_on="project_id",
                right_on="id",
                how="left",
                suffixes=("_w", "_p"),
            )
            att["hours"] = att.apply(
                lambda r: hours_between(r["time_in"], r["time_out"]), axis=1
            )
            view = att.rename(
                columns={
                    "worker_code": "Worker ID",
                    "name_w": "Name",
                    "role": "Role",
                    "trade": "Trade",
                    "name_p": "Project",
                    "time_in": "Time In",
                    "time_out": "Time Out",
                    "hours": "Hours",
                }
            )[
                [
                    "Worker ID",
                    "Name",
                    "Role",
                    "Trade",
                    "Project",
                    "Time In",
                    "Time Out",
                    "Hours",
                ]
            ]
            st.dataframe(view, use_container_width=True)


def page_employees():
    st.markdown("### 👤 Employees – Master Data")

    workers = get_workers()

    with st.expander("Employee List", expanded=True):
        if workers.empty:
            st.info("No employees found yet. Use the form below to add.")
        else:
            filter_text = st.text_input("Filter by name / trade / role", "")
            df = workers.copy()
            if filter_text:
                f = filter_text.lower()
                df = df[
                    df["name"].str.lower().str.contains(f)
                    | df["role"].str.lower().str.contains(f)
                    | df["trade"].str.lower().str.contains(f)
                ]
            show_cols = [
                "worker_code",
                "name",
                "role",
                "trade",
                "salary",
                "visa_expiry",
                "phone",
            ]
            st.dataframe(df[show_cols], use_container_width=True)

    st.markdown("---")
    col_left, col_right = st.columns([1.2, 1])

    with col_left:
        st.markdown("#### ➕ Add New Employee")
        with st.form("add_emp_form"):
            name = st.text_input("Name")
            role = st.text_input("Role")
            trade = st.text_input("Trade")
            salary = st.number_input("Basic Salary", 0.0, step=100.0)
            visa = st.date_input("Visa Expiry", TODAY)
            phone = st.text_input("Phone")
            photo = st.file_uploader(
                "Photo (stored in Supabase Storage)",
                type=["png", "jpg", "jpeg"],
            )
            submitted = st.form_submit_button("Save New Employee")

        if submitted:
            if not name.strip():
                st.warning("Name is required.")
            else:
                code = f"NPS-W{workers.shape[0] + 1:04d}"
                photo_url = None
                if photo is not None:
                    photo_url = upload_photo_to_supabase(photo, code)
                add_worker(
                    code,
                    name.strip(),
                    role.strip(),
                    trade.strip(),
                    salary,
                    visa.isoformat(),
                    phone.strip(),
                    photo_url,
                )
                st.success(f"Employee {name} added.")
                st.rerun()

    with col_right:
        st.markdown("#### ✏️ Edit Employee / ID Card")
        if workers.empty:
            st.info("No employees yet.")
            return

        emp_names = workers["name"].tolist()
        selected = st.selectbox("Select employee", emp_names)
        emp = workers[workers["name"] == selected].iloc[0]

        render_id_card(emp)

        with st.form("edit_emp_form"):
            new_name = st.text_input("Name", emp["name"])
            new_role = st.text_input("Role", emp["role"])
            new_trade = st.text_input("Trade", emp["trade"])
            new_salary = st.number_input("Salary", value=float(emp["salary"]))
            new_visa = st.date_input("Visa Expiry", emp["visa_expiry"])
            new_phone = st.text_input("Phone", emp["phone"])
            new_photo = st.file_uploader(
                "Replace Photo", type=["png", "jpg", "jpeg"]
            )
            save_changes = st.form_submit_button("Update Employee")

        if save_changes:
            photo_url = emp["photo_url"]
            if new_photo is not None:
                photo_url = upload_photo_to_supabase(new_photo, emp["worker_code"])
            update_worker(
                emp["id"],
                new_name.strip(),
                new_role.strip(),
                new_trade.strip(),
                new_salary,
                new_visa.isoformat(),
                new_phone.strip(),
                photo_url,
            )
            st.success("Employee updated.")
            st.rerun()

        if st.button("❌ Delete This Employee"):
            delete_worker(emp["id"])
            st.success("Employee deleted.")
            st.rerun()


def page_projects():
    st.markdown("### 🏗 Projects – List & Status")

    projects = get_projects()
    col1, col2 = st.columns([1.3, 1])

    with col1:
        st.markdown("#### Current Projects")
        if projects.empty:
            st.info("No projects yet. Add one using the form.")
        else:
            df = projects.rename(
                columns={"id": "ID", "name": "Project", "held": "Held (1=yes)"}
            )
            st.dataframe(df, use_container_width=True)

    with col2:
        st.markdown("#### ➕ Add New Project")
        with st.form("add_project_form"):
            pname = st.text_input("Project Name")
            held = st.checkbox("Held (paused/on hold)")
            submitted = st.form_submit_button("Save Project")

        if submitted:
            if not pname.strip():
                st.warning("Project name is required.")
            else:
                add_project(pname.strip(), int(held))
                st.success("Project added.")
                st.rerun()

        st.markdown("---")
        st.markdown("#### ✏️ Edit / Delete Project")

        if projects.empty:
            st.info("No projects to edit.")
            return

        names = projects["name"].tolist()
        selected = st.selectbox("Select project", names)
        row = projects[projects["name"] == selected].iloc[0]

        with st.form("edit_project_form"):
            new_name = st.text_input("Project Name", row["name"])
            new_held = st.checkbox("Held", bool(row["held"]))
            save = st.form_submit_button("Update Project")

        if save:
            update_project(row["id"], new_name.strip(), int(new_held))
            st.success("Project updated.")
            st.rerun()

        if st.button("❌ Delete Project"):
            delete_project(row["id"])
            st.success("Project deleted.")
            st.rerun()


def page_assignments():
    st.markdown("### 🔗 Worker–Project Assignments")

    workers = get_workers()
    projects = get_projects()
    assigns = get_assignments()

    if workers.empty or projects.empty:
        st.info("Need workers and projects before assigning.")
        return

    st.info("Tick the projects for each worker, then click Save Assignments at the bottom.")

    for _, worker in workers.iterrows():
        st.markdown(
            f"#### 👤 {worker['name']} – {worker['role']} ({worker['trade']})"
        )
        cols = st.columns(3)
        for i, (_, proj) in enumerate(projects.iterrows()):
            col = cols[i % 3]
            assigned = not assigns[
                (assigns["worker_id"] == worker["id"])
                & (assigns["project_id"] == proj["id"])
            ].empty
            checked = col.checkbox(
                proj["name"],
                value=assigned,
                key=f"assign_{worker['id']}_{proj['id']}",
            )
            if checked and not assigned:
                assign_worker_to_project(proj["id"], worker["id"])
            if not checked and assigned:
                unassign_worker(proj["id"], worker["id"])

    if st.button("💾 Save Assignments"):
        st.success("Assignments updated.")
        st.rerun()


def page_attendance():
    st.markdown("### 📅 Attendance – Time In / Time Out")

    workers = get_workers()
    projects = get_projects()

    if workers.empty or projects.empty:
        st.info("Need workers and projects first.")
        return

    st.markdown(f"**Date:** {TODAY.isoformat()}")

    with st.form("att_form"):
        for _, w in workers.iterrows():
            c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
            c1.write(f"**{w['name']}**")
            proj_name = c2.selectbox(
                "Project",
                projects["name"],
                key=f"proj_{w['id']}",
            )
            t_in = c3.time_input(
                "In",
                value=time(7, 0),
                key=f"in_{w['id']}",
            )
            t_out = c3.time_input(
                "Out",
                value=time(16, 0),
                key=f"out_{w['id']}",
            )
            present = c4.checkbox("Present", key=f"pre_{w['id']}")

        submitted = st.form_submit_button("Save Attendance")

    if submitted:
        for _, w in workers.iterrows():
            proj = st.session_state[f"proj_{w['id']}"]
            p_id = projects[projects["name"] == proj]["id"].iloc[0]
            mark_attendance(
                w["id"],
                p_id,
                TODAY.isoformat(),
                int(st.session_state[f"pre_{w['id']}"]),
                st.session_state[f"in_{w['id']}"].strftime("%H:%M"),
                st.session_state[f"out_{w['id']}"].strftime("%H:%M"),
            )
        st.success("Attendance saved.")
        st.rerun()


def page_reports():
    st.markdown("### 📊 Reports & Analytics")

    choice = st.selectbox(
        "Select Report Type",
        ["Daily Attendance", "Monthly Payroll Summary", "Visa Status"],
    )

    if choice == "Daily Attendance":
        att = get_attendance(TODAY.isoformat())
        workers = get_workers()
        projects = get_projects()

        if att.empty:
            st.info("No attendance for today.")
            return

        df = att.merge(
            workers[["id", "worker_code", "name"]],
            left_on="worker_id",
            right_on="id",
            how="left",
        ).merge(
            projects[["id", "name"]],
            left_on="project_id",
            right_on="id",
            how="left",
            suffixes=("_w", "_p"),
        )
        df["hours"] = df.apply(
            lambda r: hours_between(r["time_in"], r["time_out"]), axis=1
        )

        view = df.rename(
            columns={
                "worker_code": "Worker ID",
                "name_w": "Name",
                "name_p": "Project",
                "att_date": "Date",
                "time_in": "Time In",
                "time_out": "Time Out",
                "hours": "Hours",
            }
        )[
            [
                "Worker ID",
                "Name",
                "Project",
                "Date",
                "Time In",
                "Time Out",
                "Hours",
                "signed_in",
            ]
        ]
        st.dataframe(view, use_container_width=True)

    elif choice == "Visa Status":
        w = get_workers()
        if w.empty:
            st.info("No employees.")
            return
        w["visa_color"], w["visa_label"] = zip(
            *w["visa_expiry"].apply(get_visa_status)
        )
        view = w[
            ["worker_code", "name", "role", "trade", "visa_expiry", "visa_label"]
        ]
        st.dataframe(view, use_container_width=True)

    elif choice == "Monthly Payroll Summary":
        c1, c2 = st.columns(2)
        year = c1.number_input("Year", 2024, 2100, TODAY.year)
        month = c2.number_input("Month", 1, 12, TODAY.month)

        df = generate_monthly_payroll(year, month)
        if df.empty:
            st.info("No payroll data for this month.")
            return

        st.dataframe(df, use_container_width=True)
        st.metric("Total Net Payroll", f"{df['net_pay'].sum():,.2f} QAR")


def page_payroll():
    st.markdown("### 💰 Payroll & Payslips")

    c1, c2 = st.columns(2)
    year = c1.number_input("Year", 2024, 2100, TODAY.year)
    month = c2.number_input("Month", 1, 12, TODAY.month)

    if st.button("Generate Payroll"):
        df = generate_monthly_payroll(year, month)
        if df.empty:
            st.info("No data for this month.")
            return

        st.dataframe(df, use_container_width=True)
        total = df["net_pay"].sum()
        st.success(f"Total Payroll = {total:,.2f} QAR")

        st.markdown("---")
        st.markdown("#### 📄 Download Individual Payslip (A5)")

        emp_names = df["name"].tolist()
        sel = st.selectbox("Employee", emp_names)
        row = df[df["name"] == sel].iloc[0]

        if st.button("Generate Payslip PDF"):
            pdf = generate_payslip_pdf(row, year, month)
            if pdf is None:
                st.warning("ReportLab not installed on server.")
            else:
                st.download_button(
                    label=f"Download {sel} Payslip",
                    data=pdf,
                    file_name=f"{sel}_payslip_{month}_{year}.pdf",
                    mime="application/pdf",
                )


def page_database_admin():
    st.markdown("### 🗄 Database Admin (Read-Only)")

    tab1, tab2, tab3 = st.tabs(["Employees", "Projects", "Assignments"])

    with tab1:
        st.write("Employees table:")
        st.dataframe(get_workers(), use_container_width=True)

    with tab2:
        st.write("Projects table:")
        st.dataframe(get_projects(), use_container_width=True)

    with tab3:
        st.write("Assignments table:")
        st.dataframe(get_assignments(), use_container_width=True)


def page_user_admin():
    st.markdown("### 👥 User Management")

    role = st.session_state.get("role")
    if role != "admin":
        st.error("Access denied. Only admin users can manage accounts.")
        return

    st.info("Create new login accounts for HR / Supervisors / Viewers.")

    with st.form("create_user_form"):
        new_user = st.text_input("Username")
        new_pass = st.text_input("Password", type="password")
        new_role = st.selectbox("Role", ["admin", "hr", "supervisor", "viewer"])
        submitted = st.form_submit_button("Create User")

    if submitted:
        if not new_user or not new_pass:
            st.warning("Username and password are required.")
        else:
            create_user(new_user, new_pass, new_role)
            st.success("User created successfully.")
