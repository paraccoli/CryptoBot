from discord.ext import commands
from ..database.database import SessionLocal
from ..database.models import User, DailyStats, Wallet
from datetime import datetime, timedelta
from ..utils.logger import Logger
from collections import defaultdict
from ..utils.config import Config
from ..utils.embed_builder import EmbedBuilder
from ..database.models import Transaction
import discord

class ParaccoliEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = Logger(__name__)
        self.config = Config()  # Configインスタンスを作成
        self.start_time = datetime.now()
        self.message_history = defaultdict(list)  # ユーザーごとのメッセージ履歴
        self.warning_count = defaultdict(int)     # ユーザーごとの警告回数
        self.clear_messages = {}  # クリアメッセージのIDとユーザーIDを保存
        self.mining_warnings = {}  # ユーザーごとの警告回数
        self.last_warning = {}     # 最後の警告時刻
        self.daily_warnings = {}  # ユーザーごとの日次警告回数
        self.last_daily_warning = {}  # 最後の日次警告時刻
        self.form_warnings = {}  # サポートチャンネル用の警告カウンター
        self.last_form_warning = {}  # サポートチャンネル用の最終警告時間

    @commands.Cog.listener()
    async def on_ready(self):
        """Bot起動時の処理"""
        self.logger.info(f"Logged in as {self.bot.user.name}")
        await self.bot.tree.sync()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        # マイニングチャンネルの監視
        if message.channel.id == self.config.mining_channel_id:
            if not message.content.startswith("/mine"):
                await message.delete()
                await self._handle_warning(
                    message,
                    self.mining_warnings,
                    self.last_warning,
                    "mine",
                    "マイニング"
                )

        # デイリーボーナスチャンネルの監視
        elif message.channel.id == self.config.daily_channel_id:
            if not message.content.startswith("/daily"):
                await message.delete()
                await self._handle_warning(
                    message,
                    self.daily_warnings,
                    self.last_daily_warning,
                    "daily",
                    "デイリーボーナス"
                )

        # 初心者ガイドチャンネルの監視
        elif message.channel.id == self.config.rookie_channel_id:
            if not message.content.startswith("/register"):
                await message.delete()
                await self._handle_warning(
                    message,
                    self.daily_warnings,
                    self.last_daily_warning,
                    "register",
                    "初心者ガイド"
                )

        # スパム検知（チャンネルに関係なく実行）
        user_id = message.author.id
        current_time = datetime.now()
        
        # 1分以上前のメッセージを削除
        self.message_history[user_id] = [
            (msg, time) for msg, time in self.message_history[user_id]
            if current_time - time < timedelta(minutes=1)
        ]
        
        # 新しいメッセージを追加
        self.message_history[user_id].append((message.content, current_time))
        
        # スパムチェック
        if self._is_spam(user_id):
            warning_count = self.warning_count[user_id] + 1
            self.warning_count[user_id] = warning_count
            
            # スパムメッセージを削除
            try:
                await message.delete()
            except Exception as e:
                self.logger.error(f"スパムメッセージ削除エラー: {str(e)}")
            
            if warning_count >= 3:
                # 3回警告で-100PARCペナルティ
                db = SessionLocal()
                try:
                    user = db.query(User).filter(User.discord_id == str(user_id)).first()
                    if user and user.wallet:
                        user.wallet.parc_balance = max(0, user.wallet.parc_balance - 100)
                        penalty_tx = Transaction(
                            from_address=user.wallet.address,
                            to_address=None,
                            amount=100,
                            transaction_type="penalty",
                            timestamp=datetime.now()
                        )
                        db.add(penalty_tx)
                        db.commit()
                        
                        await message.channel.send(
                            embed=EmbedBuilder.spam_penalty(str(user_id)),
                            delete_after=30
                        )
                        self.warning_count[user_id] = 0
                finally:
                    db.close()
            else:
                await message.channel.send(
                    embed=EmbedBuilder.spam_warning(str(user_id), warning_count),
                    delete_after=10
                )
                return

        # 通常のアクティビティ計測
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.discord_id == str(message.author.id)).first()
            if user:
                user.message_count += 1
                db.commit()
        except Exception as e:
            self.logger.error(f"Message count error: {str(e)}")
        finally:
            db.close()

    async def _handle_warning(self, message, warnings_dict, last_warning_dict, command_type, channel_type):
        """警告処理の共通関数"""
        user_id = message.author.id
        current_time = datetime.now()

        # 過去の警告をクリーンアップ (10分以上経過)
        if user_id in last_warning_dict:
            if (current_time - last_warning_dict[user_id]) > timedelta(minutes=10):
                warnings_dict[user_id] = 0

        # 警告回数を更新
        warnings_dict[user_id] = warnings_dict.get(user_id, 0) + 1
        last_warning_dict[user_id] = current_time

        try:
            is_third_warning = warnings_dict[user_id] >= 3
            
            warning_embed = EmbedBuilder.channel_restriction_warning(
                str(user_id), command_type, warnings_dict[user_id]
            )
            
            # 警告メッセージを送信
            await message.channel.send(
                embed=warning_embed,
                delete_after=30 if is_third_warning else 10
            )

            # DMでも通知
            try:
                member = await message.guild.fetch_member(user_id)
                if member:
                    await member.send(embed=warning_embed)
            except Exception as e:
                self.logger.error(f"DM送信エラー: {str(e)}")

        except Exception as e:
            self.logger.error(f"警告メッセージ送信エラー: {str(e)}")

        # 3回警告でタイムアウト
        if warnings_dict[user_id] >= 3:
            try:
                member = await message.guild.fetch_member(user_id)
                if member:
                    # 1分間のタイムアウト
                    timeout_duration = timedelta(minutes=1)
                    await member.timeout(timeout_duration, reason=f"{channel_type}チャンネルでのルール違反")
                    
                    # タイムアウト通知
                    timeout_embed = EmbedBuilder.timeout_notification(str(user_id))
                    await message.channel.send(embed=timeout_embed, delete_after=60)
                    
                    # 警告カウントをリセット
                    warnings_dict[user_id] = 0
                    
            except Exception as e:
                self.logger.error(f"タイムアウト適用エラー: {str(e)}")

        # 3回警告でペナルティ
        if warnings_dict[user_id] >= 3:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.discord_id == str(user_id)).first()
                if user and user.wallet:
                    penalty_amount = 100
                    if user.wallet.parc_balance >= penalty_amount:
                        penalty_tx = Transaction(
                            from_address=user.wallet.address,
                            to_address=None,
                            amount=penalty_amount,
                            transaction_type="penalty",
                            timestamp=current_time
                        )
                        db.add(penalty_tx)
                        user.wallet.parc_balance -= penalty_amount
                        db.commit()

                        penalty_embed = discord.Embed(
                            title="🔥 ペナルティ発動",
                            description=f"警告回数が3回に達したため、{penalty_amount} PARCが燃焼されました。",
                            color=discord.Color.red()
                        )
                        await message.channel.send(
                            embed=penalty_embed,
                            delete_after=30
                        )

                    warnings_dict[user_id] = 0

            except Exception as e:
                self.logger.error(f"ペナルティ処理エラー: {str(e)}")
            finally:
                db.close()

    def _is_spam(self, user_id: int) -> bool:
        """スパムチェック"""
        messages = self.message_history[user_id]
        if len(messages) < 5:  # 5メッセージ未満は無視
            return False
            
        # 直近5メッセージを確認
        recent_messages = messages[-5:]
        first_message = recent_messages[0][0]
        
        # 同一メッセージが3回以上連続で投稿されているかチェック
        same_message_count = sum(1 for msg, _ in recent_messages if msg == first_message)
        
        # 5秒以内に5メッセージ以上、または同一メッセージが3回以上
        time_diff = recent_messages[-1][1] - recent_messages[0][1]
        return time_diff.seconds <= 5 or same_message_count >= 3

    async def check_game_clear(self, user_id: int, current_price: float, db_session):
        """ゲームクリア条件チェックと処理"""
        try:
            user = db_session.query(User).filter(User.discord_id == str(user_id)).first()
            if not user or not user.wallet:
                return

            total_assets = user.wallet.parc_balance * current_price + user.wallet.jpy_balance
            
            # 一億円到達でクリア
            if total_assets >= 100_000_000 and not user.has_cleared:
                # クリア情報を更新
                user.has_cleared = True
                db_session.commit()

                # クリア通知用のEmbed作成
                embed = discord.Embed(
                    title="🎉 億り人達成！",
                    description=(
                        f"<@{user_id}>が資産一億円を達成しました！\n"
                        "全員で祝福しましょう！ 🎊"
                    ),
                    color=discord.Color.gold()
                )
                
                embed.add_field(
                    name="📊 総資産",
                    value=f"¥{total_assets:,.0f}",
                    inline=False
                )
                
                embed.add_field(
                    name="💰 内訳",
                    value=(
                        f"PARC: {user.wallet.parc_balance:.2f} (¥{user.wallet.parc_balance * current_price:,.0f})\n"
                        f"JPY: ¥{user.wallet.jpy_balance:,}"
                    ),
                    inline=False
                )

                embed.add_field(
                    name="🎮 継続プレイ",
                    value="さらなる高みを目指す場合は🎮を選択",
                    inline=True
                )

                embed.add_field(
                    name="🔄 新規スタート",
                    value="新しく始める場合は🔄を選択",
                    inline=True
                )

                # イベントチャンネルに通知
                event_channel = self.bot.get_channel(self.config.event_channel_id)
                if event_channel:
                    clear_message = await event_channel.send(
                        content="@everyone 億り人の誕生です！みんなで祝いましょう！",
                        embed=embed
                    )
                    await clear_message.add_reaction("🎮")
                    await clear_message.add_reaction("🔄")
                    # メッセージIDとユーザーIDを保存
                    self.clear_messages[clear_message.id] = user_id
                return True
        except Exception as e:
            self.logger.error(f"ゲームクリアチェックエラー: {str(e)}")
            return False

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """リアクション追加時の処理"""
        if payload.user_id == self.bot.user.id:
            return

        # クリアメッセージのリアクションかチェック
        if payload.message_id not in self.clear_messages:
            return

        # クリアしたユーザーのリアクションかチェック
        if str(payload.user_id) != str(self.clear_messages[payload.message_id]):
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return

        if str(payload.emoji) == "🎮":
            # 継続プレイ用のEmbed
            embed = discord.Embed(
                title="🎮 ゲーム継続",
                description=(
                    f"{payload.member.mention}が億り人としてゲームを継続します！\n"
                    "さらなる高みを目指して頑張りましょう！"
                ),
                color=discord.Color.green()
            )
            
            embed.set_footer(text="新たな目標: 10億円を目指して...")
            
            await channel.send(embed=embed)
            del self.clear_messages[payload.message_id]

        elif str(payload.emoji) == "🔄":
            # 新規スタート
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.discord_id == str(payload.user_id)).first()
                if user:
                    # ウォレットをリセット
                    user.wallet.parc_balance = 100
                    user.wallet.jpy_balance = 100000  # 初期資金10万円
                    user.has_cleared = False
                    db.commit()

                    # リセット通知用のEmbed
                    embed = discord.Embed(
                        title="🔄 新規スタート",
                        description=(
                            f"{payload.member.mention}が新たな挑戦を開始します！\n"
                            "再度、億り人を目指しましょう！"
                        ),
                        color=discord.Color.blue()
                    )

                    embed.add_field(
                        name="💰 初期資金",
                        value="100,000 JPY",
                        inline=True
                    )

                    embed.add_field(
                        name="🎯 目標",
                        value="1億円達成",
                        inline=True
                    )

                    embed.set_footer(text="がんばってください！")

                    await channel.send(embed=embed)
                    del self.clear_messages[payload.message_id]

            except Exception as e:
                self.logger.error(f"リセットエラー: {str(e)}")
                # エラー通知用のEmbed
                error_embed = discord.Embed(
                    title="⚠️ エラー",
                    description="ウォレットのリセット中にエラーが発生しました。",
                    color=discord.Color.red()
                )
                await channel.send(embed=error_embed)
            finally:
                db.close()

async def setup(bot):
    await bot.add_cog(ParaccoliEvents(bot))