import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from config import Config
# 🔥 [新增] 导入 Decimal 类型
from decimal import Decimal
# 🔥 [修改] 增加 func 导入，用于聚合统计
from sqlalchemy import or_, func
# 导入所有模型
# 🔥 [修改] 导入新增模型 ProductSKU, ShippingTemplate
from models import db, User, CommunityPost, FarmerInfo, Product, \
    BehaviorLog, ItemSimilarity, CartItem, Order, OrderItem, ProductSKU, ShippingTemplate
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError

# 🔥 [新增] 导入推荐引擎核心类
from recommend import RecommenderEngine

app = Flask(__name__)
app.config.from_object(Config)

# 初始化数据库
db.init_app(app)

# 🔥 [新增] 初始化推荐引擎
# 注意：RecommenderEngine 内部需要使用 app_context，传入 app 实例
recommender = RecommenderEngine(app)

# ==========================================
# 🔥 图片上传配置与目录检测
# ==========================================
# 确保配置中有 UPLOAD_FOLDER
if not hasattr(app.config, 'UPLOAD_FOLDER') or not app.config['UPLOAD_FOLDER']:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')

# 自动创建上传目录
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    try:
        os.makedirs(app.config['UPLOAD_FOLDER'])
        print(f"✅ 上传目录已创建: {app.config['UPLOAD_FOLDER']}")
    except Exception as e:
        print(f"❌ 创建上传目录失败: {e}")


# 辅助函数：检查文件扩展名
def allowed_file(filename):
    allowed_exts = app.config.get('ALLOWED_EXTENSIONS', {'png', 'jpg', 'jpeg', 'gif'})
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_exts


# 🔥 [新增] 初始化函数：确保默认运费模板存在（修复外键约束失败问题）
def init_shipping_templates():
    # 检查默认模板是否存在
    if ShippingTemplate.query.count() == 0:
        # 注意：这里使用 commit=False 来防止在 create_all 块内提前提交
        default_template = ShippingTemplate(template_id=1, name="默认运费", base_cost=10.00)
        cold_chain_template = ShippingTemplate(template_id=2, name="冷链运费", base_cost=25.00)

        db.session.add_all([default_template, cold_chain_template])
        db.session.commit()
        print("✅ 默认运费模板已初始化 (ID 1, 2)！")


# ==========================================
# 🔥 自动建表逻辑
# ==========================================
with app.app_context():
    try:
        db.create_all()
        print("✅ 数据库表已检测/创建成功！")

        # 🔥 [新增] 调用初始化函数，确保运费模板数据存在
        init_shipping_templates()

    except Exception as e:
        print(f"❌ 数据库连接失败，请检查 config.py 里的密码: {e}")


# --- 上下文处理器 ---
@app.context_processor
def inject_user():
    user = None
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
    return dict(current_user=user)


# 🔥 [修改] 运费计算占位符 (返回 Decimal)
def calculate_shipping_cost(cart_items, address):
    """
    实际的运费计算需要根据收货地址、商品重量/件数、运费模板来计算。
    这里为简化，统一返回一个基础运费。
    """
    # 🔥 [修复] 返回 Decimal 类型
    if not cart_items:
        return Decimal('0.00')

    # 未来可扩展：根据 cart_items[0].sku.product.shipping_template 决定运费
    return Decimal('10.00')


# ==========================================
# 🌐 核心页面路由
# ==========================================

@app.route('/')
def index():
    """商城首页：已接入核心推荐算法"""
    q = request.args.get('q', '')

    # 🔥 [修改] 基础查询：仅筛选已上架商品
    base_query = Product.query.filter(Product.is_on_sale == True)

    # 1. 如果有搜索词，优先处理搜索
    if q:
        products = base_query.filter(  # 🔥 [修改] 从 base_query 开始过滤
            or_(
                Product.name.contains(q),
                Product.category.contains(q),
                Product.origin.contains(q)
            )
        ).all()
        recommendation_msg = f"🔍 搜索结果: '{q}'"

    # 2. 如果没有搜索词，尝试调用推荐算法
    else:
        # 默认回退方案（热门/最新）
        fallback_products = base_query.order_by(Product.product_id.desc()).all()  # 🔥 [修改] 从 base_query 开始排序
        products = fallback_products
        recommendation_msg = "🔥 热门农产品推荐"

        # 仅对已登录用户尝试个性化推荐
        if 'user_id' in session:
            try:
                # 调用 recommend.py 中的算法获取推荐 ID 列表
                recommended_ids = recommender.get_recommendations(session['user_id'])

                if recommended_ids:
                    # 根据 ID 获取商品详情
                    # 注意：SQL查询结果顺序不一定按 IN 列表排序，需要手动重排
                    # 🔥 [修改] 增加 is_on_sale 过滤，只推荐上架商品
                    rec_products = Product.query.filter(
                        Product.product_id.in_(recommended_ids),
                        Product.is_on_sale == True
                    ).all()

                    # 建立 ID -> Product 映射
                    product_map = {p.product_id: p for p in rec_products}

                    # 按推荐分数顺序构建列表
                    sorted_products = [product_map[pid] for pid in recommended_ids if pid in product_map]

                    if sorted_products:
                        products = sorted_products
                        recommendation_msg = "✨ 猜你喜欢 (为您定制)"
            except Exception as e:
                print(f"⚠️ 推荐算法调用失败，已回退到热门列表: {e}")
                # 出错时保持默认的 products (热门) 不变

    return render_template('index.html', products=products, search_query=q, recommendation_msg=recommendation_msg)


