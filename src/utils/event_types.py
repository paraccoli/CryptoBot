from dataclasses import dataclass
from typing import List, Dict
import random

@dataclass
class EventType:
    name: str
    description: str
    details: str
    min_change: int
    max_change: int
    is_positive: bool
    probability: float

class EventTypes:
    EVENTS = {
        "positive": [
            EventType(
                name="🏆 大規模提携",
                description="複数の大手企業とパートナーシップを締結！",
                details="大手テクノロジー企業および金融機関との戦略的パートナーシップにより、Paraccoliの利用範囲が大幅に拡大します。新たな決済システムの統合、クロスプラットフォームでのトークン利用、そしてグローバルなマーケットプレイスでの採用が期待されます。これにより、トークンの実用性と価値の向上が見込まれます。既存のユーザーには特別な特典が付与され、新規ユーザーの参入も促進されます。",
                min_change=50,
                max_change=75,
                is_positive=True,
                probability=0.3
            ),
            EventType(
                name="💫 技術革新",
                description="画期的な新機能の実装に成功！",
                details="最新のブロックチェーン技術を採用し、トランザクション処理速度が10倍に向上しました。新しいスマートコントラクト機能により、自動化された取引システムが導入され、ユーザー間の取引がより安全かつ効率的になります。さらに、AIを活用した価格予測システムも実装され、投資判断のサポートが強化されました。これらの技術革新により、プラットフォーム全体のパフォーマンスが大幅に改善されます。",
                min_change=50,
                max_change=75,
                is_positive=True,
                probability=0.35
            ),
            EventType(
                name="📈 海外取引所上場",
                description="大手取引所への上場が決定！",
                details="世界最大級の仮想通貨取引所への上場が正式に決定しました。これにより、Paraccoliの国際的な認知度が飛躍的に向上し、世界中の投資家からのアクセスが可能になります。取引所の厳格な審査をパスしたことで、プロジェクトの信頼性も証明されました。上場に伴い、新たな取引ペアが追加され、より柔軟な取引オプションが提供されます。また、機関投資家向けの特別なプログラムも開始予定です。",
                min_change=50,
                max_change=80,
                is_positive=True,
                probability=0.2
            ),
            EventType(
                name="🚀 新サービス開始",
                description="画期的な新サービスがスタート！",
                details="Paraccoliエコシステムに、分散型金融（DeFi）サービスが導入されます。これには、流動性プール、イールドファーミング、レンディングプロトコルが含まれ、トークン保有者に新たな収益機会を提供します。さらに、クロスチェーンブリッジの実装により、他のブロックチェーンネットワークとのシームレスな資産移転が可能になります。モバイルアプリケーションもリリースされ、いつでもどこでもサービスにアクセスできるようになります。",
                min_change=60,
                max_change=90,
                is_positive=True,
                probability=0.15
            ),
            EventType(
                name="🎮 ゲーム連携",
                description="大手ゲーム会社とのコラボレーション決定！",
                details="世界的な人気を誇る複数のゲームタイトルとの戦略的パートナーシップが成立しました。ゲーム内でParaccoliトークンが公式通貨として採用され、アイテム購入やキャラクターカスタマイズに使用可能になります。また、ゲーム内実績に応じた特別なNFTの発行も開始されます。これにより、ゲーマーコミュニティとの強力な連携が実現し、新たなユーザー層の開拓が期待されます。さらに、eスポーツトーナメントでの賞金としてもParaccoliが採用されることが決定しました。",
                min_change=50,
                max_change=80,
                is_positive=True,
                probability=0.25
            ),
            EventType(
                name="🎨 NFTアップデート",
                description="NFTシステムの大規模アップデート実施！",
                details="NFTプラットフォームに革新的な機能が追加されました。新たに導入された'Dynamic NFT'システムにより、NFTの属性が保有者の活動やマーケット状況に応じて進化するようになります。また、複数のNFTを組み合わせて新しい希少なNFTを作成できる'NFT Fusion'システムも実装されました。さらに、NFTのフラクショナル化により、高額NFTの共同保有が可能になり、より多くのユーザーが参加できるようになります。アートギャラリーやバーチャルミュージアムなど、NFTの展示・取引のための新しいプラットフォームも開設されます。",
                min_change=65,
                max_change=90,
                is_positive=True,
                probability=0.3
            )
        ],
        "negative": [
            EventType(
                name="⚠️ 技術的問題",
                description="一時的な技術的問題が発生しています",
                details="ネットワークの負荷増大により、一部のトランザクション処理に遅延が発生しています。技術チームが24時間体制で問題の解決に当たっており、システムの安定性向上のための緊急メンテナンスを実施中です。この間、一部の取引機能が制限される可能性があります。ユーザーの資産は安全に保管されていますが、重要な取引は問題が解決するまでお待ちいただくことを推奨します。現在の推定復旧時間は約12時間です。最新の状況はステータスページで随時更新されます。",
                min_change=-10,
                max_change=-5,
                is_positive=False,
                probability=0.3
            ),
            EventType(
                name="💢 市場混乱",
                description="市場に一時的な混乱が発生しています",
                details="グローバルな暗号資産市場の急激な変動により、一時的な価格の乱高下が発生しています。大量の売り注文により、一部の取引ペアで流動性の低下が見られます。市場の安定化を図るため、一時的に取引制限を設けさせていただく場合があります。また、レバレッジ取引の倍率を一時的に引き下げる措置を講じています。市場の正常化に向けて、流動性プロバイダーとの協力を強化し、価格の安定化を図っています。",
                min_change=-10,
                max_change=-5,
                is_positive=False,
                probability=0.25
            ),
            EventType(
                name="⛔ セキュリティ警告",
                description="システムへの不正アクセスを検知",
                details="セキュリティモニタリングシステムにより、一部のアカウントへの不正アクセスの試みが検知されました。ユーザーの資産保護のため、一時的に全アカウントの出金を停止し、セキュリティ監査を実施しています。また、二段階認証の強制適用や、IPアドレスの制限など、追加のセキュリティ対策を導入しています。現時点で資産の流出は確認されていませんが、すべてのユーザーにパスワードの変更を推奨します。セキュリティチームは24時間体制で状況を監視し、必要な対策を講じています。",
                min_change=-10,
                max_change=-5,
                is_positive=False,
                probability=0.25
            ),
            EventType(
                name="📉 規制強化",
                description="各国で厳しい規制が導入される...",
                details="複数の主要国において、暗号資産取引に関する新たな規制が導入されることが発表されました。これにより、KYC/AML要件の厳格化、取引限度額の設定、特定の取引タイプの制限などが必要となります。コンプライアンス対応のため、一部のサービスを一時的に停止または制限する必要があります。法務チームは各国の規制当局と積極的に協議を行い、必要な許認可の取得を進めています。新しい規制枠組みへの対応計画を策定中であり、詳細は順次公表されます。",
                min_change=-15,
                max_change=-10,
                is_positive=False,
                probability=0.2
            ),
            EventType(
                name="🌪 ネットワーク障害",
                description="一時的なネットワーク接続の問題が発生",
                details="主要なデータセンターでの予期せぬ障害により、一部のネットワークサービスに接続問題が発生しています。バックアップシステムへの切り替えを実施していますが、完全な復旧まで数時間を要する見込みです。この間、取引の遅延や一時的な利用制限が発生する可能性があります。技術チームは24時間体制で復旧作業に当たっており、進捗状況は定期的に更新されます。ユーザーの資産は安全に保管されていますが、重要な取引は復旧後に実施することを推奨します。",
                min_change=-15,
                max_change=-10,
                is_positive=False,
                probability=0.25
            ),
            EventType(
                name="🔥 競合参入",
                description="強力な競合サービスが市場参入...",
                details="大手テクノロジー企業が、革新的な機能を備えた競合サービスを発表しました。新サービスは、より低い手数料体系と高度な取引機能を提供し、市場シェアの獲得を目指しています。これに対応するため、当プロジェクトでは手数料体系の見直しと新機能の前倒し実装を検討しています。また、既存ユーザーへの特別優遇プログラムの導入や、ユニークな差別化要素の強化を進めています。マーケティング戦略も刷新し、プロジェクトの強みをより効果的にアピールしていく予定です。長期的な競争力強化のための投資も継続して実施します。",
                min_change=-20,
                max_change=-15,
                is_positive=False,
                probability=0.2
            )
        ]
    }

    @staticmethod
    def get_random_event() -> EventType:
        """確率重み付けを考慮してランダムなイベントを取得"""
        # ポジティブ/ネガティブをランダムに選択
        event_type = random.choice(["positive", "negative"])
        events = EventTypes.EVENTS[event_type]
        
        # 確率に基づいてイベントを選択
        total_prob = sum(event.probability for event in events)
        r = random.uniform(0, total_prob)
        
        cumulative_prob = 0
        for event in events:
            cumulative_prob += event.probability
            if r <= cumulative_prob:
                return event
                
        return events[-1]  # 万が一の場合は最後のイベントを返す

    @staticmethod
    def split_effect(total_change: float) -> List[float]:
        """イベントの効果を複数回に分割"""
        effects = []
        
        # 分割回数をランダムに決定（5-10回）
        num_splits = random.randint(5, 10)
        
        # 一回あたりの基本変動率を計算
        base_change = total_change / num_splits
        remaining_change = total_change
        
        # 初回は大きめの変動（基本変動の-1.5 ~ 2.0倍）
        initial_factor = random.uniform(-1.5, 2.0)
        first_change = min(base_change * initial_factor, remaining_change)
        effects.append(first_change)
        remaining_change -= first_change
        
        # 残りの変動を残りの回数で分配
        for i in range(num_splits - 1):
            if i == num_splits - 2:  # 最後の分割
                effects.append(remaining_change)
            else:
                # ランダムな比率で残りを分配（残額の10-30%）
                change = min(remaining_change * random.uniform(0.1, 0.3), remaining_change)
                effects.append(change)
                remaining_change -= change
        
        return effects