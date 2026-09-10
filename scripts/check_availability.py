"""
Checks https://mods.org/showtimes/ for a target date and emails you (via Gmail
SMTP) the first time a showing on that date stops being marked "SOLD OUT."

Required environment variables:
    GMAIL_ADDRESS        - Gmail address to send from
    GMAIL_APP_PASSWORD   - 16-char Gmail App Password (not your normal password)

Optional environment variables:
    NOTIFY_EMAIL   - where to send the alert (defaults to GMAIL_ADDRESS)
    TARGET_DATE    - date heading text to look for (default: "December 17, 2026")
    MOVIE_KEYWORD  - substring identifying the movie's showtime lines
                     (default: "Dune: Part Three")
    STATE_FILE     - path to the state-tracking file (default: "state.txt")
"""

import os
import re
import smtplib
import sys
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

SHOWTIMES_URL = "https://mods.org/showtimes/"
TARGET_DATE = os.environ.get("TARGET_DATE", "December 17, 2026")
MOVIE_KEYWORD = os.environ.get("MOVIE_KEYWORD", "Dune: Part Three")
STATE_FILE = os.environ.get("STATE_FILE", "state.txt")

GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", GMAIL_ADDRESS)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
YEAR_PATTERN = re.compile(r"\b20\d{2}\b")


def fetch_page_lines():
    resp = requests.get(
        SHOWTIMES_URL,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ShowtimeMonitor/1.0)"},
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text("\n")
    return [line.strip() for line in text.split("\n") if line.strip()]


def get_date_block(lines, target_date):
    """Return the lines between the target date heading and the next date heading."""
    start = None
    for i, line in enumerate(lines):
        if target_date in line:
            start = i
            break

    if start is None:
        return None

    block = []
    for line in lines[start + 1:]:
        looks_like_next_date_heading = (
            YEAR_PATTERN.search(line)
            and any(day in line for day in WEEKDAYS)
            and target_date not in line
        )
        if looks_like_next_date_heading:
            break
        block.append(line)

    return block


def find_available_showtimes(block, movie_keyword):
    """Lines mentioning the movie that do NOT also say SOLD OUT."""
    return [
        line for line in block
        if movie_keyword in line and "SOLD OUT" not in line.upper()
    ]


def send_email(available_lines):
    subject = f"Tickets available: {MOVIE_KEYWORD} on {TARGET_DATE}"
    body = (
        f"A showing on {TARGET_DATE} at the MODS AutoNation IMAX no longer "
        f"shows as sold out:\n\n"
        + "\n".join(f"- {line}" for line in available_lines)
        + f"\n\nBook here: {SHOWTIMES_URL}\n"
    )
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = NOTIFY_EMAIL

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, [NOTIFY_EMAIL], msg.as_string())


def read_previous_state():
    if not os.path.exists(STATE_FILE):
        return "sold_out"
    with open(STATE_FILE) as f:
        return f.read().strip() or "sold_out"


def write_state(state):
    with open(STATE_FILE, "w") as f:
        f.write(state)


def main():
    lines = fetch_page_lines()
    block = get_date_block(lines, TARGET_DATE)

    if block is None:
        print(
            f"Could not find a section for '{TARGET_DATE}' on the page. "
            "The date may have rolled off the schedule, or the page layout changed."
        )
        sys.exit(0)

    available_lines = find_available_showtimes(block, MOVIE_KEYWORD)
    previous_state = read_previous_state()

    if available_lines:
        print(f"Availability found for {TARGET_DATE}:")
        for line in available_lines:
            print(f"  - {line}")

        if previous_state != "available":
            send_email(available_lines)
            write_state("available")
            print("Email sent. State updated to 'available'.")
        else:
            print("Already notified for this availability window — skipping email.")
    else:
        print(f"No availability found for {TARGET_DATE}. Still sold out.")
        if previous_state != "sold_out":
            write_state("sold_out")
            print("State reset to 'sold_out'.")


if __name__ == "__main__":
    main()
