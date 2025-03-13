import random
import discord
from datetime import datetime, time, timedelta, timezone
import asyncio
from discord import Embed, Color
import pytz
from ..database.models import Event, User
from ..database.database import SessionLocal
from ..utils.logger import setup_logger, Logger
from ..utils.embed_builder import EmbedBuilder
from .event_types import EventTypes
from ..utils.config import Config


class EventManager:
    def __init__(self, bot=None):
        """EventManagerの初期化"""
        self.bot = bot
        self.cooldown_hours = 0.5  # 30分に変更
        self.last_event_time = None
        self.last_daily_event = datetime.now().date()
        self.current_event = None
        self.remaining_effects = []
        self.logger = Logger(__name__)
        self.config = Config()

    def set_bot(self, bot):
        """Botインスタンスを設定"""
        self.bot = bot

    async def notify_event(self, event: dict):
        """イベント通知を送信"""
        if not self.bot:
            return

        try:
            # イベント用のEmbed作成
            embed = Embed(
                title=event["name"],
                description=event["description"],
                color=Color.green() if event["total_change"] > 0 else Color.red(),
                timestamp=datetime.now()
            )

            embed.add_field(
                name="予想価格変動",
                value=f"{event['total_change']:+}%",
                inline=False
            )

            # イベントチャンネルに通知
            channel = self.bot.get_channel(self.config.event_channel_id)
            if channel:
                await channel.send(embed=embed)

            # 全ユーザーにDM通知
            db = SessionLocal()
            try:
                users = db.query(User).all()
                for user in users:
                    try:
                        member = await self.bot.fetch_user(int(user.discord_id))
                        if member:
                            await member.send(embed=embed)
                    except Exception as e:
                        self.logger.error(f"DM送信エラー: {str(e)}")
            finally:
                db.close()

        except Exception as e:
            self.logger.error(f"イベント通知エラー: {str(e)}")

    async def check_daily_event(self):
        """1日1回のイベントチェック"""
        now = datetime.now()
        
        # 日付が変わっていて、まだ今日のイベントが発生していない場合
        if now.date() > self.last_daily_event:
            # ランダムな時間（9:00-21:00の間）を選択
            target_hour = random.randint(9, 20)
            if now.hour >= target_hour:
                self.last_daily_event = now.date()
                return await self.trigger_and_notify_event()

        return None

    async def trigger_and_notify_event(self):
        """イベントの発生と通知を行う"""
        if not self.can_trigger_event():
            return None
            
        event = self.trigger_event()
        if event:
            await self._notify_event(event)
            return event
        return None

    def can_trigger_event(self) -> bool:
        """イベント発生条件のチェック"""
        now = datetime.now()
        
        # クールダウン時間を30分に変更
        if self.last_event_time:
            time_diff = now - self.last_event_time
            if time_diff.total_seconds() < 1800:  # 30分 = 1800秒
                return False

        # 9:00-21:00の間のみ発生、かつ毎時00分か30分の時のみ
        if not (9 <= now.hour < 21):
            return False
        
        # 00分か30分の時のみイベント発生を許可
        if now.minute not in [0, 30]:
            return False

        return True

    def is_event_ending(self) -> bool:
        """イベント終了判定"""
        # イベントが存在し、残り効果がない場合に終了
        return (self.current_event is not None and 
                (not self.remaining_effects or len(self.remaining_effects) == 0))

    def _update_base_price(self, price: float):
        """基準価格を更新"""
        self.last_base_price = price
        self.logger.info(f"基準価格を更新: ¥{self.last_base_price:,.2f}")

    def trigger_event(self) -> dict:
        """イベントを発生させる"""
        if not self.can_trigger_event():
            return None

        # イベントをランダムに選択
        event_type = EventTypes.get_random_event()
        total_change = random.randint(
            event_type.min_change,
            event_type.max_change
        )

        # ネガティブイベントの場合、より多くの分割回数を設定
        if total_change < 0:
            split_count = random.randint(12, 16)  # ネガティブは12-16回に分割
            # 1回あたりの最大変動を制限
            max_change_per_step = -8.0  # 最大8%の下落に制限
        else:
            split_count = random.randint(6, 10)   # ポジティブは6-10回に分割
            max_change_per_step = 10.0  # 上昇は10%まで許容

        self.remaining_effects = []
        remaining = total_change

        for i in range(split_count):
            # 残りの変動を均等に分配
            base_effect = remaining / (split_count - i)
            
            # ランダム性を持たせつつ、最大変動率を制限
            if total_change < 0:
                # ネガティブの場合
                effect = max(
                    base_effect * random.uniform(0.7, 1.3),
                    max_change_per_step
                )
            else:
                # ポジティブの場合
                effect = min(
                    base_effect * random.uniform(0.7, 1.3),
                    max_change_per_step
                )

            self.remaining_effects.append(effect)
            remaining -= effect

        # 最後の効果で調整（誤差修正）
        if self.remaining_effects:
            self.remaining_effects[-1] += remaining

        # イベント情報を設定
        self.current_event = {
            "name": event_type.name,
            "description": event_type.description,
            "details": event_type.details,
            "total_change": total_change,
            "is_positive": event_type.is_positive,
            "progress": 1,
            "total_steps": split_count
        }

        self.last_event_time = datetime.now(timezone.utc)
        self.logger.info(
            f"イベント発生: {event_type.name}\n"
            f"目標変動率: {total_change:+.2f}%\n"
            f"分割回数: {split_count}回\n"
            f"1回あたりの最大変動: {max_change_per_step:+.2f}%"
        )
        return self.current_event

    def get_next_price_target(self) -> float:
        """次の価格目標を取得"""
        if not self.remaining_effects:
            return None
        return float(self.remaining_effects[0]) if self.remaining_effects else 0.0

    def _create_event(self, change_percent: float) -> dict:
        """イベント情報を生成"""
        # EmbedBuilderからイベント情報を取得
        events = EmbedBuilder.EVENT_INFO["positive" if change_percent > 0 else "negative"]
        event = random.choice(events)
        
        return {
            "name": event["name"],
            "description": event["description"],
            "details": event["details"],
            "total_change": change_percent,
            "is_positive": change_percent > 0,
            "progress": 1
        }

    def _get_last_event(self) -> Event:
        """最後のイベント情報を取得"""
        db = SessionLocal()
        try:
            return db.query(Event)\
                .order_by(Event.timestamp.desc())\
                .first()
        finally:
            db.close()

    def create_event_embed(self) -> Embed:
        """イベント通知用のEmbed作成"""
        if not self.current_event:
            return None
            
        color = Color.green() if self.current_event["is_positive"] else Color.red()
        embed = Embed(
            title=self.current_event["name"],
            description=self.current_event["description"],
            color=color,
            timestamp=datetime.now()
        )
        
        change = self.current_event["total_change"]
        embed.add_field(
            name="予想価格変動",
            value=f"{change:+}%",
            inline=False
        )
        
        return embed

    def reset(self):
        """イベント状態のリセット"""
        self.event_count = 0
        self.total_change = 0
        self.remaining_effects = []
        self.current_event = None
        self.event_in_progress = False

    async def _notify_event(self, event: dict, is_final: bool = False):
        """イベント通知の送信"""
        try:
            if is_final:
                # 終了時は実際の変動を表示
                embed = discord.Embed(
                    title="🔔 イベント終了",
                    description=f"{event['name']}のイベントが終了しました。",
                    color=discord.Color.light_grey(),
                    timestamp=datetime.now()
                )
                embed.add_field(
                    name="📊 最終変動率",
                    value=f"{event['total_change']:+.2f}%",
                    inline=False
                )
            else:
                # 発生時は予想変動を示唆だけ
                magnitude = "大幅" if abs(event["total_change"]) > 50 else "緩やかな"
                direction = "上昇" if event["total_change"] > 0 else "下落"
                
                color = discord.Color.red() if event["total_change"] < 0 else discord.Color.green()
                embed = discord.Embed(
                    title=f"🔔 発生 {event['name']}",
                    description=event['description'],
                    color=color,
                    timestamp=datetime.now()
                )

                if 'details' in event:
                    embed.add_field(
                        name="📋 詳細",
                        value=f"```{event['details']}```",
                        inline=False
                    )

                embed.add_field(
                    name="📊 市場予測",
                    value=f"```価格の{magnitude}{direction}が予想されます```",
                    inline=False
                )

            embed.set_footer(text="Paraccoli Market Event")

            # チャンネルとDMに通知を送信
            if self.bot:
                channel = self.bot.get_channel(self.config.event_channel_id)
                if channel:
                    await channel.send(embed=embed)

                db = SessionLocal()
                try:
                    users = db.query(User).all()
                    for user in users:
                        try:
                            discord_user = await self.bot.fetch_user(int(user.discord_id))
                            if discord_user:
                                await discord_user.send(embed=embed)
                        except Exception as e:
                            self.logger.error(f"DM送信エラー (User ID: {user.discord_id}): {str(e)}")
                finally:
                    db.close()

        except Exception as e:
            self.logger.error(f"イベント通知エラー: {str(e)}")
            self.logger.exception(e)