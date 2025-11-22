import pandas as pd
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import create_engine
from datetime import date
from models import db, BehaviorLog, ItemSimilarity, Product

# 定义行为权重：购买权重最高
BEHAVIOR_WEIGHTS = {
    1: 1.0,  # 点击/浏览
    2: 2.0,  # 收藏
    3: 3.0,  # 加购
    4: 5.0  # 购买
}


class RecommenderEngine:
    def __init__(self, app):
        self.app = app
        self.similarity_matrix = None
        self.item_ids = None
        self.top_n = 10
        self.load_engine()

    def load_engine(self):
        with self.app.app_context():
            self.engine = create_engine(self.app.config['SQLALCHEMY_DATABASE_URI'])

    def load_data(self):
        """加载数据并构建评分矩阵"""
        sql = "SELECT user_id, product_id, behavior_type FROM T_Behavior_Log"
        try:
            df = pd.read_sql(sql, self.engine)
        except:
            return None
        if df.empty: return None

        # 计算加权分
        df['score'] = df['behavior_type'].apply(lambda x: BEHAVIOR_WEIGHTS.get(x, 1.0))
        # 构建矩阵 (User x Item)
        rating_matrix = df.groupby(['user_id', 'product_id'])['score'].sum().unstack(fill_value=0)
        self.item_ids = rating_matrix.columns.tolist()
        return rating_matrix

    def calculate_and_save_similarity(self):
        """离线计算物品相似度并存入数据库"""
        rating_matrix = self.load_data()
        if rating_matrix is None: return

        # 计算物品相似度 (Item-Based)
        item_user_matrix = rating_matrix.T
        self.similarity_matrix = cosine_similarity(item_user_matrix)
        sim_df = pd.DataFrame(self.similarity_matrix, index=self.item_ids, columns=self.item_ids)

        similarity_data = []
        today = date.today()

        # 遍历矩阵上三角
        for i in range(len(self.item_ids)):
            for j in range(i + 1, len(self.item_ids)):
                score = sim_df.iloc[i, j]
                if score > 0.0:
                    similarity_data.append({
                        'item_a_id': int(self.item_ids[i]),
                        'item_b_id': int(self.item_ids[j]),
                        'similarity_score': float(score),
                        'update_date': today
                    })

        with self.app.app_context():
            try:
                # 清空旧数据并插入新数据
                ItemSimilarity.query.delete()
                if similarity_data:
                    db.session.bulk_insert_mappings(ItemSimilarity, similarity_data)
                db.session.commit()
                print(f"✅ 相似度计算完成，更新了 {len(similarity_data)} 条记录")
            except Exception as e:
                db.session.rollback()
                print(f"❌ 计算存储失败: {e}")

    def get_recommendations(self, user_id, num_recommendations=10):
        """在线推荐：获取 Top-N 商品ID列表"""
        with self.app.app_context():
            # 获取用户的高权重行为 (加购/购买)
            user_logs = BehaviorLog.query.filter(BehaviorLog.user_id == user_id,
                                                 BehaviorLog.behavior_type.in_([3, 4])).all()

        # 冷启动：如果没有高权重行为，返回热门商品
        if not user_logs:
            all_products = Product.query.order_by(Product.product_id.desc()).limit(self.top_n).all()
            return [p.product_id for p in all_products]

        # 计算用户偏好
        user_ratings = {}
        for log in user_logs:
            score = BEHAVIOR_WEIGHTS.get(log.behavior_type, 1.0)
            user_ratings[log.product_id] = user_ratings.get(log.product_id, 0) + score

        recommended_scores = {}
        with self.app.app_context():
            for item_id, score in user_ratings.items():
                # 查相似物品
                similar_items = ItemSimilarity.query.filter(
                    (ItemSimilarity.item_a_id == item_id) | (ItemSimilarity.item_b_id == item_id)).all()
                for sim in similar_items:
                    rec_id = sim.item_b_id if sim.item_a_id == item_id else sim.item_a_id
                    # 过滤掉用户已经产生过行为的物品
                    if rec_id not in user_ratings:
                        recommended_scores[rec_id] = recommended_scores.get(rec_id, 0) + sim.similarity_score * score

        # 如果算不出推荐结果，兜底返回热门
        if not recommended_scores:
            all_products = Product.query.order_by(Product.product_id.desc()).limit(num_recommendations).all()
            return [p.product_id for p in all_products]

        # 排序返回
        sorted_recs = sorted(recommended_scores.items(), key=lambda x: x[1], reverse=True)
        return [item[0] for item in sorted_recs][:num_recommendations]