from datetime import datetime, time, timedelta
import pytz

class TradingHours:
    """取引時間を管理するクラス"""
    
    # 取引時間の設定
    MORNING_SESSION_START = time(9, 0)   # 前場開始: 9:00
    MORNING_SESSION_END = time(11, 30)   # 前場終了: 11:30
    AFTERNOON_SESSION_START = time(12, 30)  # 後場開始: 12:30
    AFTERNOON_SESSION_END = time(15, 30)  # 後場終了: 15:30
    
    # 通知タイミング
    NOTIFICATION_BEFORE = 5  # 開始/終了の5分前に通知
    
    # セッション開始・終了判定の許容時間（秒）
    SESSION_TRANSITION_TOLERANCE = 60  # 1分以内
    
    @classmethod
    def get_current_time(cls):
        """現在の日本時間を取得"""
        jst = pytz.timezone('Asia/Tokyo')
        return datetime.now(jst)
    
    @classmethod
    def is_trading_hours(cls):
        """現在が取引時間内かどうかを判定"""
        current_time = cls.get_current_time().time()
        
        # 前場（9:00-11:30）または後場（12:30-15:30）の時間内か確認
        morning_session = (cls.MORNING_SESSION_START <= current_time < cls.MORNING_SESSION_END)
        afternoon_session = (cls.AFTERNOON_SESSION_START <= current_time < cls.AFTERNOON_SESSION_END)
        
        return morning_session or afternoon_session
    
    @classmethod
    def get_session_name(cls):
        """現在の取引セッション名を取得（前場/後場/時間外）"""
        if not cls.is_trading_hours():
            return "取引時間外"
            
        current_time = cls.get_current_time().time()
        if cls.MORNING_SESSION_START <= current_time < cls.MORNING_SESSION_END:
            return "前場"
        else:
            return "後場"
    
    @classmethod
    def get_next_event(cls):
        """次の取引イベント（開始/終了）とその時間を取得"""
        current_datetime = cls.get_current_time()
        current_time = current_datetime.time()
        
        # 今日の日付
        today = current_datetime.date()
        
        # 各イベント時刻を今日の日付と組み合わせて作成
        morning_start = datetime.combine(today, cls.MORNING_SESSION_START).replace(tzinfo=current_datetime.tzinfo)
        morning_end = datetime.combine(today, cls.MORNING_SESSION_END).replace(tzinfo=current_datetime.tzinfo)
        afternoon_start = datetime.combine(today, cls.AFTERNOON_SESSION_START).replace(tzinfo=current_datetime.tzinfo)
        afternoon_end = datetime.combine(today, cls.AFTERNOON_SESSION_END).replace(tzinfo=current_datetime.tzinfo)
        
        # 現在時刻が各イベント時刻より前かどうか確認し、次のイベントを特定
        if current_time < cls.MORNING_SESSION_START:
            return ("morning_start", morning_start)
        elif current_time < cls.MORNING_SESSION_END:
            return ("morning_end", morning_end)
        elif current_time < cls.AFTERNOON_SESSION_START:
            return ("afternoon_start", afternoon_start)
        elif current_time < cls.AFTERNOON_SESSION_END:
            return ("afternoon_end", afternoon_end)
        else:
            # 翌日の前場開始を返す
            next_day = today + timedelta(days=1)
            next_morning_start = datetime.combine(next_day, cls.MORNING_SESSION_START).replace(tzinfo=current_datetime.tzinfo)
            return ("morning_start", next_morning_start)
    
    @classmethod
    def get_minutes_to_next_event(cls):
        """次のイベントまでの分数を取得"""
        _, next_event_time = cls.get_next_event()
        current_time = cls.get_current_time()
        
        # 時間差を分に変換
        delta = next_event_time - current_time
        return int(delta.total_seconds() / 60)
    
    @classmethod
    def should_notify_before_event(cls):
        """イベント開始前の通知タイミングかどうかを確認"""
        minutes_to_next = cls.get_minutes_to_next_event()
        return minutes_to_next == cls.NOTIFICATION_BEFORE

    @classmethod
    def get_next_session_start(cls):
        """次の取引セッション開始時間を取得"""
        current_time = cls.get_current_time().time()
        current_date = cls.get_current_time().date()
        
        if current_time < cls.MORNING_SESSION_START:
            # 今日の前場開始まで
            return datetime.combine(current_date, cls.MORNING_SESSION_START).replace(tzinfo=cls.get_current_time().tzinfo)
        elif current_time < cls.AFTERNOON_SESSION_START:
            # 今日の後場開始まで
            return datetime.combine(current_date, cls.AFTERNOON_SESSION_START).replace(tzinfo=cls.get_current_time().tzinfo)
        else:
            # 翌営業日の前場開始まで
            next_day = current_date + timedelta(days=1)
            return datetime.combine(next_day, cls.MORNING_SESSION_START).replace(tzinfo=cls.get_current_time().tzinfo)

    @classmethod
    def time_to_next_session_text(cls):
        """次のセッションまでの時間を表示用テキストで返す"""
        next_session = cls.get_next_session_start()
        now = cls.get_current_time()
        
        delta = next_session - now
        hours, remainder = divmod(delta.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if hours > 0:
            return f"あと約{int(hours)}時間{int(minutes)}分"
        else:
            return f"あと約{int(minutes)}分"
    
    @classmethod
    def is_session_start(cls, session_type="any"):
        """取引セッション開始直後かどうかを判定"""
        current_time = cls.get_current_time()
        current_seconds = current_time.hour * 3600 + current_time.minute * 60 + current_time.second
        
        # 前場開始
        if session_type in ["morning", "any"]:
            morning_start_seconds = cls.MORNING_SESSION_START.hour * 3600 + cls.MORNING_SESSION_START.minute * 60
            if abs(current_seconds - morning_start_seconds) <= cls.SESSION_TRANSITION_TOLERANCE:
                return True
                
        # 後場開始
        if session_type in ["afternoon", "any"]:
            afternoon_start_seconds = cls.AFTERNOON_SESSION_START.hour * 3600 + cls.AFTERNOON_SESSION_START.minute * 60
            if abs(current_seconds - afternoon_start_seconds) <= cls.SESSION_TRANSITION_TOLERANCE:
                return True
                
        return False
    
    @classmethod
    def is_session_end(cls, session_type="any"):
        """取引セッション終了直後かどうかを判定"""
        current_time = cls.get_current_time()
        current_seconds = current_time.hour * 3600 + current_time.minute * 60 + current_time.second
        
        # 前場終了
        if session_type in ["morning", "any"]:
            morning_end_seconds = cls.MORNING_SESSION_END.hour * 3600 + cls.MORNING_SESSION_END.minute * 60
            if abs(current_seconds - morning_end_seconds) <= cls.SESSION_TRANSITION_TOLERANCE:
                return True
                
        # 後場終了
        if session_type in ["afternoon", "any"]:
            afternoon_end_seconds = cls.AFTERNOON_SESSION_END.hour * 3600 + cls.AFTERNOON_SESSION_END.minute * 60
            if abs(current_seconds - afternoon_end_seconds) <= cls.SESSION_TRANSITION_TOLERANCE:
                return True
                
        return False
    
    @classmethod
    def get_session_type(cls):
        """現在のセッションタイプを取得（前場/後場/なし）"""
        if not cls.is_trading_hours():
            return None
            
        current_time = cls.get_current_time().time()
        if cls.MORNING_SESSION_START <= current_time < cls.MORNING_SESSION_END:
            return "morning"
        else:
            return "afternoon"

    @classmethod
    def get_session_time(cls, session_type):
        """セッションの時刻を取得する"""
        if session_type == "morning_start":
            return cls.MORNING_SESSION_START
        elif session_type == "morning_end":
            return cls.MORNING_SESSION_END
        elif session_type == "afternoon_start":
            return cls.AFTERNOON_SESSION_START
        elif session_type == "afternoon_end":
            return cls.AFTERNOON_SESSION_END
        else:
            return None