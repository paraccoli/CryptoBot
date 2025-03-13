from discord import Embed, Colour
import discord
from datetime import datetime, timedelta

from ..database.models import PriceHistory, Wallet
from ..database.database import SessionLocal


class EmbedBuilder:
    @staticmethod
    def success(title: str, description: str = None) -> Embed:
        embed = Embed(
            title=f"✅ {title}",
            description=description,
            color=Colour.green(),
            timestamp=datetime.now()
        )
        return embed

    @staticmethod
    def error(title: str, description: str = None) -> Embed:
        embed = Embed(
            title=f"❌ {title}",
            description=description,
            color=Colour.red(),
            timestamp=datetime.now()
        )
        return embed

    @staticmethod
    def info(title: str, description: str = None) -> Embed:
        embed = Embed(
            title=f"ℹ️ {title}",
            description=description,
            color=Colour.blue(),
            timestamp=datetime.now()
        )
        return embed

    @staticmethod
    def wallet(address: str, parc_balance: int, jpy_balance: int) -> Embed:
        """ウォレット情報のEmbed作成"""
        embed = Embed(
            title="👛 ウォレット情報",
            color=Colour.gold(),
            timestamp=datetime.now()
        )
        
        embed.add_field(
            name="💳 アドレス", 
            value=f"`{address}`", 
            inline=False
        )
        
        embed.add_field(
            name="🪙 PARC残高", 
            value=f"`{parc_balance:,}` PARC", 
            inline=True
        )
        
        embed.add_field(
            name="💹 JPY残高", 
            value=f"¥`{jpy_balance:,}`", 
            inline=True
        )
        
        if parc_balance > 0:
            # 現在の価格で換算した総資産を表示
            db = SessionLocal()
            try:
                current_price = db.query(PriceHistory)\
                    .order_by(PriceHistory.timestamp.desc())\
                    .first()
                
                if current_price:
                    total_value = jpy_balance + (parc_balance * current_price.price)
                    embed.add_field(
                        name="💰 総資産（概算）", 
                        value=f"¥`{total_value:,.0f}`", 
                        inline=False
                    )
            finally:
                db.close()
        
        embed.set_footer(text="Paraccoli Wallet • 更新")
        return embed

    @staticmethod
    def ranking(title: str, rankings: list) -> Embed:
        embed = Embed(
            title=title,
            color=Colour.gold(),
            timestamp=datetime.now()
        )
        
        if not rankings:
            embed.description = "アクティブなユーザーがいません"
            return embed
            
        for i, (user, count) in enumerate(rankings, 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, "👑")
            embed.add_field(
                name=f"{medal} {i}位: {user}",
                value=f"メッセージ数: {count:,}",
                inline=False
            )
        
        embed.set_footer(text="上位3名には報酬が配布されます")
        return embed

    @staticmethod
    def spam_warning(user_id: str, warning_count: int) -> Embed:
        embed = Embed(
            title="⚠️ スパム警告",
            description=f"<@{user_id}>のスパム行為を検出しました",
            color=Colour.yellow()
        )
        embed.add_field(
            name="警告回数",
            value=f"⚠️ {warning_count}/3",
            inline=False
        )
        embed.add_field(
            name="注意事項",
            value="連続した同一メッセージの投稿は禁止されています",
            inline=False
        )
        return embed

    @staticmethod
    def spam_penalty(user_id: str) -> Embed:
        """スパムペナルティのEmbed作成"""
        embed = Embed(
            title="⛔ スパムペナルティ",
            description=f"<@{user_id}>に-100PARCのペナルティが課されました",
            color=Colour.red()
        )
        embed.add_field(
            name="理由",
            value="継続的なスパム行為によるペナルティ",
            inline=False
        )
        embed.add_field(
            name="処罰内容",
            value="-100 PARCのペナルティ",
            inline=False
        )
        return embed

    @staticmethod
    def price_info(price_data: PriceHistory) -> Embed:
        """価格情報のEmbed作成"""
        embed = Embed(
            title="🪙 PARC 価格情報",
            color=Colour.gold() if price_data.close >= price_data.open else Colour.red(),
            timestamp=datetime.now()
        )
        
        # 価格情報
        change_percent = ((price_data.close - price_data.open) / price_data.open) * 100
        embed.add_field(
            name="💹 現在価格",
            value=f"¥ {price_data.close:,.2f}\n({change_percent:+.2f}%)",
            inline=True
        )
        
        # 取引量
        embed.add_field(
            name="📊 24h取引量",
            value=f"{price_data.volume:,.0f} PARC",
            inline=True
        )
        
        # 時価総額
        embed.add_field(
            name="💰 時価総額",
            value=f"¥ {price_data.market_cap:,.0f}",
            inline=True
        )
        
        return embed

    @staticmethod
    def create_rules_embed() -> discord.Embed:
        """ルール説明のEmbed作成"""
        embed = discord.Embed(
            title="📜 Paraccoli Cryptoのルール",
            description="Project Paraccoliへようこそ！\n快適な取引環境を維持するために以下のルールを守ってください。",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="🎮 基本ルール",
            value=(
                "• 初期資金として100,000JPYが付与されます\n"
                "• 億り人達成でゲームクリアとなります\n"
                "• クリア後は継続プレイまたはリセットが選択できます\n"
                "• 不正行為や悪質な行為は禁止です"
            ),
            inline=False
        )

        embed.add_field(
            name="💰 取引ルール",
            value=(
                "• 取引手数料は0.1%です\n"
                "• 最小取引単位は0.01PARCです\n"
                "• 指値注文は24時間有効です\n"
                "• 成行注文は即時執行されます"
            ),
            inline=False
        )

        embed.add_field(
            name="⛏️ マイニングルール",
            value=(
                "• マイニングは24時間に1回実行可能です\n"
                "• 1日の採掘上限は1,000PARCです\n"
                "• 総発行上限は1億PARCです\n"
                "• マイニング報酬は市場の状況により変動します"

            ),
            inline=False
        )

        embed.add_field(
            name="⚠️ 禁止事項",
            value=(
                "• 複数アカウントの使用\n"
                "• 自動売買ボットの使用\n"
                "• 他のユーザーへの嫌がらせ\n"
                "• 意図的な市場操作"
            ),
            inline=False
        )

        embed.set_footer(text="ルールは随時更新される場合があります")
        return embed

    @staticmethod
    def create_help_embed():
        embed = discord.Embed(
            title="ℹ️ 🌟 Paraccoli - 基本ガイド",
            description="Paraccoliを使いこなすための基本情報をご紹介します",
            color=0x2ecc71
        )

        # Paraccoliの説明
        embed.add_field(
            name="💎 Project Paraccoliとは",
            value="Project Paraccoliは、Discord上で利用できる\n仮想通貨取引シミュレーションゲームです。\nユーザーはチャット活動や取引を通じて資産を増やし、\n目標達成を目指します。",
            inline=False
        )

        # 主な特徴
        embed.add_field(
            name="🎯 主な特徴",
            value="""- チャット参加で通貨が採掘できる
- 日々のログインでボーナスがもらえる
- 取引所で売買が可能
- ユーザー間で送金できる
- AIによる価格予測機能
- 価格変動によるトレードも楽しめる""",
            inline=False
        )

        # はじめ方
        embed.add_field(
            name="🎮 はじめ方",
            value="""**1️⃣ ウォレットの作成:**
- `/register`: https://discord.com/channels/1339125839954055230/1339161155901587466で口座を開設
- 初期ボーナス: 100 PARC と 100,000 JPY獲得

**2️⃣ 通貨を増やす:**
- `/mine`: https://discord.com/channels/1339125839954055230/1339128725463105536でマイニング実行（24時間毎）
- `/daily`: https://discord.com/channels/1339125839954055230/1339846644547588176でデイリーボーナス獲得（24時間毎）
- 取引所: 売買取引

**3️⃣ 取引を始める:**
- `/buy`: PARC購入
- `/sell`: PARC売却
- `/send`: PARC送金""",
            inline=False
        )

        # 取引所の使い方
        embed.add_field(
            name="📊 取引所の使い方",
            value="""**1️⃣ 価格チェック:**
- `/market`: 現在価格を確認
- `/predictor`: AI価格予測
- https://discord.com/channels/1339125839954055230/1339129695652024391: リアルタイム更新

**2️⃣ 注文方法:**
- 成行注文: 即時実行
- 指値注文: 価格を指定
- `/cancel`: 注文キャンセル

**3️⃣ アラート設定:**
- `/alert`: 価格通知（最大3件）
- `/alerts`: 設定一覧
- `/alert_delete`: 削除""",
            inline=False
        )

        # 資産管理
        embed.add_field(
            name="💰 資産管理",
            value="""**1️⃣ 残高確認:**
- `/wallet`: 残高照会
- `/history`: 取引履歴

**2️⃣ 送金機能:**
- ウォレットアドレス指定
- Discord ID指定
- 手数料: 0.1%

**3️⃣ 取引制限:**
- 最小取引量: 0.01 PARC
- 24h上限: 1,000 PARC
- クールダウン: 1時間""",
            inline=False
        )

        # AI予測機能
        embed.add_field(
            name="🔮 AI予測機能",
            value="""**1️⃣ 予測モデル:**
- LSTM（深層学習）
- 線形回帰
- Prophet（メタ社開発）
- XGBoost（勾配ブースティング）
- アンサンブル（複合モデル）

**2️⃣ 予測設定:**
- 1-60分の範囲で予測
- 信頼度スコア付き
- グラフ表示機能""",
            inline=False
        )

        # 便利な機能
        embed.add_field(
            name="📱 便利な機能",
            value="""**1️⃣ 統計情報:**
- `/stats`: システム全体の統計

**2️⃣ 問い合わせ:**
- `/form`: 開発者連絡
- バグ報告/改善提案
- 新機能リクエスト""",
            inline=False
        )

        # 注意事項
        embed.add_field(
            name="⚠️ 注意事項",
            value="""- スパム行為は厳重に禁止されています
- 価格は需要と供給で変動します
- 取引にはリスクが伴います
- お困りの際は `/form` で問い合わせを""",
            inline=False
        )

        embed.set_footer(text=f"Last Updated: {datetime.now().strftime('%Y-%m-%d-%H:%M')}")
        return embed

    @staticmethod
    def create_words_embed():
        embed = discord.Embed(
            title="ℹ️ 📚 Paraccoli - 用語集",
            description="取引所で使用される専門用語の解説",
            color=0xe74c3c
        )

        # 基本用語
        embed.add_field(
            name="💰 基本用語",
            value="""**PARC (パラッコリー):**
- Paraccoliの略称および単位
- コミュニティ通貨の基本単位

**ウォレット (財布):**
- PARCとJPYの保管場所
- 個別のアドレスで管理

**マイニング (採掘):**
- チャット活動による報酬獲得
- https://discord.com/channels/1339125839954055230/1339128725463105536で24時間毎に実行可能
- メッセージ数に応じて変動

**デイリーボーナス:**
- 毎日受け取れる基本報酬
- https://discord.com/channels/1339125839954055230/1339846644547588176で24時間毎に実行可能
- 連続ログインでボーナス増加""",
            inline=False
        )

        # 取引用語
        embed.add_field(
            name="📈 取引用語",
            value="""**スワップ (両替):**
- PARC⇄JPYの即時交換
- 手数料0.1%が適用

**スリッページ:**
- 予想価格と実際の価格の差
- 取引時に設定可能

**約定 (やくじょう):**
- 取引が成立すること
- 条件が合致すると即時実行

**指値 (さしね):**
- 価格を指定しての注文
- 指定価格で待機""",
            inline=False
        )

        # 市場用語
        embed.add_field(
            name="📊 市場用語",
            value="""**流動性:**
- 市場での取引のしやすさ
- 取引量が多いほど高い

**ボラティリティ:**
- 価格の変動の大きさ
- 市場の不安定さを示す

**トレンド:**
- 価格の継続的な方向性
- 上昇/下降/横ばい

**サポート/レジスタンス:**
- 価格の下値/上値の目安
- 反発が起こりやすい価格帯""",
            inline=False
        )

        # システム用語
        embed.add_field(
            name="🔧 システム用語",
            value="""**バーン (焼却):**
- 取引手数料の自動消却
- 総供給量の調整機能

**ガス代 (手数料):**
- 取引時の手数料
- 全取引の0.1%

**アービトラージ:**
- 価格差を利用した取引
- 市場の効率化に貢献

**エアドロップ:**
- イベントでの報酬配布
- ランキング報酬など""",
            inline=False
        )

        embed.set_footer(text=f"Last Updated: {datetime.now().strftime('%Y-%m-%d-%H:%M')}")
        return embed

    @staticmethod
    def create_commands_embed():
        embed = discord.Embed(
            title="ℹ️ ⌨️ Paraccoli - コマンド一覧",
            description="利用可能なコマンドの詳細説明です",
            color=0x3498db
        )

        # 初期設定コマンド
        embed.add_field(
            name="🔰 初期設定コマンド(チャンネル指定)",
            value="""**/register:**
- https://discord.com/channels/1339125839954055230/1339161155901587466で実行可能
- ウォレットを作成
- 初期ボーナス100PARC と 100,000JPY付与

**/daily:**
- https://discord.com/channels/1339125839954055230/1339846644547588176で実行可能
- デイリーボーナスを受け取る
- 連続ログインで報酬増加

**/mine:**
- https://discord.com/channels/1339125839954055230/1339128725463105536で実行可能
- マイニングを実行
- チャット数に応じてPARCを採掘
- 24時間に1回実行可能""",
            inline=False
        )

        # 基本操作コマンド
        embed.add_field(
            name="💰 基本操作コマンド",
            value="""**/wallet:**
- PARC/JPY残高の確認
- 総資産の表示

    **/send <@ユーザー/ウォレットアドレス> <数量>:**
- 指定先にPARCを送金
- 手数料0.1%

    **/history:**
- 取引履歴の確認
- 直近の取引を表示""",
            inline=False
        )

        # 取引関連コマンド
        embed.add_field(
            name="📈 取引関連コマンド",
            value="""**/buy <数量> [価格]:**
- PARC購入（成行/指値）
- 価格指定で指値注文

    **/sell <数量> [価格]:**
- PARC売却（成行/指値）
- 価格指定で指値注文

    **/market:**
- 現在の価格を確認
- 24時間の変動も表示

    **/cancel <注文ID>:**
- 指値注文をキャンセル
- 複数指定可能（カンマ区切り）""",
            inline=False
        )

        # アラート関連コマンド
        embed.add_field(
            name="⏰ アラート関連コマンド",
            value="""**/alert <価格> <条件>:**
- 価格アラートを設定
- above/below指定

    **/alerts:**
- アラート一覧を表示
- 最大3件まで設定可能

    **/alert_delete <アラートID>:**
- 指定したアラートを削除""",
            inline=False
        )

        # 情報確認コマンド
        embed.add_field(
            name="📊 情報確認コマンド",
            value="""**/stats:**
- システム全体の統計
- 取引量や価格推移""",
            inline=False
        )

        # その他のコマンド
        embed.add_field(
            name="📝 その他のコマンド",
            value="""**/form <カテゴリ> <内容>:**
- 開発者への問い合わせ
- バグ報告/改善提案等""",
            inline=False
        )

        # 補足情報
        embed.add_field(
            name="ℹ️ 補足情報",
            value="""- [] は省略可能な引数を示します
- <> は必須の引数を示します""",
            inline=False
        )

        embed.set_footer(text=f"Last Updated: {datetime.now().strftime('%Y-%m-%d-%H:%M')}")
        return embed

    @staticmethod
    def market(price_history: PriceHistory) -> Embed:
        embed = Embed(
            title="📊 PARC/JPY マーケット情報",
            color=Colour.gold(),
            timestamp=datetime.now()
        )

        embed.add_field(
            name="💰 現在価格",
            value=f"¥{price_history.price:.2f}",  # 小数点第2位まで
            inline=True
        )

        embed.add_field(
            name="💴 JPY残高",
            value=f"¥{Wallet.jpy_balance:,}",  # 整数のみ
            inline=True
        )
        return embed

    @staticmethod
    def event(event_data: dict) -> Embed:
        """イベント通知用のEmbed作成"""
        embed = Embed(
            title=event_data["name"],
            description=event_data["description"],
            color=Colour.green() if event_data["is_positive"] else Colour.red(),
            timestamp=datetime.now()
        )

        # イベントの詳細情報
        if "details" in event_data:
            embed.add_field(
                name="📋 詳細情報",
                value=event_data["details"],
                inline=False
            )

        # 変動率（小数点第2位まで）
        embed.add_field(
            name="📊 予想価格変動",
            value=f"{event_data['total_change']:.2f}%",
            inline=False
        )

        # イベントの進行状況
        if "progress" in event_data:
            embed.add_field(
                name="⏳ 進行状況",
                value=f"{event_data['progress']}/2",
                inline=False
            )

        embed.set_footer(text="Paraccoli Event Notification")
        return embed

    @staticmethod
    def game_clear(user_id: str, total_assets: float) -> Embed:
        """ゲームクリア通知用のEmbed作成"""
        embed = Embed(
            title="🎉 ゲームクリア達成！",
            description=f"<@{user_id}>が資産一億円を達成してゲームをクリアしました！",
            color=Colour.gold(),
            timestamp=datetime.now()
        )

        embed.add_field(
            name="💰 総資産",
            value=f"¥{total_assets:,.0f}",
            inline=False
        )

        embed.add_field(
            name="🎮 ゲーム継続",
            value="より高い目標を目指す場合は🎮を選択",
            inline=True
        )

        embed.add_field(
            name="🔄 リセット",
            value="新規スタートする場合は🔄を選択",
            inline=True
        )

        return embed

    @staticmethod
    def create_channel_rules_embed(channel_type: str) -> discord.Embed:
        """特殊チャンネルのルール説明Embedを作成"""
        if channel_type == "mining":
            title = "⛏️ マイニングチャンネル - ルール"
            description = "このチャンネルでは `/mine` コマンドのみを使用できます"
            command = "/mine"
            color = discord.Color.gold()
        elif channel_type == "daily":
            title = "🎁 デイリーボーナスチャンネル - ルール"
            description = "このチャンネルでは `/daily` コマンドのみを使用できます"
            command = "/daily"
            color = discord.Color.green()
        elif channel_type == "register":
            title = "📝 初心者ガイドチャンネル - ルール"
            description = "このチャンネルでは `/register` コマンドのみを使用できます"
            command = "/register"
            color = discord.Color.blue()
        else:
            title = "チャンネルルール"
            description = "このチャンネルには特別なルールがあります"
            command = "指定されたコマンド"
            color = discord.Color.blurple()

        embed = discord.Embed(
            title=title,
            description=description,
            color=color
        )

        embed.add_field(
            name="⚠️ 注意事項",
            value=(
                f"- このチャンネルでは `{command}` コマンドだけが使用できます\n"
                "- その他のメッセージは自動的に削除されます\n"
                "- メッセージの連投は禁止されており、違反するとタイムアウトされます\n"
                "- 3回警告を受けると1分間のタイムアウトが適用されます"
            ),
            inline=False
        )

        embed.set_footer(text=f"最終更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        return embed

    @staticmethod
    def channel_restriction_warning(user_id: str, command_type: str, warning_count: int) -> discord.Embed:
        """チャンネル制限の警告Embedを作成"""
        embed = discord.Embed(
            title="⚠️ チャンネル制限",
            description=f"<@{user_id}> このチャンネルでは `/{command_type}` コマンドのみ使用できます",
            color=discord.Color.yellow()
        )
        embed.add_field(
            name="警告回数",
            value=f"{warning_count}/3"
        )
        return embed

    @staticmethod
    def timeout_notification(user_id: str, duration: int = 60) -> discord.Embed:
        """タイムアウト通知のEmbedを作成"""
        embed = discord.Embed(
            title="⏱️ タイムアウト",
            description=f"<@{user_id}> チャンネルルール違反により{duration}秒間タイムアウトされました",
            color=discord.Color.red()
        )
        embed.add_field(
            name="理由",
            value="複数回のチャンネルルール違反またはメッセージの連投",
            inline=False
        )
        return embed

    @staticmethod
    def create_support_embed():
        """サポートチャンネルの説明Embedを作成"""
        embed = discord.Embed(
            title="🆘 サポートチャンネルへようこそ",
            description="困ったときの質問、お問い合わせ用チャンネルです\nサーバーでわからないことがあれば経験者及び運営が回答してくれます。",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="📋 お問い合わせ方法",
            value=(
                "バグ報告、機能提案、質問等は `/form` コマンドで運営にお問合せください。\n"
                "以下のカテゴリから選択できます："
            ),
            inline=False
        )
        
        embed.add_field(
            name="カテゴリ一覧",
            value=(
                "• **バグ報告** - 不具合やエラーの報告\n"
                "• **機能提案** - 新機能や改善のアイデア\n"
                "• **質問** - 使い方や仕様についての質問\n"
                "• **その他** - 上記に当てはまらないお問い合わせ"
            ),
            inline=False
        )
        
        embed.add_field(
            name="⚠️ 注意事項",
            value=(
                "• お問い合わせはプライベートに処理されます\n"
                "• 具体的な内容を詳しく記載してください\n"
                "• スクリーンショットなどの添付が必要な場合は、その旨をお知らせください\n"
                "• 回答まで時間がかかる場合があります"
            ),
            inline=False
        )
        
        embed.set_footer(text=f"Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        return embed

    @staticmethod
    def market_manipulation_warning(manipulation_type: str, details: str) -> discord.Embed:
        """市場操作の警告Embedを作成"""
        embed = discord.Embed(
            title="⚠️ 市場操作の可能性を検出",
            description="システムが市場操作の可能性を検出しました。取引モニタリングが強化されます。",
            color=discord.Color.orange(),
            timestamp=datetime.now()
        )
        
        embed.add_field(
            name="🔍 検出タイプ",
            value=manipulation_type,
            inline=False
        )
        
        embed.add_field(
            name="📋 詳細",
            value=details,
            inline=False
        )
        
        embed.add_field(
            name="⚠️ 注意",
            value="市場操作は禁止されており、アカウント凍結などのペナルティの対象となります。",
            inline=False
        )
        
        embed.set_footer(text="Paraccoli Market Protection System")
        return embed

    @staticmethod
    def market_info(base_price, random_prices, current_random, price_range, latest_price):
        """市場情報のEmbed作成"""
        embed = discord.Embed(
            title="🪙 PARC 市場情報",
            description=f"**現在価格: ¥{current_random:,.2f}**",
            color=0x3498db
        )
        
        # 基本情報
        embed.add_field(
            name="基準価格",
            value=f"¥{base_price:,.2f}",
            inline=True
        )
        
        # 価格帯
        embed.add_field(
            name="価格変動範囲",
            value=f"¥{price_range['min']:,.2f} 〜 ¥{price_range['max']:,.2f}",
            inline=True
        )
        
        # 提示価格一覧
        price_list = "\n".join([f"• ¥{price:,.2f}" for price in random_prices])
        embed.add_field(
            name="提示価格一覧",
            value=price_list,
            inline=False
        )
        
        # 24時間の変動率
        if latest_price:
            day_ago = datetime.now() - timedelta(days=1)
            old_price = latest_price.price  # 24時間前のデータがない場合は最新のを使用
            change_rate = ((current_random - old_price) / old_price) * 100
            
            embed.add_field(
                name="24時間変動",
                value=f"{change_rate:+.2f}%",
                inline=True
            )
        
        embed.set_footer(text=f"更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        return embed

    @staticmethod
    def trading_hours_notice():
        """取引時間の案内Embedを作成"""
        embed = discord.Embed(
            title="📢 ParaccoliCrypto 取引時間のご案内",
            description="ParaccoliCrypto の取引時間は、**以下のスケジュール** に従います。\n"
                        "**時間外は注文が受け付けられない** ため、ご注意ください！",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="🕒 取引時間",
            value=(
                "📌 **前場:** **9:00 ～ 11:30**\n"
                "📌 **後場:** **12:30 ～ 15:30**\n"
                "💤 **昼休み:** **11:30 ～ 12:30（取引不可）**"
            ),
            inline=False
        )
        
        embed.add_field(
            name="💡 注意事項",
            value=(
                "💡 **取引時間外は、指値注文の設定のみ可能です！**\n"
                "🔥 **時間内にしっかりトレードして、チャンスを掴みましょう！** 🚀"
            ),
            inline=False
        )
        
        embed.set_footer(text="運営: Project Paraccoli【PARC】")
        return embed

    @staticmethod
    def trading_start_soon():
        """取引開始5分前のお知らせ"""
        embed = discord.Embed(
            title="⏳ まもなく取引開始",
            description="🚀 **5分後に ParaccoliCrypto の取引が開始されます！** 🚀\n"
                        "今のうちにマーケットを確認し、エントリーの準備をしましょう！",
            color=discord.Color.gold()
        )
        
        embed.add_field(
            name="📊 現在の市場状況をチェック！",
            value=(
                "✅ `/market` → 最新の価格を確認\n"
                "✅ `/alert` → 価格通知を設定\n"
                "✅ `/predict` → AIによる価格予測"
            ),
            inline=False
        )
        
        embed.add_field(
            name="💡 ヒント",
            value="**市場の動きを見逃さず、チャンスを掴もう！**",
            inline=False
        )
        
        embed.set_footer(text="運営: Project Paraccoli【PARC】")
        return embed

    @staticmethod
    def trading_started(session_name):
        """取引開始のお知らせ"""
        embed = discord.Embed(
            title="🚀 取引開始",
            description="📢 **現在、ParaccoliCrypto の取引が開始されました！** 📢\n"
                        "🎯 **チャンスを逃さず、トレードを始めましょう！**",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="📝 取引情報",
            value=(
                f"📌 **取引時間:** {session_name}\n"
                "📌 **現在の市場価格:** `/market` で確認\n"
                "📌 **取引のヒント:**\n"
                "- **成行注文** で即時取引\n"
                "- **指値注文** で狙った価格でエントリー\n"
                "- **AI価格予測** でトレンドをチェック"
            ),
            inline=False
        )
        
        embed.add_field(
            name="🔥 今すぐ",
            value="**今すぐ取引を開始しよう！** 🚀",
            inline=False
        )
        
        embed.set_footer(text="運営: Project Paraccoli【PARC】")
        return embed

    @staticmethod
    def trading_end_soon():
        """取引終了5分前のお知らせ"""
        embed = discord.Embed(
            title="⚠️ 取引終了5分前",
            description="📢 **あと5分で本日の取引時間が終了します！** 📢\n"
                        "💡 **ポジションの調整 & 最終取引を忘れずに！**",
            color=discord.Color.gold()
        )
        
        embed.add_field(
            name="📝 確認事項",
            value=(
                "✅ `/wallet` → 資産状況を確認\n"
                "✅ `/history` → 取引履歴をチェック\n"
                "✅ `/sell` → ポジション整理（利確 or 損切り）"
            ),
            inline=False
        )
        
        embed.add_field(
            name="⚠️ 注意",
            value=(
                "⚠️ **取引終了後は、翌営業日まで新規注文ができません！**\n"
                "🔥 **最後のチャンスを活かそう！** 🚀"
            ),
            inline=False
        )
        
        embed.set_footer(text="運営: Project Paraccoli【PARC】")
        return embed

    @staticmethod
    def trading_ended():
        """取引終了のお知らせ"""
        embed = discord.Embed(
            title="📢 取引終了",
            description="⏳ **本日の ParaccoliCrypto の取引時間が終了しました！** ⏳\n"
                        "皆さん、今日の取引お疲れさまでした！",
            color=discord.Color.dark_blue()
        )
        
        embed.add_field(
            name="📊 マーケット状況を振り返ろう！",
            value=(
                "✅ `/market` → 最終価格をチェック\n"
                "✅ `/history` → 今日の取引履歴を確認\n"
                "✅ `/predict` → 明日の価格予測を見て準備"
            ),
            inline=False
        )
        
        embed.add_field(
            name="💡 次回に向けて",
            value="**次の取引時間までに戦略を立て、次回のチャンスに備えましょう！**",
            inline=False
        )
        
        embed.set_footer(text="運営: Project Paraccoli【PARC】")
        return embed

    @staticmethod
    def trading_session_open(session_name, price, change_rate):
        """取引セッション開始時の始値通知"""
        # 価格変動に応じて色を変更
        if change_rate > 0:
            color = discord.Color.green()
            change_text = f"📈 **+{change_rate:.2f}%**"
        elif change_rate < 0:
            color = discord.Color.red()
            change_text = f"📉 **{change_rate:.2f}%**"
        else:
            color = discord.Color.light_grey()
            change_text = "**±0.00%**"
            
        embed = discord.Embed(
            title=f"🔔 {session_name}始値",
            description=f"ParaccoliCrypto の{session_name}が始まりました！\n"
                        f"始値: **¥{price:,.2f}** （前日比: {change_text}）",
            color=color
        )
        
        embed.add_field(
            name="💡 取引のヒント",
            value=(
                "✅ `/market` で最新の市場情報を確認\n"
                "✅ `/buy` で購入、`/sell` で売却\n"
                "✅ `/limit` で指値注文を設定"
            ),
            inline=False
        )
        
        embed.set_footer(text=f"取引時間: 前場 9:00～11:30 / 後場 12:30～15:30")
        return embed

    @staticmethod
    def trading_session_close(session_name, price, change_amount, change_rate, volume):
        """取引セッション終了時の終値通知"""
        # 価格変動に応じて色を変更
        if change_rate > 0:
            color = discord.Color.green()
            change_text = f"📈 **+¥{change_amount:,.2f} (+{change_rate:.2f}%)**"
        elif change_rate < 0:
            color = discord.Color.red()
            change_text = f"📉 **-¥{abs(change_amount):,.2f} ({change_rate:.2f}%)**"
        else:
            color = discord.Color.light_grey()
            change_text = "**±¥0.00 (±0.00%)**"
            
        embed = discord.Embed(
            title=f"🔔 {session_name}終値",
            description=f"ParaccoliCrypto の{session_name}が終了しました！",
            color=color
        )
        
        embed.add_field(
            name="📊 終値情報",
            value=(
                f"**¥{price:,.2f}**\n"
                f"前回比: {change_text}\n"
                f"取引量: **{volume:,.2f} PARC**"
            ),
            inline=False
        )
        
        if session_name == "前場":
            next_session = "後場は12:30から開始します。"
        else:  # 後場
            next_session = "次回の取引は明日9:00からです。"
            
        embed.add_field(
            name="⏰ 次の取引",
            value=next_session,
            inline=False
        )
        
        embed.set_footer(text=f"取引時間: 前場 9:00～11:30 / 後場 12:30～15:30")
        return embed