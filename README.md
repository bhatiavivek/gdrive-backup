# Google Drive Backup

Google Drive Backup is a Python script that allows you to backup your Google Drive contents to a local directory. It replicates the folder structure of your Google Drive, handles file conversions for Google Workspace formats, and provides options for incremental backups based on date ranges.

## Features

- Authenticate with Google Drive using OAuth 2.0
- Replicate Google Drive folder structure locally
- Convert Google Workspace format files (Docs, Sheets, Slides) to standard formats
- Handle duplicate filenames and file versions
- Filter files based on modification date range
- Store file metadata in a local SQLite database
- Flexible logging options (console and/or file)

## Prerequisites

- Python 3.7 or higher
- Google Cloud project with the Drive API enabled
- OAuth 2.0 credentials (client_secret.json) for your Google Cloud project

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/google-drive-backup.git
   cd google-drive-backup
   ```

2. Install the required Python packages:
   ```
   pip install -r requirements.txt
   ```

3. Place your `credentials.json` file (OAuth 2.0 client ID) in the project directory.

## Usage

Run the script using the following command:

```
python gdrive_backup.py [OPTIONS]
```

### Options:

- `--backup-dir DIRECTORY`: Directory to store downloaded files. Default is ~/gdrive-backup
- `--start-date [%Y-%m-%d]`: Start date for file sync (YYYY-MM-DD). Default is 2010-01-01.
- `--end-date [%Y-%m-%d]`: End date for file sync (YYYY-MM-DD). Default is today.
- `--log-console / --no-log-console`: Enable/disable console logging. Default is disabled.
- `--log-file / --no-log-file`: Enable/disable file logging. Default is disabled.
- `--log-level [DEBUG|INFO|WARNING|ERROR|CRITICAL]`: Set the logging level. Default is INFO.
- `--help`: Show the help message and exit.

### Example:

To backup files modified between January 1, 2023, and June 30, 2023, with console logging enabled:

```
python gdrive_backup.py --backup-dir ~/my_drive_backup --start-date 2023-01-01 --end-date 2023-06-30 --log-console --log-level INFO
```

## File Structure

The backed-up files will be organized in the following structure:

```
backup_dir/
├── File1.ext
├── File2.ext
├── Folder1/
│   ├── SubFile1.ext
│   └── SubFolder/
│       └── SubSubFile1.ext
└── Google Workspace Files/
    ├── Document1.docx
    ├── Spreadsheet1.xlsx
    └── Presentation1.pptx
```

## Limitations

- The script currently does not support backing up Google Forms or Google Sites.
- Shared drives (formerly Team Drives) are not supported in this version.
- Files larger than 1GB may experience issues during download.

## Contributing

Contributions to the Google Drive Backup project are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This project is not affiliated with, officially maintained, or endorsed by Google. Use at your own risk.