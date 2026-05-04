import os
from decimal import Decimal

from sqlalchemy import or_

from models import Product
from services.assistant.intent_router import detect_intent
from services.assistant.policy_engine import check_after_sales_eligibility
from services.kg.kg_query import find_product_facts


def _build_product_cards(products, base_url):
    cards = []
    for p in products:
        min_price = min((sku.price for sku in p.skus), default=Decimal('0.00'))
        cards.append({
            'product_id': p.product_id,
            'name': p.name,
            'category': p.category,
            'origin': p.origin,
            'price': float(min_price),
            'url': f"{base_url}/product/{p.product_id}",
        })
    return cards


def _search_products(question, limit=5):
    keywords = [k for k in question.strip().split() if k]
    query = Product.query.filter(Product.is_on_sale == True)

    if keywords:
        cond = []
        for kw in keywords[:5]:
            cond.extend([
                Product.name.contains(kw),
                Product.category.contains(kw),
                Product.origin.contains(kw),
                Product.description.contains(kw),
            ])
        query = query.filter(or_(*cond))

    return query.limit(limit).all()


def build_mall_answer(qwen_client, question):
    """商城全局客服：根据问题推荐站内商品并附详情页链接。"""
    base_url = os.getenv('MALL_BASE_URL', 'http://127.0.0.1:5000')
    products = _search_products(question)
    product_cards = _build_product_cards(products, base_url)

    if not product_cards:
        return {
            'intent': 'mall_assistant',
            'answer': '暂时没有匹配到商品，你可以换个关键词试试（例如：牛肉、苹果、有机蔬菜）。',
            'recommendations': [],
        }

    prompt = f"""
你是商城智能客服，请根据候选商品推荐并回答用户问题。
要求：
1) 用中文回答，简洁友好；
2) 优先推荐 3-5 个最相关商品；
3) 每个推荐都引用商品名+价格+详情链接；
4) 不要编造不存在的商品。

用户问题: {question}
候选商品: {product_cards}
"""

    llm_text = qwen_client.generate(prompt)
    if not llm_text:
        lines = ["根据你的需求，推荐这些商品："]
        for item in product_cards[:5]:
            lines.append(f"- {item['name']}（¥{item['price']}）详情：{item['url']}")
        llm_text = "\n".join(lines)

    return {
        'intent': 'mall_assistant',
        'answer': llm_text,
        'recommendations': product_cards[:5],
    }


def build_answer(graph_client, qwen_client, merchant_id, user_id, question, order_id=None):
    intent = detect_intent(question)
    facts = find_product_facts(graph_client, merchant_id, question[:12])

    if intent == 'after_sales':
        if not order_id:
            return {
                'intent': intent,
                'answer': '请提供订单ID，我才能判断该订单是否符合售后条件。',
                'facts': facts,
                'policy_result': None,
            }
        policy = check_after_sales_eligibility(user_id, order_id)
    else:
        policy = None

    prompt = f"""
你是商家智能客服。请严格依据已知事实回答，不要编造。
商家ID: {merchant_id}
用户问题: {question}
意图: {intent}
事实数据: {facts}
售后判定: {policy}
请给出简洁、可执行的中文回复。
"""
    llm_text = qwen_client.generate(prompt)
    answer = llm_text or '暂无可用回复，请稍后重试。'

    return {
        'intent': intent,
        'answer': answer,
        'facts': facts,
        'policy_result': policy,
    }
