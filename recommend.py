import pandas as pd
import numpy as np
import jieba
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import create_engine
from datetime import datetime, date
from models import db, BehaviorLog, ItemSimilarity, Product

# ==========================================
# ⚙️ 算法超参数配置 (论文中可作为调优参数)
# ==========================================
# 1. 行为权重字典
BEHAVIOR_WEIGHTS = {
    1: 1.0,  # 点击
    2: 3.0,  # 收藏
    3: 5.0,  # 加购
    4: 10.0  # 购买
}

# 2. 混合推荐权重 (CF vs Content)
ALPHA = 0.7  # 协同过滤(行为)的权重
BETA = 0.3  # 内容推荐(文本)的权重

# 3. 时间衰减半衰期 (单位: 天)
# 意味着每过 30 天，用户行为的参考价值减半
HALF_LIFE_DAYS = 30.0


class RecommenderEngine:
    def __init__(self, app):
        self.app = app
        self.engine = None
        self.item_ids = None
        self.load_engine()

    def load_engine(self):
        with self.app.app_context():
            self.engine = create_engine(self.app.config['SQLALCHEMY_DATABASE_URI'])

    # -------------------------------------------------------------------------
    # 核心模块 A: 基于协同过滤的相似度 (Item-Based CF)
    # -------------------------------------------------------------------------
    def _compute_collaborative_similarity(self):
        """计算基于用户行为的物品相似度矩阵"""
        print("   [1/3] 正在计算协同过滤相似度 (Behavior)...")
        with self.app.app_context():
            logs = db.session.query(
                BehaviorLog.user_id,
                BehaviorLog.product_id,
                BehaviorLog.behavior_type
            ).all()

            if not logs:
                return None, []

            # 转为 DataFrame
            data = [{'user_id': l.user_id, 'product_id': l.product_id, 'behavior_type': l.behavior_type} for l in logs]
            df = pd.DataFrame(data)

            # 加权分
            df['score'] = df['behavior_type'].apply(lambda x: BEHAVIOR_WEIGHTS.get(x, 1.0))

            # 合并同一用户对同一商品的多次行为
            df = df.groupby(['user_id', 'product_id'])['score'].sum().reset_index()

            # 构建透视表 (User x Item)
            rating_matrix = df.pivot(index='user_id', columns='product_id', values='score').fillna(0)

            # 记录所有的 item_ids
            item_ids = rating_matrix.columns.tolist()

            # 计算余弦相似度 (Item x Item)
            # Item-Based: 需要转置为 Item x User
            item_sim_matrix = cosine_similarity(rating_matrix.T)

            # 转为 DataFrame
            sim_df = pd.DataFrame(item_sim_matrix, index=item_ids, columns=item_ids)
            return sim_df, item_ids

    # -------------------------------------------------------------------------
    # 核心模块 B: 基于内容的相似度 (Content-Based TF-IDF)
    # -------------------------------------------------------------------------
    def _compute_content_similarity(self, all_item_ids):
        """计算基于文本特征的物品相似度矩阵"""
        print("   [2/3] 正在计算内容相似度 (TF-IDF NLP)...")
        with self.app.app_context():
            # 获取所有商品的文本信息
            products = Product.query.filter(Product.product_id.in_(all_item_ids)).all()

            # 构建映射: id -> text
            # 文本 = 标题 + 分类 + 描述
            product_corpus = []
            ordered_ids = []

            for p in products:
                # 数据清洗：处理空值
                name = p.name or ""
                category = p.category or ""
                desc = p.description or ""
                origin = p.origin or ""

                # 文本组合
                raw_text = f"{name} {category} {desc} {origin}"

                # 🔥 中文分词 (Jieba)
                # 将 "红富士苹果" 切割为 "红富士 苹果"
                seg_list = jieba.cut(raw_text)
                text_processed = " ".join(seg_list)

                product_corpus.append(text_processed)
                ordered_ids.append(p.product_id)

            if not product_corpus:
                return None

            # TF-IDF 向量化
            tfidf_vec = TfidfVectorizer()
            tfidf_matrix = tfidf_vec.fit_transform(product_corpus)

            # 计算余弦相似度
            content_sim_matrix = cosine_similarity(tfidf_matrix)

            # 转为 DataFrame
            sim_df = pd.DataFrame(content_sim_matrix, index=ordered_ids, columns=ordered_ids)
            return sim_df

    # -------------------------------------------------------------------------
    # 核心模块 C: 混合加权与存储
    # -------------------------------------------------------------------------
    def calculate_and_save_similarity(self):
        """主训练流程：混合 CF 与 Content"""
        print("🚀 [算法启动] 开始训练混合推荐模型...")

        # 1. 计算 CF 相似度
        cf_sim_df, item_ids = self._compute_collaborative_similarity()
        if cf_sim_df is None:
            print("❌ 行为数据不足，无法训练。")
            return

        self.item_ids = item_ids

        # 2. 计算 Content 相似度
        content_sim_df = self._compute_content_similarity(item_ids)

        # 3. 混合矩阵
        # 确保两个矩阵索引对齐
        if content_sim_df is not None:
            # 对齐索引 (处理可能的缺漏)
            content_sim_df = content_sim_df.reindex(index=item_ids, columns=item_ids, fill_value=0)

            # 🔥 核心公式：Hybrid_Sim = α * CF + β * Content
            final_sim_df = (ALPHA * cf_sim_df) + (BETA * content_sim_df)
            print(f"   [3/3] 矩阵融合完成 (α={ALPHA}, β={BETA})")
        else:
            final_sim_df = cf_sim_df
            print("   [3/3] 仅使用 CF 矩阵 (无文本数据)")

        # 4. 保存到数据库
        similarity_data = []
        today = date.today()

        # 遍历上三角矩阵存储
        count = 0
        for i in range(len(item_ids)):
            id_i = item_ids[i]
            for j in range(i + 1, len(item_ids)):
                id_j = item_ids[j]

                score = final_sim_df.loc[id_i, id_j]

                if score > 0.001:  # 过滤极小值
                    similarity_data.append({
                        'item_a_id': int(id_i),
                        'item_b_id': int(id_j),
                        'similarity_score': float(score),
                        'update_date': today
                    })
                    count += 1

        with self.app.app_context():
            try:
                db.session.query(ItemSimilarity).delete()
                if similarity_data:
                    db.session.bulk_insert_mappings(ItemSimilarity, similarity_data)
                db.session.commit()
                print(f"✅ [模型训练成功] 更新了 {count} 条混合相似度记录！")
            except Exception as e:
                db.session.rollback()
                print(f"❌ 存储失败: {e}")

    # -------------------------------------------------------------------------
    # 在线推荐模块 (含时间衰减)
    # -------------------------------------------------------------------------
    def get_recommendations(self, user_id, num_recommendations=10):
        """获取推荐列表，引入时间衰减"""
        with self.app.app_context():
            # 获取用户历史行为 (带时间戳)
            user_logs = db.session.query(
                BehaviorLog.product_id,
                BehaviorLog.behavior_type,
                BehaviorLog.timestamp
            ).filter(BehaviorLog.user_id == user_id).all()

        if not user_logs:
            return []

        user_preference_scores = {}
        now = datetime.now()

        # 1. 计算用户当前偏好 (User Profile)
        for pid, btype, timestamp in user_logs:
            # 基础分
            base_score = BEHAVIOR_WEIGHTS.get(btype, 1.0)

            # 🔥 时间衰减计算 (Newton's Law of Cooling style)
            # 距离现在过去了多少天
            delta_days = (now - timestamp).days
            if delta_days < 0: delta_days = 0

            # 衰减系数: 1 / (1 + days)
            # 或者是指数衰减: math.exp(-lambda * t)
            # 这里用简单的半衰期公式
            time_weight = np.power(0.5, delta_days / HALF_LIFE_DAYS)

            final_score = base_score * time_weight

            user_preference_scores[pid] = user_preference_scores.get(pid, 0) + final_score

        # 2. 扩散推荐
        recommended_scores = {}
        seed_ids = list(user_preference_scores.keys())

        with self.app.app_context():
            # 查相似度表 (这里查出来的是已经是混合过 Content+CF 的结果)
            similar_items = ItemSimilarity.query.filter(
                (ItemSimilarity.item_a_id.in_(seed_ids)) | (ItemSimilarity.item_b_id.in_(seed_ids))
            ).all()

            for sim in similar_items:
                # 确定推荐目标
                if sim.item_a_id in user_preference_scores:
                    seed_id = sim.item_a_id
                    target_id = sim.item_b_id
                else:
                    seed_id = sim.item_b_id
                    target_id = sim.item_a_id

                # 过滤已购买/已交互
                if target_id in user_preference_scores:
                    continue

                # 预测分 = 用户对种子的兴趣(含时间衰减) * 物品相似度(含内容混合)
                score = user_preference_scores[seed_id] * sim.similarity_score
                recommended_scores[target_id] = recommended_scores.get(target_id, 0) + score

        # 3. 排序返回
        sorted_recs = sorted(recommended_scores.items(), key=lambda x: x[1], reverse=True)
        return [item[0] for item in sorted_recs][:num_recommendations]