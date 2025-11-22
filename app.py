import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from config import Config
from sqlalchemy import or_
# 导入所有模型 (包括 CartItem, Order, OrderItem)
from models import db, User, CommunityPost, FarmerInfo, Product, BehaviorLog, ItemSimilarity, CartItem, Order, OrderItem
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError  # 导入完整性错误处理

app = Flask(__name__)
app.config.from_object(Config)

# 初始化数据库
db.init_app(app)

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


# ==========================================
# 🔥 自动建表逻辑
# ==========================================
with app.app_context():
    try:
        db.create_all()
        print("✅ 数据库表已检测/创建成功！")
    except Exception as e:
        print(f"❌ 数据库连接失败，请检查 config.py 里的密码: {e}")


# --- 上下文处理器 ---
@app.context_processor
def inject_user():
    user = None
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
    return dict(current_user=user)


# ==========================================
# 🌐 核心页面路由
# ==========================================

@app.route('/')
def index():
    """商城首页：商品展示与搜索"""
    q = request.args.get('q', '')

    if q:
        products = Product.query.filter(
            or_(
                Product.name.contains(q),
                Product.category.contains(q),
                Product.origin.contains(q)
            )
        ).all()
        recommendation_msg = f"🔍 搜索结果: '{q}'"
    else:
        products = Product.query.order_by(Product.product_id.desc()).all()
        recommendation_msg = "🔥 热门农产品推荐"

    return render_template('index.html', products=products, search_query=q, recommendation_msg=recommendation_msg)


@app.route('/product/<int:product_id>')
def product_detail(product_id):
    """商品详情页"""
    product = Product.query.get_or_404(product_id)

    # 记录用户浏览行为 (行为类型 1)
    if 'user_id' in session:
        try:
            new_log = BehaviorLog(
                user_id=session['user_id'],
                product_id=product_id,
                behavior_type=1
            )
            db.session.add(new_log)
            db.session.commit()
        except:
            pass  # 忽略重复记录错误

    return render_template('product_detail.html', product=product)


# ==========================================
# 🏘️ 社区功能
# ==========================================

@app.route('/community')
def community():
    posts = CommunityPost.query.order_by(CommunityPost.post_date.desc()).all()
    return render_template('community.html', posts=posts)


# ==========================================
# 🛒 购物车功能
# ==========================================

@app.route('/cart')
def view_cart():
    """查看购物车页面"""
    if 'user_id' not in session:
        flash('请先登录以查看购物车。')
        return redirect(url_for('login'))

    # 查询当前用户购物车中的所有商品
    cart_items = CartItem.query.filter_by(user_id=session['user_id']).all()

    total_price = sum(item.product.price * item.quantity for item in cart_items)

    # 渲染 cart.html (现在 checkout 路由存在，不会报错)
    return render_template('cart.html', cart_items=cart_items, total_price=total_price)


@app.route('/cart/add/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    """添加商品到购物车"""
    if 'user_id' not in session:
        flash('请先登录才能添加商品到购物车。')
        return redirect(url_for('login'))

    user_id = session['user_id']
    quantity = int(request.form.get('quantity', 1))

    if quantity <= 0:
        flash('数量必须大于零。', 'error')
        return redirect(url_for('product_detail', product_id=product_id))

    # 查找该商品是否已在购物车
    cart_item = CartItem.query.filter_by(user_id=user_id, product_id=product_id).first()

    try:
        if cart_item:
            # 如果存在，更新数量
            cart_item.quantity += quantity
        else:
            # 如果不存在，创建新的购物车项
            new_cart_item = CartItem(
                user_id=user_id,
                product_id=product_id,
                quantity=quantity
            )
            db.session.add(new_cart_item)

        db.session.commit()

        # 记录加购行为 (行为类型 3)
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
    """结算页面：展示商品和收货信息"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    cart_items = CartItem.query.filter_by(user_id=session['user_id']).all()
    if not cart_items:
        flash("购物车为空，无法结算。", 'error')
        return redirect(url_for('index'))

    total_price = sum(item.product.price * item.quantity for item in cart_items)

    # 渲染 checkout.html
    return render_template('checkout.html', cart_items=cart_items, total_price=total_price)


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
    total_amount = request.form.get('total_amount', type=float)

    cart_items = CartItem.query.filter_by(user_id=user_id).all()

    if not cart_items or total_amount <= 0:
        flash("订单无效。", 'error')
        return redirect(url_for('view_cart'))

    try:
        # 2. 创建订单主表记录
        new_order = Order(
            user_id=user_id,
            total_amount=total_amount,
            receiver_name=receiver_name,
            receiver_phone=receiver_phone,
            address=address,
            status=2  # 简化流程，直接设为 "待发货" (已支付)
        )
        db.session.add(new_order)
        db.session.flush()  # 立即获取 order_id

        # 3. 遍历购物车，创建订单详情记录，并记录购买行为
        for item in cart_items:
            product = item.product

            # 检查库存
            if product.stock < item.quantity:
                raise ValueError(f"商品 {product.name} 库存不足。")

            # 创建订单详情项
            new_order_item = OrderItem(
                order_id=new_order.order_id,
                product_id=product.product_id,
                farmer_id=product.farmer_id,
                quantity=item.quantity,
                price=product.price
            )
            db.session.add(new_order_item)

            # 扣减库存
            product.stock -= item.quantity

            # 记录购买行为 (最高权重，行为类型 4)
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

            # 3. 保存商品
            new_product = Product(
                farmer_id=user.user_id,
                name=request.form.get('name'),
                category=request.form.get('category'),
                price=request.form.get('price'),
                stock=int(request.form.get('stock') or 0),
                origin=request.form.get('origin'),
                description=request.form.get('description'),
                image_url=image_url
            )
            db.session.add(new_product)
            db.session.commit()
            flash('🎉 发布成功！')
            return redirect(url_for('profile'))
        except Exception as e:
            print(f"发布错误: {e}")
            flash(f'❌ 发布失败: {e}')

    return render_template('publish.html')


# ==========================================
# 📦 订单查看路由
# ==========================================

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
    # first_or_404() 确保如果找不到订单会返回 404 错误
    order = Order.query.filter_by(order_id=order_id, user_id=session['user_id']).first_or_404()

    # 状态映射
    status_map = {1: '待支付', 2: '待发货', 3: '待收货', 4: '已完成', 5: '已取消'}

    return render_template('order_detail.html', order=order, status_map=status_map)


# ==========================================
# 🛡️ 管理员功能
# ==========================================

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


# ==========================================
# 🔒 API: 行为采集
# ==========================================

@app.route('/api/collect_behavior', methods=['POST'])
def collect_behavior():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': '未登录'}), 401

    data = request.get_json()
    try:
        new_log = BehaviorLog(
            user_id=session['user_id'],
            product_id=data.get('product_id'),
            behavior_type=int(data.get('behavior_type'))  # 2:收藏, 3:加购
        )
        db.session.add(new_log)
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ==========================================
# 🔐 认证路由
# ==========================================

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