@app.route('/product/<int:product_id>')
def product_detail(product_id):
    """商品详情页：接入 Item-Based 协同过滤 -> 热门商品兜底 + 收藏状态检查"""
    product = Product.query.get_or_404(product_id)

    # 🔥 [新增] 检查商品是否上架（非农户/管理员用户）
    current_user = User.query.get(session.get('user_id'))
    if not product.is_on_sale and (not current_user or current_user.role == 0):
        flash('🚫 该商品已下架或正在维护中。')
        return redirect(url_for('index'))

    # 1. 检查用户是否已收藏 (用于前端显示实心/空心星星)
    has_favorited = False
    if 'user_id' in session:
        fav_log = BehaviorLog.query.filter_by(
            user_id=session['user_id'],
            product_id=product_id,
            behavior_type=2  # 2 代表收藏
        ).first()
        if fav_log:
            has_favorited = True

        # 记录用户浏览行为 (类型 1)
        try:
            new_log = BehaviorLog(
                user_id=session['user_id'],
                product_id=product_id,
                behavior_type=1
            )
            db.session.add(new_log)
            db.session.commit()
        except:
            pass

    # 2. 策略一：尝试获取“协同过滤”推荐 (基于物品相似度)
    recommendations = []

    # 查询相似度表
    similar_items = ItemSimilarity.query.filter(
        or_(ItemSimilarity.item_a_id == product_id, ItemSimilarity.item_b_id == product_id)
    ).order_by(ItemSimilarity.similarity_score.desc()).limit(4).all()

    if similar_items:
        related_ids = []
        for item in similar_items:
            # 提取另一端的商品ID
            target_id = item.item_b_id if item.item_a_id == product_id else item.item_a_id
            related_ids.append(target_id)

        if related_ids:
            # 按ID获取商品并在内存中保持相似度排序
            # 🔥 [修改] 增加 is_on_sale 过滤
            products_unsorted = Product.query.filter(
                Product.product_id.in_(related_ids),
                Product.is_on_sale == True
            ).all()
            product_map = {p.product_id: p for p in products_unsorted}
            recommendations = [product_map[pid] for pid in related_ids if pid in product_map]

    # 3. 策略二 (热门兜底)：如果算法无结果，推荐“收藏/购买”最多的商品
    if not recommendations:
        # SQL逻辑: 统计 behavior_type 为 2(收藏) 或 4(购买) 的记录数，按降序取 Top 4
        # Note: 此时 Top 4 可能会包含已下架商品，但在下一步过滤掉。
        top_products_query = db.session.query(
            BehaviorLog.product_id,
            func.count(BehaviorLog.log_id).label('count')
        ).filter(
            BehaviorLog.behavior_type.in_([2, 4]),  # 只统计高权重行为
            BehaviorLog.product_id != product_id  # 排除当前商品自己
        ).group_by(
            BehaviorLog.product_id
        ).order_by(
            func.count(BehaviorLog.log_id).desc()
        ).limit(4).all()

        if top_products_query:
            top_ids = [r.product_id for r in top_products_query]
            # 🔥 [修改] 增加 is_on_sale 过滤
            products_unsorted = Product.query.filter(
                Product.product_id.in_(top_ids),
                Product.is_on_sale == True
            ).all()
            product_map = {p.product_id: p for p in products_unsorted}
            recommendations = [product_map[pid] for pid in top_ids if pid in product_map]

    # 4. 策略三 (冷启动兜底)：如果连热门数据都没有，推荐同分类或最新商品
    if not recommendations:
        # 优先同分类
        recommendations = Product.query.filter(  # 🔥 [修改] 增加 is_on_sale 过滤
            Product.category == product.category,
            Product.product_id != product_id,
            Product.is_on_sale == True
        ).limit(4).all()

    if not recommendations:
        # 最后尝试全站最新
        recommendations = Product.query.filter(  # 🔥 [修改] 增加 is_on_sale 过滤
            Product.product_id != product_id,
            Product.is_on_sale == True
        ).order_by(Product.product_id.desc()).limit(4).all()

    # 🔥 [新增] 查询所有关联 SKU
    product_skus = ProductSKU.query.filter_by(product_id=product_id).order_by(ProductSKU.price.asc()).all()

    return render_template('product_detail.html',
                           product=product,
                           recommendations=recommendations,
                           has_favorited=has_favorited,
                           product_skus=product_skus)  # 🔥 [修改] 传递 SKUs


