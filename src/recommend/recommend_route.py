from fastapi import APIRouter, HTTPException, Depends
from src.recommend.model import NewTaskRequest, RecommendationResponse
from src.recommend.recommend_service import RecommendationService
from src.firebase.firebase_service import FirebaseService
from src.configs.firebase_config import initialize_firebase

router = APIRouter()

# Initialize services
db = initialize_firebase()
firebase_service = FirebaseService(db)
recommendation_service = RecommendationService(
    similarity_weight=0.6,
    hierarchy_weight=0.3,
    workload_weight=0.1
)


@router.post("/recommend", response_model=RecommendationResponse)
async def recommend_employees(request: NewTaskRequest):
    """
    Gợi ý nhân sự cho task mới
    Tự động lấy dữ liệu từ Firebase
    """
    try:
        # Lấy tất cả users và tasks từ Firebase
        users = firebase_service.get_all_users()
        tasks = firebase_service.get_all_tasks()

        if not users:
            raise HTTPException(status_code=404, detail="No users found in database")

        # Get recommendations
        recommendations = recommendation_service.recommend(
            new_task_title=request.title,
            new_task_description=request.description,
            new_task_type=request.type,
            new_task_parent=request.parent,
            users_data=users,
            all_tasks=tasks,
            firebase_service=firebase_service,
            top_k=request.top_k
        )

        return RecommendationResponse(
            recommendations=recommendations,
            total_candidates=len(users)
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/user/{user_id}/tasks")
async def get_user_tasks(user_id: str):
    """Debug endpoint: Xem tasks của user"""
    try:
        tasks = firebase_service.get_tasks_by_assignee(user_id)
        return {
            "user_id": user_id,
            "total_tasks": len(tasks),
            "tasks": tasks
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Health check"""
    try:
        # Test Firebase connection
        users_count = len(firebase_service.get_all_users())
        tasks_count = len(firebase_service.get_all_tasks())

        return {
            "status": "ok",
            "service": "employee-recommendation",
            "firebase_connected": True,
            "users_count": users_count,
            "tasks_count": tasks_count
        }
    except Exception as e:
        return {
            "status": "error",
            "service": "employee-recommendation",
            "firebase_connected": False,
            "error": str(e)
        }