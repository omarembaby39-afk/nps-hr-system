
import streamlit as st
from modules.db import check_password


def login_page():
    st.title("🔐 NPS HR – Login")
    st.write("Please sign in to continue.")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        ok, user = check_password(username, password)
        if ok:
            st.session_state["logged_in"] = True
            st.session_state["user_id"] = user[0]
            st.session_state["username"] = user[1]
            st.session_state["role"] = user[3]
            st.success(f"Welcome, {user[1]}!")
            st.rerun()
        else:
            st.error("Invalid username or password")
