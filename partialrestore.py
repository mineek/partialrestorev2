import os
import sys

from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service
from pymobiledevice3.exceptions import PyMobileDevice3Exception

from pymobiledevice3.cli.cli_common import Command
from pymobiledevice3.exceptions import NoDeviceConnectedError, PyMobileDevice3Exception
from pymobiledevice3.lockdown import LockdownClient
from pymobiledevice3.services.diagnostics import DiagnosticsService
from pymobiledevice3.services.installation_proxy import InstallationProxyService

import click
import traceback
import sqlite3
import tempfile
import shutil

backup_db = None
backup_path_global = None

def read_backup(backup_path):
    global backup_db
    backup_db = sqlite3.connect(os.path.join(backup_path, "Manifest.db"))

class AppData:
    def __init__(self, identifier, backup_files, row, backup_folders):
        self.identifier = identifier
        self.backup_files = backup_files
        self.backup_folders = []
        self.row = None

    def __str__(self):
        return f"AppData(identifier={self.identifier}, backup_files={self.backup_files}, backup_folders={self.backup_folders})"
    
appDataMap = {}

def build_app_data_map():
    cursor = backup_db.cursor()
    cursor.execute("SELECT `fileID`, `domain`, `relativePath`, `flags` FROM Files WHERE domain LIKE 'AppDomain%' AND domain NOT LIKE 'AppDomainPlugin%'")
    rows = cursor.fetchall()
    for row in rows:
        # print(row)
        domain = row[1]
        app_id = domain.split("-")[1]
        if app_id not in appDataMap:
            appDataMap[app_id] = AppData(app_id, [], row, [])
        hash = row[0]
        backupPath = hash[:2] + "/" + hash
        # if flags = 2 then it's a directory
        if row[3] == 2:
            appDataMap[app_id].backup_folders.append(backupPath)
        else:
            appDataMap[app_id].backup_files.append(backupPath)
    cursor.close()

def build_backup_from_appdata(app_datas):
    tempdir = tempfile.mkdtemp()
    print(f"Building backup at {tempdir}")
    for app_data in app_datas:
        for backup_file in app_data.backup_files:
            backup_file_path = os.path.join(backup_path_global, backup_file)
            dest_path = os.path.join(tempdir, backup_file)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.copy(backup_file_path, dest_path)
        for backup_folder in app_data.backup_folders:
            # dk if this is needed but we ball
            dest_path = os.path.join(tempdir, backup_folder)
            os.makedirs(dest_path, exist_ok=True)
    shutil.copy(os.path.join(backup_path_global, "Info.plist"), os.path.join(tempdir, "Info.plist"))
    shutil.copy(os.path.join(backup_path_global, "Status.plist"), os.path.join(tempdir, "Status.plist"))
    shutil.copy(os.path.join(backup_path_global, "Manifest.plist"), os.path.join(tempdir, "Manifest.plist"))
    manifest = os.path.join(tempdir, "Manifest.db")
    shutil.copy(os.path.join(backup_path_global, "Manifest.db"), manifest)
    conn = sqlite3.connect(manifest)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Files")
    rows = cursor.fetchall()
    for row in rows:
        hash = row[0]
        backupPath = hash[:2] + "/" + hash
        if backupPath not in app_data.backup_files and backupPath not in app_data.backup_folders:
            cursor.execute("DELETE FROM Files WHERE fileID = ?", (hash,))
    cursor.close()
    conn.commit()
    conn.close()
    return tempdir

def restore_backup_from_path(backupPath):
    print(f"Restoring backup from {backupPath}")
    lockdown = create_using_usbmux()
    with Mobilebackup2Service(lockdown) as bs:
        bs.restore(backupPath, system=True, reboot=True, copy=False, source=".", remove=False)
    print("Restore complete")

@click.command(cls=Command)
@click.option(
    "--backup-path",
    "-b",
    default=None,
    help="Path to the backup to restore from",
)
@click.option(
    "--list-apps",
    "-l",
    is_flag=True,
    help="List app data from the backup that can be restored",
)
@click.option(
    "--restore-app",
    "-r",
    multiple=True,
    help="Restore app data from the backup",
)
@click.pass_context
def cli(ctx, service_provider: LockdownClient, backup_path, list_apps, restore_app):
    print("Mineek's awesome partial restore tool")
    if backup_path is None:
        raise click.UsageError("Backup path is required")
    global backup_path_global
    backup_path_global = backup_path
    read_backup(backup_path)
    build_app_data_map()
    if list_apps:
        for app_data in appDataMap.values():
            print(app_data)
    if restore_app:
        target_apps = restore_app
        print(f"Restoring app data for {target_apps}")
        app_datas = []
        for app_id in target_apps:
            app_datas.append(appDataMap[app_id])
        print(f"Restoring {len(app_datas)} apps")
        for app_data in app_datas:
            print(app_data)
        backup_path = build_backup_from_appdata(app_datas)
        print(f"Built backup at {backup_path}, ARE YOU SURE YOU WANT TO RESTORE THIS?")
        sure = input("Type 'yes' to confirm: ")
        if sure == "yes":
            restore_backup_from_path(backup_path)
        else:
            print("Aborting")
    print("Done")

def main():
    try:
        cli(standalone_mode=False)
    except NoDeviceConnectedError:
        click.secho("No device connected!", fg="red")
        click.secho("Please connect your device and try again.", fg="red")
        exit(1)
    except click.UsageError as e:
        click.secho(e.format_message(), fg="red")
        click.echo(cli.get_help(click.Context(cli)))
        exit(2)
    except Exception:
        click.secho("An error occurred!", fg="red")
        click.secho(traceback.format_exc(), fg="red")
        exit(1)
    exit(0)

if __name__ == "__main__":
    main()
