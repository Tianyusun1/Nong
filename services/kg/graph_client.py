import os
from neo4j import GraphDatabase


class GraphClient:
    def __init__(self):
        self.enabled = os.getenv('NEO4J_ENABLED', '0') == '1'
        self.database = os.getenv('NEO4J_DATABASE', 'mall_assistant_kg')
        self._driver = None

        if self.enabled:
            uri = os.getenv('NEO4J_URI', 'bolt://127.0.0.1:7687')
            user = os.getenv('NEO4J_USER', 'neo4j')
            pwd = os.getenv('NEO4J_PASSWORD', '12345678')
            self._driver = GraphDatabase.driver(uri, auth=(user, pwd))
            self._ensure_database_exists()

    def _ensure_database_exists(self):
        """在 Neo4j 中确保指定数据库存在（需要管理员权限）。"""
        if not self._driver or not self.database:
            return
        try:
            with self._driver.session(database='system') as session:
                session.run(f"CREATE DATABASE `{self.database}` IF NOT EXISTS")
            print(f"✅ Neo4j 数据库已确认存在: {self.database}")
        except Exception as e:
            print(f"⚠️ Neo4j 数据库创建/检查失败，继续使用当前配置: {e}")

    def run(self, cypher, **params):
        if not self.enabled or self._driver is None:
            return []
        with self._driver.session(database=self.database) as session:
            result = session.run(cypher, **params)
            return [r.data() for r in result]

    def close(self):
        if self._driver:
            self._driver.close()