# ==========================================
# 🏘️ 社区功能
# ==========================================

@app.route('/community')
def community():
    posts = CommunityPost.query.order_by(CommunityPost.post_date.desc()).all()
    return render_template('community.html', posts=posts)


# 🔥 [新增] 删除帖子路由
@app.route('/community/delete/<int:post_id>', methods=['POST'])
def delete_post(post_id):
    """删除社区帖子，仅限作者或管理员操作"""
    if 'user_id' not in session:
        flash('请先登录。')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    post = CommunityPost.query.get_or_404(post_id)

    # 权限检查：必须是帖子作者 (post.user_id) 或管理员 (role=2)
    if post.user_id != user.user_id and user.role != 2:
        flash('🚫 权限不足，无法删除此帖子。', 'error')
        return redirect(url_for('community'))

    try:
        db.session.delete(post)
        db.session.commit()
        flash('✅ 帖子已成功删除。')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ 删除失败: {e}', 'error')

    return redirect(url_for('community'))


# ==========================================
# 🛒 购物车功能
# ==========================================

@app.route('/cart')
def view_cart():
    """查看购物车页面"""
    if 'user_id' not in session:
        flash('请先登录以查看购物车。')
        return redirect(url_for('login'))

    # 查询当前用户购物车中的所有 SKU 项
    cart_items = CartItem.query.filter_by(user_id=session['user_id']).all()

    # 🔥 [修改] 总价计算基于 item.sku.price
    total_price = sum(item.sku.price * item.quantity for item in cart_items)

    return render_template('cart.html', cart_items=cart_items, total_price=total_price)


# @app.route('/cart/add/<int:product_id>', methods=['POST']) # Original
@app.route('/cart/add/<int:sku_id>', methods=['POST'])  # 🔥 [修改] 接收 sku_id
def add_to_cart(sku_id):  # 🔥 [修改] 接收 sku_id
    """添加 SKU 到购物车"""
    if 'user_id' not in session:
        flash('请先登录才能添加商品到购物车。')
        return redirect(url_for('login'))

    user_id = session['user_id']
    quantity = int(request.form.get('quantity', 1))

    sku = ProductSKU.query.get_or_404(sku_id)

    if quantity <= 0:
        flash('数量必须大于零。', 'error')
        return redirect(url_for('product_detail', product_id=sku.product_id))

    # 查找该 SKU 是否已在购物车
    cart_item = CartItem.query.filter_by(user_id=user_id, sku_id=sku_id).first()  # 🔥 [修改] 查询 sku_id

    try:
        # 🔥 [新增] 库存检查 (SKU 级别)
        current_in_cart = cart_item.quantity if cart_item else 0
        if sku.stock < quantity + current_in_cart:
            flash(f'⚠️ 库存不足，当前库存为 {sku.stock}。', 'error')
            return redirect(url_for('product_detail', product_id=sku.product_id))

        if cart_item:
            # 如果存在，更新数量
            cart_item.quantity += quantity
        else:
            # 如果不存在，创建新的购物车项
            new_cart_item = CartItem(
                user_id=user_id,
                sku_id=sku_id,  # 🔥 [修改] 使用 sku_id
                quantity=quantity
            )
            db.session.add(new_cart_item)

        db.session.commit()

        # 记录加购行为 (BehaviorLog 仍使用 Product ID)
        product_id = sku.product_id  # 从 SKU 获取 Product ID
        new_log = BehaviorLog(user_id=user_id, product_id=product_id, behavior_type=3)
        db.session.add(new_log)
        db.session.commit()

        flash('✅ 商品已成功加入购物车！')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ 加入购物车失败: {e}', 'error')

    return redirect(url_for('view_cart'))


@app.route('/cart/update', methods=['POST'])
def update_cart():
    """更新购物车中商品的数量"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    cart_item_id = request.form.get('item_id', type=int)
    new_quantity = request.form.get('quantity', type=int)

    cart_item = CartItem.query.filter_by(id=cart_item_id, user_id=session['user_id']).first()

    if cart_item and new_quantity is not None:
        if new_quantity > 0:
            # 🔥 [修改] 检查库存，使用 item.sku.stock
            if new_quantity > cart_item.sku.stock:
                flash(f'⚠️ 数量不能超过库存 ({cart_item.sku.stock})。', 'error')
            else:
                cart_item.quantity = new_quantity
                db.session.commit()
        elif new_quantity == 0:
            db.session.delete(cart_item)
            db.session.commit()
            flash('商品已从购物车移除。')
        else:
            flash('数量无效。')

    return redirect(url_for('view_cart'))


@app.route('/cart/remove/<int:item_id>')
def remove_from_cart(item_id):
    """从购物车移除单个商品"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    cart_item = CartItem.query.filter_by(id=item_id, user_id=session['user_id']).first()

    if cart_item:
        db.session.delete(cart_item)
        db.session.commit()
        flash('商品已成功从购物车移除。')

    return redirect(url_for('view_cart'))


