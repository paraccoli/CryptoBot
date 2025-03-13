from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
import os
from dotenv import load_dotenv
from ..utils.logger import Logger
from contextlib import contextmanager

load_dotenv()

# MySQL接続情報
MYSQL_USER = os.getenv('MYSQL_USER', 'root')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
MYSQL_PORT = os.getenv('MYSQL_PORT', '3306')
MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'paraccoli')

# MySQL用のURLを作成
DATABASE_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"

# エンジン設定
engine = create_engine(
    DATABASE_URL,
    pool_size=20,  # コネクションプール数
    max_overflow=10,  # 最大オーバーフロー数
    pool_timeout=30,  # タイムアウト時間
    pool_recycle=1800  # コネクション再利用時間(30分)
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db():
    """データベースの初期化とテーブルの作成"""
    # 先にモデルをインポート
    from .models import User, Wallet, Transaction, DailyStats, Base
    
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        Logger.error(f"Database initialization failed: {e}")
        raise

def get_db():
    """データベースセッションを取得するジェネレータ"""
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()

@contextmanager
def transaction_context():
    """トランザクションコンテキストマネージャー"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

@contextmanager
def db_session():
    """DBセッション管理用コンテキストマネージャー"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()