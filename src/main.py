from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from src.chat.chat_routes import router as chat_router
from src.video.video_server import router as call_router
from src.recommend.recommend_route import router as recommendation_router

app = FastAPI(
    title="WHMS Backend API",
    description="API for Warehouse Management System with chat, video call, and recommendation",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# Include routers
app.include_router(chat_router, prefix="/api")
app.include_router(call_router, prefix="/call")
app.include_router(
    recommendation_router,
    prefix="/api/recommendation",
    tags=["recommendation"]
)

@app.get("/")
async def root():
    return {
        "message": "WHMS Backend API is running",
        "version": "1.0.0",
        "endpoints": {
            "chat": "/api",
            "video_call": "/call",
            "recommendation": "/api/recommendation"
        }
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}