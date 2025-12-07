from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from typing import List, Dict
from src.recommend.model import EmployeeRecommendation, RecommendationBreakdown


class RecommendationService:
    def __init__(self,
                 similarity_weight: float = 0.6,
                 hierarchy_weight: float = 0.3,
                 workload_weight: float = 0.1):
        self.similarity_weight = similarity_weight
        self.hierarchy_weight = hierarchy_weight
        self.workload_weight = workload_weight

        self.vectorizer = TfidfVectorizer(
            max_features=1000,
            ngram_range=(1, 2),
            stop_words='english',
            lowercase=True
        )

    def _preprocess_text(self, title: str, description: str, major: str = "") -> str:
        """Kết hợp title, description và major thành text"""
        text = f"{title} {description} {major}".lower().strip()
        return text

    def _calculate_similarity(self,
                              new_task_text: str,
                              employee_tasks_texts: List[str]) -> float:
        """Tính cosine similarity"""
        if not employee_tasks_texts:
            return 0.0

        all_texts = [new_task_text] + employee_tasks_texts

        try:
            vectors = self.vectorizer.fit_transform(all_texts)
            similarities = cosine_similarity(vectors[0:1], vectors[1:])
            return float(np.max(similarities))
        except:
            return 0.0

    def _calculate_hierarchy_bonus(self,
                                   new_task_hierarchy: tuple,
                                   employee_tasks: List[Dict],
                                   firebase_service) -> float:
        """
        Tính điểm bonus theo hierarchy
        new_task_hierarchy: (epic_id, sprint_id, story_id)
        """
        new_epic, new_sprint, new_story = new_task_hierarchy
        max_bonus = 0.0

        for task in employee_tasks:
            task_id = task.get('id', '')
            if not task_id:
                continue

            epic, sprint, story = firebase_service.get_task_hierarchy(task_id)

            # Cùng story -> bonus cao nhất
            if story and story == new_story:
                max_bonus = max(max_bonus, 0.3)
            # Cùng sprint
            elif sprint and sprint == new_sprint:
                max_bonus = max(max_bonus, 0.2)
            # Cùng epic
            elif epic and epic == new_epic:
                max_bonus = max(max_bonus, 0.1)

        return max_bonus

    def _calculate_workload_penalty(self, active_task_count: int) -> float:
        """
        Tính penalty dựa trên số lượng task đang làm
        Càng nhiều task -> penalty càng cao -> score càng thấp
        """
        if active_task_count == 0:
            return 1.0  # Không có penalty
        elif active_task_count <= 2:
            return 0.9
        elif active_task_count <= 4:
            return 0.7
        elif active_task_count <= 6:
            return 0.5
        else:
            return 0.3  # Nhiều task quá

    def recommend(self,
                  new_task_title: str,
                  new_task_description: str,
                  new_task_type: str,
                  new_task_parent: str,
                  users_data: List[Dict],
                  all_tasks: List[Dict],
                  firebase_service,
                  top_k: int = 5) -> List[EmployeeRecommendation]:
        """
        Gợi ý nhân sự dựa trên:
        - Similarity với tasks đã làm
        - Hierarchy (cùng story/sprint/epic)
        - Workload hiện tại
        """

        # Xác định hierarchy của task mới
        if new_task_parent:
            new_task_hierarchy = firebase_service.get_task_hierarchy(new_task_parent)
        else:
            new_task_hierarchy = ("", "", "")

        new_task_text = self._preprocess_text(new_task_title, new_task_description)
        recommendations = []

        for user in users_data:
            user_id = user.get('id', '')
            if not user_id:
                continue

            # Lấy tasks của user
            user_tasks = [t for t in all_tasks if user_id in t.get('assignees', [])]
            completed_tasks = [t for t in user_tasks if t.get('status', 0) == 100]
            active_tasks = [t for t in user_tasks if t.get('status', 0) < 10]

            if not completed_tasks:
                # Không có lịch sử -> skip
                continue

            # 1. Calculate similarity score
            user_tasks_texts = [
                self._preprocess_text(
                    t.get('title', ''),
                    t.get('description', ''),
                    user.get('major', '')
                )
                for t in completed_tasks
            ]
            similarity_score = self._calculate_similarity(new_task_text, user_tasks_texts)

            # 2. Calculate hierarchy bonus
            hierarchy_bonus = self._calculate_hierarchy_bonus(
                new_task_hierarchy,
                completed_tasks,
                firebase_service
            )

            # 3. Calculate workload penalty
            workload_penalty = self._calculate_workload_penalty(len(active_tasks))

            # 4. Calculate final score
            final_score = (
                                  similarity_score * self.similarity_weight +
                                  hierarchy_bonus * self.hierarchy_weight
                          ) * workload_penalty

            recommendations.append(
                EmployeeRecommendation(
                    employee_id=user_id,
                    name=user.get('name', ''),
                    email=user.get('email', ''),
                    major=user.get('major', ''),
                    final_score=round(final_score, 4),
                    breakdown=RecommendationBreakdown(
                        similarity_score=round(similarity_score, 4),
                        hierarchy_bonus=round(hierarchy_bonus, 4),
                        workload_penalty=round(workload_penalty, 4)
                    ),
                    matching_tasks_count=len(completed_tasks),
                    current_workload=len(active_tasks)
                )
            )

        # Sort by final score
        recommendations.sort(key=lambda x: x.final_score, reverse=True)

        return recommendations[:top_k]