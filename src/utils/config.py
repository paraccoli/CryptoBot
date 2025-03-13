import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
import asyncio
from datetime import datetime
import psutil
import sys
from pathlib import Path

# プロジェクトのルートディレクトリをPYTHONPATHに追加
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

# .envファイルを読み込む
load_dotenv()

# 環境変数の取得と型変換
def get_env_int(key: str, default: int = 0) -> int:
    """環境変数を整数として取得"""
    value = os.getenv(key)
    return int(value) if value is not None else default

class Config:

    temp_file_max_age = 300  # 5分（秒単位）
    log_retention_days = 7   # ログ保持日数
    backup_retention_count = 10  # 保持するバックアップ数

    def __init__(self):
        load_dotenv()
        self._load_config()

    def _load_config(self):
        required_env_vars = [
            'DISCORD_TOKEN',
            'CLIENT_ID',
            'CLIENT_SECRET',
            'DISCORD_REGISTER_CHANNEL_ID',
            'DISCORD_DAILY_CHANNEL_ID',
            'DISCORD_MINING_CHANNEL_ID',
            'DISCORD_CHART_CHANNEL_ID',
            'DISCORD_RULES_CHANNEL_ID',
            'DISCORD_HELP_CHANNEL_ID',
            'DISCORD_WORDS_CHANNEL_ID',
            'DISCORD_COMMANDS_CHANNEL_ID',
            'DISCORD_EVENT_CHANNEL_ID',
            'DISCORD_HISTORY_CHANNEL_ID',
            'DISCORD_FORM_CHANNEL_ID',
            'DISCORD_PREDICT_CHANNEL_ID',
            'DISCORD_EXECUTIVE_ROLE_ID',
            'DISCORD_FUNDMANAGER_ROLE_ID',
            'DISCORD_SHAREHOLDER_ROLE_ID',
            'DISCORD_EMPLOYEE_ROLE_ID',
            'DISCORD_GUILD_ID',
            'DISCORD_ROOKIE_CHANNEL_ID',
            'DISCORD_REALTIME_CHART_CHANNEL_ID'
        ]
        
        for var in required_env_vars:
            if not os.getenv(var):
                raise ValueError(f"Missing required environment variable: {var}")
        
        # Discord設定
        self.version = "1.7.0"  # アプリケーションのバージョンを設定
        self.discord_token = os.getenv('DISCORD_TOKEN')
        self.client_id = os.getenv('CLIENT_ID')
        self.client_secret = os.getenv('CLIENT_SECRET')
        self.register_channel_id = int(os.getenv('DISCORD_REGISTER_CHANNEL_ID'))
        self.daily_channel_id = int(os.getenv('DISCORD_DAILY_CHANNEL_ID'))
        self.mining_channel_id = int(os.getenv('DISCORD_MINING_CHANNEL_ID'))
        self.log_channel_id = int(os.getenv('DISCORD_LOG_CHANNEL_ID'))
        self.chart_channel_id = int(os.getenv('DISCORD_CHART_CHANNEL_ID'))
        self.rules_channel_id = int(os.getenv('DISCORD_RULES_CHANNEL_ID'))
        self.help_channel_id = int(os.getenv('DISCORD_HELP_CHANNEL_ID'))
        self.words_channel_id = int(os.getenv('DISCORD_WORDS_CHANNEL_ID'))
        self.commands_channel_id = int(os.getenv('DISCORD_COMMANDS_CHANNEL_ID'))
        self.event_channel_id = int(os.getenv('DISCORD_EVENT_CHANNEL_ID'))
        self.history_channel_id = int(os.getenv('DISCORD_HISTORY_CHANNEL_ID'))
        self.form_channel_id = int(os.getenv('DISCORD_FORM_CHANNEL_ID'))
        self.predict_channel_id = int(os.getenv('DISCORD_PREDICT_CHANNEL_ID'))
        self.admin_user_id = int(os.getenv('DISCORD_ADMIN_USER_ID'))
        self.executive_role_id = int(os.getenv('DISCORD_EXECUTIVE_ROLE_ID'))
        self.fundmanager_role_id = int(os.getenv('DISCORD_FUNDMANAGER_ROLE_ID'))
        self.shareholder_role_id = int(os.getenv('DISCORD_SHAREHOLDER_ROLE_ID'))
        self.employee_role_id = int(os.getenv('DISCORD_EMPLOYEE_ROLE_ID'))
        self.guild_id = int(os.getenv('DISCORD_GUILD_ID'))
        self.rookie_channel_id = int(os.getenv('DISCORD_ROOKIE_CHANNEL_ID'))
        self.realtime_chart_channel_id = int(os.getenv('DISCORD_REALTIME_CHART_CHANNEL_ID'))

        # データベース設定
        self.database_url = os.getenv('DATABASE_URL', 'sqlite:///paraccoli.db')

        # Paraccoli設定
        self.daily_mining_limit = 1000  # 1日の採掘上限
        self.max_supply = 100_000_000  # 発行上限（1億枚）
        self.mining_cooldown = 3600    # マイニングのクールダウン（秒）

# Discord Channel IDs
DISCORD_RULES_CHANNEL_ID = get_env_int('DISCORD_RULES_CHANNEL_ID')
DISCORD_HELP_CHANNEL_ID = get_env_int('DISCORD_HELP_CHANNEL_ID')
DISCORD_WORDS_CHANNEL_ID = get_env_int('DISCORD_WORDS_CHANNEL_ID')
DISCORD_COMMANDS_CHANNEL_ID = get_env_int('DISCORD_COMMANDS_CHANNEL_ID')
DISCORD_ROOKIE_CHANNEL_ID = get_env_int('DISCORD_ROOKIE_CHANNEL_ID')
DISCORD_ADMIN_USER_ID = get_env_int('DISCORD_ADMIN_USER_ID')
DISCORD_GUILD_ID = get_env_int('DISCORD_GUILD_ID')