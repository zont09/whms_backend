from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.chat.chat_routes import router as chat_router
from src.video.video_server import router as call_router
from src.recommend.recommend_route import router as recommendation_router

app = FastAPI(
    title="Task Management API",
    description="API for task management with employee recommendation",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

app.include_router(chat_router, prefix="/api")
app.include_router(call_router, prefix="/call")
app.include_router(recommendation_router, prefix="/api/recommendation", tags=["recommendation"])