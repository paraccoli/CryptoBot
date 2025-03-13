# Paraccoli Crypto【PARC】

Discordで動作する仮想通貨取引シミュレーションボット。実際の仮想通貨市場のように、マイニング、取引、価格変動を体験できます。

## 📌 概要

Paraccoli Crypto（PARC）は、Discord上で仮想通貨取引をシミュレーションできるボットです。ユーザーは仮想通貨「PARC」を取引しながら市場の変動を予測し、資産を増やすことを目指します。

主な機能:
- 🪙 仮想通貨「PARC」の売買シミュレーション
- 💰 ウォレット管理と送金機能
- ⛏️ マイニング機能でPARCを獲得
- 🔮 AI搭載の価格予測ツール
- 📊 詳細な統計情報とランキングシステム

## 🚀 インストール方法

```bash
# リポジトリをクローン
git clone https://github.com/paraccoli/CryptoBot.git
cd CryptoBot

# 必要パッケージのインストール
pip install -r requirements.txt

# データベースの初期設定
alembic upgrade head
```

## ⚙️ 設定方法

1. `.env`ファイルを作成し、以下の環境変数を設定してください:

```
DISCORD_TOKEN=your_discord_bot_token
CLIENT_ID=your_discord_client_id
CLIENT_SECRET=your_discord_client_secret
DISCORD_REGISTER_CHANNEL_ID=channel_id_for_registration
DISCORD_DAILY_CHANNEL_ID=channel_id_for_daily_bonus
DISCORD_MINING_CHANNEL_ID=channel_id_for_mining
DISCORD_LOG_CHANNEL_ID=channel_id_for_logs
DISCORD_CHART_CHANNEL_ID=channel_id_for_charts
DISCORD_RULES_CHANNEL_ID=channel_id_for_rules
DISCORD_HELP_CHANNEL_ID=channel_id_for_help
DISCORD_ADMIN_USER_ID=your_admin_user_id
```

2. 起動:

```bash
# 直接モジュールとして実行
python -m src.bot.main
```

## 🔧 主な機能

### 取引機能
- `/buy [数量] [価格]` - PARCの購入 (成行/指値)
- `/sell [数量] [価格]` - PARCの売却 (成行/指値)
- `/market` - 市場の現在価格を確認
- `/cancel [注文ID]` - 指値注文のキャンセル

### 資産管理
- `/wallet` - 現在のPARC/JPY残高を確認
- `/history` - 取引履歴を確認
- `/send [ユーザー] [数量]` - 他のユーザーにPARCを送金

### 価格予測
- `/predict [時間] [モデルタイプ]` - AIによる価格予測
- `/alert [価格] [条件]` - 価格が指定範囲に達したら通知

### マイニング
- `/mine` - 24時間ごとにPARCを採掘
- `/daily` - デイリーボーナスを受け取る
- `/stats` - システム全体の統計情報を表示

## 🗃️ ファイル構成

```
.
├── alembic.ini              - Alembic設定ファイル
├── migrations/              - データベーススキーマ管理
├── data/                    - 保存データ
│   ├── permanent_flags.json - 永続フラグ設定
│   └── price_state.json     - 価格状態データ
├── src/                     - ソースコード
│   ├── bot/                 - ボット機能
│   ├── database/            - データベース関連
│   ├── models/              - データモデル
│   ├── utils/               - ユーティリティ
│   └── websocket/           - Websocket機能
└── run_websocket.py         - 起動スクリプト
```


## 📄 ライセンス

LICENSE ファイルをご確認ください。

## 👥 貢献方法

1. このリポジトリをフォーク
2. 機能ブランチを作成 (`git checkout -b amazing-feature`)
3. 変更をコミット (`git commit -m 'Add amazing feature'`)
4. ブランチにプッシュ (`git push origin amazing-feature`)
5. Pull Requestを作成

---

🚀 **Let's trade and grow together!** 🚀
