from discord.ext import tasks, commands
from ..database.database import SessionLocal
from ..database.models import User, DailyStats
from datetime import datetime, timedelta, timezone
import pytz
from ..utils.embed_builder import EmbedBuilder
from ..utils.trading_hours import TradingHours
from ..utils.logger import Logger
from ..utils.config import Config
from discord import Embed
from ..database.models import Transaction
from sqlalchemy import func
from ..utils.chart_builder import ChartBuilder
from ..database.models import PriceHistory
from ..utils.price_calculator import PriceCalculator
from ..utils.event_manager import EventManager
import discord
import time
import os
import logging
import random
import base64
import shutil
from ..database.models import Order
from ..database.models import Wallet
from sqlalchemy.orm import Session
import asyncio




class ParaccoliTasks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)  # Loggerクラスではなく標準のloggingを使用
        self.config = Config()
        self.event_manager = EventManager(bot)
        self.reset_daily_stats.start()
        self.process_orders.start()
        self.update_price_info.start()
        self.check_daily_event.start()
        self.save_manipulation_flags.start()  # フラグ保存タスク開始
        self.save_flags_periodically.start()  # 新しいタスクを追加
        self.backup_permanent_flags.start()   # 永続フラグのバックアップタスクを開始
        self.update_random_prices.start()  # 10秒ごとのランダム価格更新タスク
        self.check_trading_hours.start()  # 取引時間監視タスクを開始
        self.last_trading_notification = None  # 最後の通知タイプを保存
        self.last_session_price = None
        self.last_session_time = None
        self.last_session_type = None
        self.cleanup_logs.start()  # 古いログファイルの削除タスク
        self.cleanup_backups.start()  # 古いバックアップの削除タスク
        self.cleanup_logs_frequently.start()  # 30分ごとのログクリーンアップを追加
        self.cleanup_temp_data.start()  # 30分ごとの不要データクリーンアップを追加
        self.save_price_state.start()  # 新しいタスクを開始
        # セッション開始・終了通知のフラグ
        self.today_morning_open_notified = False
        self.today_morning_close_notified = False
        self.today_afternoon_open_notified = False
        self.today_afternoon_close_notified = False
        self.last_trading_state = False


    def cog_unload(self):
        self.reset_daily_stats.cancel()
        self.process_orders.cancel()
        self.update_price_info.cancel()
        self.check_daily_event.cancel()
        self.cleanup_logs_frequently.cancel()  # 追加したタスクのキャンセル
        self.cleanup_temp_data.cancel()  # 追加したタスクのキャンセル
        self.save_price_state.cancel()

    @tasks.loop(minutes=30)  # 30分ごとに実行
    async def cleanup_logs_frequently(self):
        """
        30分ごとにlogsフォルダ内のファイルを全て削除する
        """
        try:
            # ログディレクトリのパス
            log_dir = "logs"
            self.logger.info("logsフォルダの全ファイルを削除します...")
            
            if not os.path.exists(log_dir):
                self.logger.warning(f"ログディレクトリ {log_dir} が存在しません")
                return
                
            # 削除前にバックアップを作成（最新のログは残しておく）
            current_log_file = f"paraccoli_{datetime.now().strftime('%Y%m%d')}.log"
            current_log_path = os.path.join(log_dir, current_log_file)
            
            if os.path.exists(current_log_path):
                # 念のため一時バックアップを作成
                backup_dir = "backup/logs_backup"
                os.makedirs(backup_dir, exist_ok=True)
                backup_path = os.path.join(backup_dir, f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{current_log_file}")
                shutil.copy2(current_log_path, backup_path)
                self.logger.info(f"現在のログをバックアップしました: {backup_path}")
            
            # ログファイルを全て削除
            deleted_count = 0
            for file in os.listdir(log_dir):
                file_path = os.path.join(log_dir, file)
                if os.path.isfile(file_path):
                    try:
                        os.remove(file_path)
                        deleted_count += 1
                    except Exception as e:
                        self.logger.error(f"ログファイル削除エラー: {file} - {e}")
            
            self.logger.info(f"logsフォルダ内のファイルを全て削除しました: {deleted_count}ファイル")
            
        except Exception as e:
            self.logger.error(f"ログクリーンアップエラー: {e}", exc_info=True)

    @cleanup_logs_frequently.before_loop
    async def before_cleanup_logs_frequently(self):
        """ログ削除タスク開始前の処理"""
        await self.bot.wait_until_ready()


    @tasks.loop(minutes=30)  # 30分ごとに実行
    async def cleanup_temp_data(self):
        """
        30分ごとにtemp内の不要データとbackup内のchartsフォルダを削除する
        """
        try:
            self.logger.info("一時データのクリーンアップを開始...")

            # tempディレクトリのクリーンアップ
            await self._cleanup_temp_folder()
            
            # backupディレクトリ内のchartsフォルダのクリーンアップ
            await self._cleanup_backup_charts()
            
        except Exception as e:
            self.logger.error(f"一時データクリーンアップエラー: {e}", exc_info=True)

    async def _cleanup_temp_folder(self):
        """tempフォルダ内の古いファイルを削除"""
        try:
            temp_dir = "temp"
            
            if not os.path.exists(temp_dir):
                self.logger.warning(f"tempフォルダが存在しません: {temp_dir}")
                return
                
            # 30分以上前のファイルを削除（チャートは頻繁に作成されるため）
            cutoff_time = time.time() - (30 * 60)  # 30分前
            
            deleted_count = 0
            for item in os.listdir(temp_dir):
                item_path = os.path.join(temp_dir, item)
                if os.path.isfile(item_path):
                    if os.path.getmtime(item_path) < cutoff_time:
                        try:
                            os.remove(item_path)
                            deleted_count += 1
                        except Exception as e:
                            self.logger.error(f"ファイル削除エラー: {item} - {e}")
                elif os.path.isdir(item_path):
                    if os.path.getmtime(item_path) < cutoff_time:
                        try:
                            shutil.rmtree(item_path)
                            deleted_count += 1
                        except Exception as e:
                            self.logger.error(f"ディレクトリ削除エラー: {item} - {e}")
            
            self.logger.info(f"tempフォルダ内の古いファイル削除完了: {deleted_count}アイテム削除")
            
        except Exception as e:
            self.logger.error(f"tempフォルダクリーンアップエラー: {e}")

    async def _cleanup_backup_charts(self):
        """バックアップフォルダ内のchartsデータを削除"""
        try:
            backup_dir = "backup"
            
            if not os.path.exists(backup_dir):
                self.logger.warning(f"バックアップフォルダが存在しません: {backup_dir}")
                return
                
            # 3時間以上前のバックアップのchartsフォルダを削除
            cutoff_time = time.time() - (3 * 60 * 60)  # 3時間
            
            deleted_count = 0
            for date_folder in os.listdir(backup_dir):
                date_folder_path = os.path.join(backup_dir, date_folder)
                
                # データフォルダのみ処理（日付形式のフォルダ）
                if not os.path.isdir(date_folder_path) or not date_folder[0].isdigit():
                    continue
                    
                charts_folder = os.path.join(date_folder_path, 'charts')
                if os.path.exists(charts_folder) and os.path.isdir(charts_folder):
                    # chartsフォルダの更新時間をチェック
                    if os.path.getmtime(charts_folder) < cutoff_time:
                        try:
                            shutil.rmtree(charts_folder)
                            self.logger.info(f"古いchartsフォルダを削除: {charts_folder}")
                            deleted_count += 1
                        except Exception as e:
                            self.logger.error(f"chartsフォルダ削除エラー: {charts_folder} - {e}")
            
            self.logger.info(f"バックアップ内のチャートデータクリーンアップ完了: {deleted_count}フォルダ削除")
            
        except Exception as e:
            self.logger.error(f"バックアップchartsフォルダクリーンアップエラー: {e}")

    @cleanup_temp_data.before_loop
    async def before_cleanup_temp_data(self):
        """不要データ削除タスク開始前の処理"""
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=60)  # 1分おきにチェック
    async def check_trading_hours(self):
        """取引時間の監視と通知"""
        if not self.bot.is_ready():
            return
            
        try:
            # 現在の時刻を取得
            current_time = TradingHours.get_current_time()
            self.logger.info(f"取引時間チェック: {current_time.strftime('%H:%M:%S')}")
            
            # 現在の取引時間状態
            is_trading_hours = TradingHours.is_trading_hours()
            
            # 前場開始時刻と終了時刻を取得
            # get_session_time がなく、エラーになっているので直接アクセス
            morning_start = datetime.combine(current_time.date(), TradingHours.MORNING_SESSION_START)
            morning_start = pytz.timezone('Asia/Tokyo').localize(morning_start)
            
            morning_end = datetime.combine(current_time.date(), TradingHours.MORNING_SESSION_END)
            morning_end = pytz.timezone('Asia/Tokyo').localize(morning_end)
            
            # 後場開始時刻と終了時刻を取得
            afternoon_start = datetime.combine(current_time.date(), TradingHours.AFTERNOON_SESSION_START)
            afternoon_start = pytz.timezone('Asia/Tokyo').localize(afternoon_start)
            
            afternoon_end = datetime.combine(current_time.date(), TradingHours.AFTERNOON_SESSION_END)
            afternoon_end = pytz.timezone('Asia/Tokyo').localize(afternoon_end)
            
            # 取引状態が変わったときのみ通知
            if is_trading_hours != self.last_trading_state:
                self.last_trading_state = is_trading_hours
                
                if is_trading_hours:
                    # 取引時間開始通知
                    session_name = "前場" if current_time.time() < TradingHours.AFTERNOON_SESSION_START else "後場"
                    notification = f"🔔 **{session_name}の取引が開始しました**"
                    await self._send_trading_notification(notification)
                    self.last_trading_notification = "start"
                else:
                    # 取引時間終了通知
                    session_name = "前場" if current_time.time() < TradingHours.AFTERNOON_SESSION_START else "後場"
                    notification = f"🔔 **{session_name}の取引が終了しました**"
                    await self._send_trading_notification(notification)
                    self.last_trading_notification = "end"
                    
        except Exception as e:
            self.logger.error(f"取引時間チェックエラー: {e}", exc_info=True)

    @check_trading_hours.before_loop
    async def before_check_trading_hours(self):
        """取引時間監視タスク開始前の処理"""
        await self.bot.wait_until_ready()


    @tasks.loop(hours=24)  # 24時間に1回実行
    async def cleanup_logs(self):
        """
        古いログファイルを削除（指定日数より古いものを削除）
        デフォルトでは7日以上前のログを削除
        """
        try:
            # ログディレクトリのパス
            log_dir = "logs"
            self.logger.info("古いログファイルのクリーンアップを開始...")
            
            # 保持する日数（デフォルト: 7日）
            keep_days = 7
            
            if not os.path.exists(log_dir):
                self.logger.warning(f"ログディレクトリ {log_dir} が存在しません")
                return
                
            # 現在の日付
            current_date = datetime.now()
            # 削除基準日（7日前）
            cutoff_date = current_date - timedelta(days=keep_days)
            cutoff_timestamp = cutoff_date.timestamp()
            
            deleted_count = 0
            skipped_count = 0
            
            # ログファイルを確認
            for file in os.listdir(log_dir):
                file_path = os.path.join(log_dir, file)
                
                # ファイルが「paraccoli_」で始まるログファイルかチェック
                if file.startswith("paraccoli_") and file.endswith(".log"):
                    file_mtime = os.path.getmtime(file_path)
                    
                    # ファイルの更新日時が基準日より古いかチェック
                    if file_mtime < cutoff_timestamp:
                        try:
                            os.remove(file_path)
                            deleted_count += 1
                            self.logger.info(f"古いログファイルを削除: {file}")
                        except Exception as e:
                            self.logger.error(f"ログファイル削除エラー: {file} - {e}")
                    else:
                        skipped_count += 1
            
            self.logger.info(f"ログクリーンアップ完了: {deleted_count}ファイル削除, {skipped_count}ファイル保持")
        
        except Exception as e:
            self.logger.error(f"ログクリーンアップエラー: {e}", exc_info=True)

    @tasks.loop(hours=24)  # 24時間に1回実行
    async def cleanup_backups(self):
        """
        古いバックアップを削除（最新の10個だけ残す）
        """
        try:
            # バックアップディレクトリのパス
            backup_dir = "backup"
            self.logger.info("バックアップのクリーンアップを開始...")
            
            # 保持するバックアップの数（デフォルト: 10）
            keep_backups = 10
            
            if not os.path.exists(backup_dir):
                self.logger.warning(f"バックアップディレクトリ {backup_dir} が存在しません")
                return
                
            # バックアップディレクトリの一覧を取得し、更新日時でソート
            backups = []
            for dir_name in os.listdir(backup_dir):
                dir_path = os.path.join(backup_dir, dir_name)
                if os.path.isdir(dir_path):
                    # ディレクトリの更新日時を取得
                    mtime = os.path.getmtime(dir_path)
                    backups.append((dir_path, mtime))
            
            # 更新日時の新しい順にソート
            backups.sort(key=lambda x: x[1], reverse=True)
            
            # 保持する数を超えたバックアップを削除
            if len(backups) > keep_backups:
                for dir_path, _ in backups[keep_backups:]:
                    try:
                        shutil.rmtree(dir_path)
                        self.logger.info(f"古いバックアップを削除: {os.path.basename(dir_path)}")
                    except Exception as e:
                        self.logger.error(f"バックアップ削除エラー: {os.path.basename(dir_path)} - {e}")
                
                self.logger.info(f"バックアップクリーンアップ完了: {len(backups) - keep_backups}個削除, {keep_backups}個保持")
            else:
                self.logger.info(f"削除するバックアップはありません: 現在{len(backups)}個 (上限: {keep_backups}個)")
        
        except Exception as e:
            self.logger.error(f"バックアップクリーンアップエラー: {e}", exc_info=True)


    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """リアクションに応じてチャートの時間枠を変更"""
        if payload.user_id == self.bot.user.id:
            return  # Botのリアクションは無視
        
        # 設定済みチャンネルIDと一致するか確認
        chart_channel_id = getattr(self.config, 'chart_channel_id', None)
        if not chart_channel_id or int(chart_channel_id) != payload.channel_id:
            return
        
        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return
        
        try:
            # リアクションしたユーザーを取得
            user = await self.bot.fetch_user(payload.user_id)
            if not user:
                return
                
            # リアクションされたメッセージを取得
            message = await channel.fetch_message(payload.message_id)
            if message.author != self.bot.user:
                return
            
            # 時間枠とエモジの対応
            time_frames = {
                "⏱️": 10,   # 10分
                "🕒": 30,   # 30分
                "🕐": 60    # 60分
            }
            
            emoji = str(payload.emoji)
            if emoji not in time_frames:
                return
            
            minutes = time_frames[emoji]
            chart_type = {10: "short", 30: "medium", 60: "long"}[minutes]
            
            # チャート画像を取得
            db = SessionLocal()
            try:
                # データを取得
                history = db.query(PriceHistory)\
                    .filter(PriceHistory.timestamp >= datetime.now() - timedelta(hours=2))\
                    .order_by(PriceHistory.timestamp.asc())\
                    .all()
                    
                if not history:
                    return
                    
                # 新しいチャート生成
                timestamp = int(datetime.now().timestamp())
                chart_path = f"temp/price_chart_{chart_type}_{timestamp}.png"
                
                ChartBuilder.create_price_chart(history, chart_path, minutes=minutes)
                
                # 既存の埋め込みを取得して更新
                embed = message.embeds[0] if message.embeds else None
                if not embed:
                    return
                    
                # タイトルを更新
                embed.title = f"🪙 PARC/JPY チャート ({minutes}分間)"
                
                # 新しいファイルとEmbedでメッセージを更新
                file = discord.File(chart_path, filename="chart.png")
                embed.set_image(url="attachment://chart.png")
                
                # チャンネルでのメッセージを更新
                await message.edit(attachments=[file], embed=embed)
                
                # DMにも同じチャートを送信
                dm_embed = discord.Embed(
                    title=f"🪙 PARC/JPY チャート ({minutes}分間)",
                    description=f"時間枠: {minutes}分",
                    color=embed.color,
                    timestamp=datetime.now()
                )
                
                # 同じフィールドをコピー
                for field in embed.fields:
                    dm_embed.add_field(
                        name=field.name,
                        value=field.value,
                        inline=field.inline
                    )
                
                # DMに送信
                dm_embed.set_image(url="attachment://chart.png")
                dm_embed.set_footer(text=f"リクエストされたチャート | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                
                await user.send(file=discord.File(chart_path, filename="chart.png"), embed=dm_embed)
                
                # リアクションを削除
                try:
                    await message.remove_reaction(payload.emoji, user)
                except Exception as e:
                    self.logger.error(f"リアクション削除エラー: {str(e)}")
                    
            finally:
                db.close()
        
        except Exception as e:
            self.logger.error(f"チャート時間枠変更エラー: {e}", exc_info=True)


    @tasks.loop(hours=24)
    async def reset_daily_stats(self):
        """日次統計のリセット"""
        db = SessionLocal()
        try:
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            
            # 昨日の統計を保存
            yesterday_stats = db.query(DailyStats).filter(
                DailyStats.date == yesterday
            ).first()
            
            if yesterday_stats:
                self.logger.info(f"Yesterday's mining: {yesterday_stats.total_mined} PARC")
            
            # 今日の統計を初期化
            today_stats = DailyStats(
                date=today,
                total_mined=0,
                total_transactions=0
            )
            db.add(today_stats)
            db.commit()
            
        except Exception as e:
            self.logger.error(f"Failed to reset daily stats: {e}")
        finally:
            db.close()

    @tasks.loop(minutes=1)
    async def process_orders(self):
        """指値注文の処理"""
        db = SessionLocal()
        try:
            # 現在の価格をリアルタイムチャートの価格に変更
            price_calculator = self.bot.price_calculator if hasattr(self.bot, 'price_calculator') else PriceCalculator(self.bot)
            current_price = price_calculator.get_latest_random_price()
            
            # 未約定の注文を取得
            pending_orders = db.query(Order)\
                .filter(Order.status == 'pending')\
                .all()

            for order in pending_orders:
                try:
                    # 買い注文の処理
                    if order.side == 'buy' and order.price >= current_price:
                        await self._execute_buy_order(order, current_price, db)
                    
                    # 売り注文の処理
                    elif order.side == 'sell' and order.price <= current_price:
                        await self._execute_sell_order(order, current_price, db)

                except Exception as e:
                    self.logger.error(f"Order processing error: {str(e)}")
                    continue

        except Exception as e:
            self.logger.error(f"Order processing loop error: {str(e)}")
        finally:
            db.close()

    async def _execute_buy_order(self, order: Order, current_price: float, db: Session):
        """買い注文の執行"""
        wallet = db.query(Wallet).filter(Wallet.address == order.wallet_address).first()
        if not wallet:
            return

        # 取引手数料の計算
        fee = order.amount * current_price * 0.001  # 0.1%
        total_cost = (order.amount * current_price) + fee

        # 残高チェック
        if wallet.jpy_balance < total_cost:
            order.status = 'cancelled'
            db.commit()
            return

        # 取引実行
        wallet.jpy_balance -= total_cost
        wallet.parc_balance += order.amount

        # 取引記録
        transaction = Transaction(
            to_address=wallet.address,
            amount=order.amount,
            price=current_price,
            fee=fee,
            transaction_type="buy",
            order_type="limit"
        )
        db.add(transaction)

        # 手数料の記録
        fee_transaction = Transaction(
            from_address=wallet.address,
            amount=fee,
            transaction_type="fee"
        )
        db.add(fee_transaction)

        # 注文状態の更新
        order.status = 'filled'
        db.commit()

        # 通知の送信
        try:
            user = db.query(User).filter(User.wallet.has(address=wallet.address)).first()
            if user:
                member = await self.bot.fetch_user(int(user.discord_id))
                if member:
                    embed = EmbedBuilder.success(
                        "指値注文が約定しました 💹",
                        f"{order.amount:,} PARCを ¥{total_cost:,.0f} で購入しました"
                    )
                    embed.add_field(
                        name="💰 取引詳細",
                        value=(
                            f"価格: ¥{current_price:,.2f}/PARC\n"
                            f"手数料: ¥{fee:,.0f} (0.1%)"
                        ),
                        inline=False
                    )
                    embed.add_field(
                        name="💳 新しい残高",
                        value=(
                            f"PARC: {wallet.parc_balance:,}\n"
                            f"JPY: ¥{wallet.jpy_balance:,}"
                        ),
                        inline=False
                    )
                    await member.send(embed=embed)
        except Exception as e:
            self.logger.error(f"Notification error: {str(e)}")

    async def _execute_sell_order(self, order: Order, current_price: float, db: Session):
        """売り注文の執行"""
        wallet = db.query(Wallet).filter(Wallet.address == order.wallet_address).first()
        if not wallet:
            return

        # PARC残高チェック
        if wallet.parc_balance < order.amount:
            order.status = 'cancelled'
            db.commit()
            return

        # 取引金額と手数料の計算
        sale_amount = order.amount * current_price
        fee = sale_amount * 0.001  # 0.1%
        total_amount = sale_amount - fee

        # 取引実行
        wallet.parc_balance -= order.amount
        wallet.jpy_balance += total_amount

        # 取引記録
        transaction = Transaction(
            from_address=wallet.address,
            amount=order.amount,
            price=current_price,
            fee=fee,
            transaction_type="sell",
            order_type="limit"
        )
        db.add(transaction)

        # 手数料の記録（燃焼）
        fee_transaction = Transaction(
            from_address=wallet.address,
            amount=fee,
            transaction_type="fee"
        )
        db.add(fee_transaction)

        # 注文状態の更新
        order.status = 'filled'
        db.commit()

        # 通知の送信
        try:
            user = db.query(User).filter(User.wallet.has(address=wallet.address)).first()
            if user:
                member = await self.bot.fetch_user(int(user.discord_id))
                if member:
                    embed = EmbedBuilder.success(
                        "指値注文が約定しました 💹",
                        f"{order.amount:,} PARCを ¥{total_amount:,.0f} で売却しました"
                    )
                    embed.add_field(
                        name="💰 取引詳細",
                        value=(
                            f"価格: ¥{current_price:,.2f}/PARC\n"
                            f"手数料: ¥{fee:,.0f} (0.1%)"
                        ),
                        inline=False
                    )
                    embed.add_field(
                        name="💳 新しい残高",
                        value=(
                            f"PARC: {wallet.parc_balance:,}\n"
                            f"JPY: ¥{wallet.jpy_balance:,}"
                        ),
                        inline=False
                    )
                    await member.send(embed=embed)
        except Exception as e:
            self.logger.error(f"Notification error: {str(e)}")

    async def cleanup_old_charts(self, temp_dir: str = "temp", max_age: int = 300):
        """古いチャート画像を削除（5分以上経過したものを削除）"""
        try:
            if not os.path.exists(temp_dir):
                self.logger.warning(f"一時ディレクトリ {temp_dir} が存在しません")
                return
                
            current_time = time.time()
            deleted_count = 0
            
            for file in os.listdir(temp_dir):
                # チャート画像ファイルだけでなく、一時ファイルも対象に
                if (file.startswith("price_chart_") or file.startswith("temp_")) and file.endswith((".png", ".jpg", ".jpeg")):
                    file_path = os.path.join(temp_dir, file)
                    
                    # ファイルの更新日時をチェック
                    if os.path.isfile(file_path) and (current_time - os.path.getmtime(file_path) > max_age):
                        try:
                            os.remove(file_path)
                            deleted_count += 1
                        except Exception as e:
                            self.logger.error(f"チャート削除エラー: {file} - {e}")
            
            # 大量のファイルを削除した場合だけログ出力（頻繁に実行されるので）
            if deleted_count > 0:
                self.logger.info(f"{deleted_count}個の古い画像ファイルを削除しました")
                
        except Exception as e:
            self.logger.error(f"チャート清掃エラー: {e}")


    @tasks.loop(minutes=1)
    async def update_price_info(self):
        """価格情報の更新(1分毎)"""
        if not self.bot.is_ready():
            return

        try:
            # 現在の時刻とセッション情報を取得
            current_time = TradingHours.get_current_time()
            is_trading_hours = TradingHours.is_trading_hours()
            session_type = TradingHours.get_session_type()  # morning, afternoon, None
            
            # 日付変更時にフラグをリセット
            if hasattr(self, '_last_check_date'):
                if self._last_check_date != current_time.date():
                    self.today_morning_open_notified = False
                    self.today_morning_close_notified = False
                    self.today_afternoon_open_notified = False
                    self.today_afternoon_close_notified = False
                    self._last_check_date = current_time.date()
            else:
                self._last_check_date = current_time.date()
            
            # 取引開始・終了のタイミング検出
            if TradingHours.is_session_start("morning") and not self.today_morning_open_notified:
                # 前場開始 - 始値通知
                await self._notify_session_open("前場")
                self.today_morning_open_notified = True
            
            elif TradingHours.is_session_end("morning") and not self.today_morning_close_notified:
                # 前場終了 - 終値通知
                await self._notify_session_close("前場")
                self.today_morning_close_notified = True
                
            elif TradingHours.is_session_start("afternoon") and not self.today_afternoon_open_notified:
                # 後場開始 - 始値通知
                await self._notify_session_open("後場")
                self.today_afternoon_open_notified = True
                
            elif TradingHours.is_session_end("afternoon") and not self.today_afternoon_close_notified:
                # 後場終了 - 終値通知
                await self._notify_session_close("後場")
                self.today_afternoon_close_notified = True
            
            # 取引時間外は最新価格の計算をスキップ
            # ただし、セッション開始・終了直後は例外とする
            if not is_trading_hours and not (TradingHours.is_session_start() or TradingHours.is_session_end()):
                self.logger.info("取引時間外のため、価格計算をスキップします")
                return
                    
            # 重複計算防止フラグの確認
            if hasattr(self, '_calculating_price') and self._calculating_price:
                self.logger.warning("前回の価格計算がまだ実行中です。スキップします。")
                return
            
            # 計算中フラグを設定
            self._calculating_price = True
            
            # 最新価格の計算とDB保存
            db = SessionLocal()
            try:
                now = datetime.now()
                
                # Botインスタンスからprize_calculatorを取得
                price_calculator = self.bot.price_calculator if hasattr(self.bot, 'price_calculator') else PriceCalculator(self.bot)
                
                # 価格を1回だけ計算
                self.logger.info("1分間隔の価格計算を開始...")
                current_price = price_calculator.calculate_price(db)
                self.logger.info(f"価格計算完了: ¥{current_price:,.2f}")
                
                # ChartBuilderに計算価格を設定
                from src.utils.chart_builder import ChartBuilder
                ChartBuilder.set_calculated_price(current_price)
                
                # 24時間取引量を取得
                yesterday = datetime.now() - timedelta(days=1)
                volume_24h = db.query(func.sum(Transaction.amount))\
                    .filter(
                        Transaction.timestamp >= yesterday,
                        Transaction.transaction_type.in_(['buy', 'sell'])
                    ).scalar() or 0

                # 過去の価格を取得
                last_price = db.query(PriceHistory)\
                    .order_by(PriceHistory.timestamp.desc())\
                    .first()

                # 変動率計算
                price_change = ((current_price - last_price.price) / last_price.price * 100) if last_price else 0

                # 新しい価格履歴を作成
                new_price = PriceHistory(
                    timestamp=datetime.now(),
                    price=current_price,
                    volume=volume_24h,
                    market_cap=current_price * volume_24h
                )
                db.add(new_price)
                db.commit()

                # 取引セッションの状態を保存
                if is_trading_hours or TradingHours.is_session_end():
                    self.last_session_price = current_price
                    self.last_session_time = current_time
                    self.last_session_type = session_type

                # チャート生成用のデータ取得(直近60分)
                price_history = db.query(PriceHistory)\
                    .filter(PriceHistory.timestamp >= datetime.now() - timedelta(hours=2))\
                    .order_by(PriceHistory.timestamp.asc())\
                    .all()

                # tempディレクトリが存在しない場合は作成
                os.makedirs("temp", exist_ok=True)

                # Discord用とウェブサイト用のチャートパスを設定
                timestamp = int(now.timestamp())
                
                # 複数の時間枠のチャートを生成
                chart_paths = {}
                for minutes, chart_type in [(10, "short"), (30, "medium"), (60, "long")]:
                    chart_path = f"temp/price_chart_{chart_type}_{timestamp}.png"
                    website_chart_path = f"temp/website_chart_{chart_type}.png"
                    
                    # チャート生成 - 異なる時間枠で
                    ChartBuilder.create_price_chart(price_history, website_chart_path, minutes=minutes)
                    
                    # 同じパスをコピー（Discordチャート用）
                    if os.path.exists(website_chart_path):
                        import shutil
                        shutil.copy2(website_chart_path, chart_path)
                        
                    # パスを保存
                    chart_paths[chart_type] = chart_path

                # WebSocket用のデータ準備
                try:
                    with open(f"temp/website_chart_long.png", "rb") as f:
                        chart_base64 = base64.b64encode(f.read()).decode('utf-8')

                    # マーケットデータを作成
                    market_data = {
                        "type": "market_update",
                        "data": {
                            "chart": chart_base64,
                            "current_price": float(current_price),
                            "change_rate": float(price_change),
                            "volume_24h": int(volume_24h),
                            "timestamp": int(now.timestamp())
                        }
                    }

                    # マーケットデータを更新
                    from src.websocket.market_socket import data_manager
                    data_manager.update_data(market_data)
                    self.logger.info("マーケットデータを更新しました")
                except ImportError:
                    self.logger.warning("WebSocketモジュールのdata_managerが利用できません")
                except Exception as e:
                    self.logger.error(f"マーケットデータ更新エラー: {str(e)}")

                # 古いチャートのクリーンアップを実行
                await self.cleanup_old_charts()

                # チャートチャンネルが設定されているか確認
                channel_id = self.config.chart_channel_id
                if not channel_id:
                    self.logger.warning("チャートチャンネルIDが設定されていません")
                    return

                channel = self.bot.get_channel(int(channel_id))
                if not channel:
                    self.logger.warning(f"チャートチャンネル({channel_id})が見つかりません")
                    return

                # Embedの作成
                embed = discord.Embed(
                    title="🪙 PARC/JPY チャート (60分間)",
                    description="⏱️: 10分チャート\n🕒: 30分チャート\n🕐: 60分チャート",
                    color=discord.Color.green() if price_change >= 0 else discord.Color.red(),
                    timestamp=datetime.now()
                )

                embed.add_field(name="💰 現在値", value=f"¥{current_price:,.2f}", inline=True)
                embed.add_field(name="📊 変動率", value=f"{price_change:+.2f}%", inline=True)
                embed.add_field(name="📈 出来高(24h)", value=f"{volume_24h:,} PARC", inline=True)

                # デフォルトは60分チャート
                file = discord.File(chart_paths["long"], filename="chart.png")
                embed.set_image(url="attachment://chart.png")

                # 古いメッセージを削除して新しいメッセージを送信
                async for message in channel.history(limit=1):
                    if message.author == self.bot.user:
                        await message.delete()
                        break

                message = await channel.send(file=file, embed=embed)
                
                # リアクション追加
                await message.add_reaction("⏱️")  # 10分
                await message.add_reaction("🕒")  # 30分
                await message.add_reaction("🕐")  # 60分

            except Exception as e:
                self.logger.error(f"チャート更新エラー: {e}", exc_info=True)
                if db and db.is_active:
                    db.rollback()
            finally:
                if db:
                    db.close()
                # 計算完了フラグをリセット
                self._calculating_price = False

            # 取引時間外の場合は、リアルタイムチャートの更新をスキップ
            if not is_trading_hours:
                self.logger.info("取引時間外: 価格を記録しましたが、リアルタイムチャートの更新はスキップします")
                # リアルタイムチャート更新のスキップ
                self._calculating_price = False
                return

            await self.cleanup_old_charts()

        except Exception as e:
            # 全体のエラーハンドリング
            if hasattr(self, '_calculating_price'):
                self._calculating_price = False  # エラー時もフラグをリセット
            self.logger.error(f"価格情報更新エラー: {e}", exc_info=True)

    async def _notify_session_open(self, session_name):
        """取引セッション開始時の始値通知"""
        try:
            # イベントチャンネルを取得
            channel_id = self.config.event_channel_id
            if not channel_id:
                self.logger.warning("イベントチャンネルIDが設定されていません")
                return
                
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                self.logger.warning(f"イベントチャンネル({channel_id})が見つかりません")
                return
            
            # 最新の価格情報を取得
            db = SessionLocal()
            try:
                current_price_data = db.query(PriceHistory).order_by(PriceHistory.timestamp.desc()).first()
                
                if not current_price_data:
                    self.logger.warning("始値通知: 価格データが取得できませんでした")
                    return
                
                # 前回との比較データを取得 (昨日の終値と比較)
                yesterday = TradingHours.get_current_time().date() - timedelta(days=1)
                prev_price_data = db.query(PriceHistory)\
                    .filter(func.date(PriceHistory.timestamp) == yesterday)\
                    .order_by(PriceHistory.timestamp.desc())\
                    .first()
                
                # 変化率を計算
                if prev_price_data:
                    prev_price = prev_price_data.price
                    change_rate = ((current_price_data.price - prev_price) / prev_price) * 100
                else:
                    # 前日データがない場合は変化なしとする
                    change_rate = 0.0
                
                # 始値通知を送信
                embed = EmbedBuilder.trading_session_open(
                    session_name=session_name,
                    price=current_price_data.price,
                    change_rate=change_rate
                )
                
                self.logger.info(f"{session_name}始値通知: ¥{current_price_data.price:,.2f} (変化率: {change_rate:.2f}%)")
                await channel.send(content="|| @here ||", embed=embed)
                
            finally:
                db.close()
                
        except Exception as e:
            self.logger.error(f"始値通知エラー: {e}", exc_info=True)

    async def _notify_session_close(self, session_name):
        """取引セッション終了時の終値通知"""
        try:
            # イベントチャンネルを取得
            channel_id = self.config.event_channel_id
            if not channel_id:
                self.logger.warning("イベントチャンネルIDが設定されていません")
                return
                
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                self.logger.warning(f"イベントチャンネル({channel_id})が見つかりません")
                return
            
            # 最新の価格情報を取得
            db = SessionLocal()
            try:
                current_price_data = db.query(PriceHistory).order_by(PriceHistory.timestamp.desc()).first()
                
                if not current_price_data:
                    self.logger.warning("終値通知: 価格データが取得できませんでした")
                    return
                
                # 当日のセッション開始時の価格を取得
                today = TradingHours.get_current_time().date()
                today_start = datetime.combine(today, TradingHours.MORNING_SESSION_START).replace(tzinfo=pytz.timezone('Asia/Tokyo'))
                
                # セッションに応じた時間帯を設定
                if session_name == "前場":
                    session_start = datetime.combine(today, TradingHours.MORNING_SESSION_START).replace(tzinfo=pytz.timezone('Asia/Tokyo'))
                    session_end = datetime.combine(today, TradingHours.MORNING_SESSION_END).replace(tzinfo=pytz.timezone('Asia/Tokyo'))
                else:  # 後場
                    session_start = datetime.combine(today, TradingHours.AFTERNOON_SESSION_START).replace(tzinfo=pytz.timezone('Asia/Tokyo'))
                    session_end = datetime.combine(today, TradingHours.AFTERNOON_SESSION_END).replace(tzinfo=pytz.timezone('Asia/Tokyo'))
                
                # セッション開始時の価格を取得
                session_open_data = db.query(PriceHistory)\
                    .filter(PriceHistory.timestamp >= session_start, PriceHistory.timestamp <= session_start + timedelta(minutes=5))\
                    .order_by(PriceHistory.timestamp)\
                    .first()
                
                if session_open_data:
                    open_price = session_open_data.price
                else:
                    # セッション開始時のデータがない場合は現在の価格を使用
                    open_price = current_price_data.price
                
                # 変化量と変化率を計算
                close_price = current_price_data.price
                change_amount = close_price - open_price
                change_rate = (change_amount / open_price) * 100
                
                # セッション中の取引量を集計
                volume_data = db.query(func.sum(Transaction.amount))\
                    .filter(Transaction.created_at >= session_start, Transaction.created_at <= session_end)\
                    .filter(Transaction.transaction_type.in_(['buy', 'sell']))\
                    .scalar()
                
                volume = volume_data if volume_data else 0
                
                # 終値通知を送信
                embed = EmbedBuilder.trading_session_close(
                    session_name=session_name,
                    price=close_price,
                    change_amount=abs(change_amount),
                    change_rate=change_rate,
                    volume=volume
                )
                
                self.logger.info(f"{session_name}終値通知: ¥{close_price:,.2f} (変化: {change_amount:+,.2f} / {change_rate:+.2f}%) 取引量: {volume:,.2f} PARC")
                await channel.send(content="|| @here ||", embed=embed)
                
            finally:
                db.close()
                
        except Exception as e:
            self.logger.error(f"終値通知エラー: {e}", exc_info=True)


    @tasks.loop(minutes=5)
    async def check_daily_event(self):
        """定期的なイベントチェック"""
        if not self.bot.is_ready():
            return
            
        try:
            await self.event_manager.check_daily_event()
        except Exception as e:
            self.logger.error(f"Daily event check error: {str(e)}")

    @check_daily_event.before_loop
    async def before_check_daily_event(self):
        """イベントチェックタスク開始前の処理"""
        await self.bot.wait_until_ready()

    @tasks.loop(hours=1)
    async def save_manipulation_flags(self):
        """操作検出フラグを定期的に保存"""
        try:
            if hasattr(self.bot, 'price_calculator'):
                self.bot.price_calculator._save_permanent_flags()
                self.logger.info("市場操作検出フラグを定期保存しました")
        except Exception as e:
            self.logger.error(f"定期保存エラー: {str(e)}")

    @tasks.loop(minutes=15)  # 15分ごとに保存
    async def save_flags_periodically(self):
        """操作検出フラグを定期的に保存"""
        try:
            if hasattr(self.bot, 'price_calculator'):
                self.bot.price_calculator._save_permanent_flags()
                self.logger.info("操作検出フラグを定期保存しました")
        except Exception as e:
            self.logger.error(f"フラグの定期保存に失敗しました: {e}")

    @tasks.loop(minutes=5)
    async def save_permanent_flags(self):
        """永続的なフラグを定期的に保存"""
        try:
            if hasattr(self.bot, "price_calculator"):
                self.bot.price_calculator._save_permanent_flags()
                self.logger.info("永続フラグを定期的に保存しました")
        except Exception as e:
            self.logger.error(f"永続フラグの定期保存エラー: {e}")

    @tasks.loop(minutes=10)
    async def backup_permanent_flags(self):
        """永続フラグを定期的に保存"""
        try:
            if hasattr(self.bot, 'price_calculator') and self.bot.price_calculator:
                self.bot.price_calculator._save_permanent_flags()
                self.logger.info("永続フラグの定期バックアップを実行しました")
        except Exception as e:
            self.logger.error(f"永続フラグバックアップエラー: {str(e)}")

    @tasks.loop(seconds=10)
    async def update_random_prices(self):
        """ランダム価格を10秒ごとに更新"""
        if not self.bot.is_ready():
            return
        
        try:
            # 取引時間外は価格更新をスキップ
            # セッション開始・終了直後も含めて完全にスキップ
            if not TradingHours.is_trading_hours():
                # 1分に1回程度だけログ出力
                if datetime.now().second % 60 == 0:
                    self.logger.info("取引時間外のため、リアルタイム価格更新をスキップします")
                return
                
            # price_calculatorインスタンスを取得
            price_calculator = self.bot.price_calculator if hasattr(self.bot, 'price_calculator') else PriceCalculator(self.bot)
            
            # チャートビルダーからの補間価格を優先
            from src.utils.chart_builder import ChartBuilder
            current_price = ChartBuilder.generate_interpolated_price()
            
            # 補間価格が生成できない場合は、PriceCalculatorから制限されたランダム価格を取得
            if current_price is None:
                current_price = price_calculator.generate_random_price()
                self.logger.info(f"補間価格が生成できないため、制限付きランダム価格を使用: ¥{current_price:,.2f}")
            else:
                self.logger.info(f"補間価格を使用: ¥{current_price:,.2f}")
            
            # 10秒ごとの履歴を更新
            ChartBuilder.update_realtime_history(current_price)
            self.logger.info(f"リアルタイム履歴を更新しました: ¥{current_price:,.2f} (履歴数: {len(ChartBuilder._realtime_history)})")
            
            # Botのステータスを更新
            await self.bot.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name=f"PARC ¥{current_price:,.2f}"
                )
            )
            
            # リアルタイムチャート更新
            await self._update_realtime_chart(current_price, price_calculator)
            
        except Exception as e:
            self.logger.error(f"ランダム価格更新エラー: {str(e)}", exc_info=True)

    async def _update_realtime_chart(self, current_price, price_calculator):
        """リアルタイムチャートの更新"""
        if not self.bot.is_ready():
            return
            
        try:
            # チャート更新フラグの確認
            if hasattr(self, '_updating_chart') and self._updating_chart:
                self.logger.debug("チャート更新が既に実行中です。スキップします。")
                return
                
            # チャート更新中フラグを設定
            self._updating_chart = True
            
            # リアルタイムチャートチャンネルを取得
            realtime_channel_id = self.config.realtime_chart_channel_id
            if not realtime_channel_id:
                self.logger.warning("リアルタイムチャートチャンネルIDが設定されていません")
                self._updating_chart = False
                return

            channel = self.bot.get_channel(int(realtime_channel_id))
            if not channel:
                self.logger.warning(f"リアルタイムチャートチャンネル({realtime_channel_id})が見つかりません")
                self._updating_chart = False
                return
                
            # 基本価格情報を取得
            db = SessionLocal()
            try:
                # 直近の履歴データを取得
                price_history = db.query(PriceHistory)\
                    .order_by(PriceHistory.timestamp.desc())\
                    .limit(60).all()  # 60件のデータを取得
                    
                price_history.reverse()  # 古い順に並べ替え
                
                if not price_history:
                    self.logger.warning("価格履歴データがありません")
                    self._updating_chart = False
                    return
                
                # チャート生成
                from src.utils.chart_builder import ChartBuilder
                ChartBuilder.initialize()  # 初期化確認
                
                # 一時フォルダの確認
                os.makedirs("temp", exist_ok=True)
                
                # タイムスタンプ
                timestamp = int(time.time())
                chart_path = f"temp/realtime_chart_{timestamp}.png"
                
                # リアルタイムチャート生成
                ChartBuilder.create_realtime_chart(
                    price_history, 
                    current_price, 
                    price_calculator.base_price, 
                    price_calculator.price_range,
                    chart_path
                )
                
                # リアルタイムチャート表示用のEmbed
                now = datetime.now()
                embed = discord.Embed(
                    title="PARC/JPY リアルタイムチャート",
                    description="10秒ごとに更新される取引価格",
                    color=discord.Color.gold() if current_price >= price_calculator.base_price else discord.Color.red(),
                    timestamp=now
                )
                
                # フィールド: 現在値
                embed.add_field(name="💰 現在値", value=f"¥{current_price:,.2f}", inline=True)
                
                # 価格帯対比の変化率
                change_percent = ((current_price - price_calculator.base_price) / price_calculator.base_price) * 100
                embed.add_field(name="📊 基準比", value=f"{change_percent:+.2f}%", inline=True)
                
                # 価格帯情報
                embed.add_field(
                    name="⚖️ 価格帯", 
                    value=f"¥{price_calculator.price_range['min']:,.2f} 〜 ¥{price_calculator.price_range['max']:,.2f}", 
                    inline=True
                )
                
                # チャート画像の添付
                file = discord.File(chart_path, filename="chart.png")
                embed.set_image(url="attachment://chart.png")
                
                # ページフッター
                embed.set_footer(text="10分間のみデータ表示 • 10秒ごと更新")
                
                # 古いメッセージを削除して新しいメッセージを送信
                try:
                    async for message in channel.history(limit=1):
                        if message.author == self.bot.user:
                            await message.delete()
                            break
                except Exception as e:
                    self.logger.error(f"古いメッセージの削除エラー: {str(e)}")
                
                await channel.send(file=file, embed=embed)
                
            except Exception as e:
                self.logger.error(f"リアルタイムチャート更新エラー: {str(e)}", exc_info=True)
            finally:
                db.close()
                self._updating_chart = False  # チャート更新フラグをリセット
                
        except Exception as e:
            self._updating_chart = False  # エラー時もフラグをリセット
            self.logger.error(f"リアルタイムチャート処理エラー: {str(e)}", exc_info=True)

    @tasks.loop(minutes=5)
    async def save_price_state(self):
        """価格情報を定期的に保存"""
        try:
            if hasattr(self.bot, 'price_calculator'):
                self.bot.price_calculator._save_price_state()
        except Exception as e:
            self.logger.error(f"価格状態の保存エラー: {e}", exc_info=True)

    async def _send_trading_notification(self, message):
        """取引時間の通知を送信する"""
        try:
            # イベントチャンネルを取得
            channel_id = self.config.event_channel_id
            if not channel_id:
                self.logger.warning("イベントチャンネルIDが設定されていません")
                return
                
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                self.logger.warning(f"イベントチャンネル({channel_id})が見つかりません")
                return
            
            # 通知メッセージを送信
            await channel.send(message)
            self.logger.info(f"取引時間通知を送信: {message}")
            
        except Exception as e:
            self.logger.error(f"取引時間通知エラー: {e}", exc_info=True)


    

async def setup(bot):
    await bot.add_cog(ParaccoliTasks(bot))