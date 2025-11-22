import os
print("FILES:", os.listdir("."))

import streamlit as st

from modules.db import init_db, create_user
from modules.ui_pages import (
    page_dashboard,
    page_employees,
    page_projects,
    page_assignments,
    page_attendance,
    page_reports,
    page_payroll,
    page_database_admin,
    page_user_admin,
)
from modules.login import login_page


st.set_page_config(
    page_title="NPS HR – Cloud System",
    page_icon="🛠",
    layout="wide",
    initial_sidebar_state="expanded",
)


# Initialize DB and bootstrap first admin from secrets (optional)
init_db()
if "bootstrap_done" not in st.session_state:
    try:
        u = st.secrets["bootstrap"]["username"]
        p = st.secrets["bootstrap"]["password"]
        if u and p:
            create_user(u, p, "admin")
    except Exception:
        pass
    st.session_state["bootstrap_done"] = True


# Login protection
if "logged_in" not in st.session_state or not st.session_state["logged_in"]:
    login_page()
    st.stop()

# Theme toggle (Dark / Light)
if "theme" not in st.session_state:
    st.session_state["theme"] = "Dark"

theme = st.sidebar.radio(
    "Theme",
    ["Dark", "Light"],
    index=0 if st.session_state["theme"] == "Dark" else 1,
    key="theme_radio",
)
st.session_state["theme"] = theme

if theme == "Dark":
    bg = "#020617"
    text = "#e5e7eb"
    sidebar_bg = "#020617"
else:
    bg = "#f9fafb"
    text = "#020617"
    sidebar_bg = "#e5e7eb"

st.markdown(
    f"""
    <style>
    .main {{
        background-color: {bg};
        color: {text};
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    [data-testid="stSidebar"] {{
        background-color: {sidebar_bg};
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

# Header
st.markdown("## Nile Projects Service – HR Cloud System")
st.caption("MEP Contracting · Workforce · Attendance · Payroll")


# Sidebar
st.sidebar.markdown("### NPS HR")
st.sidebar.write(
    "User: **{}** · Role: **{}**".format(
        st.session_state.get("username", "Unknown"),
        st.session_state.get("role", "N/A"),
    )
)

PAGES = {
    "Dashboard": page_dashboard,
    "Employees": page_employees,
    "Projects": page_projects,
    "Assignments": page_assignments,
    "Attendance": page_attendance,
    "Reports": page_reports,
    "Payroll": page_payroll,
    "Database Admin": page_database_admin,
    "User Management": page_user_admin,
}

page = st.sidebar.radio("Navigation", list(PAGES.keys()))

if st.sidebar.button("Logout"):
    st.session_state.clear()
    st.rerun()

# Render page
PAGES[page]()

# Footer
st.markdown("---")
st.caption("Nile Projects Service Company — HR Cloud System · Powered by Streamlit & Supabase")
