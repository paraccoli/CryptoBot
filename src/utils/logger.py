import logging
import sys
from datetime import datetime
import os
from logging.handlers import RotatingFileHandler
import pytz



def setup_logger(name: str) -> logging.Logger:
    """ロガーのセットアップ"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # 既存のハンドラを削除して重複を防ぐ
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # 日付ベースのログファイル名
    log_dir = 'logs'
    os.makedirs(log_dir, exist_ok=True)
    log_file = f'{log_dir}/paraccoli_{datetime.now().strftime("%Y%m%d")}.log'
    
    # フォーマッターの作成
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # コンソール用のシンプルなフォーマッター
    console_formatter = logging.Formatter(
        '%(message)s'  # メッセージのみを表示
    )
    
    # ファイルハンドラの設定
    file_handler = logging.FileHandler(
        filename=log_file,
        encoding='utf-8',
        mode='a'
    )
    file_handler.setFormatter(file_formatter)
    
    # コンソールハンドラの設定
    console_handler = logging.StreamHandler(sys.stdout)  # 標準出力に変更
    console_handler.setFormatter(console_formatter)
    
    # ハンドラを追加
    if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        logger.addHandler(file_handler)
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        logger.addHandler(console_handler)

    return logger

class Logger:
    def __init__(self, name):
        self.logger = setup_logger(name)
        self.name = name

    def debug(self, message):
        self.logger.debug(message)

    def info(self, message):
        self.logger.info(message)

    def warning(self, message):
        self.logger.warning(message)

    def error(self, message, exc_info=False):
        self.logger.error(message, exc_info=exc_info)

    def critical(self, message):
        self.logger.critical(message)

# グローバルロガーのインスタンス作成
logger = setup_logger('paraccoli')