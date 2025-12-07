from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from typing import List, Dict
from src.recommend.model import EmployeeRecommendation, RecommendationBreakdown
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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

            print(f"[THINK CHECK] Comparing hierarchies: {new_task_hierarchy} - {(epic, sprint, story)} : <{task_id}>")

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

        logger.info("=" * 80)
        logger.info(f"🎯 BẮT ĐẦU RECOMMENDATION")
        logger.info(f"📝 Task mới: {new_task_title}")
        logger.info(f"📋 Type: {new_task_type}, Parent: {new_task_parent}")
        logger.info(f"👥 Tổng số users: {len(users_data)}")
        logger.info(f"📦 Tổng số tasks: {len(all_tasks)}")

        # Xác định hierarchy của task mới
        if new_task_parent:
            new_task_hierarchy = firebase_service.get_task_hierarchy(new_task_parent)
            logger.info(
                f"🏗️ Hierarchy: Epic={new_task_hierarchy[0]}, Sprint={new_task_hierarchy[1]}, Story={new_task_hierarchy[2]}")
        else:
            new_task_hierarchy = ("", "", "")
            logger.info(f"⚠️ Không có parent - không có hierarchy bonus")

        new_task_text = self._preprocess_text(new_task_title, new_task_description)
        logger.info(f"📄 Task text đã xử lý (first 100 chars): {new_task_text[:100]}...")

        recommendations = []
        users_processed = 0
        users_with_tasks = 0
        users_with_completed_tasks = 0

        for user in users_data:
            user_id = user.get('id', '')
            user_name = user.get('name', 'Unknown')

            if not user_id:
                logger.warning(f"⚠️ User không có ID: {user}")
                continue

            users_processed += 1

            # Lấy tasks của user
            user_tasks = [t for t in all_tasks if user_id in t.get('assignees', [])]
            completed_tasks = [t for t in user_tasks if t.get('status', 0) == 0]
            active_tasks = [t for t in user_tasks if t.get('status', 0) >= 100]

            if user_tasks:
                users_with_tasks += 1

            logger.info(f"\n👤 User: {user_name} (ID: {user_id})")
            logger.info(
                f"   📊 Total tasks: {len(user_tasks)}, Completed: {len(completed_tasks)}, Active: {len(active_tasks)}")

            if not completed_tasks:
                logger.info(f"   ❌ Bỏ qua - không có task đã hoàn thành")
                continue

            users_with_completed_tasks += 1

            # Log một vài completed tasks để debug
            for i, task in enumerate(completed_tasks[:3]):
                logger.info(
                    f"   📝 Task {i + 1}: {task.get('title', 'No title')[:50]}... (status: {task.get('status')})")

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
            logger.info(f"   🎯 Similarity score: {similarity_score:.4f}")

            # 2. Calculate hierarchy bonus
            hierarchy_bonus = self._calculate_hierarchy_bonus(
                new_task_hierarchy,
                completed_tasks,
                firebase_service
            )
            logger.info(f"   🏗️ Hierarchy bonus: {hierarchy_bonus:.4f}")

            # 3. Calculate workload penalty
            workload_penalty = self._calculate_workload_penalty(len(active_tasks))
            logger.info(f"   ⚖️ Workload penalty: {workload_penalty:.4f} (active tasks: {len(active_tasks)})")

            # 4. Calculate final score
            final_score = (
                                  similarity_score * self.similarity_weight +
                                  hierarchy_bonus * self.hierarchy_weight
                          ) * workload_penalty

            logger.info(f"   ⭐ FINAL SCORE: {final_score:.4f}")
            logger.info(
                f"      = ({similarity_score:.4f} × {self.similarity_weight} + {hierarchy_bonus:.4f} × {self.hierarchy_weight}) × {workload_penalty:.4f}")

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

        logger.info(f"\n" + "=" * 80)
        logger.info(f"📊 TỔNG KẾT:")
        logger.info(f"   👥 Users được xử lý: {users_processed}/{len(users_data)}")
        logger.info(f"   📦 Users có tasks: {users_with_tasks}")
        logger.info(f"   ✅ Users có completed tasks: {users_with_completed_tasks}")
        logger.info(f"   🎯 Số lượng recommendations: {len(recommendations)}")

        if recommendations:
            logger.info(f"\n🏆 TOP {min(top_k, len(recommendations))} RECOMMENDATIONS:")
            for i, rec in enumerate(recommendations[:top_k], 1):
                logger.info(
                    f"   {i}. {rec.name} - Score: {rec.final_score:.4f} (Tasks: {rec.matching_tasks_count}, Workload: {rec.current_workload})")
        else:
            logger.warning(f"⚠️ KHÔNG TÌM THẤY RECOMMENDATIONS!")
            logger.warning(f"   Lý do có thể:")
            logger.warning(f"   - Không có user nào có completed tasks")
            logger.warning(f"   - Tất cả users đều có similarity score = 0")
            logger.warning(f"   - Data không đúng format")

        logger.info("=" * 80 + "\n")

        return recommendations[:top_k]