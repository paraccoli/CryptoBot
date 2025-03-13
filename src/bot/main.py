import discord
from discord.ext import commands, tasks
import asyncio
from ..utils.config import Config, DISCORD_RULES_CHANNEL_ID, DISCORD_HELP_CHANNEL_ID, DISCORD_WORDS_CHANNEL_ID, DISCORD_COMMANDS_CHANNEL_ID
from ..utils.logger import Logger, setup_logger
from ..database.database import init_db, SessionLocal
import os
from datetime import datetime, timedelta, timezone
from ..database.models import Wallet, PriceHistory
from ..utils.event_manager import EventManager
from ..bot.tasks import ParaccoliTasks
from ..bot.events import ParaccoliEvents
import psutil
from ..utils.embed_builder import EmbedBuilder
from ..utils.price_calculator import PriceCalculator
from ..utils.chart_builder import ChartBuilder
import pytz
from sqlalchemy import func
import glob
import json
import shutil
import signal
import platform
import logging
import sys
import codecs
from ..utils.trading_hours import TradingHours
from ..utils.embed_builder import EmbedBuilder

# Windows環境での文字化けを防止するため、標準出力のエンコーディングを設定
if platform.system() == 'Windows':
    # 標準出力と標準エラー出力をUTF-8に設定
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer)
    # コマンドプロンプトをUTF-8モードに設定するコマンドを実行
    os.system('chcp 65001 > nul')

# ロガー設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # 正しい形式
    handlers=[
        logging.StreamHandler(),  # コンソール出力
        logging.FileHandler(f"logs/paraccoli_{datetime.now().strftime('%Y%m%d')}.log", encoding='utf-8')  # ファイル出力
    ]
)

class ParaccoliBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=discord.Intents.all(),
            help_command=None
        )
        self.logger = Logger(__name__)
        self.start_time = datetime.now()
        self.config = Config()
        self.event_manager = EventManager(self)
        self.price_calculator = PriceCalculator(self)
        # タイムゾーンを設定
        self.tz = pytz.timezone('Asia/Tokyo')
        self.total_supply = 100_000_000  # 総発行上限を追加

    async def setup_hook(self):
        """Bot起動時の初期設定"""
        try:
            db = SessionLocal()
            try:
                init_db()
                self.logger.info("Database initialized successfully")
            finally:
                db.close()

            self.price_calculator = PriceCalculator(self)
            self.logger.info("PriceCalculator initialized")

            # コマンドの読み込み
            await self.load_extension("src.bot.commands")
            self.logger.info("Commands loaded successfully")

            # タスクの開始
            self.status_task.start()  # ステータス更新タスクを開始
            
            # ParaccoliTasksのインスタンス化と追加
            tasks_cog = ParaccoliTasks(self)
            await self.add_cog(tasks_cog)

            # ParaccoliEventsのインスタンス化と追加
            events_cog = ParaccoliEvents(self)
            await self.add_cog(events_cog)

            # コマンドを同期
            synced = await self.tree.sync()
            self.logger.info(f"Synced {len(synced)} commands")

            # ChartBuilder の初期化
            ChartBuilder.initialize()
            self.logger.info("ChartBuilder を初期化しました")

        except Exception as e:
            self.logger.error(f"Failed to initialize: {str(e)}")
            raise

    @tasks.loop(minutes=1)
    async def status_task(self):
        """ステータス更新タスク"""
        try:
            db = SessionLocal()
            
            # 総発行量を取得
            total_supply = db.query(func.sum(Wallet.parc_balance)).scalar() or 0
            
            # 現在価格を取得
            current_price = db.query(PriceHistory)\
                .order_by(PriceHistory.timestamp.desc())\
                .first()
            
            # 価格が取得できない場合は初期価格を使用
            price_display = current_price.price if current_price else 100.0
            
            # ステータス表示
            status_text = (
                f"💰 {total_supply:,}/{self.total_supply:,}PARC "
                f"💴 ¥{price_display:,.2f}"
            )
            
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=status_text
            )
            await self.change_presence(
                status=discord.Status.online,
                activity=activity
            )

        except Exception as e:
            self.logger.error(f"Status update error: {e}", exc_info=True)
        finally:
            db.close()

    @status_task.before_loop
    async def before_status_task(self):
        """ステータスタスク開始前の処理"""
        await self.wait_until_ready()

    async def on_ready(self):
        """Bot起動完了時の処理"""
        self.logger.info(f"{self.user} is now running!")
        
        try:
            # 起動時に一度クリーンアップを実行
            cog = self.get_cog('ParaccoliTasks')
            if cog:
                await cog.cleanup_old_charts()
                # ログとバックアップは自動的に定期実行されるので、ここでは実行しない
            
            # 既存の処理
            cog = self.get_cog('ParaccoliTasks')
            if cog:
                await cog.update_price_info()
                self.logger.info("Initial price chart generated")
            
            # サーバー情報をログに記録
            self.logger.info(f"Connected to {len(self.guilds)} servers")
            for guild in self.guilds:
                self.logger.info(f"Server: {guild.name} (ID: {guild.id})")
                self.logger.info(f"Members: {guild.member_count}")
                self.logger.info(f"Channels: {len(guild.channels)}")

            # 取引時間の案内を送信
            try:
                event_channel_id = getattr(self.config, 'event_channel_id', None)
                if (event_channel_id):
                    event_channel = self.get_channel(int(event_channel_id))
                    if event_channel:
                        await event_channel.send(embed=EmbedBuilder.trading_hours_notice())
                        self.logger.info("取引時間案内を送信しました")
                        
                        # 現在が取引時間内であれば、開始通知も送信
                        if TradingHours.is_trading_hours():
                            session_name = TradingHours.get_session_name()
                            await event_channel.send(content="|| @here ||", embed=EmbedBuilder.trading_started(session_name))
            except Exception as e:
                self.logger.error(f"取引時間案内の送信に失敗: {e}")

        except Exception as e:
            self.logger.error(f"Error in on_ready: {e}")

    async def get_currency_info(self):
        """通貨の発行状況を取得"""
        from ..database.database import SessionLocal
        from ..database.models import Transaction
        from sqlalchemy import func
        
        db = SessionLocal()
        try:
            total_supply = db.query(Transaction)\
                .filter(Transaction.transaction_type.in_(['mining', 'daily_bonus', 'ranking_reward']))\
                .with_entities(func.sum(Transaction.amount))\
                .scalar() or 0
            return total_supply
        finally:
            db.close()

    async def post_initial_messages(self):
        """各チャンネルに初期メッセージを投稿"""
        try:
            channels = {
                'rules': self.get_channel(DISCORD_RULES_CHANNEL_ID),
                'help': self.get_channel(DISCORD_HELP_CHANNEL_ID),
                'words': self.get_channel(DISCORD_WORDS_CHANNEL_ID),
                'commands': self.get_channel(DISCORD_COMMANDS_CHANNEL_ID),
                'mining': self.get_channel(self.config.mining_channel_id),
                'daily': self.get_channel(self.config.daily_channel_id),
                'register': self.get_channel(self.config.rookie_channel_id),
                'support': self.get_channel(self.config.form_channel_id)  # サポートチャンネルを追加
            }

            # 各チャンネルのメッセージをクリア
            for name, channel in channels.items():
                if channel:
                    try:
                        await channel.purge(limit=100)
                        self.logger.info(f"Purged messages in {channel.name}")
                    except discord.errors.Forbidden:
                        self.logger.warning(f"No permission to purge messages in {channel.name}")

            # Embedの作成と送信
            for name, channel in channels.items():
                if channel:
                    try:
                        if name == 'rules':
                            embed = EmbedBuilder.create_rules_embed()
                        elif name == 'help':
                            embed = EmbedBuilder.create_help_embed()
                        elif name == 'words':
                            embed = EmbedBuilder.create_words_embed()
                        elif name == 'commands':
                            embed = EmbedBuilder.create_commands_embed()
                        elif name == 'support':
                            embed = EmbedBuilder.create_support_embed()  # サポートチャンネル用のEmbed
                        elif name in ['mining', 'daily', 'register']:
                            embed = EmbedBuilder.create_channel_rules_embed(name)
                        await channel.send(embed=embed)
                        self.logger.info(f"{name.capitalize()} message posted")
                    except Exception as e:
                        self.logger.error(f"Error posting {name} message: {e}")

        except Exception as e:
            self.logger.error(f"Failed to post initial messages: {e}")

class ParaccoliGuildBot(ParaccoliBot):
    async def close(self):
        """Botのクリーンアップ処理"""
        try:
            self.logger.info("Shutting down bot...")
            await super().close()
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")

async def main():
    bot = ParaccoliGuildBot()
    try:
        # Windowsの場合はシグナルハンドラを設定しない
        if platform.system() != 'Windows':
            loop = asyncio.get_event_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.close()))

        await bot.start(bot.config.discord_token)
    except Exception as e:
        bot.logger.error(f"Failed to start bot: {e}")
        raise
    finally:
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())