# ==========================================
# 💵 结算与下单
# ==========================================

@app.route('/checkout')
def checkout():
    """结算页面：展示商品、运费和收货信息"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    cart_items = CartItem.query.filter_by(user_id=session['user_id']).all()
    if not cart_items:
        flash("购物车为空，无法结算。", 'error')
        return redirect(url_for('index'))

    # 🔥 [修改] 总价计算基于 item.sku.price (返回 Decimal)
    total_price = sum(item.sku.price * item.quantity for item in cart_items)

    # 🔥 [新增] 运费计算 (返回 Decimal)
    shipping_cost = calculate_shipping_cost(cart_items, None)

    final_total = total_price + shipping_cost  # 最终总价 = 商品总价 + 运费

    return render_template('checkout.html',
                           cart_items=cart_items,
                           total_price=total_price,
                           shipping_cost=shipping_cost,  # 🔥 [新增] 传递运费
                           final_total=final_total)  # 🔥 [新增] 传递最终总价


@app.route('/place_order', methods=['POST'])
def place_order():
    """最终下单并记录购买行为 (type=4)"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    # 1. 获取收货信息和总额
    receiver_name = request.form.get('receiver_name')
    receiver_phone = request.form.get('receiver_phone')
    address = request.form.get('address')

    total_amount_str = request.form.get('final_total')

    if not total_amount_str:
        flash("订单无效: 缺少总金额信息。", 'error')
        return redirect(url_for('checkout'))

    cart_items = CartItem.query.filter_by(user_id=user_id).all()

    if not cart_items:
        flash("订单无效: 购物车为空。", 'error')
        return redirect(url_for('view_cart'))

    try:
        # 🔥 [修正] 将表单中的总金额转换为 Decimal 进行精确计算
        total_amount_from_form = Decimal(total_amount_str)
    except Exception:
        flash("订单无效: 金额格式错误。", 'error')
        return redirect(url_for('checkout'))

    if total_amount_from_form <= Decimal('0.00'):
        flash("订单无效: 金额必须大于零。", 'error')
        return redirect(url_for('checkout'))

    # 🔥 [新增] 后端重新计算运费和总价 (使用 Decimal)
    goods_total = sum(item.sku.price * item.quantity for item in cart_items)
    shipping_cost = calculate_shipping_cost(cart_items, address)
    calculated_total = goods_total + shipping_cost

    # 验证：直接用 Decimal 进行比较
    if abs(calculated_total - total_amount_from_form) > Decimal('0.01'):
        flash("❌ 订单金额校验失败，请重新结算。", 'error')
        return redirect(url_for('checkout'))

    try:
        # 2. 创建订单主表记录
        new_order = Order(
            user_id=user_id,
            total_amount=calculated_total,  # 🔥 [修改] 使用后端计算的 Decimal 总额
            shipping_cost=shipping_cost,  # 🔥 [新增] 记录 Decimal 运费
            receiver_name=receiver_name,
            receiver_phone=receiver_phone,
            address=address,
            status=2
        )
        db.session.add(new_order)
        db.session.flush()

        # 3. 遍历购物车，创建订单详情记录，并记录购买行为
        for item in cart_items:
            sku = item.sku  # 获取当前购物车项关联的 SKU

            # 🔥 [修改] 检查库存 (SKU 级别)，并使用 with_for_update 锁定库存行（防止超卖）
            sku_lock = ProductSKU.query.filter_by(sku_id=sku.sku_id).with_for_update().first()

            if sku_lock.stock < item.quantity:
                raise ValueError(f"商品 {sku_lock.product.name} ({sku_lock.spec_name}) 库存不足。")

            product = sku_lock.product  # Parent product

            # 创建订单详情项 (基于 SKU)
            new_order_item = OrderItem(
                order_id=new_order.order_id,
                sku_id=sku_lock.sku_id,
                product_id=product.product_id,
                product_name=product.name,
                farmer_id=product.farmer_id,
                quantity=item.quantity,
                price=sku_lock.price
            )
            db.session.add(new_order_item)

            # 扣减库存 (SKU 级别)
            sku_lock.stock -= item.quantity

            # 记录购买行为 (BehaviorLog 仍然使用 Product ID)
            new_log = BehaviorLog(user_id=user_id, product_id=product.product_id, behavior_type=4)
            db.session.add(new_log)

        # 4. 清空购物车
        CartItem.query.filter_by(user_id=user_id).delete()

        # 5. 提交所有更改
        db.session.commit()
        flash(f'🎉 订单 #{new_order.order_id} 提交成功，请耐心等待发货！', 'success')
        return redirect(url_for('orders'))

    except ValueError as e:
        db.session.rollback()
        flash(f'❌ 下单失败: {e}', 'error')
        return redirect(url_for('checkout'))
    except Exception as e:
        db.session.rollback()
        print(f"致命下单错误: {e}")
        flash(f'❌ 下单失败，系统错误。', 'error')
        return redirect(url_for('checkout'))


