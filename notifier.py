import os
import smtplib
import requests
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_APP_PASSWORD = os.getenv("SMTP_APP_PASSWORD")


def send_email(to_email: str, subject: str, body: str):
    """Sends a plain-text email via Gmail SMTP."""
    if not to_email or not SMTP_EMAIL or not SMTP_APP_PASSWORD:
        return False

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_EMAIL
    msg["To"] = to_email

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_APP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False


def send_slack_message(webhook_url: str, text: str):
    """Sends a message to a Slack incoming webhook."""
    if not webhook_url:
        return False

    try:
        response = requests.post(webhook_url, json={"text": text})
        return response.status_code == 200
    except Exception as e:
        print(f"Failed to send Slack message: {e}")
        return False