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
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            logger.debug(f"Download {int(status.progress() * 100)}%.")

        fh.seek(0)
        converted_filepath = filepath + file_extension
        with open(converted_filepath, "wb") as f:
            f.write(fh.getvalue())

        logger.info(f"Converted and saved file: {converted_filepath}")
        return converted_filepath

    except HttpError as error:
        logger.error(f"An error occurred while converting file {file_id}: {error}")
        return None


def create_folder_structure(service, folder_id, local_path, conn, logger):
    try:
        # Query to get folder details
        folder = service.files().get(fileId=folder_id, fields="name,parents").execute()
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
        results = service.files().list(q=query, fields="files(id, name)").execute()
        subfolders = results.get("files", [])

        # Recursively create subfolders
        for subfolder in subfolders:
            subfolder_name = sanitize_filename(subfolder["name"])
            subfolder_path = os.path.join(folder_path, subfolder_name)
            create_folder_structure(
                service, subfolder["id"], subfolder_path, conn, logger
            )

        return folder_path

    except HttpError as error:
        logger.error(
            f"An error occurred while creating folder structure for {folder_id}: {error}"
        )
        return None


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

        # Convert dates to RFC 3339 format for the API query
        start_date_str = start_date.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        end_date_str = end_date.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )

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
            results = (
                service.files()
                .list(
                    q=query,
                    fields="nextPageToken, files(id, name, mimeType, modifiedTime, parents, version)",
                    pageSize=1000,
                    pageToken=page_token,
                )
                .execute()
            )
            items = results.get("files", [])

            for item in items:
                item_name = sanitize_filename(item["name"])
                item_path = os.path.join(folder_path, item_name)
                download_and_save_file(service, item, item_path, conn, logger)

            page_token = results.get("nextPageToken")
            if not page_token:
                break

        # Process subfolders
        subfolder_query = f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        subfolder_results = (
            service.files().list(q=subfolder_query, fields="files(id, name)").execute()
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


def download_and_save_file(service, file, filepath, conn, logger):
    try:
        file_id = file["id"]
        mime_type = file["mimeType"]

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
            done = False
            while done is False:
                status, done = downloader.next_chunk()
                logger.debug(f"Download {int(status.progress() * 100)}%.")

            fh.seek(0)
            with open(filepath, "wb") as f:
                f.write(fh.getvalue())

        filepath = handle_duplicate(filepath, is_version="version" in file)
        logger.info(f"File downloaded: {filepath}")

        # Update database
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO files (id, name, mimeType, version, parentId, modifiedTime)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                file["id"],
                file["name"],
                file["mimeType"],
                file.get("version"),
                file["parents"][0] if "parents" in file else None,
                file["modifiedTime"],
            ),
        )
        conn.commit()

    except HttpError as error:
        logger.error(f"An error occurred while downloading file {file_id}: {error}")


def backup_drive(backup_dir, start_date, end_date, logger):
    creds = authenticate()
    service = build("drive", "v3", credentials=creds)
    conn = init_database()

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
    logger.info(f"Starting Google Drive backup from {start_date} to {end_date}")
    logger.info(f"Backup directory: {backup_dir}")

    try:
        backup_drive(backup_dir, start_date, end_date, logger)
    except Exception as e:
        logger.exception(f"An unexpected error occurred: {str(e)}")


if __name__ == "__main__":
    main()
