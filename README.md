# Google Drive Backup Script

This Python script provides a robust solution for backing up your Google Drive contents to your local machine. It supports incremental backups, file versioning, and handles both Google Workspace files and standard file formats.

## Use Case

This is meant as a local last-resort backup in case you lose access to your Google account through carelessness, malice or displeasing the Borg. There's also a [companion script for backing up Google Photos](https://github.com/bhatiavivek/gphoto-backup).

## Features

- Incremental backups: Only download new or modified files
- File versioning: Keep multiple versions of files as they change
- Google Workspace file conversion: Automatically convert Google Docs, Sheets, and Slides to Microsoft Office formats
- Flexible date range: Specify start and end dates for your backup
- Database tracking: Keep track of downloaded files and their versions
- Logging: Configurable logging to console and/or file

## Prerequisites

- Python 3.6 or higher
- Google Cloud project with the Drive API enabled
- OAuth 2.0 Client ID credentials

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/gdrive-backup.git
   cd gdrive-backup
   ```

2. Install the required Python packages:
   ```
   pip install -r requirements.txt
   ```

3. Set up Google Cloud credentials (see below)

## Google Cloud Setup

To use this script, you need to set up a Google Cloud project and obtain credentials:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Google Drive API for your project
4. Create OAuth 2.0 Client ID credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Choose "Desktop app" as the application type
   - Download the client configuration and save it as `credentials.json` in the script directory

## Usage

Run the script with the following command:

```
python gdrive-backup.py [OPTIONS]
```

Options:
- `--backup-dir PATH`: Directory to store downloaded files (default: ~/gdrive-backup)
- `--start-date DATE`: Start date for file sync (YYYY-MM-DD) (default: 2010-01-01)
- `--end-date DATE`: End date for file sync (YYYY-MM-DD) (default: today)
- `--log-console / --no-log-console`: Enable/disable console logging (default: disabled)
- `--log-file / --no-log-file`: Enable/disable file logging (default: disabled)
- `--log-level LEVEL`: Set the logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) (default: INFO)

Example:
```
python gdrive-backup.py --backup-dir /path/to/backup --start-date 2023-01-01 --log-console --log-level DEBUG
```

## File Structure

The backed-up files will be organized as follows:
```
backup_dir/
├── file1.ext
├── file2.ext
├── folder1/
│   ├── file3.ext
│   └── file4.ext
├── Google Docs/
│   ├── document1.docx
│   └── document2.docx
└── __db__/
    └── drive_backup.db
```

Versioned files will be named with a version suffix, e.g., `file1.v02.ext`.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This script is not officially associated with Google. Use it at your own risk. Always ensure you have additional backups of your important data.