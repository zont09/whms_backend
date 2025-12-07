from google.cloud.firestore_v1 import FieldFilter
from typing import List, Dict, Tuple
from datetime import datetime, timedelta


class FirebaseService:
    def __init__(self, db):
        self.db = db

    def get_all_users(self) -> List[Dict]:
        """Lấy tất cả users từ Firestore"""
        users_ref = self.db.collection('users')
        docs = users_ref.where(filter=FieldFilter('enable', '==', True)).stream()

        users = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            users.append(data)

        return users

    def get_user_by_id(self, user_id: str) -> Dict:
        """Lấy user theo ID"""
        doc = self.db.collection('users').document(user_id).get()
        if doc.exists:
            data = doc.to_dict()
            data['id'] = doc.id
            return data
        return None

    def get_all_tasks(self) -> List[Dict]:
        """Lấy tất cả tasks từ Firestore"""
        tasks_ref = self.db.collection('whms_pls_working_unit')
        docs = tasks_ref.where(filter=FieldFilter('enable', '==', True)).stream()

        tasks = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            tasks.append(data)

        return tasks

    def get_tasks_by_assignee(self, user_id: str) -> List[Dict]:
        """Lấy tasks mà user đã/đang làm"""
        tasks_ref = self.db.collection('whms_pls_working_unit')
        docs = tasks_ref.where(
            filter=FieldFilter('assignees', 'array_contains', user_id)
        ).stream()

        tasks = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            tasks.append(data)

        return tasks

    def get_active_tasks_by_assignee(self, user_id: str) -> List[Dict]:
        """Lấy tasks đang active (chưa hoàn thành) của user"""
        all_tasks = self.get_tasks_by_assignee(user_id)

        # Status: 0-9 đang làm, 10+ đã hoàn thành/hủy
        active_tasks = [t for t in all_tasks if t.get('status', 0) < 10]

        return active_tasks

    def get_completed_tasks_by_assignee(self, user_id: str,
                                        limit_days: int = 90) -> List[Dict]:
        """Lấy tasks đã hoàn thành của user trong N ngày gần đây"""
        all_tasks = self.get_tasks_by_assignee(user_id)

        # Lọc tasks đã hoàn thành
        completed_tasks = [t for t in all_tasks if t.get('status', 0) == 100]

        # Lọc theo thời gian (tùy chọn)
        if limit_days > 0:
            cutoff_date = datetime.now() - timedelta(days=limit_days)
            completed_tasks = [
                t for t in completed_tasks
                if t.get('lastWorkedAt') and
                   t['lastWorkedAt'].to_datetime() >= cutoff_date
            ]

        return completed_tasks

    def get_task_hierarchy(self, task_id: str) -> Tuple[str, str, str]:
        """
        Lấy thông tin hierarchy của task
        Returns: (epic_id, sprint_id, story_id)
        """
        task = self.db.collection('whms_pls_working_unit').document(task_id).get()
        if not task.exists:
            return ("", "", "")

        data = task.to_dict()
        task_type = data.get('type', '')

        epic_id = ""
        sprint_id = ""
        story_id = ""

        if task_type == 'Nhiệm vụ':
            # Đi ngược lên để tìm story -> sprint -> epic
            parent_id = data.get('parent', '')
            if parent_id:
                parent = self.db.collection('whms_pls_working_unit').document(parent_id).get()
                if parent.exists:
                    parent_data = parent.to_dict()
                    parent_type = parent_data.get('type', '')

                    if parent_type == 'Nhóm nhiệm vụ':
                        story_id = parent_id
                        grandparent_id = parent_data.get('parent', '')
                        if grandparent_id:
                            grandparent = self.db.collection('whms_pls_working_unit').document(grandparent_id).get()
                            if grandparent.exists:
                                gp_data = grandparent.to_dict()
                                gp_type = gp_data.get('type', '')
                                if gp_type == 'Giai đoạn':
                                    sprint_id = grandparent_id
                                    ggp_id = gp_data.get('parent', '')
                                    if ggp_id:
                                        epic_id = ggp_id

        elif task_type == 'Nhóm nhiệm vụ':
            story_id = task_id
            parent_id = data.get('parent', '')
            if parent_id:
                parent = self.db.collection('whms_pls_working_unit').document(parent_id).get()
                if parent.exists:
                    parent_data = parent.to_dict()
                    if parent_data.get('type') == 'Giai đoạn':
                        sprint_id = parent_id
                        gp_id = parent_data.get('parent', '')
                        if gp_id:
                            epic_id = gp_id

        elif task_type == 'Giai đoạn':
            sprint_id = task_id
            parent_id = data.get('parent', '')
            if parent_id:
                epic_id = parent_id

        elif task_type == 'Giai đoạn':
            epic_id = task_id

        return (epic_id, sprint_id, story_id)