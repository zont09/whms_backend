from fastapi import APIRouter, HTTPException, Depends
from src.recommend.model import NewTaskRequest, RecommendationResponse
from src.recommend.recommend_service import RecommendationService
from src.firebase.firebase_service import FirebaseService
from src.configs.firebase_config import initialize_firebase

import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
        logger.info("\n" + "🚀" * 40)
        logger.info(f"📥 NHẬN REQUEST:")
        logger.info(f"   Title: {request.title}")
        logger.info(f"   Description: {request.description[:100]}...")
        logger.info(f"   Type: {request.type}")
        logger.info(f"   Parent: {request.parent}")
        logger.info(f"   Top K: {request.top_k}")

        # Lấy tất cả users và tasks từ Firebase
        logger.info(f"\n📊 ĐANG LẤY DỮ LIỆU TỪ FIREBASE...")
        users = firebase_service.get_all_users()
        logger.info(f"✅ Đã lấy {len(users)} users")

        # Log một vài users để check
        if users:
            for i, user in enumerate(users[:3]):
                logger.info(f"   User {i + 1}: {user.get('name', 'No name')} (ID: {user.get('id', 'No ID')})")

        tasks = firebase_service.get_all_tasks()
        logger.info(f"✅ Đã lấy {len(tasks)} tasks")

        # Log một vài tasks để check
        if tasks:
            for i, task in enumerate(tasks[:3]):
                logger.info(
                    f"   Task {i + 1}: {task.get('title', 'No title')[:50]}... (Assignees: {len(task.get('assignees', []))})")

        if not users:
            logger.error(f"❌ KHÔNG TÌM THẤY USERS TRONG DATABASE!")
            raise HTTPException(status_code=404, detail="No users found in database")

        if not tasks:
            logger.warning(f"⚠️ KHÔNG TÌM THẤY TASKS TRONG DATABASE!")

        # Get recommendations
        logger.info(f"\n🔍 BẮT ĐẦU PHÂN TÍCH VÀ GỢI Ý...")
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

        logger.info(f"\n✅ HOÀN THÀNH - Trả về {len(recommendations)} recommendations")
        logger.info("🚀" * 40 + "\n")

        return RecommendationResponse(
            recommendations=recommendations,
            total_candidates=len(users)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"\n❌ LỖI XẢY RA: {str(e)}", exc_info=True)
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
