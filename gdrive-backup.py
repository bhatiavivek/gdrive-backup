import os
import sys
import io
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
from googleapiclient.errors import HttpError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    after_log,
)
import requests.exceptions


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


def get_db_path(backup_dir):
    db_dir = os.path.join(backup_dir, "__db__")
    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, "drive_backup.db")


def init_database(db_file):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS files
        (id TEXT, name TEXT, mimeType TEXT, version INTEGER,
        parentId TEXT, modifiedTime TEXT, localPath TEXT,
        PRIMARY KEY (id, version))
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


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type(
        (
            requests.exceptions.RequestException,
            requests.exceptions.HTTPError,
            TimeoutError,
        )
    ),
    before_sleep=before_sleep_log(logging.getLogger(), logging.INFO),
    after=after_log(logging.getLogger(), logging.INFO),
)
def make_api_request(service, request_func, logger, *args, **kwargs):
    try:
        return request_func(*args, **kwargs).execute()
    except (
        requests.exceptions.RequestException,
        requests.exceptions.HTTPError,
        TimeoutError,
    ) as e:
        logger.error(f"API request failed: {str(e)}")
        raise


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type(
        (
            requests.exceptions.RequestException,
            requests.exceptions.HTTPError,
            TimeoutError,
        )
    ),
    before_sleep=before_sleep_log(logging.getLogger(), logging.INFO),
    after=after_log(logging.getLogger(), logging.INFO),
)
def download_file(downloader, logger):
    done = False
    while not done:
        status, done = downloader.next_chunk()
        if status:
            logger.debug(f"Download {int(status.progress() * 100)}%.")
    logger.info("Download completed.")


def sanitize_filename(filename):
    # Basic implementation - you might want to expand this
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, "_")
    return filename


def get_next_version_number(cursor, file_id):
    cursor.execute("SELECT MAX(version) FROM files WHERE id = ?", (file_id,))
    max_version = cursor.fetchone()[0]
    return (max_version or 0) + 1


def get_file_path(base_path, filename, version):
    base, ext = os.path.splitext(filename)
    if version > 1:
        return os.path.join(base_path, f"{base}.v{version:02d}{ext}")
    return os.path.join(base_path, filename)


def handle_duplicate(filepath):
    base, ext = os.path.splitext(filepath)
    version = get_next_version_number(filepath)
    return f"{base}.v{version:02d}{ext}"


def ensure_dir_exists(filepath):
    directory = os.path.dirname(filepath)
    os.makedirs(directory, exist_ok=True)


