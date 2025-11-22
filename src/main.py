from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.chat.chat_routes import router as chat_router
from src.video.video_server import router as call_router


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # hoặc domain flutter của bạn
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api")
app.include_router(call_router, prefix="/call")

# Chạy
# uvicorn main:app --reload --port 8000
