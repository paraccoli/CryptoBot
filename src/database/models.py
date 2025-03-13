import discord
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, BigInteger
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone, timedelta
from sqlalchemy.sql.sqltypes import Boolean
import os
import math

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    discord_id = Column(String(255), unique=True)  # 長さを指定
    created_at = Column(DateTime, default=datetime.utcnow)
    last_mining = Column(DateTime)
    message_count = Column(Integer, default=0)
    total_mined = Column(BigInteger, default=0)
    last_daily = Column(DateTime)
    login_streak = Column(Integer, default=0)
    has_cleared = Column(Boolean, default=False)  # クリアフラグを追加
    wallet = relationship("Wallet", back_populates="user", uselist=False)
    alerts = relationship("PriceAlert", back_populates="user")
    last_trade_timestamp = relationship("LastTradeTimestamp", back_populates="user", uselist=False)


class LastTradeTimestamp(Base):
    __tablename__ = "last_trade_timestamps"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=False)
    timestamp = Column(Float, nullable=False)  # UNIXタイムスタンプを使用

    user = relationship("User", back_populates="last_trade_timestamp")

class Wallet(Base):
    __tablename__ = "wallets"
    
    id = Column(Integer, primary_key=True)
    address = Column(String(255), unique=True)  # 長さを指定
    parc_balance = Column(Float, default=0)
    jpy_balance = Column(BigInteger, default=100000)
    user_id = Column(Integer, ForeignKey('users.id'))
    user = relationship("User", back_populates="wallet")
    orders = relationship("Order", back_populates="wallet")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # _parc_balanceの代わりにColumn定義を直接使用

    def update_balance(self, amount: float):
        """残高更新時に小数点第2位で切り捨て"""
        self.parc_balance = float(math.floor(self.parc_balance * 100) / 100)

class Transaction(Base):
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True)
    from_address = Column(String(255), ForeignKey('wallets.address'))
    to_address = Column(String(255), ForeignKey('wallets.address'))
    amount = Column(Float)
    fee = Column(Float)
    price = Column(Float)
    timestamp = Column(DateTime(timezone=True), default=datetime.now())
    transaction_type = Column(String(50))  # buy, sell, transfer, mining
    order_type = Column(String(50))  # market, limit
    status = Column(String(50), default='pending')  # pending, completed, cancelled

class DailyStats(Base):
    __tablename__ = "daily_stats"
    
    id = Column(Integer, primary_key=True)
    date = Column(DateTime)
    total_mined = Column(BigInteger, default=0)
    total_transactions = Column(Integer, default=0)

class PriceHistory(Base):
    __tablename__ = "price_history"
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), default=datetime.now())
    price = Column(Float)  # 現在価格（JPY）
    volume = Column(Float)  # 取引量
    market_cap = Column(Float)  # 時価総額
    high = Column(Float)  # 24時間最高値
    low = Column(Float)  # 24時間最安値
    open = Column(Float)  # 始値
    close = Column(Float)  # 終値

class Order(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True)
    wallet_address = Column(String(255), ForeignKey('wallets.address'))
    amount = Column(BigInteger)  # 注文量
    price = Column(Float)  # 指値価格
    timestamp = Column(DateTime, default=datetime.utcnow)
    order_type = Column(String(50))  # "limit" or "market"
    side = Column(String(50))  # "buy" or "sell"
    status = Column(String(50), default="pending")  # "pending", "filled", "cancelled"
    filled_amount = Column(BigInteger, default=0)  # 約定済み量
    
    # リレーション
    wallet = relationship("Wallet", back_populates="orders")

class HistoryPaginationView(discord.ui.View):
    def __init__(self, current_page: int, total_pages: int, get_page_data):
        super().__init__(timeout=60)
        self.current_page = current_page
        self.total_pages = total_pages
        self.get_page_data = get_page_data

        # 前のページボタン
        self.prev_button = discord.ui.Button(
            emoji="◀️",
            custom_id="prev",
            disabled=current_page == 1
        )
        self.prev_button.callback = self.prev_page

        # 次のページボタン
        self.next_button = discord.ui.Button(
            emoji="▶️",
            custom_id="next",
            disabled=current_page == total_pages
        )
        self.next_button.callback = self.next_page

        self.add_item(self.prev_button)
        self.add_item(self.next_button)

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page -= 1
        embed = await self.get_page_data(self.current_page)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page += 1
        embed = await self.get_page_data(self.current_page)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 1
        self.next_button.disabled = self.current_page == self.total_pages


class PriceAlert(Base):
    __tablename__ = "price_alerts"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    price = Column(Float)
    condition = Column(String(50))  # "above" or "below"
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="alerts")

class Event(Base):
    __tablename__ = "events"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255))  # 長さを指定
    description = Column(String(1000))  # 長さを指定
    change_percent = Column(Float)
    timestamp = Column(DateTime(timezone=True), default=datetime.now())