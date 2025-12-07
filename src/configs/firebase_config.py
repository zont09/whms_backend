import firebase_admin
from firebase_admin import credentials, firestore
from google.oauth2 import service_account
import os


def initialize_firebase():
    """
    Khởi tạo Firebase Admin SDK
    Cần đặt biến môi trường FIREBASE_CREDENTIALS_PATH
    hoặc đặt file serviceAccountKey.json trong thư mục gốc
    """
    if not firebase_admin._apps:
        CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

        # Lên 2 cấp từ src/routes/ → về project/
        BASE_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "../../"))

        # Gộp đường dẫn đến file JSON
        SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, "serviceAccountKey_whms.json")

        # Tạo credentials
        credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE)


        return firestore.Client(credentials=credentials, project=credentials.project_id)
