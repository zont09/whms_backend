from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class TaskHistoryModel(BaseModel):
    """Model cho lịch sử task (từ WorkingUnitModel)"""
    task_id: str = Field(alias="id")
    title: str
    description: str
    type: str  # epic, sprint, story, task
    parent: str = ""
    status: int
    assignees: List[str] = []
    last_worked_at: Optional[datetime] = Field(None, alias="lastWorkedAt")

    class Config:
        populate_by_name = True


class EmployeeModel(BaseModel):
    """Model cho nhân sự (từ UserModel)"""
    employee_id: str = Field(alias="id")
    name: str
    email: str
    major: str = ""  # Skill/degree - dùng để matching

    # Lấy từ WorkingUnitModel mà user đang làm
    current_tasks: List[str] = []  # List task IDs đang làm

    class Config:
        populate_by_name = True


class NewTaskRequest(BaseModel):
    """Request để tạo task mới và gợi ý nhân sự"""
    title: str
    description: str
    type: str  # epic, sprint, story, task
    parent: str = ""
    top_k: int = 5


class RecommendationBreakdown(BaseModel):
    similarity_score: float
    hierarchy_bonus: float
    workload_penalty: float


class EmployeeRecommendation(BaseModel):
    employee_id: str
    name: str
    email: str
    major: str
    final_score: float
    breakdown: RecommendationBreakdown
    matching_tasks_count: int
    current_workload: int


class RecommendationResponse(BaseModel):
    recommendations: List[EmployeeRecommendation]
    total_candidates: int