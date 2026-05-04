from services.assistant.intent_router import detect_intent
from services.assistant.policy_engine import check_after_sales_eligibility
from services.kg.kg_query import find_product_facts


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
