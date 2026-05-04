import os
import requests


class QwenClient:
    def __init__(self):
        self.base_url = os.getenv('QWEN_API_URL', 'http://127.0.0.1:8008/generate')
        self.enabled = os.getenv('QWEN_ENABLED', '0') == '1'

    def generate(self, prompt):
        if not self.enabled:
            return "【本地客服降级】模型服务未启用。根据知识库结果已返回结构化答案。"
        resp = requests.post(self.base_url, json={"prompt": prompt, "max_tokens": 512, "temperature": 0.2}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get('text') or data.get('answer') or ''
