import sqlite3
import datetime
import os

from .paths import app_data_dir

class KnowledgeBase:
    def __init__(self, db_path="knowledge.db"):
        if not os.path.isabs(db_path):
            db_path = os.path.join(app_data_dir(), db_path)
        self.conn = sqlite3.connect(db_path)
        self.create_table()

    def create_table(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS qa_pairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                is_correct BOOLEAN,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()

    def 存储问题与回答(self, 问题, 回答, 是否正确):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO qa_pairs (question, answer, is_correct)
            VALUES (?, ?, ?)
        ''', (问题, 回答, 是否正确))
        self.conn.commit()

    def 查询相似问题(self, 问题, threshold=0.5):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT question, answer, is_correct FROM qa_pairs
            WHERE question LIKE ?
        ''', ('%' + 问题 + '%',))
        rows = cursor.fetchall()
        return [{"question": row[0], "answer": row[1], "is_correct": row[2]} for row in rows]

    def 每日学习总结(self):
        cursor = self.conn.cursor()
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        cursor.execute('''
            SELECT COUNT(*) as total, 
                   SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct
            FROM qa_pairs
            WHERE date(created_at) = ?
        ''', (today,))
        row = cursor.fetchone()
        total = row[0] or 0
        correct = row[1] or 0
        return {"日期": today, "总问题数": total, "正确回答数": correct}

    def close(self):
        self.conn.close()