# ==========================================
# 👤 用户中心与发布功能
# ==========================================

@app.route('/profile')
def profile():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    return render_template('profile.html', user=user)


@app.route('/profile/edit', methods=['GET', 'POST'])
def edit_profile():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        user.email = request.form.get('email')
        user.phone = request.form.get('phone')

        if user.role == 1:
            info = FarmerInfo.query.get(user.user_id)
            if not info:
                info = FarmerInfo(farmer_id=user.user_id)
                db.session.add(info)
            info.shop_name = request.form.get('shop_name')
            info.contact_person = request.form.get('contact_person')
            info.farm_address = request.form.get('farm_address')
            info.bio = request.form.get('bio')

        db.session.commit()
        flash('✅ 资料修改成功！')
        return redirect(url_for('profile'))

    # 🔥 [修复] 渲染正确的模板：edit_profile.html
    return render_template('edit_profile.html', user=user)


@app.route('/product/publish', methods=['GET', 'POST'])
def publish_product():
    """农户发布商品 (支持图片上传)"""
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])

    # 权限检查
    if not user or user.role != 1 or user.status != 1:
        flash('❌ 无权发布，请等待审核。')
        return redirect(url_for('profile'))

    if request.method == 'POST':
        try:
            # 1. 处理图片上传
            image_url = None
            if 'image_file' in request.files:
                file = request.files['image_file']
                if file and file.filename != '' and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    image_url = url_for('static', filename='uploads/' + filename)

            # 2. 如果没上传文件，尝试使用输入的 URL
            if not image_url:
                image_url = request.form.get('image_url')

            # 🔥 [新增] 接收规格信息和运费模板ID
            spec_name = request.form.get('spec_name')
            price = request.form.get('price', type=float)
            stock = request.form.get('stock', type=int)
            shipping_template_id = request.form.get('shipping_template_id', type=int)  # 新增

            if not price or price <= 0 or stock is None or stock < 0 or not spec_name:
                raise ValueError("必须提供有效价格、库存和规格名称。")

            # 3. 保存商品主表 (Product)
            new_product = Product(
                farmer_id=user.user_id,
                name=request.form.get('name'),
                category=request.form.get('category'),
                origin=request.form.get('origin'),
                description=request.form.get('description'),
                image_url=image_url,
                shipping_template_id=shipping_template_id  # 新增
            )
            db.session.add(new_product)
            db.session.flush()  # 立即获取 product_id

            # 🔥 [新增] 创建默认 SKU
            new_sku = ProductSKU(
                product_id=new_product.product_id,
                spec_name=spec_name,  # 使用表单输入的规格名称
                price=price,
                stock=stock
            )
            db.session.add(new_sku)

            db.session.commit()
            flash('🎉 发布成功！')
            return redirect(url_for('profile'))
        except Exception as e:
            db.session.rollback()
            print(f"发布错误: {e}")
            flash(f'❌ 发布失败: {e}', 'error')  # 加上 error 标签，方便前端识别
            return redirect(url_for('publish_product'))  # 失败后返回发布页，防止数据丢失

    return render_template('publish.html')


# 🔥 [新增] 农户切换商品上下架状态
@app.route('/farmer/product/<int:product_id>/toggle_sale')
def toggle_product_status(product_id):
    """切换商品的上架/下架状态"""
    if 'user_id' not in session: return redirect(url_for('login'))

    current_user = User.query.get(session['user_id'])
    product = Product.query.get_or_404(product_id)

    # 权限检查：必须是农户 (role=1) 且是商品的发布者
    if current_user.role != 1 or product.farmer_id != current_user.user_id:
        flash('🚫 权限不足，无法操作该商品。')
        return redirect(url_for('profile'))

    product.is_on_sale = not product.is_on_sale
    db.session.commit()

    status_msg = "上架" if product.is_on_sale else "下架"
    flash(f'✅ 商品 **{product.name}** 已成功切换为 **{status_msg}** 状态！')

    # 成功后重定向回农户商品管理列表
    return redirect(url_for('profile'))