def convert_google_file(service, file_id, mime_type, filepath, logger):
    try:
        if mime_type == "application/vnd.google-apps.document":
            export_mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            file_extension = ".docx"
        elif mime_type == "application/vnd.google-apps.spreadsheet":
            export_mime_type = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            file_extension = ".xlsx"
        elif mime_type == "application/vnd.google-apps.presentation":
            export_mime_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            file_extension = ".pptx"
        elif mime_type == "application/vnd.google-apps.drawing":
            export_mime_type = "image/png"
            file_extension = ".png"
        else:
            logger.warning(f"Unsupported Google Workspace file type: {mime_type}")
            return None

        request = service.files().export_media(
            fileId=file_id, mimeType=export_mime_type
        )
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)

        download_file(downloader, logger)

        fh.seek(0)
        converted_filepath = f"{filepath}{file_extension}"
        ensure_dir_exists(converted_filepath)
        with open(converted_filepath, "wb") as f:
            f.write(fh.getvalue())

        logger.info(f"Converted and saved file: {converted_filepath}")
        return converted_filepath

    except HttpError as error:
        logger.error(f"An error occurred while converting file {file_id}: {error}")
        return None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type(
        (
            requests.exceptions.RequestException,
            requests.exceptions.HTTPError,
            TimeoutError,
        )
    ),
    before_sleep=before_sleep_log(logging.getLogger(), logging.INFO),
    after=after_log(logging.getLogger(), logging.INFO),
)
def create_folder_structure(service, folder_id, local_path, conn, logger):
    try:
        # Query to get folder details
        folder = make_api_request(
            service,
            service.files().get,
            logger,
            fileId=folder_id,
            fields="name,parents",
        )
        folder_name = sanitize_filename(folder["name"])

        # Use the provided local_path as is, since it should already include the folder name
        folder_path = local_path

        # Create the folder if it doesn't exist
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)
            logger.info(f"Created folder: {folder_path}")

        # Update database
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO folders (id, name, parentId)
            VALUES (?, ?, ?)
        """,
            (folder_id, folder_name, folder.get("parents", [None])[0]),
        )
        conn.commit()

        # Query to get subfolders
        query = f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = make_api_request(
            service, service.files().list, logger, q=query, fields="files(id, name)"
        )
        subfolders = results.get("files", [])

        # Recursively create subfolders
        for subfolder in subfolders:
            subfolder_name = sanitize_filename(subfolder["name"])
            subfolder_path = os.path.join(folder_path, subfolder_name)
            create_folder_structure(
                service, subfolder["id"], subfolder_path, conn, logger
            )

        return folder_path

    except Exception as error:
        logger.error(
            f"An error occurred while creating folder structure for {folder_id}: {error}"
        )
        raise


def is_file_in_date_range(file_modified_time, start_date, end_date):
    file_date = datetime.fromisoformat(file_modified_time.replace("Z", "+00:00"))
    return start_date <= file_date <= end_date


def setup_logging(log_console, log_file, log_level):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # Capture all levels

    # Create a formatter that includes the line number
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
    )

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

    # If no logging is enabled, add a NullHandler to suppress warnings
    if not log_console and not log_file:
        logger.addHandler(logging.NullHandler())

    return logger


def process_folder(service, folder_id, local_path, conn, start_date, end_date, logger):
    try:
        # Create folder structure first
        folder_path = create_folder_structure(
            service, folder_id, local_path, conn, logger
        )
        if not folder_path:
            return  # Skip processing if folder creation failed

        # Adjust end_date to be 23:59:59 of the specified day
        end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)

        # Convert dates to RFC 3339 format for the API query
        start_date_str = start_date.astimezone(timezone.utc).isoformat()
        end_date_str = end_date.astimezone(timezone.utc).isoformat()

        # Query to get files in the current folder within the specified date range
        query = (
            f"'{folder_id}' in parents "
            f"and modifiedTime >= '{start_date_str}' "
            f"and modifiedTime <= '{end_date_str}' "
            f"and mimeType != 'application/vnd.google-apps.folder' "
            f"and trashed = false"
        )

        page_token = None
        while True:
            results = make_api_request(
                service,
                service.files().list,
                logger,
                q=query,
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, parents, version)",
                pageSize=1000,
                pageToken=page_token,
            )
            items = results.get("files", [])

            for item in items:
                download_and_save_file(service, item, folder_path, conn, logger)

            page_token = results.get("nextPageToken")
            if not page_token:
                break

        # Process subfolders
        subfolder_query = f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        subfolder_results = make_api_request(
            service,
            service.files().list,
            logger,
            q=subfolder_query,
            fields="files(id, name)",
        )
        subfolders = subfolder_results.get("files", [])

        for subfolder in subfolders:
            subfolder_name = sanitize_filename(subfolder["name"])
            subfolder_path = os.path.join(folder_path, subfolder_name)
            process_folder(
                service,
                subfolder["id"],
                subfolder_path,
                conn,
                start_date,
                end_date,
                logger,
            )

    except HttpError as error:
        logger.error(f"An error occurred while processing folder {folder_id}: {error}")
    except KeyError as key_error:
        logger.error(
            f"KeyError in process_folder: {key_error}. Subfolder data: {subfolder}"
        )
        raise


def download_and_save_file(service, file, folder_path, conn, logger):
    try:
        file_id = file["id"]
        filename = file["name"]
        mime_type = file["mimeType"]
        modified_time = file["modifiedTime"]

        cursor = conn.cursor()

        # Check if the file already exists in our database
        cursor.execute(
            "SELECT modifiedTime, localPath FROM files WHERE id = ? ORDER BY version DESC LIMIT 1",
            (file_id,),
        )
        result = cursor.fetchone()

        new_version = get_next_version_number(cursor, file_id)

        if result:
            stored_modified_time, stored_path = result
            if stored_modified_time == modified_time:
                logger.info(f"File {filename} hasn't changed. Skipping download.")
                return

        # File is new or has changed, create a new version
        filepath = get_file_path(folder_path, filename, new_version)

        # Handle Google Workspace files
        if mime_type.startswith("application/vnd.google-apps"):
            converted_filepath = convert_google_file(
                service, file_id, mime_type, filepath, logger
            )
            if converted_filepath:
                filepath = converted_filepath
            else:
                return  # Skip this file if conversion failed
        else:
            request = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)

            download_file(downloader, logger)

            fh.seek(0)

            ensure_dir_exists(filepath)
            with open(filepath, "wb") as f:
                f.write(fh.getvalue())

        logger.info(f"File downloaded: {filepath}")

        # Update database
        cursor.execute(
            """
            INSERT INTO files 
            (id, name, mimeType, version, parentId, modifiedTime, localPath)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                file_id,
                filename,
                mime_type,
                new_version,
                file["parents"][0] if "parents" in file else None,
                modified_time,
                filepath,
            ),
        )
        conn.commit()

    except HttpError as error:
        logger.error(f"An error occurred while downloading file {file_id}: {error}")


def backup_drive(backup_dir, start_date, end_date, logger):
    creds = authenticate()
    service = build("drive", "v3", credentials=creds)
    db_file = get_db_path(backup_dir)
    conn = init_database(db_file)

    try:
        os.makedirs(backup_dir, exist_ok=True)
        process_folder(service, "root", backup_dir, conn, start_date, end_date, logger)
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

    # Ensure start_date is at the beginning of the day
    start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)

    # Ensure end_date is at the end of the day
    end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    logger.info(f"Starting Google Drive backup from {start_date} to {end_date}")
    logger.info(f"Backup directory: {backup_dir}")

    try:
        backup_drive(backup_dir, start_date, end_date, logger)
    except Exception as e:
        logger.exception(f"An unexpected error occurred: {str(e)}")


if __name__ == "__main__":
    main()
