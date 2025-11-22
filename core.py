
import streamlit as st
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import pandas as pd
import io
import calendar

try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A5
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

from supabase import create_client

from modules.db import get_workers, get_projects, get_attendance_range

STANDARD_DAILY_HOURS = 9
OVERTIME_MULTIPLIER = 1.0
TODAY = date.today()


def get_visa_status(visa_date):
    if visa_date is None:
        return "gray", "No Visa"
    try:
        exp = date.fromisoformat(str(visa_date))
    except Exception:
        return "gray", "Invalid"
    if exp > TODAY + relativedelta(months=1):
        return "green", "Valid"
    else:
        return "red", "Expiring Soon"


def hours_between(time_in, time_out):
    if not time_in or not time_out:
        return 0.0
    try:
        ti = datetime.strptime(time_in, "%H:%M")
        to = datetime.strptime(time_out, "%H:%M")
        if to < ti:
            return 0.0
        return (to - ti).total_seconds() / 3600
    except Exception:
        return 0.0


def generate_monthly_payroll(year, month, project_id=None):
    # شهر ثابت 30 يوم – الجمعة مدفوعة ضمن الراتب الشهري
    days_in_month = 30

    workers = get_workers()
    attendance = get_attendance_range(
        date(year, month, 1),
        date(year + (month // 12), (month % 12) + 1, 1),
    )

    if workers.empty:
        return pd.DataFrame()

    if attendance.empty:
        workers["days_in_month"] = days_in_month
        workers["days_present"] = 0
        workers["total_hours"] = 0
        workers["overtime_hours"] = 0
        workers["hourly_rate"] = 0
        workers["overtime_pay"] = 0
        workers["deductions"] = 0
        workers["net_pay"] = 0
        return workers

    if project_id:
        attendance = attendance[attendance["project_id"] == project_id]

    if attendance.empty:
        workers["days_in_month"] = days_in_month
        workers["days_present"] = 0
        workers["total_hours"] = 0
        workers["overtime_hours"] = 0
        workers["hourly_rate"] = 0
        workers["overtime_pay"] = 0
        workers["deductions"] = 0
        workers["net_pay"] = 0
        return workers

    # حساب ساعات العمل والأوفر تايم
    attendance["hours"] = attendance.apply(
        lambda r: hours_between(r["time_in"], r["time_out"]), axis=1
    )
    attendance["ot_hours"] = attendance["hours"].apply(
        lambda h: max(h - STANDARD_DAILY_HOURS, 0)  # أوفر تايم بعد 9 ساعات
    )

    summary = attendance.groupby("worker_id").agg(
        days_present=("att_date", "nunique"),
        total_hours=("hours", "sum"),
        overtime_hours=("ot_hours", "sum"),
    ).reset_index()

    df = workers.merge(summary, left_on="id", right_on="worker_id", how="left").fillna(0)

    # راتب اليوم = الراتب الشهري / 30
    df["days_in_month"] = days_in_month
    df["daily_rate"] = df["salary"] / days_in_month
    df["base_earned"] = df["daily_rate"] * df["days_present"]

    # راتب الساعة = راتب اليوم / 9 ساعات
    df["hourly_rate"] = df["daily_rate"] / STANDARD_DAILY_HOURS

    # أوفر تايم
    df["overtime_pay"] = df["hourly_rate"] * df["overtime_hours"] * OVERTIME_MULTIPLIER

    # خصومات (حاليًا صفر – نضيف شاشة خصومات لاحقًا)
    df["deductions"] = 0

    # صافي الراتب = راتب أساسي مكتسب + أوفر تايم - خصومات
    df["net_pay"] = (df["base_earned"] + df["overtime_pay"] - df["deductions"]).round(2)

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


def upload_photo_to_supabase(file, worker_code):
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    supabase = create_client(url, key)

    ext = file.name.split(".")[-1].lower()
    if ext not in ["png", "jpg", "jpeg"]:
        ext = "jpg"
    filename = f"{worker_code}.{ext}"

    try:
        supabase.storage.from_("employee_photos").upload(
            path=filename,
            file=file.getvalue(),
            file_options={"content-type": f"image/{ext}", "upsert": True},
        )
        public_url = f"{url}/storage/v1/object/public/employee_photos/{filename}"
        return public_url
    except Exception as e:
        st.error(f"Upload failed: {e}")
        return None


def render_id_card(worker):
    photo_url = worker.get("photo_url")
    photo_html = ""
    if photo_url:
        photo_html = (
            f"<img src='{photo_url}' "
            "style='width:90px;height:110px;border-radius:6px;"
            "object-fit:cover;border:1px solid #ddd;'>"
        )

    html = (
        "<div style='width:320px;border:2px solid #003388;border-radius:10px;"
        "padding:12px;font-family:Arial;background:#fff;'>"
        "<h3 style='margin:0;color:#003388;'>Nile Projects Service</h3>"
        "<small>Employee ID Card</small><hr>"
        "<div style='display:flex;justify-content:space-between;'>"
        "<div style='font-size:12px;'>"
        f"<strong>ID:</strong> {worker.get('worker_code')}<br>"
        f"<strong>Name:</strong> {worker.get('name')}<br>"
        f"<strong>Role:</strong> {worker.get('role')}<br>"
        f"<strong>Trade:</strong> {worker.get('trade')}<br>"
        f"<strong>Phone:</strong> {worker.get('phone')}<br>"
        f"<strong>Visa:</strong> {worker.get('visa_expiry')}"
        "</div>"
        f"<div>{photo_html}</div>"
        "</div><hr>"
        "<div style='font-size:10px;color:#888;text-align:center;'>"
        "www.nileps.com"
        "</div></div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def generate_payslip_pdf(row, year, month):
    if not REPORTLAB_AVAILABLE:
        return None

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A5)
    w, h = A5
    month_name = calendar.month_name[month]

    c.setFont("Helvetica-Bold", 14)
    c.setFillColorRGB(0, 0.2, 0.5)
    c.drawString(30, h - 40, "Nile Projects Service Company")
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    c.drawString(30, h - 55, f"Monthly Payslip - {month_name} {year}")

    c.rect(25, h - 150, w - 50, 60)
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(35, h - 95, f"Name: {row.get('name')}")
    c.drawString(35, h - 110, f"Role: {row.get('role')}")
    c.drawString(35, h - 125, f"Trade: {row.get('trade')}")

    c.rect(25, h - 290, w - 50, 120)
    y = h - 165
    c.setFont("Helvetica", 8)
    c.drawString(35, y, f"Days Present: {row.get('days_present')}")
    y -= 14
    c.drawString(35, y, f"Total Hours: {row.get('total_hours'):.2f}")
    y -= 14
    c.drawString(35, y, f"Overtime Hours: {row.get('overtime_hours'):.2f}")
    y -= 14
    c.drawString(35, y, f"Hourly Rate: {row.get('hourly_rate'):.2f}")
    y -= 14
    c.drawString(35, y, f"OT Pay: {row.get('overtime_pay'):.2f}")
    y -= 14
    c.drawString(35, y, f"Base Earned: {row.get('base_earned'):.2f}")
    y -= 14
    c.setFont("Helvetica-Bold", 10)
    c.drawString(35, y, f"NET PAY: {row.get('net_pay'):.2f}")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()
