from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# 初始化数据库对象
db = SQLAlchemy()


# ==========================================
# 1. 用户体系 (User & Farmer)
# ==========================================

class User(db.Model):
    """用户主表：存储消费者、农户和管理员的基本信息"""
    __tablename__ = 'T_User'
    user_id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    # 角色: 0-消费者, 1-农户, 2-管理员
    role = db.Column(db.Integer, default=0)

    # 状态: 1-正常/已审核, 2-待审核/冻结
    status = db.Column(db.Integer, default=1)

    # 联系方式 (个人中心编辑)
    email = db.Column(db.String(100))
    phone = db.Column(db.String(20))

    # 关联关系
    farmer_info = db.relationship('FarmerInfo', backref='user', uselist=False)
    products = db.relationship('Product', backref='farmer', lazy=True)
    posts = db.relationship('CommunityPost', backref='author', lazy=True)

    # 🔥 订单与购物车关联 (新增)
    cart_items = db.relationship('CartItem', backref='user', lazy=True)
    orders = db.relationship('Order', backref='customer', lazy=True) # 客户下的订单


class FarmerInfo(db.Model):
    """农户详情表：存储店铺专属信息"""
    __tablename__ = 'T_Farmer_Info'
    farmer_id = db.Column(db.Integer, db.ForeignKey('T_User.user_id'), primary_key=True)
    shop_name = db.Column(db.String(100))  # 店铺名称
    contact_person = db.Column(db.String(50))  # 联系人姓名
    farm_address = db.Column(db.String(255))  # 农场/发货地址
    bio = db.Column(db.Text)  # 店铺简介


# ==========================================
# 2. 商品与社区体系 (Product & Community)
# ==========================================

class Product(db.Model):
    """农产品表"""
    __tablename__ = 'T_Product'
    product_id = db.Column(db.Integer, primary_key=True)
    farmer_id = db.Column(db.Integer, db.ForeignKey('T_User.user_id'), nullable=False)

    name = db.Column(db.String(100), nullable=False)  # 商品名称
    category = db.Column(db.String(50))  # 分类 (用于搜索和冷启动)
    origin = db.Column(db.String(100))  # 产地 (用于搜索)
    price = db.Column(db.Numeric(10, 2), nullable=False)  # 价格
    stock = db.Column(db.Integer, default=0)  # 库存
    description = db.Column(db.Text)  # 详细描述
    image_url = db.Column(db.String(255))  # 图片链接


class CommunityPost(db.Model):
    """社区帖子表"""
    __tablename__ = 'T_Community_Post'
    post_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('T_User.user_id'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=False)
    post_date = db.Column(db.DateTime, default=datetime.now)
    views = db.Column(db.Integer, default=0)


# ==========================================
# 3. 推荐系统核心数据 (CF Engine Data)
# ==========================================

class BehaviorLog(db.Model):
    """用户行为日志表 (CF算法原材料)"""
    __tablename__ = 'T_Behavior_Log'
    log_id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('T_User.user_id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('T_Product.product_id'), nullable=False)

    # 行为类型: 1: 点击, 2: 收藏, 3: 加购, 4: 购买 (高权重)
    behavior_type = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now)


class ItemSimilarity(db.Model):
    """物品相似度表 (CF算法离线计算结果)"""
    __tablename__ = 'T_Item_Similarity'
    item_a_id = db.Column(db.Integer, db.ForeignKey('T_Product.product_id'), primary_key=True)
    item_b_id = db.Column(db.Integer, db.ForeignKey('T_Product.product_id'), primary_key=True)

    similarity_score = db.Column(db.Float, nullable=False)  # 相似度得分 (0~1)
    update_date = db.Column(db.Date, default=datetime.now)  # 计算时间


# ==========================================
# 🔥 4. 交易与订单体系 (Shopping Cart & Order)
# ==========================================

class CartItem(db.Model):
    """购物车项：存储用户在购物车中未结算的商品"""
    __tablename__ = 'T_Cart_Item'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('T_User.user_id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('T_Product.product_id'), nullable=False)
    quantity = db.Column(db.Integer, default=1)

    # 关联：方便查询商品信息
    product = db.relationship('Product')

    # 确保同一个用户不会重复添加同一个商品
    __table_args__ = (db.UniqueConstraint('user_id', 'product_id', name='_user_product_uc'),)


class Order(db.Model):
    """订单主表：存储订单的整体信息"""
    __tablename__ = 'T_Order'
    order_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('T_User.user_id'), nullable=False)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)

    # 状态: 1-待支付, 2-待发货, 3-待收货, 4-已完成, 5-已取消
    status = db.Column(db.Integer, default=1)
    order_date = db.Column(db.DateTime, default=datetime.now)

    # 收货信息 (简化处理，直接存在订单里)
    address = db.Column(db.String(255))
    receiver_name = db.Column(db.String(50))
    receiver_phone = db.Column(db.String(20))

    # 关联：订单详情
    items = db.relationship('OrderItem', backref='order', lazy=True)


class OrderItem(db.Model):
    """订单详情表：存储订单中包含的具体商品和价格"""
    __tablename__ = 'T_Order_Item'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('T_Order.order_id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('T_Product.product_id'), nullable=False)
    farmer_id = db.Column(db.Integer, db.ForeignKey('T_User.user_id'), nullable=False) # 冗余存储，方便农户查询

    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False) # 下单时的价格（防止商品变价）

    # 关联：方便查询商品信息
    product = db.relationship('Product')