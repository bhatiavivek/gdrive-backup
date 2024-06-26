import os
import sys
import sqlite3
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

import click
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Global variables
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
DATABASE_FILE = "drive_backup.db"


def authenticate():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return creds


def init_database():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS files
        (id TEXT PRIMARY KEY, name TEXT, mimeType TEXT, version INTEGER,
        parentId TEXT, modifiedTime TEXT)
    """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS folders
        (id TEXT PRIMARY KEY, name TEXT, parentId TEXT)
    """
    )
    conn.commit()
    return conn


def sanitize_filename(filename):
    # Basic implementation - you might want to expand this
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, "_")
    return filename


def handle_duplicate(filepath, is_version=False):
    base, ext = os.path.splitext(filepath)
    counter = 1
    new_filepath = filepath
    while os.path.exists(new_filepath):
        if is_version:
            new_filepath = f"{base}.v{counter:02d}{ext}"
        else:
            new_filepath = f"{base}.{counter:02d}{ext}"
        counter += 1
    return new_filepath


def convert_google_file(service, file_id, mime_type):
    # Placeholder implementation
    # You'll need to implement the actual conversion logic here
    pass


def download_and_save_file(service, file_id, filepath, mime_type):
    # Placeholder implementation
    # You'll need to implement the actual download and save logic here
    pass


def create_folder_structure(service, folder_id, path):
    # Placeholder implementation
    # You'll need to implement the folder creation logic here
    pass


def is_file_in_date_range(file_modified_time, start_date, end_date):
    file_date = datetime.fromisoformat(file_modified_time.replace("Z", "+00:00"))
    return start_date <= file_date <= end_date


def setup_logging(log_console, log_file, log_level):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # Capture all levels

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    if log_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if log_file:
        file_handler = RotatingFileHandler(
            "gdrive_backup.log", maxBytes=10 * 1024 * 1024, backupCount=5
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def backup_drive(backup_dir, start_date, end_date, logger):
    creds = authenticate()
    service = build("drive", "v3", credentials=creds)
    conn = init_database()

    def process_folder(folder_id, local_path):
        # Placeholder implementation
        # You'll need to implement the folder and file processing logic here
        pass

    try:
        os.makedirs(backup_dir, exist_ok=True)
        process_folder("root", backup_dir)
    finally:
        conn.close()


@click.command()
@click.option(
    "--backup-dir",
    type=click.Path(file_okay=False, dir_okay=True, writable=True),
    default=lambda: os.path.join(os.path.expanduser("~"), "gdrive-backup"),
    help="Directory to store downloaded files. Default is ~/gdrive-backup",
)
@click.option(
    "--start-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default="2010-01-01",
    help="Start date for file sync (YYYY-MM-DD). Default is 2010-01-01.",
)
@click.option(
    "--end-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=lambda: datetime.now(timezone.utc).date().isoformat(),
    help="End date for file sync (YYYY-MM-DD). Default is today.",
)
@click.option(
    "--log-console/--no-log-console",
    default=False,
    help="Enable/disable console logging. Default is disabled.",
)
@click.option(
    "--log-file/--no-log-file",
    default=False,
    help="Enable/disable file logging. Default is disabled.",
)
@click.option(
    "--log-level",
    type=click.Choice(
        ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], case_sensitive=False
    ),
    default="INFO",
    help="Set the logging level. Default is INFO.",
)
def main(backup_dir, start_date, end_date, log_console, log_file, log_level):
    """Sync and organize files from Google Drive to local storage."""
    logger = setup_logging(log_console, log_file, getattr(logging, log_level.upper()))
    logger.info(f"Starting Google Drive backup from {start_date} to {end_date}")
    logger.info(f"Backup directory: {backup_dir}")

    try:
        backup_drive(backup_dir, start_date, end_date, logger)
    except Exception as e:
        logger.exception(f"An unexpected error occurred: {str(e)}")


if __name__ == "__main__":
    main()
