import os
from neo4j import GraphDatabase


class GraphClient:
    def __init__(self):
        self.enabled = os.getenv('NEO4J_ENABLED', '0') == '1'
        self._driver = None
        if self.enabled:
            uri = os.getenv('NEO4J_URI', 'bolt://127.0.0.1:7687')
            user = os.getenv('NEO4J_USER', 'neo4j')
            pwd = os.getenv('NEO4J_PASSWORD', 'neo4j')
            self._driver = GraphDatabase.driver(uri, auth=(user, pwd))

    def run(self, cypher, **params):
        if not self.enabled or self._driver is None:
            return []
        with self._driver.session() as session:
            result = session.run(cypher, **params)
            return [r.data() for r in result]

    def close(self):
        if self._driver:
            self._driver.close()
