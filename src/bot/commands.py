# src/bot/commands.py
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands
from discord import Embed, User, Interaction, Color
from ..database.database import SessionLocal
from ..utils.embed_builder import EmbedBuilder
from ..utils.logger import Logger
from datetime import datetime, timedelta
from datetime import timezone
from ..database.models import User, Wallet, Transaction, DailyStats, HistoryPaginationView, Order, PriceHistory, PriceAlert, LastTradeTimestamp
from ..utils.config import Config
from ..utils.config import DISCORD_ADMIN_USER_ID
from ..utils.wallet_utils import generate_wallet_address
from ..utils.event_types import EventTypes
from sqlalchemy import or_, func
from sqlalchemy.orm import joinedload
from dotenv import load_dotenv
from ..utils.price_predictor import PricePredictor
from ..utils.price_calculator import PriceCalculator
from ..utils.trading_hours import TradingHours
import os
import time
import uuid
import math
import json
import glob
import shutil
import random
import numpy as np
import subprocess
import discord
import platform
from sqlalchemy.orm import Session
import asyncio

@commands.guild_only()
class ParaccoliCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = Logger(__name__)
        self.start_time = datetime.now()
        self.config = Config()

    def cleanup_old_backups(self, backup_dir: str):
        """古いバックアップファイルを削除"""
        try:
            patterns = {
                "db": "paraccoli_*.db",
                "chart": "chart_*.png",
                "state": "state_*.json"
            }

            for file_type, pattern in patterns.items():
                files = sorted(
                    glob.glob(os.path.join(backup_dir, pattern)),
                    key=os.path.getmtime,
                    reverse=True
                )

                if len(files) > 1:
                    for old_file in files[1:]:
                        try:
                            os.remove(old_file)
                            self.logger.info(f"古い{file_type}バックアップを削除: {old_file}")
                        except Exception as e:
                            self.logger.error(f"バックアップ削除エラー ({old_file}): {e}")

        except Exception as e:
            self.logger.error(f"バックアップクリーンアップエラー: {e}")

    @app_commands.command(name="register")
    async def register(self, interaction: discord.Interaction):
        """ウォレットを作成して登録"""
        await interaction.response.defer(ephemeral=True)
        
        db = SessionLocal()
        try:
            # チャンネルチェック
            if str(interaction.channel_id) != str(self.config.register_channel_id):
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        "⛔ チャンネルエラー",
                        "このコマンドは登録チャンネルでのみ使用できます"
                    )
                )
                return

            # 既存ユーザーチェック
            user = db.query(User).filter(User.discord_id == str(interaction.user.id)).first()
            if user and user.wallet:
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        "登録エラー",
                        "すでにウォレットが登録されています"
                    )
                )
                return

            # 新規ユーザー作成
            if not user:
                user = User(
                    discord_id=str(interaction.user.id),
                    created_at=datetime.now(),
                    message_count=0,
                    total_mined=0,
                    login_streak=0
                )
                db.add(user)
                db.flush()  # ユーザーIDを生成

            # ウォレット作成
            wallet_address = generate_wallet_address()
            wallet = Wallet(
                address=wallet_address,
                parc_balance=100,
                jpy_balance=100000,
                user=user
            )
            db.add(wallet)
            db.flush()  # ウォレットを先にコミット

            # 初期ボーナストランザクション作成
            bonus_tx = Transaction(
                to_address=wallet.address,
                amount=100,
                transaction_type="bonus",
                status="completed",
                timestamp=datetime.now()
            )
            db.add(bonus_tx)
            
            db.commit()

            # 結果表示
            embed = EmbedBuilder.success(
                "✅ ウォレット作成完了",
                "ウォレットが作成され、初期ボーナスが付与されました！"
            )
            embed.add_field(
                name="🔑 ウォレットアドレス", 
                value=f"`{wallet_address}`",
                inline=False
            )
            embed.add_field(
                name="🪙 PARC残高", 
                value="100 PARC",
                inline=True
            )
            embed.add_field(
                name="💴 日本円残高", 
                value="¥100,000",
                inline=True
            )
            
            await interaction.followup.send(embed=embed)

        except Exception as e:
            self.logger.error(f"Register error: {str(e)}", exc_info=True)
            db.rollback()
            await interaction.followup.send(
                embed=EmbedBuilder.error("エラー", "ウォレットの作成に失敗しました")
            )
        finally:
            db.close()

    @app_commands.command(name="daily", description="デイリーボーナスを受け取ります")
    async def daily(self, interaction: discord.Interaction):
        """デイリーボーナスの受け取り"""
        db = SessionLocal()
        try:
            # チャンネルチェック
            if str(interaction.channel_id) != str(self.config.daily_channel_id):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error(
                        "⛔ チャンネルエラー",
                        "このコマンドはhttps://discord.com/channels/1339125839954055230/1339846644547588176チャンネルでのみ使用できます"
                    ),
                    ephemeral=True
                )
                return

            # ユーザー情報取得
            user = db.query(User).filter(User.discord_id == str(interaction.user.id)).first()
            if not user or not user.wallet:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error(
                        "ウォレットが見つかりません",
                        "まずは /register でウォレットを作成してください"
                    ),
                    ephemeral=True
                )
                return

            # 最終ログイン日時チェック
            now = datetime.now()
            if user.last_daily:
                time_since_last = now - user.last_daily
                if time_since_last.days < 1:
                    next_daily = user.last_daily + timedelta(days=1)
                    await interaction.response.send_message(
                        embed=EmbedBuilder.error(
                            "まだ受け取れません",
                            f"次のデイリーボーナスは {next_daily.strftime('%Y-%m-%d %H:%M')} からです"
                        ),
                        ephemeral=True
                    )
                    return

            # ログインストリークチェック
            if user.last_daily and (now - user.last_daily).days == 1:
                user.login_streak += 1
                if user.login_streak > 7:
                    user.login_streak = 1
            else:
                user.login_streak = 1

            # ボーナス金額計算
            streak_bonus = {
                1: 100,  # 基本
                2: 150,  # +50
                3: 200,  # +100
                4: 250,  # +150
                5: 300,  # +200
                6: 350,  # +250
                7: 400,  # +300
            }
            bonus_amount = streak_bonus.get(user.login_streak, 100)

            # ボーナス付与
            user.last_daily = now
            user.wallet.parc_balance += bonus_amount

            # トランザクション記録
            tx = Transaction(
                to_address=user.wallet.address,
                amount=bonus_amount,
                transaction_type="daily_bonus",
                timestamp=now
            )
            db.add(tx)
            db.commit()

            # 結果表示
            embed = EmbedBuilder.success(
                "✨ デイリーボーナス獲得！",
                f"{interaction.user.mention} が {bonus_amount} PARC を獲得しました！"
            )
            embed.add_field(
                name="🔥 ログインストリーク",
                value=f"{user.login_streak}日目",
                inline=True
            )
            embed.add_field(
                name="💰 現在の残高",
                value=f"{user.wallet.parc_balance} PARC",
                inline=True
            )
            if user.login_streak < 7:
                embed.add_field(
                    name="📅 明日のボーナス",
                    value=f"{streak_bonus.get(user.login_streak + 1)} PARC",
                    inline=False
                )
            embed.set_footer(text=f"次回: {(now + timedelta(days=1)).strftime('%Y-%m-%d %H:%M')}")
            
            await interaction.response.send_message(embed=embed)

        except Exception as e:
            self.logger.error(f"Daily bonus error: {str(e)}", exc_info=True)
            db.rollback()
            await interaction.response.send_message(
                embed=EmbedBuilder.error("エラー", "ボーナスの受け取りに失敗しました"),
                ephemeral=True
            )
        finally:
            db.close()

    @app_commands.command(name="mine", description="チャット活動に応じてPARCを採掘します")
    @app_commands.guild_only()  # サーバー内でのみ使用可能
    async def mine(self, interaction: discord.Interaction):
        """マイニング実行"""
        # チャンネルチェック
        if str(interaction.channel_id) != str(self.config.mining_channel_id):
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "⛔ チャンネルエラー",
                    "このコマンドはhttps://discord.com/channels/1339125839954055230/1339128725463105536チャンネルでのみ使用できます"
                ),
                ephemeral=True
            )
            return

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.discord_id == str(interaction.user.id)).first()
            if not user or not user.wallet:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error(
                        "ウォレットが見つかりません",
                        "まずは /register でウォレットを作成してください"
                    ),
                    ephemeral=True
                )
                return

            # クールダウンチェック
            now = datetime.now()
            if user.last_mining:
                time_since_last = now - user.last_mining
                if time_since_last.total_seconds() < 86400:  # 24時間
                    next_mine = user.last_mining + timedelta(days=1)
                    await interaction.response.send_message(
                        embed=EmbedBuilder.error(
                            "⏳ 採掘クールダウン中",
                            f"次の採掘は {next_mine.strftime('%Y-%m-%d %H:%M')} からです"
                        ),
                        ephemeral=True
                    )
                    return

            # 現在のメッセージカウントを保存
            current_messages = user.message_count

            # 報酬計算
            base_reward = min(current_messages * 2, 1000)  # 上限1000PARC
            reward = base_reward

            # トランザクション記録
            tx = Transaction(
                to_address=user.wallet.address,
                amount=reward,
                transaction_type="mining",
                timestamp=now
            )
            db.add(tx)

            # ウォレットの残高を更新
            user.wallet.parc_balance += reward

            # ユーザー情報更新
            user.last_mining = now
            user.total_mined += reward

            # 統計情報更新
            daily_stat = db.query(DailyStats)\
                .filter(DailyStats.date == now.date())\
                .first()
            if daily_stat:
                daily_stat.total_mined += reward

            # 結果表示用の変数を保存
            display_message_count = current_messages

            # メッセージカウントをリセット
            user.message_count = 0

            db.commit()

            # マイニング成功時のみephemeral=False
            embed = EmbedBuilder.success(
                "⛏️ マイニング成功！",
                f"{reward:,} PARCを採掘しました！"
            )
            embed.add_field(
                name="💬 処理メッセージ数",
                value=f"{display_message_count:,}通",
                inline=True
            )
            embed.add_field(
                name="💰 現在の残高",
                value=f"{user.wallet.parc_balance:,} PARC",
                inline=True
            )
            embed.add_field(
                name="📊 累計採掘量",
                value=f"{user.total_mined:,} PARC",
                inline=True
            )

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            self.logger.error(f"Mining error: {str(e)}", exc_info=True)
            db.rollback()
            await interaction.response.send_message(
                embed=EmbedBuilder.error("エラー", "採掘に失敗しました"),
                ephemeral=True
            )
        finally:
            db.close()


    @app_commands.command(name="wallet", description="ウォレット情報を表示します")
    async def wallet(self, interaction: discord.Interaction):
        """ウォレット情報を表示"""
        await interaction.response.defer(ephemeral=True)
        
        db = SessionLocal()
        try:
            # トランザクションを明示的に開始
            with db.begin():
                # ユーザー情報取得（ウォレット情報も同時に取得）
                user = db.query(User).options(joinedload(User.wallet)).filter(
                    User.discord_id == str(interaction.user.id)
                ).first()

                if not user or not user.wallet:
                    await interaction.followup.send(
                        embed=EmbedBuilder.error(
                            "ウォレットが見つかりません",
                            "まずは /register でウォレットを作成してください"
                        )
                    )
                    return

                await self._display_wallet_info(interaction, user, db)

        except Exception as e:
            self.logger.error(f"Wallet command error: {e}", exc_info=True)
            db.rollback()
            await interaction.followup.send(
                embed=EmbedBuilder.error("エラー", "ウォレット情報の取得に失敗しました")
            )
        finally:
            db.close()

    async def _display_wallet_info(self, interaction: discord.Interaction, user: User, db: Session):
        """ウォレット情報の表示処理"""
        current_price = db.query(PriceHistory)\
            .order_by(PriceHistory.timestamp.desc())\
            .first()
        
        price = current_price.price if current_price else 100.0
        parc_value = math.floor(user.wallet.parc_balance * price)  # 小数点以下切り捨て
        total_value = parc_value + user.wallet.jpy_balance

        embed = discord.Embed(
            title="👛 ウォレット情報",
            description=f"アドレス: `{user.wallet.address}`",
            color=discord.Color.gold(),
            timestamp=datetime.now()
        )

        embed.add_field(
            name="🪙 PARC残高",
            value=f"`{user.wallet.parc_balance:,}` PARC\n(¥{parc_value:,})",  # 円換算値は整数表示
            inline=True
        )

        embed.add_field(
            name="💴 JPY残高",
            value=f"¥`{user.wallet.jpy_balance:,}`",  # 整数表示
            inline=True
        )

        embed.add_field(
            name="💰 総資産",
            value=f"¥`{total_value:,}`",  # 整数表示
            inline=False
        )

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="send", description="PARCを送金します")
    async def send(
        self,
        interaction: discord.Interaction,
        target: str,
        amount: int
    ):
        """PARC送金処理"""
        await interaction.response.defer(ephemeral=True)
        
        db = SessionLocal()
        try:
            # 送金元ユーザー情報取得
            sender = db.query(User).filter(
                User.discord_id == str(interaction.user.id)
            ).first()
            
            if not sender or not sender.wallet:
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        "ウォレットが見つかりません",
                        "まずは /register でウォレットを作成してください"
                    )
                )
                return

            # 送金先アドレスの特定
            to_address = None
            # メンション形式の場合
            if target.startswith('<@') and target.endswith('>'):
                discord_id = target[2:-1]
                if (discord_id.startswith('!')):
                    discord_id = discord_id[1:]
                recipient = db.query(User).filter(
                    User.discord_id == discord_id
                ).first()
                if recipient and recipient.wallet:
                    to_address = recipient.wallet.address
            # アドレス形式の場合
            else:
                wallet = db.query(Wallet).filter(
                    Wallet.address == target
                ).first()
                if wallet:
                    to_address = wallet.address

            if not to_address:
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        "送金先が見つかりません",
                        "有効なメンションまたはアドレスを指定してください"
                    )
                )
                return

            # 送金額チェック
            if amount <= 0:
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        "送金額エラー",
                        "送金額は1PARC以上を指定してください"
                    )
                )
                return

            # 残高チェック
            fee = math.ceil(amount * 0.001)  # 0.1%の手数料
            total = amount + fee
            
            if sender.wallet.parc_balance < total:
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        "残高不足",
                        f"必要金額: {total:,} PARC（手数料込み）\n"
                        f"残高: {sender.wallet.parc_balance:,} PARC"
                    )
                )
                return

            # トランザクション実行
            tx = Transaction(
                from_address=sender.wallet.address,
                to_address=to_address,
                amount=amount,
                fee=fee,
                transaction_type="transfer",
                timestamp=datetime.now(),
                status="completed"
            )
            db.add(tx)

            # 残高更新
            sender.wallet.parc_balance -= total
            recipient_wallet = db.query(Wallet).filter(
                Wallet.address == to_address
            ).first()
            recipient_wallet.parc_balance += amount

            db.commit()

            # インタラクション応答用のEmbed
            embed = discord.Embed(
                title="💸 送金完了",
                description=f"{amount:,} PARCを送金しました",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(
                name="📤 送金先",
                value=f"`{to_address}`",
                inline=False
            )
            embed.add_field(
                name="💰 手数料",
                value=f"{fee:,} PARC",
                inline=True
            )
            embed.add_field(
                name="💳 残高",
                value=f"{sender.wallet.parc_balance:,} PARC",
                inline=True
            )
            await interaction.followup.send(embed=embed)

            # 送金者へのDM通知
            try:
                sender_user = await self.bot.fetch_user(int(sender.discord_id))
                if sender_user:
                    recipient_name = f"<@{recipient_wallet.user.discord_id}>" if recipient_wallet.user else "Unknown"
                    sender_dm = discord.Embed(
                        title="📤 送金完了通知",
                        description=f"{amount:,} PARCの送金が完了しました",
                        color=discord.Color.green(),
                        timestamp=datetime.now()
                    )
                    sender_dm.add_field(
                        name="📫 送金先",
                        value=f"{recipient_name}\n`{to_address}`",
                        inline=False
                    )
                    sender_dm.add_field(
                        name="💸 取引内容",
                        value=(
                            f"送金額: {amount:,} PARC\n"
                            f"手数料: {fee:,} PARC\n"
                            f"合計: {total:,} PARC"
                        ),
                        inline=False
                    )
                    sender_dm.add_field(
                        name="💰 現在の残高",
                        value=f"{sender.wallet.parc_balance:,} PARC",
                        inline=False
                    )
                    sender_dm.set_footer(text="取引ID: " + str(tx.id))
                    await sender_user.send(embed=sender_dm)
            except Exception as e:
                self.logger.error(f"Failed to send DM to sender: {e}")

            # 受取人へのDM通知
            if recipient_wallet.user:
                try:
                    recipient_user = await self.bot.fetch_user(int(recipient_wallet.user.discord_id))
                    if recipient_user:
                        sender_name = f"<@{sender.discord_id}>"
                        embed = discord.Embed(
                            title="📥 入金通知",
                            description=f"{amount:,} PARCを受け取りました",
                            color=discord.Color.green(),
                            timestamp=datetime.now()
                        )
                        embed.add_field(
                            name="📤 送金元",
                            value=f"{sender_name}\n`{sender.wallet.address}`",
                            inline=False
                        )
                        embed.add_field(
                            name="💳 残高",
                            value=f"{recipient_wallet.parc_balance:,} PARC",
                            inline=True
                        )
                        await recipient_user.send(embed=embed)
                except Exception as e:
                    self.logger.error(f"Failed to send DM to recipient: {e}")

        except Exception as e:
            self.logger.error(f"Send error: {str(e)}", exc_info=True)
            db.rollback()
            await interaction.followup.send(
                embed=EmbedBuilder.error("エラー", "送金に失敗しました")
            )
        finally:
            db.close()

    @app_commands.command(name="history", description="取引履歴を表示します")
    @app_commands.describe(page="表示するページ番号")
    async def history(self, interaction: discord.Interaction, page: int = 1):
        """取引履歴の表示"""
        await interaction.response.defer(ephemeral=True)
        ITEMS_PER_PAGE = 5

        async def get_page_data(page_num: int) -> discord.Embed:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.discord_id == str(interaction.user.id)).first()
                transactions = db.query(Transaction)\
                    .filter(or_(
                        Transaction.from_address == user.wallet.address,
                        Transaction.to_address == user.wallet.address
                    ))\
                    .order_by(Transaction.timestamp.desc())\
                    .offset((page_num - 1) * ITEMS_PER_PAGE)\
                    .limit(ITEMS_PER_PAGE)\
                    .all()

                embed = discord.Embed(
                    title="📋 取引履歴",
                    color=discord.Color.blue(),
                    timestamp=datetime.now()
                )

                for tx in transactions:
                    is_send = tx.from_address == user.wallet.address
                    tx_type_map = {
                        "transfer": "💸 送金",
                        "mining": "⛏️ 採掘",
                        "daily_bonus": "🎁 デイリー",
                        "buy": "🛍️ 購入",
                        "sell": "💰 売却",
                        "fee": "💱 手数料",
                        "bonus": "🎯 ボーナス"
                    }
                    
                    title = f"{tx_type_map.get(tx.transaction_type, '❓ ' + tx.transaction_type)}"
                    
                    value = []
                    value.append(f"{'送信' if is_send else '受信'}: {tx.amount:,} PARC")
                    if tx.price:
                        value.append(f"価格: ¥{tx.price:,.2f}")
                    if tx.fee:
                        value.append(f"手数料: {tx.fee:,} PARC")
                    value.append(f"日時: {tx.timestamp.strftime('%Y/%m/%d %H:%M')}")
                    
                    addr = tx.to_address if is_send else tx.from_address
                    if addr:
                        value.append(f"相手: `{addr[:8]}...{addr[-6:]}`")

                    embed.add_field(
                        name=title,
                        value="\n".join(value),
                        inline=False
                    )

                total_tx = db.query(Transaction)\
                    .filter(or_(
                        Transaction.from_address == user.wallet.address,
                        Transaction.to_address == user.wallet.address
                    ))\
                    .count()
                total_pages = math.ceil(total_tx / ITEMS_PER_PAGE)
                embed.set_footer(text=f"📄 ページ {page_num}/{total_pages} • 全{total_tx}件の取引")

                return embed
            finally:
                db.close()

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.discord_id == str(interaction.user.id)).first()
            if not user or not user.wallet:
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        "🚫 ウォレットが見つかりません",
                        "まずは /register でウォレットを作成してください"
                    )
                )
                return

            total_tx = db.query(Transaction)\
                .filter(or_(
                    Transaction.from_address == user.wallet.address,
                    Transaction.to_address == user.wallet.address
                ))\
                .count()

            if total_tx == 0:
                await interaction.followup.send(
                    embed=EmbedBuilder.info(
                        "📭 取引履歴なし",
                        "まだ取引履歴がありません"
                    )
                )
                return

            total_pages = math.ceil(total_tx / ITEMS_PER_PAGE)
            embed = await get_page_data(page)
            view = HistoryPaginationView(page, total_pages, get_page_data)
            await interaction.followup.send(embed=embed, view=view)

        except Exception as e:
            self.logger.error(f"History error: {str(e)}", exc_info=True)
            await interaction.followup.send(
                embed=EmbedBuilder.error("エラー", "取引履歴の取得に失敗しました")
            )
        finally:
            db.close()

    @app_commands.command(name="market", description="現在の市場価格情報を表示")
    async def market(self, interaction: discord.Interaction):
        """現在の市場情報を表示"""
        await interaction.response.defer(ephemeral=True)  
        
        db = SessionLocal()
        try:
            # 最新の価格情報を取得
            latest_price = db.query(PriceHistory).order_by(PriceHistory.timestamp.desc()).first()
            
            # 最新の価格情報が取得できない場合のフォールバック
            if latest_price is None:
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        "データなし", 
                        "市場価格情報が見つかりません。取引時間外の可能性があります。\n\n"
                        "📌 **前場:** **9:00 ～ 11:30**\n"
                        "📌 **後場:** **12:30 ～ 15:30**"
                    )
                )
                return
            
            price_calculator = self.bot.price_calculator
            
            # 現在のランダム価格を取得
            random_prices = price_calculator.get_all_random_prices()
            current_random = price_calculator.get_latest_random_price()  # 最新のランダム価格を使用
 
            
            # 24時間の変動率を計算
            yesterday = datetime.now() - timedelta(days=1)
            day_before = db.query(PriceHistory).filter(
                PriceHistory.timestamp >= yesterday
            ).order_by(PriceHistory.timestamp.asc()).first()
            
            day_change = 0
            if day_before:
                day_change = ((latest_price.price - day_before.price) / day_before.price) * 100
            
            # 市場情報を作成（カスタマイズしたEmbedを直接作成）
            embed = discord.Embed(
                title="🪙 PARC/JPY マーケット情報",
                color=discord.Color.gold() if day_change >= 0 else discord.Color.red(),
                timestamp=datetime.now()
            )
            
            # 現在価格情報（大きく表示）
            embed.add_field(
                name="💰 現在価格",
                value=f"**¥{latest_price.price:,.2f}**",
                inline=False
            )
            
            # 24時間変動率
            change_emoji = "📈" if day_change >= 0 else "📉"
            embed.add_field(
                name=f"{change_emoji} 24時間変動",
                value=f"{day_change:+.2f}%",
                inline=True
            )
            
            # リアルタイム価格
            embed.add_field(
                name="⚡ リアルタイム価格",
                value=f"¥{current_random:,.2f}",
                inline=True
            )
            
            # 価格帯情報
            embed.add_field(
                name="⚖️ 価格帯",
                value=(
                    f"基準価格: **¥{price_calculator.base_price:,.2f}**\n"
                    f"最小: ¥{price_calculator.price_range['min']:,.2f}\n"
                    f"最大: ¥{price_calculator.price_range['max']:,.2f}"
                ),
                inline=False
            )
            
            # チャート情報
            embed.add_field(
                name="📊 チャート",
                value=(
                    "**リアルタイムチャート：** <#1346092959103455264>\n"
                    "**取引履歴チャート：** <#1339160503553097758>"
                ),
                inline=False
            )
            
            # 取引コマンド情報
            embed.add_field(
                name="📝 取引コマンド",
                value=(
                    "`/buy <数量> [価格]` - PARC購入\n"
                    "`/sell <数量> [価格]` - PARC売却\n"
                    "`/orders` - 注文一覧表示"
                ),
                inline=False
            )
            
            # フッター情報
            embed.set_footer(text="価格は10秒ごとに更新されます • ephemeral表示")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"市場情報表示エラー: {e}", exc_info=True)
            await interaction.followup.send(
                embed=EmbedBuilder.error("エラー", "市場情報の取得に失敗しました"),
                ephemeral=True
            )
        finally:
            db.close()

    @app_commands.command(name="alert", description="価格アラートを設定します")
    @app_commands.describe(
        price="アラート価格（JPY）",
        condition="条件（以上/以下）"
    )
    @app_commands.choices(condition=[
        Choice(name="以上", value="above"),
        Choice(name="以下", value="below")
    ])
    async def alert(
        self, 
        interaction: discord.Interaction,
        price: float,
        condition: str
    ):
        await interaction.response.defer(ephemeral=True)
        
        db = SessionLocal()
        try:
            with db.begin():
                user = db.query(User).filter(
                    User.discord_id == str(interaction.user.id)
                ).first()

                if not user:
                    await interaction.followup.send(
                        embed=EmbedBuilder.error(
                            "エラー",
                            "アカウントが見つかりません"
                        )
                    )
                    return

                # アラート件数チェック
                alert_count = db.query(PriceAlert).filter(
                    PriceAlert.user_id == user.id,
                    PriceAlert.active == True
                ).count()

                if alert_count >= 3:
                    await interaction.followup.send(
                        embed=EmbedBuilder.error(
                            "上限エラー",
                            "アラートは最大3件まで設定できます"
                        )
                    )
                    return

                # 現在価格を取得
                current_price = db.query(PriceHistory)\
                    .order_by(PriceHistory.timestamp.desc())\
                    .first()

                # アラート登録
                alert = PriceAlert(
                    user_id=user.id,
                    price=price,
                    condition=condition,
                    active=True,
                    created_at=datetime.now()
                )
                db.add(alert)
                db.flush()  # IDを生成するためにflush

                embed = discord.Embed(
                    title="⏰ アラート設定完了",
                    description=f"価格が¥{price:,.2f}を{'超えた' if condition == 'above' else '下回った'}時に通知します",
                    color=discord.Color.green()
                )
                embed.add_field(
                    name="📊 現在価格",
                    value=f"¥{current_price.price:,.2f}",
                    inline=True
                )
                embed.add_field(
                    name="🔔 アラートID",
                    value=str(alert.id),
                    inline=True
                )
                
                await interaction.followup.send(embed=embed)

        except Exception as e:
            self.logger.error(f"Alert error: {str(e)}", exc_info=True)
            db.rollback()
            await interaction.followup.send(
                embed=EmbedBuilder.error(
                    "エラー",
                    "アラートの設定に失敗しました"
                )
            )
        finally:
            db.close()

    @app_commands.command(name="buy", description="PARCを購入します")
    @app_commands.describe(
        amount="購入するPARCの数量",
        price="指値価格（指定しない場合は成行注文）"
    )
    async def buy(
        self,
        interaction: discord.Interaction,
        amount: float,
        price: float = None
    ):
        """PARC購入処理"""
        await interaction.response.defer(ephemeral=True)
        db = SessionLocal()

        try:
            # 取引時間外の場合、指値注文以外は拒否
            if not TradingHours.is_trading_hours() and price is None:
                session_name = TradingHours.get_session_name()
                next_event_type, next_event_time = TradingHours.get_next_event()
                minutes_to_next = TradingHours.get_minutes_to_next_event()
                
                next_session_text = "前場開始" if "morning_start" in next_event_type else \
                                "後場開始" if "afternoon_start" in next_event_type else \
                                "明日の前場開始"
                
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        "取引時間外エラー",
                        f"現在は{session_name}です。取引時間外は指値注文のみ可能です。\n"
                        f"成行注文は取引時間内にお願いします。\n\n"
                        f"📌 **前場:** **9:00 ～ 11:30**\n"
                        f"📌 **後場:** **12:30 ～ 15:30**\n\n"
                        f"次の取引開始: {next_event_time.strftime('%H:%M')}（あと約{minutes_to_next}分）"
                    )
                )
                return

            # ユーザー情報の確認
            user = db.query(User).filter(User.discord_id == str(interaction.user.id)).first()
            if not user or not user.wallet:
                await interaction.followup.send(
                    embed=EmbedBuilder.error("エラー", "ウォレットが見つかりません")
                )
                return

            # 数量を丸める
            amount = round(amount, 2)
            
            # リアルタイムチャート価格を取得
            price_calculator = self.bot.price_calculator
            price_info = price_calculator.get_price_range_for_trading()
            current_market_price = price_info['current']
            
            order_price = price if price else current_market_price
            total_cost = math.floor(amount * order_price)

            # 最小取引額チェック
            if total_cost < 1:
                await interaction.followup.send(
                    embed=EmbedBuilder.error("注文エラー", "取引金額が1円未満になる注文は出せません")
                )
                return

            if price is None:  # 成行注文
                fee = math.ceil(total_cost * 0.001)  # 0.1%の手数料
                total_with_fee = total_cost + fee

                # 残高チェック
                if user.wallet.jpy_balance < total_with_fee:
                    await interaction.followup.send(
                        embed=EmbedBuilder.error(
                            "残高不足",
                            f"必要金額: ¥{total_with_fee:,.0f}（手数料込み）\n"
                            f"残高: ¥{user.wallet.jpy_balance:,.0f}"
                        )
                    )
                    return

                # 残高更新
                user.wallet.jpy_balance -= total_with_fee
                user.wallet.parc_balance += amount

                # 取引トランザクションを記録
                transaction = Transaction(
                    from_address=None,
                    to_address=user.wallet.address,
                    amount=amount,
                    fee=fee,
                    price=current_market_price,
                    timestamp=datetime.now(),
                    transaction_type="buy",
                    order_type="market",
                    status="completed"
                )
                db.add(transaction)
                db.flush()  # トランザクションIDを取得するためにflush

                # トランザクションIDをハッシュのように表示
                tx_id = f"0x{transaction.id:x}{uuid.uuid4().hex[:8]}"

                # 結果表示用のEmbed作成
                embed = discord.Embed(
                    title="✅ 購入が完了しました",
                    description=f"{amount:,} PARC を購入しました",
                    color=discord.Color.green(),
                    timestamp=datetime.now()
                )

                embed.add_field(
                    name="💰 取引詳細",
                    value=(
                        f"数量: {amount:,} PARC\n"
                        f"単価: ¥{current_market_price:,.2f}/PARC\n"
                        f"合計: ¥{total_cost:,}\n"
                        f"手数料: ¥{fee:,}"
                    ),
                    inline=False
                )

                # 価格情報を追加
                embed.add_field(
                    name="💹 取引価格情報",
                    value=(
                        f"取引価格: ¥{current_market_price:,.2f}/PARC\n"
                        f"基準価格: ¥{price_info['base']:,.2f}\n"
                        f"変動率: {price_info['change']:+.2f}%"
                    ),
                    inline=False
                )

                embed.add_field(
                    name="💳 新しい残高",
                    value=(
                        f"PARC: {user.wallet.parc_balance:,}\n"
                        f"JPY: ¥{user.wallet.jpy_balance:,}"
                    ),
                    inline=False
                )

                embed.add_field(
                    name="📝 トランザクション",
                    value=f"`{tx_id}`",
                    inline=False
                )

            else:  # 指値注文
                if price <= 0:
                    await interaction.followup.send(
                        embed=EmbedBuilder.error("エラー", "指値価格は0より大きい値を指定してください")
                    )
                    return

                # 指値価格が適正範囲内かチェック
                if price < price_info['min'] * 0.5 or price > price_info['max'] * 1.5:
                    await interaction.followup.send(
                        embed=EmbedBuilder.error(
                            "価格が範囲外です",
                            f"価格は ¥{price_info['min'] * 0.5:,.2f} から ¥{price_info['max'] * 1.5:,.2f} の範囲で指定してください"
                        )
                    )
                    return

                limit_cost = math.floor(amount * price)
                limit_fee = math.ceil(limit_cost * 0.001)  # 0.1%の手数料
                limit_total = limit_cost + limit_fee

                if user.wallet.jpy_balance < limit_total:
                    await interaction.followup.send(
                        embed=EmbedBuilder.error(
                            "残高不足",
                            f"必要金額: ¥{limit_total:,.0f}（手数料込み）\n"
                            f"残高: ¥{user.wallet.jpy_balance:,.0f}"
                        )
                    )
                    return

                # 指値注文の作成
                order = Order(
                    wallet_address=user.wallet.address,
                    amount=amount,
                    price=price,
                    timestamp=datetime.now(),
                    order_type="limit",
                    side="buy",
                    status="pending"
                )
                db.add(order)
                db.flush()  # OrderIDを取得するためにflush
                
                # 残高の更新
                user.wallet.jpy_balance -= limit_total
                
                # 注文IDをハッシュのように表示
                order_id = f"0x{order.id:x}{uuid.uuid4().hex[:8]}"

                # 結果表示用のEmbed作成
                embed = discord.Embed(
                    title="📝 指値注文を受付けました",
                    description=f"{amount:,} PARC の購入注文",
                    color=discord.Color.blue(),
                    timestamp=datetime.now()
                )

                embed.add_field(
                    name="💰 注文詳細",
                    value=(
                        f"数量: {amount:,} PARC\n"
                        f"指値: ¥{price:,.2f}/PARC\n"
                        f"予定金額: ¥{math.floor(amount * price):,}\n"
                        f"手数料(予定): ¥{math.ceil(math.floor(amount * price) * 0.001):,}"
                    ),
                    inline=False
                )

                # 現在価格情報を追加
                embed.add_field(
                    name="💹 現在の市場情報",
                    value=(
                        f"現在価格: ¥{current_market_price:,.2f}/PARC\n"
                        f"基準価格: ¥{price_info['base']:,.2f}\n"
                        f"変動幅: ¥{price_info['min']:,.2f}～¥{price_info['max']:,.2f}"
                    ),
                    inline=False
                )

                embed.add_field(
                    name="💳 現在の残高",
                    value=(
                        f"PARC: {user.wallet.parc_balance:,}\n"
                        f"JPY: ¥{user.wallet.jpy_balance:,}"
                    ),
                    inline=False
                )

                embed.add_field(
                    name="📝 注文ID",
                    value=f"`{order_id}`",
                    inline=False
                )
                
            # 変更をコミットしてメッセージを送信
            db.commit()
            await interaction.followup.send(embed=embed)

        except Exception as e:
            self.logger.error(f"Buy error: {str(e)}", exc_info=True)
            db.rollback()
            await interaction.followup.send(
                embed=EmbedBuilder.error("エラー", "購入に失敗しました")
            )
        finally:
            db.close()

    @app_commands.command(name="sell", description="保有しているPARCを売却します")
    @app_commands.describe(
        amount="売却するPARCの数量",
        price="指値価格（指定しない場合は成行注文）"
    )
    async def sell(
        self,
        interaction: discord.Interaction,
        amount: float,
        price: float = None
    ):
        """PARCの売却処理"""
        await interaction.response.defer(ephemeral=True)
        db = SessionLocal()

        try:
            # 取引時間外の場合、指値注文以外は拒否
            if not TradingHours.is_trading_hours() and price is None:
                session_name = TradingHours.get_session_name()
                next_event_type, next_event_time = TradingHours.get_next_event()
                minutes_to_next = TradingHours.get_minutes_to_next_event()
                
                next_session_text = "前場開始" if "morning_start" in next_event_type else \
                                "後場開始" if "afternoon_start" in next_event_type else \
                                "明日の前場開始"
                
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        "取引時間外エラー",
                        f"現在は{session_name}です。取引時間外は指値注文のみ可能です。\n"
                        f"成行注文は取引時間内にお願いします。\n\n"
                        f"📌 **前場:** **9:00 ～ 11:30**\n"
                        f"📌 **後場:** **12:30 ～ 15:30**\n\n"
                        f"次の取引開始: {next_event_time.strftime('%H:%M')}（あと約{minutes_to_next}分）"
                    )
                )
                return

            # ユーザー情報確認
            user = db.query(User).filter(User.discord_id == str(interaction.user.id)).first()
            if not user or not user.wallet:
                await interaction.followup.send(
                    embed=EmbedBuilder.error("エラー", "ウォレットが見つかりません")
                )
                return

            # 最小取引量チェック
            if amount < 0.01:
                await interaction.followup.send(
                    embed=EmbedBuilder.error("注文エラー", "最小取引量は0.01 PARCです")
                )
                return

            amount = round(amount, 2)

            # 残高チェック
            if amount > user.wallet.parc_balance:
                await interaction.followup.send(
                    embed=EmbedBuilder.error("エラー", "残高が不足しています")
                )
                return

            # リアルタイムチャート価格を取得
            price_calculator = self.bot.price_calculator
            price_info = price_calculator.get_price_range_for_trading()
            current_market_price = price_info['current']

            if price is None:  # 成行注文の場合
                # 売却金額の計算
                sale_amount = math.floor(amount * current_market_price)
                fee = math.ceil(sale_amount * 0.001)  # 0.1%の手数料
                total_amount = sale_amount - fee

                # 残高更新
                user.wallet.parc_balance -= amount
                user.wallet.jpy_balance += total_amount

                # 売却トランザクションを記録
                sell_tx = Transaction(
                    from_address=user.wallet.address,
                    amount=amount,
                    price=current_market_price,
                    fee=fee,
                    transaction_type="sell",
                    timestamp=datetime.now(),
                    status="completed"
                )
                db.add(sell_tx)
                db.flush()  # トランザクションIDを取得するためにflush

                # トランザクションIDをハッシュのように表示
                tx_id = f"0x{sell_tx.id:x}{uuid.uuid4().hex[:8]}"

                # 手数料トランザクションを記録
                fee_tx = Transaction(
                    from_address=user.wallet.address,
                    amount=fee,
                    transaction_type="fee",
                    timestamp=datetime.now()
                )
                db.add(fee_tx)
                db.commit()

                # ゲームクリアチェック
                try:
                    events_cog = self.bot.get_cog("ParaccoliEvents")
                    if events_cog:
                        await events_cog.check_game_clear(
                            interaction.user.id,
                            current_market_price,
                            db
                        )
                except Exception as e:
                    self.logger.error(f"Game clear check error: {str(e)}")

                # 結果表示用のEmbed作成
                embed = discord.Embed(
                    title="💰 売却が完了しました",
                    description=f"{amount:,} PARC を売却しました",
                    color=discord.Color.green(),
                    timestamp=datetime.now()
                )

                embed.add_field(
                    name="💰 取引詳細",
                    value=(
                        f"数量: {amount:,} PARC\n"
                        f"単価: ¥{current_market_price:,.2f}/PARC\n"
                        f"売却額: ¥{sale_amount:,}\n"
                        f"手数料: ¥{fee:,}\n"
                        f"受取金額: ¥{total_amount:,}"
                    ),
                    inline=False
                )

                # 価格情報を追加
                embed.add_field(
                    name="💹 取引価格情報",
                    value=(
                        f"取引価格: ¥{current_market_price:,.2f}/PARC\n"
                        f"基準価格: ¥{price_info['base']:,.2f}\n"
                        f"変動率: {price_info['change']:+.2f}%"
                    ),
                    inline=False
                )

                embed.add_field(
                    name="💳 新しい残高",
                    value=(
                        f"PARC: {user.wallet.parc_balance:,}\n"
                        f"JPY: ¥{user.wallet.jpy_balance:,}"
                    ),
                    inline=False
                )

                embed.add_field(
                    name="📝 トランザクション",
                    value=f"`{tx_id}`",
                    inline=False
                )

                await interaction.followup.send(embed=embed)

            else:  # 指値注文の場合
                # 指値価格チェック
                if price <= 0:
                    await interaction.followup.send(
                        embed=EmbedBuilder.error("エラー", "指値価格は0より大きい値を指定してください")
                    )
                    return

                # 指値価格が適正範囲内かチェック
                if price < price_info['min'] * 0.5 or price > price_info['max'] * 1.5:
                    await interaction.followup.send(
                        embed=EmbedBuilder.error(
                            "価格が範囲外です",
                            f"価格は ¥{price_info['min'] * 0.5:,.2f} から ¥{price_info['max'] * 1.5:,.2f} の範囲で指定してください"
                        )
                    )
                    return

                # 指値注文の作成
                order = Order(
                    wallet_address=user.wallet.address,
                    amount=amount,
                    price=price,
                    timestamp=datetime.now(),
                    order_type="limit",
                    side="sell",
                    status="pending"
                )

                # PARCをロック
                user.wallet.parc_balance -= amount

                db.add(order)
                db.flush()  # OrderIDを取得するためにflush
                
                # 注文IDをハッシュのように表示
                order_id = f"0x{order.id:x}{uuid.uuid4().hex[:8]}"

                # 変更をコミット
                db.commit()

                # 結果表示用のEmbed作成
                embed = discord.Embed(
                    title="📝 指値注文を受付けました",
                    description=f"{amount:,} PARC の売却注文",
                    color=discord.Color.blue(),
                    timestamp=datetime.now()
                )

                embed.add_field(
                    name="💰 注文詳細",
                    value=(
                        f"数量: {amount:,} PARC\n"
                        f"指値: ¥{price:,.2f}/PARC\n"
                        f"予定売却額: ¥{math.floor(amount * price):,}\n"
                        f"手数料(予定): ¥{math.ceil(math.floor(amount * price) * 0.001):,}"
                    ),
                    inline=False
                )

                # 現在価格情報を追加
                embed.add_field(
                    name="💹 現在の市場情報",
                    value=(
                        f"現在価格: ¥{current_market_price:,.2f}/PARC\n"
                        f"基準価格: ¥{price_info['base']:,.2f}\n"
                        f"変動幅: ¥{price_info['min']:,.2f}～¥{price_info['max']:,.2f}"
                    ),
                    inline=False
                )

                embed.add_field(
                    name="💳 現在の残高",
                    value=(
                        f"PARC: {user.wallet.parc_balance:,}\n"
                        f"JPY: ¥{user.wallet.jpy_balance:,}"
                    ),
                    inline=False
                )

                embed.add_field(
                    name="📝 注文ID",
                    value=f"`{order_id}`",
                    inline=False
                )

                await interaction.followup.send(embed=embed)

        except Exception as e:
            self.logger.error(f"Sell error: {str(e)}", exc_info=True)
            db.rollback()
            await interaction.followup.send(
                embed=EmbedBuilder.error("エラー", "売却に失敗しました")
            )
        finally:
            db.close()

    @app_commands.command(name="alerts", description="設定中のアラート一覧を表示します")
    async def alerts(self, interaction: discord.Interaction):
        """アラート一覧表示"""
        await interaction.response.defer(ephemeral=True)
        
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.discord_id == str(interaction.user.id)).first()
            if not user:
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        "エラー", 
                        "ユーザーが見つかりません"
                    )
                )
                return

            # アクティブなアラート取得
            alerts = db.query(PriceAlert)\
                .filter(
                    PriceAlert.user_id == user.id,
                    PriceAlert.active == True
                )\
                .all()

            if not alerts:
                await interaction.followup.send(
                    embed=EmbedBuilder.info(
                        "アラートなし",
                        "設定中のアラートはありません"
                    )
                )
                return

            # 現在価格を取得
            current_price = db.query(PriceHistory)\
                .order_by(PriceHistory.timestamp.desc())\
                .first()
            
            price = current_price.price if current_price else 100.0

            embed = discord.Embed(
                title="🔔 アラート一覧",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )

            for alert in alerts:
                condition_text = "以上" if alert.condition == "above" else "以下"
                embed.add_field(
                    name=f"アラート #{alert.id}",
                    value=(
                        f"価格: ¥{alert.price:,.2f} {condition_text}\n"
                        f"設定日時: {alert.created_at.strftime('%Y/%m/%d %H:%M')}"
                    ),
                    inline=False
                )

            embed.set_footer(text=f"現在価格: ¥{price:,.2f}")
            await interaction.followup.send(embed=embed)

        except Exception as e:
            self.logger.error(f"Alerts list error: {str(e)}", exc_info=True)
            await interaction.followup.send(
                embed=EmbedBuilder.error("エラー", "アラート一覧の取得に失敗しました")
            )
        finally:
            db.close()

    @app_commands.command(name="alert_delete", description="アラートを削除します")
    @app_commands.describe(alert_id="削除するアラートID")
    async def alert_delete(self, interaction: discord.Interaction, alert_id: int):
        """アラート削除処理"""
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.discord_id == str(interaction.user.id)).first()
            if not user:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("エラー", "ユーザーが見つかりません"),
                    ephemeral=True
                )
                return

            # アラート取得
            alert = db.query(PriceAlert)\
                .filter(
                    PriceAlert.id == alert_id,
                    PriceAlert.user_id == user.id,
                    PriceAlert.active == True
                )\
                .first()

            if not alert:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error(
                        "アラートが見つかりません",
                        "指定されたIDのアラートは存在しないか、既に削除されています"
                    ),
                    ephemeral=True
                )
                return

            # アラート削除
            alert.active = False
            db.commit()

            await interaction.response.send_message(
                embed=EmbedBuilder.success(
                    "✅ アラート削除完了",
                    f"アラートID: {alert_id} を削除しました"
                ),
                ephemeral=True
            )

        except Exception as e:
            self.logger.error(f"Alert delete error: {str(e)}", exc_info=True)
            db.rollback()
            await interaction.response.send_message(
                embed=EmbedBuilder.error("エラー", "アラートの削除に失敗しました"),
                ephemeral=True
            )
        finally:
            db.close()

    @app_commands.command(name="stats", description="システム全体の統計情報を表示します")
    async def stats(self, interaction: discord.Interaction):
        """システム統計情報の表示"""
        await interaction.response.defer(ephemeral=True)
        
        db = SessionLocal()
        try:
            # 基本統計情報
            total_users = db.query(func.count(User.id)).scalar() or 0
            total_wallets = db.query(func.count(Wallet.id)).scalar() or 0
            total_supply = db.query(func.sum(Wallet.parc_balance)).scalar() or 0
            
            # 現在価格を取得
            current_price = db.query(PriceHistory)\
                .order_by(PriceHistory.timestamp.desc())\
                .first()
            price = current_price.price if current_price else 100.0

            # 取引統計
            yesterday = datetime.now() - timedelta(days=1)
            volume_24h = db.query(func.sum(Transaction.amount))\
                .filter(
                    Transaction.timestamp >= yesterday,
                    Transaction.transaction_type.in_(['buy', 'sell'])
                ).scalar() or 0

            # システム稼働時間
            uptime = datetime.now() - self.start_time
            days, remainder = divmod(uptime.total_seconds(), 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime_str = f"{int(days)}日 {int(hours)}時間 {int(minutes)}分"
            
            # 最高値・最安値（全期間）
            all_time_high = db.query(func.max(PriceHistory.price)).scalar() or price
            all_time_low = db.query(func.min(PriceHistory.price)).scalar() or price
            
            # 総取引件数
            total_transactions = db.query(func.count(Transaction.id)).scalar() or 0
            
            # 注文情報
            pending_orders = db.query(func.count(Order.id))\
                .filter(Order.status == 'pending')\
                .scalar() or 0
            
            # システム採掘情報
            total_mined = db.query(func.sum(User.total_mined)).scalar() or 0
            
            # 最もアクティブなユーザー（メッセージ数ベース）
            most_active_user = db.query(User)\
                .order_by(User.message_count.desc())\
                .first()
            
            # 統計情報を表示
            embed = discord.Embed(
                title="📊 システム統計",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )

            # システム情報
            version = getattr(self.config, "version", "1.0.0")  # デフォルト値を設定
            embed.add_field(
                name="🖥️ システム情報",
                value=(
                    f"稼働時間: {uptime_str}\n"
                    f"バージョン: v{version}\n"
                    f"Python: {platform.python_version()}"
                ),
                inline=False
            )

            # ユーザー情報
            embed.add_field(
                name="👥 ユーザー統計",
                value=(
                    f"総ユーザー数: {total_users:,}\n"
                    f"総ウォレット数: {total_wallets:,}\n"
                    f"最もアクティブ: <@{most_active_user.discord_id}> ({most_active_user.message_count:,}メッセージ)" if most_active_user else "データなし"
                ),
                inline=False
            )

            # 価格情報
            embed.add_field(
                name="💰 価格情報",
                value=(
                    f"現在価格: ¥{price:,.2f}\n"
                    f"史上最高値: ¥{all_time_high:,.2f}\n"
                    f"史上最安値: ¥{all_time_low:,.2f}\n"
                    f"時価総額: ¥{total_supply * price:,.0f}" if isinstance(total_supply, float) else f"時価総額: ¥{float(total_supply) * price:,.0f}"
                ),
                inline=False
            )

            # 取引情報
            embed.add_field(
                name="📈 取引統計",
                value=(
                    f"24時間取引量: {volume_24h:,} PARC\n"
                    f"総取引件数: {total_transactions:,}件\n"
                    f"未約定注文数: {pending_orders:,}件\n"
                    f"総採掘量: {total_mined:,} PARC ({float(total_mined) * price:,.0f}円相当)"  # total_minedをfloatに変換
                ),
                inline=False
            )

            # 発行情報
            max_supply = self.config.max_supply
            circulating_percent = (float(total_supply) / max_supply) * 100 if max_supply > 0 else 0  # total_supplyもfloatに変換
            
            embed.add_field(
                name="🪙 発行情報",
                value=(
                    f"総発行量: {total_supply:,} PARC\n"
                    f"最大発行量: {max_supply:,} PARC\n"
                    f"発行率: {circulating_percent:.2f}%"
                ),
                inline=False
            )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Stats error: {str(e)}", exc_info=True)
            await interaction.followup.send(
                embed=EmbedBuilder.error("エラー", "統計情報の取得に失敗しました")
            )
        finally:
            db.close()

    @app_commands.command(name="form", description="開発者へ問い合わせを送信します")
    @app_commands.describe(
        category="問い合わせカテゴリ",
        content="問い合わせ内容"
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="バグ報告", value="bug"),
        app_commands.Choice(name="機能提案", value="feature"),
        app_commands.Choice(name="質問", value="question"),
        app_commands.Choice(name="その他", value="other")
    ])
    async def form(
        self,
        interaction: Interaction,
        category: str,
        content: str
    ):
        """問い合わせフォーム処理"""
        await interaction.response.defer(ephemeral=True)
        
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.discord_id == str(interaction.user.id)).first()
            if not user:
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        "エラー",
                        "ユーザー登録が必要です"
                    )
                )
                return

            category_map = {
                "bug": "🐛 バグ報告",
                "feature": "💡 機能提案",
                "question": "❓ 質問",
                "other": "📝 その他"
            }

            # 管理者へDM送信
            try:
                admin_user = await self.bot.fetch_user(DISCORD_ADMIN_USER_ID)
                if admin_user:
                    admin_embed = Embed(
                        title=f"📨 新規問い合わせ",
                        color=Color.blue(),
                        timestamp=datetime.now()
                    )
                    admin_embed.add_field(
                        name="カテゴリ",
                        value=category_map[category],
                        inline=True
                    )
                    admin_embed.add_field(
                        name="送信者",
                        value=f"{interaction.user.name}#{interaction.user.discriminator}\n(ID: {interaction.user.id})",
                        inline=True
                    )
                    admin_embed.add_field(
                        name="問い合わせ内容",
                        value=content,
                        inline=False
                    )
                    await admin_user.send(embed=admin_embed)
            except Exception as e:
                self.logger.error(f"Failed to send DM to admin: {e}")

            # 送信者への確認
            confirm_embed = EmbedBuilder.success(
                "✅ 問い合わせ送信完了",
                "開発チームに送信しました。回答をお待ちください。"
            )
            confirm_embed.add_field(
                name="カテゴリ",
                value=category_map[category],
                inline=True
            )
            confirm_embed.add_field(
                name="送信日時",
                value=datetime.now().strftime("%Y/%m/%d %H:%M"),
                inline=True
            )
            confirm_embed.add_field(
                name="問い合わせ内容",
                value=content[:1000] + ("..." if len(content) > 1000 else ""),
                inline=False
            )

            await interaction.followup.send(embed=confirm_embed)

        except Exception as e:
            self.logger.error(f"Form error: {e}", exc_info=True)
            await interaction.followup.send(
                embed=EmbedBuilder.error(
                    "エラー",
                    "問い合わせの送信に失敗しました"
                )
            )
        finally:
            db.close()

    @app_commands.command(name="orders", description="指値注文一覧を表示します")
    async def orders(self, interaction: discord.Interaction):
        """指値注文一覧表示"""
        await interaction.response.defer(ephemeral=True)
        
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.discord_id == str(interaction.user.id)).first()
            if not user or not user.wallet:
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        "ウォレットが見つかりません",
                        "まずは /register でウォレットを作成してください"
                    )
                )
                return

            # 現在の注文を取得
            orders = db.query(Order)\
                .filter(
                    Order.wallet_address == user.wallet.address,
                    Order.status == 'pending'
                )\
                .order_by(Order.timestamp.desc())\
                .all()

            if not orders:
                await interaction.followup.send(
                    embed=EmbedBuilder.info(
                        "注文なし",
                        "未約定の注文はありません"
                    )
                )
                return

            # 現在価格を取得
            current_price = db.query(PriceHistory)\
                .order_by(PriceHistory.timestamp.desc())\
                .first()
            price = current_price.price if current_price else 100.0

            # 注文一覧を表示
            embed = discord.Embed(
                title="📝 未約定の注文一覧",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )

            for order in orders:
                side = "買い" if order.side == "buy" else "売り"
                embed.add_field(
                    name=f"注文 #{order.id}",
                    value=(
                        f"{side}注文: {order.amount:,} PARC\n"
                        f"指値: ¥{order.price:,.2f}\n"
                        f"日時: {order.timestamp.strftime('%Y/%m/%d %H:%M')}"
                    ),
                    inline=False
                )

            embed.set_footer(text=f"現在価格: ¥{price:,.2f}")
            await interaction.followup.send(embed=embed)

        except Exception as e:
            self.logger.error(f"Orders error: {str(e)}", exc_info=True)
            await interaction.followup.send(
                embed=EmbedBuilder.error("エラー", "注文一覧の取得に失敗しました")
            )
        finally:
            db.close()

    @app_commands.command(name="cancel", description="指値注文をキャンセルします")
    @app_commands.describe(
        order_ids="キャンセルする注文ID（複数の場合はカンマ区切り）"
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        order_ids: str
    ):
        """注文キャンセル処理"""
        db = SessionLocal()
        try:
            # ユーザー情報取得
            user = db.query(User).filter(User.discord_id == str(interaction.user.id)).first()
            if not user or not user.wallet:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error(
                        "ウォレットが見つかりません",
                        "まずは /register でウォレットを作成してください"
                    ),
                    ephemeral=True
                )
                return

            # 注文IDをリストに変換
            id_list = [int(id.strip()) for id in order_ids.split(',')]
            
            # 注文情報取得 - ここを'pending'に修正
            orders = db.query(Order)\
                .filter(
                    Order.id.in_(id_list),
                    Order.wallet_address == user.wallet.address,
                    Order.status == 'pending'  # 'open'から'pending'に修正
                )\
                .all()

            if not orders:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error(
                        "注文が見つかりません",
                        "指定された注文IDが見つからないか、既にキャンセル/約定済みです"
                    ),
                    ephemeral=True
                )
                return

            # キャンセル処理
            cancelled_orders = []
            for order in orders:
                # 残高返却
                if order.side == "buy":
                    total_cost = order.amount * order.price
                    fee = math.ceil(total_cost * 0.001)
                    user.wallet.jpy_balance += total_cost + fee
                else:
                    user.wallet.parc_balance += order.amount

                order.status = "cancelled"
                cancelled_orders.append(order)

            db.commit()

            # 結果通知
            embed = EmbedBuilder.success(
                "✅ 注文キャンセル完了",
                f"{len(cancelled_orders)}件の注文をキャンセルしました"
            )

            for order in cancelled_orders:
                embed.add_field(
                    name=f"📝 注文 #{order.id}",
                    value=(
                        f"{'買い' if order.side == 'buy' else '売り'} "
                        f"{order.amount:,} PARC @ ¥{order.price:,.2f}"
                    ),
                    inline=False
                )

            embed.add_field(
                name="💳 現在の残高",
                value=(
                    f"PARC: {user.wallet.parc_balance:,}\n"
                    f"JPY: ¥{user.wallet.jpy_balance:,}"
                ),
                inline=False
            )

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except ValueError:
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "入力エラー",
                    "注文IDは数字（カンマ区切り）で入力してください"
                ),
                ephemeral=True
            )
        except Exception as e:
            self.logger.error(f"Cancel error: {str(e)}", exc_info=True)
            db.rollback()
            await interaction.response.send_message(
                embed=EmbedBuilder.error("エラー", "注文のキャンセルに失敗しました"),
                ephemeral=True
            )
        finally:
            db.close()

    @app_commands.command(name="rich", description="PARC/JPY保有ランキングを表示します")
    async def rich(self, interaction: discord.Interaction):
        """資産ランキングの表示"""
        await interaction.response.defer(ephemeral=True)
        
        db = SessionLocal()
        try:
            # 現在価格を取得
            current_price = db.query(PriceHistory)\
                .order_by(PriceHistory.timestamp.desc())\
                .first()
            price = current_price.price if current_price else 100.0

            # PARC保有ランキング取得
            parc_ranking = db.query(User, Wallet)\
                .join(Wallet)\
                .filter(Wallet.parc_balance > 0)\
                .order_by(Wallet.parc_balance.desc())\
                .limit(3)\
                .all()

            # JPY保有ランキング取得
            jpy_ranking = db.query(User, Wallet)\
                .join(Wallet)\
                .filter(Wallet.jpy_balance > 0)\
                .order_by(Wallet.jpy_balance.desc())\
                .limit(3)\
                .all()

            # Embed作成
            embed = discord.Embed(
                title="🏆 資産ランキング",
                color=discord.Color.gold(),
                timestamp=datetime.now()
            )

            # PARC保有ランキング表示
            parc_ranking_text = []
            for i, (user, wallet) in enumerate(parc_ranking, 1):
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉"
                value_jpy = wallet.parc_balance * price
                parc_ranking_text.append(
                    f"{medal} <@{user.discord_id}>\n"
                    f"└ {wallet.parc_balance:,} PARC (¥{value_jpy:,.0f})"
                )

            embed.add_field(
                name="🪙 PARCクジラランキング",
                value="\n".join(parc_ranking_text) if parc_ranking_text else "データなし",
                inline=False
            )

            # JPY保有ランキング表示
            jpy_ranking_text = []
            for i, (user, wallet) in enumerate(jpy_ranking, 1):
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉"
                jpy_ranking_text.append(
                    f"{medal} <@{user.discord_id}>\n"
                    f"└ ¥{wallet.jpy_balance:,}"
                )

            embed.add_field(
                name="💴 JPYクジラランキング",
                value="\n".join(jpy_ranking_text) if jpy_ranking_text else "データなし",
                inline=False
            )

            embed.set_footer(text=f"現在価格: ¥{price:,.2f}")
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Rich ranking error: {str(e)}", exc_info=True)
            await interaction.followup.send(
                embed=EmbedBuilder.error(
                    "エラー",
                    "ランキングの取得に失敗しました"
                )
            )
        finally:
            db.close()

    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.command(name="admin_end", description="管理者専用コマンド")
    async def admin_end(self, interaction: discord.Interaction):
        """Bot終了処理"""
        # 管理者のみ実行可能
        if str(interaction.user.id) != str(DISCORD_ADMIN_USER_ID):
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "権限エラー", 
                    "このコマンドは管理者のみ使用できます"
                ),
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            # 現在時刻
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # バックアップディレクトリ
            backup_dir = os.path.join('backup', timestamp)
            os.makedirs(backup_dir, exist_ok=True)
            
            # データベースのバックアップ
            db_file = 'paraccoli.db'
            db_backup = os.path.join(backup_dir, 'paraccoli.db')
            if os.path.exists(db_file):
                shutil.copy2(db_file, db_backup)
            
            # チャートのバックアップ
            chart_files = glob.glob('temp/*.png')
            chart_backup = None
            if (chart_files):
                chart_dir = os.path.join(backup_dir, 'charts')
                os.makedirs(chart_dir, exist_ok=True)
                for chart in chart_files:
                    shutil.copy2(chart, os.path.join(chart_dir, os.path.basename(chart)))
                chart_backup = chart_dir
                    
            # 設定ファイルの作成
            config = {
                "timestamp": timestamp,
                "database": db_backup,
                "chart": chart_backup,
                "last_price": None
            }

            # 最新価格の取得
            db = SessionLocal()
            try:
                last_price = db.query(PriceHistory)\
                    .order_by(PriceHistory.timestamp.desc())\
                    .first()
                if last_price:
                    config["last_price"] = last_price.price
            finally:
                db.close()
            
            # 市場操作検出フラグの永続保存
            if hasattr(self.bot, 'price_calculator'):
                self.bot.price_calculator._save_permanent_flags()
                self.logger.info("市場操作検出フラグをファイルに保存しました")
            
            # 設定ファイル保存
            with open(os.path.join(backup_dir, 'config.json'), 'w') as f:
                json.dump(config, f, indent=2)
            
            await interaction.followup.send(
                embed=EmbedBuilder.success(
                    "✅ Botを終了します",
                    f"バックアップが完了しました\n保存先: {backup_dir}"
                )
            )
            
            # Botを終了
            await self.bot.close()
            
        except Exception as e:
            self.logger.error(f"終了処理エラー: {str(e)}")
            await interaction.followup.send(
                embed=EmbedBuilder.error(
                    "エラー", 
                    f"終了処理中にエラーが発生しました: {str(e)}"
                )
            )

    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.command(name="admin_log", description="管理者専用コマンド")
    async def admin_log(self, interaction: discord.Interaction, lines: app_commands.Range[int, 1, 50] = 10):
        """ログ表示 (管理者専用)"""
        # アドミンユーザーチェック
        if str(interaction.user.id) != str(DISCORD_ADMIN_USER_ID):
            return

        # チャンネルチェック
        if str(interaction.channel_id) != str(os.getenv('DISCORD_LOG_CHANNEL_ID')):
            return

        await interaction.response.defer(ephemeral=True)
        
        try:
            # 現在のログファイルパスを取得
            log_file = f"logs/paraccoli_{datetime.now().strftime('%Y%m%d')}.log"
            
            if not os.path.exists(log_file):
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        "ログなし",
                        "本日のログファイルが見つかりません"
                    ),
                    ephemeral=True
                )
                return

            # ログを読み込み
            with open(log_file, 'r', encoding='utf-8') as f:
                log_lines = f.readlines()[-lines:]

            # ログをJISエンコーディングで処理
            log_text = ''.join(log_lines).encode('cp932', 'ignore').decode('cp932')

            # ログの長さをチェック
            if len(log_text) > 4000:  # Discordの文字数制限を考慮
                log_text = log_text[-4000:]  # 最新の4000文字のみ表示

            embed = discord.Embed(
                title="📋 最新のログ",
                description=f"```{log_text}```",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            embed.set_footer(text=f"最新{lines}行を表示")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Log display error: {str(e)}", exc_info=True)
            await interaction.followup.send(
                embed=EmbedBuilder.error("エラー", "ログの取得に失敗しました"),
                ephemeral=True
            )


    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.command(name="admin_event", description="管理者専用コマンド")
    @app_commands.describe(
        event_type="イベントのタイプ",
        index="イベントのインデックス（0-4）"
    )
    @app_commands.choices(event_type=[
        app_commands.Choice(name="📈 ポジティブ", value="positive"),
        app_commands.Choice(name="📉 ネガティブ", value="negative")
    ])
    
    async def admin_event(
        self,
        interaction: discord.Interaction,
        event_type: app_commands.Choice[str],
        index: int = None
    ):
        """イベントを強制的に発生させる（開発者用）"""
        # 開発者チェック
        if str(interaction.user.id) != str(DISCORD_ADMIN_USER_ID):
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "権限エラー",
                    "このコマンドは開発者のみ使用できます"
                ),
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        
        try:
            if self.bot.event_manager.current_event:
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        "イベントエラー",
                        "すでにイベントが進行中です"
                    ),
                    ephemeral=True
                )
                return

            # イベントの選択とバリデーション
            events = EventTypes.EVENTS[event_type.value]
            if index is not None:
                if not 0 <= index < len(events):
                    await interaction.followup.send(
                        embed=EmbedBuilder.error(
                            "パラメータエラー",
                            f"指定されたインデックス {index} のイベントは存在しません"
                        ),
                        ephemeral=True
                    )
                    return
                selected_event = events[index]
            else:
                selected_event = random.choice(events)

            # イベントの設定
            change_percent = random.uniform(
                selected_event.min_change,  # データクラスのフィールドとしてアクセス
                selected_event.max_change   # データクラスのフィールドとしてアクセス
            )

            # イベント情報を生成
            event_info = {
                "name": selected_event.name,
                "description": selected_event.description,
                "details": selected_event.details,
                "total_change": change_percent,
                "is_positive": selected_event.is_positive,
                "progress": 1
            }

            # イベントマネージャーに設定
            self.bot.event_manager.current_event = event_info
            self.bot.event_manager.remaining_effects = EventTypes.split_effect(change_percent)
            self.bot.event_manager.last_event_time = datetime.now(timezone.utc)

            # イベント通知を送信
            await self.bot.event_manager._notify_event(event_info)

            await interaction.followup.send(
                embed=EmbedBuilder.success(
                    "イベント発生",
                    f"{selected_event.name} を強制発生させました\n"
                    f"変動率: {change_percent:.2f}%"
                ),
                ephemeral=True
            )

        except Exception as e:
            self.logger.error(f"Force event error: {str(e)}", exc_info=True)
            await interaction.followup.send(
                embed=EmbedBuilder.error(
                    "エラー",
                    "イベントの発生に失敗しました"
                ),
                ephemeral=True
            )

    def _calculate_mining_amount(self, message_count: int, daily_mined: int, total_mined: int) -> int:
        """
        メッセージ数に応じたマイニング量を計算
        - アクティビティに応じた基本採掘量
        - 一日の採掘上限を考慮
        - 総発行上限を考慮
        """
        if message_count == 0:
            return 0

        # アクティビティに応じた基本採掘量
        base_amount = min(message_count * 2, 1000)  # 最大1000PARC

        # 一日の採掘上限を考慮
        remaining_daily = self.config.daily_mining_limit - daily_mined
        base_amount = min(base_amount, remaining_daily)

        # 総発行上限を考慮
        remaining_total = self.config.max_supply - total_mined
        base_amount = min(base_amount, remaining_total)

        return base_amount

    def error_handler(func):
        async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
            db = SessionLocal()
            try:
                await func(self, interaction, db, *args, **kwargs)
            except Exception as e:
                self.logger.error(f"{func.__name__} error: {str(e)}", exc_info=True)
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("エラーが発生しました", str(e)),
                    ephemeral=True
                )
            finally:
                db.close()
        return wrapper

    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.command(name="admin_idchange", description="管理者専用コマンド")
    @app_commands.describe(
        target="変更するID設定",
        new_id="新しいチャンネルまたはユーザーID"
    )
    @app_commands.choices(target=[
        app_commands.Choice(name="⛏️ マイニングチャンネル", value="DISCORD_MINING_CHANNEL_ID"),
        app_commands.Choice(name="📜 ルールチャンネル", value="DISCORD_RULES_CHANNEL_ID"),
        app_commands.Choice(name="❓ ヘルプチャンネル", value="DISCORD_HELP_CHANNEL_ID"),
        app_commands.Choice(name="📚 単語集チャンネル", value="DISCORD_WORDS_CHANNEL_ID"),
        app_commands.Choice(name="🎮 コマンドチャンネル", value="DISCORD_COMMANDS_CHANNEL_ID"),
        app_commands.Choice(name="📋 ログチャンネル", value="DISCORD_LOG_CHANNEL_ID"),
        app_commands.Choice(name="🎲 イベントチャンネル", value="DISCORD_EVENT_CHANNEL_ID"),
        app_commands.Choice(name="📊 チャートチャンネル", value="DISCORD_CHART_CHANNEL_ID"),
        app_commands.Choice(name="👑 管理者ユーザー", value="DISCORD_ADMIN_USER_ID")
    ])
    async def admin_idchange(
        self,
        interaction: discord.Interaction,
        target: app_commands.Choice[str],
        new_id: str
    ):
        """Discord IDの設定を変更"""
        # 管理者チェック
        if str(interaction.user.id) != str(DISCORD_ADMIN_USER_ID):
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "権限エラー",
                    "このコマンドは管理者のみ使用できます"
                ),
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            # IDの形式チェック
            if not new_id.isdigit():
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        "入力エラー",
                        "IDは数字のみで入力してください"
                    )
                )
                return

            # 現在の設定を取得
            current_value = os.getenv(target.value)

            # .envファイルを更新（引用符なしで保存）
            dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
            with open(dotenv_path, 'r', encoding='utf-8') as file:
                lines = file.readlines()

            with open(dotenv_path, 'w', encoding='utf-8') as file:
                for line in lines:
                    if line.startswith(f"{target.value}="):
                        file.write(f"{target.value}={new_id}\n")
                    else:
                        file.write(line)

            # 環境変数を更新
            os.environ[target.value] = new_id

            # 結果を表示
            embed = discord.Embed(
                title="✅ ID設定を更新しました",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(
                name="設定項目",
                value=f"`{target.value}`",
                inline=False
            )
            embed.add_field(
                name="変更前",
                value=f"`{current_value}`",
                inline=True
            )
            embed.add_field(
                name="変更後",
                value=f"`{new_id}`",
                inline=True
            )
            
            await interaction.followup.send(embed=embed)
            
            # ログ出力
            self.logger.info(
                f"ID設定を更新: {target.value}\n"
                f"変更前: {current_value}\n"
                f"変更後: {new_id}"
            )

        except Exception as e:
            self.logger.error(f"ID change error: {str(e)}", exc_info=True)
            await interaction.followup.send(
                embed=EmbedBuilder.error(
                    "エラー",
                    "ID設定の更新に失敗しました"
                )
            )

    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.command(name="admin_restart", description="管理者専用コマンド")
    async def admin_restart(self, interaction: discord.Interaction):
        """Bot再起動処理"""
        # 管理者チェック
        if str(interaction.user.id) != str(DISCORD_ADMIN_USER_ID):
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "権限エラー",
                    "このコマンドは管理者のみ使用できます"
                ),
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            # 市場操作検出フラグの永続保存
            if hasattr(self.bot, 'price_calculator'):
                self.bot.price_calculator._save_permanent_flags()
                self.logger.info("再起動前に市場操作検出フラグをファイルに保存しました")
                
            # 再起動メッセージを送信
            embed = discord.Embed(
                title="🔄 再起動を開始します",
                description="Botを再起動しています...",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            await interaction.followup.send(embed=embed)

            # 環境変数を再読み込み
            load_dotenv(override=True)
            
            self.logger.info("Bot再起動を開始します...")

            # aiohttp セッションをクローズ
            if hasattr(self.bot, 'session') and self.bot.session:
                await self.bot.session.close()

            # イベントループを取得
            loop = asyncio.get_event_loop()

            # 新しいプロセスを起動（非同期処理の前に実行）
            if os.name == 'nt':  # Windows
                subprocess.Popen(
                    ['cmd', '/c', 'start', 'cmd', '/k', 'python', '-m', 'src.bot.main'],
                    creationflags=subprocess.CREATE_NEW_CONSOLE
                )
            else:  # Linux/Mac
                os.system('python3 -m src.bot.main &')

            # Botをクローズ
            await self.bot.close()

            # 残っているタスクをキャンセル
            for task in asyncio.all_tasks(loop):
                if task is not asyncio.current_task():
                    task.cancel()

            # 少し待機して、タスクが適切にキャンセルされるのを待つ
            await asyncio.sleep(1)

            # プロセスを終了
            self.logger.info(f"現在のプロセス（PID: {os.getpid()}）を終了します")
            os._exit(0)

        except Exception as e:
            self.logger.error(f"Restart error: {str(e)}", exc_info=True)
            error_embed = discord.Embed(
                title="❌ 再起動エラー",
                description=f"再起動中にエラーが発生しました:\n```{str(e)}```",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            await interaction.followup.send(embed=error_embed)

    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.command(name="admin_add", description="管理者専用コマンド")
    @app_commands.describe(
        currency="追加する通貨の種類",
        user="対象ユーザー",
        amount="追加する金額"
    )
    @app_commands.choices(currency=[
        Choice(name="🪙 PARC", value="parc"),
        Choice(name="💴 JPY", value="jpy")
    ])
    async def admin_add(
        self,
        interaction: discord.Interaction,
        currency: Choice[str],
        user: discord.Member,
        amount: float
    ):
        """管理者用の残高追加処理"""
        # 管理者チェック
        if str(interaction.user.id) != str(DISCORD_ADMIN_USER_ID):
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "権限エラー", 
                    "このコマンドは管理者のみ使用できます"
                ),
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        
        db = SessionLocal()
        try:
            # 対象ユーザーの取得
            target_user = db.query(User).filter(
                User.discord_id == str(user.id)
            ).first()

            if not target_user or not target_user.wallet:
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        "エラー",
                        "対象ユーザーのウォレットが見つかりません"
                    )
                )
                return

            # 金額のバリデーション
            if amount <= 0:
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        "エラー",
                        "金額は0より大きい値を指定してください"
                    )
                )
                return

            # 残高の更新
            if currency.value == "parc":
                target_user.wallet.parc_balance += amount
                currency_symbol = "PARC"
            else:  # jpy
                target_user.wallet.jpy_balance += amount
                currency_symbol = "JPY"

            # トランザクション記録
            tx = Transaction(
                to_address=target_user.wallet.address,
                amount=amount,
                transaction_type="admin_add",
                timestamp=datetime.now(),
                status="completed"
            )
            db.add(tx)
            
            db.commit()

            # 結果通知
            embed = EmbedBuilder.success(
                "✅ 残高追加完了",
                f"{user.mention} に {amount:,} {currency_symbol} を追加しました"
            )
            embed.add_field(
                name="💰 現在の残高",
                value=(
                    f"PARC: {target_user.wallet.parc_balance:,}\n"
                    f"JPY: ¥{target_user.wallet.jpy_balance:,}"
                ),
                inline=False
            )

            await interaction.followup.send(embed=embed)

            # ユーザーへのDM通知
            try:
                user_embed = discord.Embed(
                    title="💰 残高が追加されました",
                    description=f"管理者により {amount:,} {currency_symbol} が追加されました",
                    color=discord.Color.green(),
                    timestamp=datetime.now()
                )
                user_embed.add_field(
                    name="現在の残高",
                    value=(
                        f"PARC: {target_user.wallet.parc_balance:,}\n"
                        f"JPY: ¥{target_user.wallet.jpy_balance:,}"
                    ),
                    inline=False
                )
                await user.send(embed=user_embed)
            except Exception as e:
                self.logger.error(f"Failed to send DM to user: {e}")

        except Exception as e:
            self.logger.error(f"Admin add error: {str(e)}", exc_info=True)
            db.rollback()
            await interaction.followup.send(
                embed=EmbedBuilder.error("エラー", "残高の追加に失敗しました")
            )
        finally:
            db.close()

    @app_commands.command(name="predict", description="AIを使用して価格予測を行います")
    @app_commands.describe(
        minutes="予測する時間（1-60分）",
        model_type="使用する予測モデル"
    )
    @app_commands.choices(model_type=[
        Choice(name="🤖 Hybrid LSTM-CNN（高精度）", value="hybrid"),
        Choice(name="🧠 LSTM（深層学習）", value="lstm"),
        Choice(name="📈 Prophet（統計）", value="prophet"),
        Choice(name="🌳 XGBoost（勾配ブースティング）", value="xgboost"),
        Choice(name="📊 線形回帰（シンプル）", value="linear"),
        Choice(name="🎯 アンサンブル（複合）", value="ensemble")
    ])
    async def predict(
        self,
        interaction: discord.Interaction,
        minutes: app_commands.Range[int, 1, 60],
        model_type: str
    ):
        """価格予測を行うコマンド"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # 進捗メッセージ
            progress_embed = discord.Embed(
                title="🔮 予測モデルを準備中...",
                description=f"選択されたモデル: {model_type}\n予測時間: {minutes}分",
                color=discord.Color.blue()
            )
            await interaction.followup.send(embed=progress_embed, ephemeral=True)


            predictor = PricePredictor()
            result = await predictor.predict_price(minutes, model_type)

            if not result["success"]:
                await interaction.edit_original_response(
                    embed=EmbedBuilder.error("予測エラー", result["error"])
                )
                return
            
            # モデル固有の説明文
            model_info = {
                "hybrid": {
                    "name": "Hybrid LSTM-CNN",
                    "desc": "LSTMとCNNを組み合わせた高度な深層学習モデル",
                    "color": discord.Color.purple()
                },
                "lstm": {
                    "name": "LSTM",
                    "desc": "時系列データに特化した深層学習モデル",
                    "color": discord.Color.blue()
                },
                "prophet": {
                    "name": "Prophet",
                    "desc": "Metaが開発した時系列予測モデル",
                    "color": discord.Color.green()
                },
                "xgboost": {
                    "name": "XGBoost",
                    "desc": "高速で精度の高い勾配ブースティングモデル",
                    "color": discord.Color.gold()
                },
                "linear": {
                    "name": "線形回帰",
                    "desc": "シンプルで解釈しやすい統計モデル",
                    "color": discord.Color.greyple()
                },
                "ensemble": {
                    "name": "アンサンブル",
                    "desc": "複数のモデルを組み合わせた総合予測",
                    "color": discord.Color.red()
                }
            }

            model_data = model_info.get(model_type, {
                "name": "Unknown Model",
                "desc": "モデルの説明がありません",
                "color": discord.Color.default()
            })
            
            # 現在価格を取得
            db = SessionLocal()
            current_price = db.query(PriceHistory)\
                .order_by(PriceHistory.timestamp.desc())\
                .first()
            db.close()
            
            predicted_price = result["predicted_price"]
            current_price = current_price.price
            change_percent = ((predicted_price - current_price) / current_price) * 100
            
            # 予測結果のEmbed作成
            embed = discord.Embed(
                title=f"🔮 {minutes}分後の価格予測",
                description=f"**{model_data['name']}** を使用\n{model_data['desc']}",
                color=model_data['color'],
                timestamp=datetime.now()
            )
            
            # 価格情報
            embed.add_field(
                name="💰 現在価格",
                value=f"¥{current_price:,.2f}",
                inline=True
            )
            
            embed.add_field(
                name="🎯 予測価格",
                value=f"¥{predicted_price:,.2f}",
                inline=True
            )
            
            # 変動率と方向
            direction = "↗️" if change_percent > 0 else "↘️" if change_percent < 0 else "➡️"
            embed.add_field(
                name=f"📈 予測変動 {direction}",
                value=f"{change_percent:+.2f}%",
                inline=True
            )
            
            # 信頼度スコア
            confidence = result['confidence'] * 100
            confidence_bar = "█" * int(confidence / 10) + "░" * (10 - int(confidence / 10))
            embed.add_field(
                name="🎯 信頼度",
                value=f"`{confidence_bar}` {confidence:.1f}%",
                inline=False
            )
            
            # 予測範囲
            embed.add_field(
                name="📊 予測範囲",
                value=f"¥{predicted_price * 0.95:,.2f} 〜 ¥{predicted_price * 1.05:,.2f}",
                inline=False
            )
            
            # グラフを添付
            if result.get("graph"):
                file = discord.File(result["graph"], filename="prediction.png")
                embed.set_image(url="attachment://prediction.png")
                await interaction.edit_original_response(embed=embed, attachments=[file])
            else:
                await interaction.edit_original_response(embed=embed)

        except Exception as e:
            self.logger.error(f"Prediction error: {str(e)}")
            await interaction.edit_original_response(
                embed=EmbedBuilder.error(
                    "予測エラー",
                    "予測の実行中にエラーが発生しました。"
                )
            )

async def setup(bot):
    cog = ParaccoliCommands(bot)
    await bot.add_cog(cog)
    
    # 管理者コマンドを一般ユーザーには非表示にする
    for command in cog.get_app_commands():
        if command.name.startswith("admin_"):
            command.guild_only = True  # サーバーでのみ使用可能
            
            # 管理者のみが閲覧・使用できるように設定
            permissions = discord.Permissions()
            permissions.administrator = True
            command.default_permissions = permissions