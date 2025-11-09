from motor.motor_asyncio import AsyncIOMotorClient
from motor.motor_asyncio import AsyncIOMotorGridFSBucket
import os

MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://zont09:mgdb124536@whms.lczpcgb.mongodb.net/?appName=WHMS")
DB_NAME = os.getenv("DB_NAME", "chatdb")

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]
fs_bucket = AsyncIOMotorGridFSBucket(db)
messages_col = db["messages"]
