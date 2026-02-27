# app/services/drive_service.py
import os
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

class DriveService:
    def __init__(self):
        self.scopes = ['https://www.googleapis.com/auth/drive.file']
        self.credentials_file = 'credentials.json'
        self.folder_id = os.environ.get('GOOGLE_DRIVE_FOLDER_ID', '0AOry37mTRYhKUk9PVA')

        self.credentials = service_account.Credentials.from_service_account_file(
            self.credentials_file, 
            scopes=self.scopes
        )
        self.service = build('drive', 'v3', credentials=self.credentials)

    async def upload_file(self, file_name: str, file_content: bytes, mime_type: str) -> str:
        file_metadata = {
            'name': file_name,
            'parents': [self.folder_id]
        }
        
        media = MediaIoBaseUpload(
            io.BytesIO(file_content),
            mimetype=mime_type,
            resumable=True
        )
        
        file = self.service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink',
            supportsAllDrives=True
        ).execute()
        
        return file.get('webViewLink')