@app.route('/product/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    """农户修改已发布的商品信息和规格"""
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])

    product = Product.query.get_or_404(product_id)
    # 我们只修改第一个 SKU，因为它在模板中是唯一可编辑的
    main_sku = ProductSKU.query.filter_by(product_id=product_id).first()

    # 权限检查：必须是农户且是该商品的发布者
    if not user or user.role != 1 or product.farmer_id != user.user_id:
        flash('🚫 权限不足，无法编辑该商品。')
        return redirect(url_for('profile'))

    if request.method == 'POST':
        try:
            # 1. 严格校验和类型转换 (解决无法保存的问题)
            spec_name_input = request.form.get('spec_name')
            price_str = request.form.get('price')
            stock_str = request.form.get('stock')

            if not price_str or not stock_str or not spec_name_input:
                raise ValueError("规格名称、价格和库存字段不能为空。")

            # 尝试类型转换
            price_val = float(price_str)
            stock_val = int(stock_str)

            if price_val <= 0 or stock_val < 0:
                raise ValueError("价格必须大于零，库存不能为负数。")

            # 2. 图片 URL 处理 (保留上次的优化逻辑)
            image_url = product.image_url
            is_file_uploaded = False

            if 'image_file' in request.files:
                file = request.files['image_file']
                if file and file.filename != '' and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    image_url = url_for('static', filename='uploads/' + filename)
                    is_file_uploaded = True

            manual_url_input = request.form.get('image_url')

            if not is_file_uploaded:
                if manual_url_input:
                    image_url = manual_url_input
                else:
                    image_url = None

            # 3. 更新 Product 主表字段
            product.name = request.form.get('name')
            product.category = request.form.get('category')
            product.origin = request.form.get('origin')
            product.description = request.form.get('description')
            product.image_url = image_url
            product.shipping_template_id = request.form.get('shipping_template_id', type=int)

            # 4. 更新主要 SKU 规格
            if main_sku:
                main_sku.spec_name = spec_name_input
                main_sku.price = price_val  # 使用已校验的值
                main_sku.stock = stock_val  # 使用已校验的值
            else:
                # 这种情况应该在创建商品时被避免
                raise Exception("商品规格（SKU）数据丢失，无法更新。")

            db.session.commit()
            flash('✅ 商品信息修改成功！')
            return redirect(url_for('profile'))

        except ValueError as ve:
            # 捕获我们新增的校验错误
            db.session.rollback()
            flash(f'❌ 数据校验失败: {ve}', 'error')
            # 保持在当前页面，允许用户修改
            return redirect(url_for('edit_product', product_id=product_id))

        except Exception as e:
            # 捕获其他数据库或系统错误
            db.session.rollback()
            print(f"编辑错误: {e}")
            flash(f'❌ 编辑失败，系统错误: {e}', 'error')
            return redirect(url_for('edit_product', product_id=product_id))

    return render_template('edit_product.html', product=product, skus=[main_sku] if main_sku else [])


