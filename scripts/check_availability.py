"""
Checks https://mods.org/showtimes/ for a target date and emails you (via Gmail
SMTP) the first time a showing on that date has a real, clickable ticket link
(i.e. is not sold out).

Required environment variables:
    GMAIL_ADDRESS        - Gmail address to send from
    GMAIL_APP_PASSWORD   - 16-char Gmail App Password (not your normal password)

Optional environment variables:
    NOTIFY_EMAIL   - where to send the alert (defaults to GMAIL_ADDRESS)
    TARGET_DATE    - date heading substring to look for (default: "December 17, 2026")
    MOVIE_KEYWORD  - substring identifying the movie's showtime rows
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
TICKET_DOMAIN = "blackbaudhosting"

GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", GMAIL_ADDRESS)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
YEAR_PATTERN = re.compile(r"\b20\d{2}\b")
TIME_PATTERN = re.compile(r"\b\d{1,2}:\d{2}\s*[ap]\.?m\.?", re.IGNORECASE)


def fetch_soup():
    resp = requests.get(
        SHOWTIMES_URL,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ShowtimeMonitor/1.0)"},
    )
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def is_date_heading_row(row_text):
    """A heading row names a weekday + year but has no showtime (no a.m./p.m.)."""
    return (
        any(day in row_text for day in WEEKDAYS)
        and YEAR_PATTERN.search(row_text)
        and not TIME_PATTERN.search(row_text)
    )


def find_available_showtimes(soup, target_date, movie_keyword):
    """
    Walk the showtimes table row by row, tracking which date section we're in.
    A showing counts as "available" only if its row both mentions the movie
    AND contains a real ticket-purchase hyperlink (MODS removes the link
    entirely once a showing sells out, which is a much more reliable signal
    than searching for the literal text "SOLD OUT").
    """
    rows = soup.find_all("tr")
    in_target_section = False
    available = []

    for row in rows:
        row_text = row.get_text(" ", strip=True)
        if not row_text:
            continue

        if is_date_heading_row(row_text):
            in_target_section = target_date in row_text
            continue

        if not in_target_section:
            continue

        # MODS lists their after-midnight showing (technically the next
        # calendar day, ~1:00 a.m.) under the previous day's heading via a
        # marker row. That showing isn't really "on" the target date, so
        # treat the marker as ending the target-date section.
        if "AFTER MIDNIGHT" in row_text.upper():
            in_target_section = False
            continue

        if movie_keyword not in row_text:
            continue

        link = row.find("a", href=True)
        has_real_ticket_link = link is not None and TICKET_DOMAIN in link["href"]

        if has_real_ticket_link and "SOLD OUT" not in row_text.upper():
            available.append(row_text)

    return available


def send_email(available_lines):
    subject = f"Tickets available: {MOVIE_KEYWORD} on {TARGET_DATE}"
    body = (
        f"A showing on {TARGET_DATE} at the MODS AutoNation IMAX now has an "
        f"active ticket link:\n\n"
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
    soup = fetch_soup()
    available_lines = find_available_showtimes(soup, TARGET_DATE, MOVIE_KEYWORD)
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
