import os


class Config:
    # 数据库配置
    SQLALCHEMY_DATABASE_URI = 'mysql+pymysql://root:2021sunt01@localhost:3306/AgriRecommendDB'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'your_secret_key_for_session'

    # 🔥 新增：图片上传配置
    # 获取当前项目根目录
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    # 图片保存文件夹: static/uploads
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    # 允许上传的文件类型
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}