@app.route('/product/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    """农户删除商品及其所有关联数据"""
    if 'user_id' not in session: return redirect(url_for('login'))
    current_user = User.query.get(session['user_id'])

    # 查找商品，确保存在
    product = Product.query.get_or_404(product_id)

    # 权限检查：必须是农户且是该商品的发布者
    if not current_user or current_user.role != 1 or product.farmer_id != current_user.user_id:
        flash('🚫 权限不足，无法删除该商品。')
        return redirect(url_for('profile'))

    try:
        # ⚠️ 必须先删除所有关联的外键数据，才能删除主商品
        # 1. 删除所有 SKU
        ProductSKU.query.filter_by(product_id=product_id).delete()
        # 2. 删除所有购物车项 (CartItem 现关联 SKU，但为保险仍可检查)
        # 3. 删除所有关联社区帖子
        CommunityPost.query.filter_by(related_product_id=product_id).delete()
        # 4. 删除所有行为日志 (CF数据源)
        BehaviorLog.query.filter_by(product_id=product_id).delete()
        # 5. 删除所有相似度记录 (CF结果)
        ItemSimilarity.query.filter(
            (ItemSimilarity.item_a_id == product_id) | (ItemSimilarity.item_b_id == product_id)
        ).delete()

        # 6. 删除商品主表
        db.session.delete(product)
        db.session.commit()

        flash(f'✅ 商品 **{product.name}** 及其所有关联数据已彻底删除。')

    except Exception as e:
        db.session.rollback()
        print(f"删除商品错误: {e}")
        flash('❌ 删除商品失败，可能存在未清理的订单关联数据。')

    return redirect(url_for('profile'))


@app.route('/profile/orders')
def orders():
    """消费者：查看自己的订单列表"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_orders = Order.query.filter_by(user_id=session['user_id']).order_by(Order.order_date.desc()).all()

    status_map = {
        1: '待支付',
        2: '待发货',
        3: '待收货',
        4: '已完成',
        5: '已取消'
    }

    return render_template('orders.html', orders=user_orders, status_map=status_map)


@app.route('/order/<int:order_id>')
def order_detail(order_id):
    """订单详情页：展示订单内的商品、收货信息等"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # 查找特定订单，并确保该订单属于当前用户
    order = Order.query.filter_by(order_id=order_id, user_id=session['user_id']).first_or_404()

    # 状态映射
    status_map = {1: '待支付', 2: '待发货', 3: '待收货', 4: '已完成', 5: '已取消'}

    return render_template('order_detail.html', order=order, status_map=status_map)


@app.route('/profile/favorites')
def view_favorites():
    """查看我的收藏列表"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # 1. 查询该用户所有 behavior_type=2 (收藏) 的日志
    # 按时间倒序排列，最近收藏的在前面
    logs = BehaviorLog.query.filter_by(
        user_id=session['user_id'],
        behavior_type=2
    ).order_by(BehaviorLog.timestamp.desc()).all()

    # 2. 提取商品ID并去重 (用户可能多次点击收藏)
    # 使用 list(dict.fromkeys()) 保持顺序去重
    product_ids = list(dict.fromkeys([log.product_id for log in logs]))

    favorites = []
    if product_ids:
        # 3. 根据ID查询商品详情
        # 🔥 [修改] 增加 is_on_sale 过滤
        products = Product.query.filter(
            Product.product_id.in_(product_ids),
            Product.is_on_sale == True
        ).all()
        # 建立 ID -> Product 对象的映射，以便按收藏顺序排序
        product_map = {p.product_id: p for p in products}

        for pid in product_ids:
            if pid in product_map:
                favorites.append(product_map[pid])

    return render_template('favorites.html', favorites=favorites)


@app.route('/community/new', methods=['GET', 'POST'])
def new_post():
    """发布新帖子 (支持关联商品)"""
    if 'user_id' not in session:
        flash('请先登录后再发帖。')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        # 获取关联的商品ID (如果是 'none' 或者空，则为 None)
        product_id_str = request.form.get('product_id')
        related_product_id = int(product_id_str) if product_id_str and product_id_str != 'none' else None

        if not title or not content:
            flash('标题和内容不能为空！', 'error')
        else:
            try:
                new_post = CommunityPost(
                    user_id=session['user_id'],
                    title=title,
                    content=content,
                    related_product_id=related_product_id  # 🔥 保存关联商品
                )
                db.session.add(new_post)
                db.session.commit()
                flash('🎉 帖子发布成功！')
                return redirect(url_for('community'))
            except Exception as e:
                db.session.rollback()
                flash(f'发布失败: {e}', 'error')

    # GET 请求：如果是农户，获取他的商品列表
    my_products = []
    if user.role == 1:  # 1 = 农户
        # 🔥 [修改] 仅获取已上架的商品供关联
        my_products = Product.query.filter_by(farmer_id=user.user_id, is_on_sale=True).all()

    return render_template('publish_post.html', my_products=my_products)


@app.route('/admin/dashboard')
def admin_dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if user.role != 2:
        flash('🚫 权限不足')
        return redirect(url_for('index'))

    pending_farmers = User.query.filter_by(role=1, status=2).all()
    return render_template('admin_dashboard.html', farmers=pending_farmers)


@app.route('/admin/approve/<int:user_id>')
def approve_farmer(user_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    current_user = User.query.get(session['user_id'])
    if current_user.role != 2: return "无权操作", 403

    farmer = User.query.get(user_id)
    if farmer:
        farmer.status = 1
        db.session.commit()
        flash(f'✅ {farmer.username} 已审核通过！')
    return redirect(url_for('admin_dashboard'))


# 🔥 [新增] 管理员手动触发推荐模型训练的路由
@app.route('/admin/train_model')
def train_model():
    """手动触发推荐算法的离线计算 (计算物品相似度)"""
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if not user or user.role != 2:
        return "无权操作", 403

    try:
        # 调用核心算法进行离线计算，并更新数据库中的 ItemSimilarity 表
        recommender.calculate_and_save_similarity()
        flash('✅ 推荐模型训练完成！物品相似度矩阵已更新。')
    except Exception as e:
        print(f"训练失败: {e}")
        flash(f'❌ 模型训练失败: {e}')

    return redirect(url_for('admin_dashboard'))


# ==========================================
# 🔒 API: 行为采集 (含收藏状态切换)
# ==========================================

@app.route('/api/collect_behavior', methods=['POST'])
def collect_behavior():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': '未登录'}), 401

    data = request.get_json()
    product_id = data.get('product_id')
    behavior_type = int(data.get('behavior_type'))  # 2:收藏, 3:加购, 4:购买

    if not product_id:
        return jsonify({'status': 'error', 'message': '参数错误'}), 400

    try:
        # 🔥 如果是收藏操作 (type=2)，检查是否需要切换状态
        if behavior_type == 2:
            # 1. 查找所有该用户对该商品的收藏记录 (可能有多条)
            existing_logs = BehaviorLog.query.filter_by(
                user_id=session['user_id'],
                product_id=product_id,
                behavior_type=2
            ).all()

            if existing_logs:
                # 🔥 存在记录 -> 全部删除 (彻底取消收藏)
                for log in existing_logs:
                    db.session.delete(log)
                action = 'removed'
                msg = '已取消收藏'
            else:
                # 不存在 -> 添加一条新记录
                new_log = BehaviorLog(
                    user_id=session['user_id'],
                    product_id=product_id,
                    behavior_type=2
                )
                db.session.add(new_log)
                action = 'added'
                msg = '收藏成功'
        else:
            # 其他行为 (如加购、购买)，直接添加记录，不去重
            new_log = BehaviorLog(
                user_id=session['user_id'],
                product_id=product_id,
                behavior_type=behavior_type
            )
            db.session.add(new_log)
            action = 'added'
            msg = '操作成功'

        db.session.commit()
        return jsonify({'status': 'success', 'action': action, 'message': msg})

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/farmer/dashboard')
def farmer_dashboard():
    """助农数据看板：核心业务统计"""
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])

    # 权限控制：只有认证农户能看
    if not user or user.role != 1:
        flash('🚫 您不是农户，无法查看数据看板。')
        return redirect(url_for('profile'))

    # --- 1. 核心指标统计 ---
    # 统计该农户所有商品的销售总额和总销量
    # Note: OrderItem 仍包含 price 和 quantity，计算逻辑不变
    sales_stats = db.session.query(
        func.sum(OrderItem.quantity).label('total_sales'),
        func.sum(OrderItem.price * OrderItem.quantity).label('total_revenue')
    ).filter(OrderItem.farmer_id == user.user_id).first()

    total_sales = sales_stats.total_sales or 0
    total_revenue = sales_stats.total_revenue or 0

    # 统计该农户所有商品的总浏览量 (PV)
    # 关联 BehaviorLog 和 Product 表
    views_stats = db.session.query(func.count(BehaviorLog.log_id)) \
        .join(Product, BehaviorLog.product_id == Product.product_id) \
        .filter(Product.farmer_id == user.user_id, BehaviorLog.behavior_type == 1) \
        .scalar()

    total_views = views_stats or 0

    # 计算转化率 (下单数 / 浏览数)
    # 注意：简单起见，这里用总销量/总浏览量估算
    conversion_rate = round((total_sales / total_views * 100), 2) if total_views > 0 else 0

    # --- 2. 推荐效果统计 (体现算法价值) ---
    # 统计该农户商品被“收藏”和“加购”的次数 (高意向行为)
    high_intent_stats = db.session.query(func.count(BehaviorLog.log_id)) \
        .join(Product, BehaviorLog.product_id == Product.product_id) \
        .filter(
        Product.farmer_id == user.user_id,
        BehaviorLog.behavior_type.in_([2, 3])  # 2=收藏, 3=加购
    ).scalar()

    # --- 3. 热销商品 Top 5 ---
    top_products = db.session.query(
        Product.name,
        func.sum(OrderItem.quantity).label('sold_count')
    ).join(OrderItem, Product.product_id == OrderItem.product_id) \
        .filter(Product.farmer_id == user.user_id) \
        .group_by(Product.product_id) \
        .order_by(func.sum(OrderItem.quantity).desc()) \
        .limit(5).all()

    return render_template('farmer_dashboard.html',
                           total_sales=total_sales,
                           total_revenue=total_revenue,
                           total_views=total_views,
                           conversion_rate=conversion_rate,
                           high_intent_count=high_intent_stats or 0,
                           top_products=top_products)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        role = int(request.form.get('role'))

        if User.query.filter_by(username=username).first():
            flash('⚠️ 用户名已存在')
            return redirect(url_for('register'))

        new_user = User(
            username=username,
            password_hash=generate_password_hash(request.form.get('password')),
            role=role,
            status=1 if role == 0 else 2
        )
        db.session.add(new_user)
        db.session.commit()
        flash('注册成功，请登录')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password_hash, request.form.get('password')):
            session['user_id'] = user.user_id
            flash(f'👋 欢迎 {user.username}')
            return redirect(url_for('profile'))
        else:
            flash('❌ 用户名或密码错误')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':

    app.run(debug=True, port=5000)