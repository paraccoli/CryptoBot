import discord
from discord import Embed
from ..database.database import SessionLocal
from ..database.models import Company, User, CompanyMember, CompanyShare, CompanyTransaction,  CompanyEventParticipant, CompanyEvent
from ..utils.embed_builder import EmbedBuilder
from sqlalchemy.orm import Session
from ..utils.config import Config
import math



class CompanyInviteView(discord.ui.View):
    def __init__(self, company_id: int, user_id: int, role: str, share_percentage: float = None): # role を追加
        super().__init__(timeout=86400)  # 24時間で期限切れ
        self.company_id = company_id
        self.user_id = int(user_id)
        self.role = role
        self.share_percentage = share_percentage
        self.config = Config()

    async def on_timeout(self):
        """招待期限切れ時の処理"""
        for child in self.children:
            child.disabled = True
        
        try:
            await self.message.edit(
                embed=EmbedBuilder.info("この招待は期限切れです"),
                view=self
            )
        except:
            pass

    @discord.ui.button(label="承認", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        """招待承認処理"""
        print(f"[DEBUG] Button pressed by {interaction.user.id}, expected {self.user_id}")  # デバッグログ

        if interaction.user.id != self.user_id:
            await interaction.response.send_message("この招待の対象者ではありません", ephemeral=True)
            return

        db = SessionLocal()
        try:
            company_id_debug = self.company_id  # デバッグ用変数
            print(f"[DEBUG] company_id in accept function: {company_id_debug}") # company_id をログ出力

            company = db.query(Company).filter(Company.id == self.company_id).first()
            if not company:
                await interaction.response.send_message("会社情報が見つかりません", ephemeral=True)
                print(f"[ERROR] Company not found for company_id: {self.company_id}") # エラーログ追加
                return
            print(f"[DEBUG] Company found: {company.name} (ID: {company.id})") # 会社情報をログ出力


            # ユーザーが既に会社に所属していないか確認
            existing_member = db.query(CompanyMember).filter(
                CompanyMember.user_id == interaction.user.id
            ).first()
            if existing_member:
                await interaction.response.send_message("既に会社に所属しています", ephemeral=True)
                return

            # 会社メンバーとして追加
            new_member = CompanyMember(
                company_id=company.id,
                user_id=interaction.user.id,
                role=self.role # 招待時に選択されたロールを保存
            )
            db.add(new_member)

            # Discordロール付与
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("サーバーが見つかりません", ephemeral=True)
                return

            role_map = {
                "officer": self.config.executive_role_id,
                "member": self.config.employee_role_id,
                "shareholder": self.config.shareholder_role_id
            }
            discord_role = guild.get_role(role_map[self.role])
            if discord_role:
                await interaction.user.add_roles(discord_role)
                print(f"[DEBUG] {interaction.user.display_name} に {self.role} のロールを付与しました")
            else:
                print(f"[ERROR] Role {self.role} の Discord ロールが見つかりません")  # エラーログ

            # プライベートチャンネルへのアクセス権付与 (カテゴリとチャンネルが存在しない場合は作成)
            category_name = f"🏢{company.name}"
            category = discord.utils.get(guild.categories, name=category_name)
            if not category:
                # カテゴリが存在しない場合は作成
                category = await guild.create_category(category_name)
                print(f"[DEBUG] カテゴリ {category_name} を作成しました")

            channel_name = "プライベートチャンネル" # チャンネル名は固定
            private_channel = discord.utils.get(category.channels, name=channel_name)
            if not private_channel:
                # チャンネルが存在しない場合は作成
                private_channel = await category.create_text_channel(channel_name)
                print(f"[DEBUG] チャンネル {channel_name} を作成しました")

            # チャンネルへのアクセス権を設定
            await private_channel.set_permissions(interaction.user, read_messages=True, send_messages=True)
            print(f"[DEBUG] {interaction.user.display_name} にプライベートチャンネルへのアクセス権を付与しました")


            # 招待を削除
            db.query(CompanyInviteView).filter(
                CompanyInviteView.company_id == self.company_id,
                CompanyInviteView.user_id == str(self.user_id)
            ).delete()
            db.commit()


            embed = EmbedBuilder.success(
                f"{company.name} に参加しました",
                f"{interaction.user.mention} が {company.name} の {self.role} になりました", # インスタンス変数 self.role を使用
                fields=[
                    Embed("役職", self.role) # インスタンス変数 self.role を使用
                ]
            )
            await interaction.response.edit_message(embed=embed, view=None)

        except Exception as e:
            db.rollback()
            error_message = str(e) # エラーメッセージを変数に格納
            print(f"[ERROR] 参加処理中にエラー: {error_message}")  # 詳細なエラーログ
            await interaction.response.send_message(f"参加処理中にエラーが発生しました: {error_message}", ephemeral=True) # エラーメッセージをユーザーに送信
        finally:
            db.close()

class DividendApprovalView(discord.ui.View):
    def __init__(self, company_id: int, amount: int):
        super().__init__(timeout=3600)  # 1時間で期限切れ
        self.company_id = company_id
        self.amount = amount
        self.approvals = set()
        self.rejections = set()

    async def process_dividend(self, db: Session, company: Company):
        """配当金の分配処理"""
        # 株主情報を取得
        shares = db.query(CompanyShare)\
            .filter(CompanyShare.company_id == company.id)\
            .all()

        # 配当金を分配
        for share in shares:
            dividend_amount = self.amount * (share.share_percentage / 100)
            
            # ユーザーのウォレットに配当金を追加
            user = share.user
            user.wallet.parc_balance += dividend_amount

            # トランザクション記録
            tx = CompanyTransaction(
                company_id=company.id,
                transaction_type="dividend",
                amount=dividend_amount,
                description=f"Dividend payment to {user.discord_id}"
            )
            db.add(tx)

        # 会社の資産から配当金を差し引く
        company.total_assets -= self.amount

    @discord.ui.button(label="承認", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = SessionLocal()
        try:
            # 役員権限チェック
            member = db.query(CompanyMember)\
                .filter(
                    CompanyMember.company_id == self.company_id,
                    CompanyMember.user_id == interaction.user.id,
                    CompanyMember.role.in_(["representative", "officer"])
                ).first()

            if not member:
                await interaction.response.send_message(
                    "この操作には役員権限が必要です", ephemeral=True
                )
                return

            self.approvals.add(interaction.user.id)

            # 役員の過半数が承認したか確認
            total_officers = db.query(CompanyMember)\
                .filter(
                    CompanyMember.company_id == self.company_id,
                    CompanyMember.role.in_(["representative", "officer"])
                ).count()

            if len(self.approvals) > total_officers / 2:
                # 配当実行
                company = db.query(Company).get(self.company_id)
                await self.process_dividend(db, company)
                db.commit()

                embed = EmbedBuilder.success(
                    "配当金の分配完了",
                    f"{self.amount:,} PARCの配当金を分配しました"
                )
                await interaction.message.edit(embed=embed, view=None)
            else:
                await interaction.response.send_message(
                    f"承認完了（{len(self.approvals)}/{math.ceil(total_officers/2)}）",
                    ephemeral=True
                )

        except Exception as e:
            db.rollback()
            await interaction.response.send_message(
                "配当処理中にエラーが発生しました", ephemeral=True
            )
        finally:
            db.close()

    @discord.ui.button(label="否決", style=discord.ButtonStyle.red)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = SessionLocal()
        try:
            member = db.query(CompanyMember)\
                .filter(
                    CompanyMember.company_id == self.company_id,
                    CompanyMember.user_id == interaction.user.id,
                    CompanyMember.role.in_(["representative", "officer"])
                ).first()

            if not member:
                await interaction.response.send_message(
                    "この操作には役員権限が必要です", ephemeral=True
                )
                return

            self.rejections.add(interaction.user.id)

            # 役員の過半数が否決したか確認
            total_officers = db.query(CompanyMember)\
                .filter(
                    CompanyMember.company_id == self.company_id,
                    CompanyMember.role.in_(["representative", "officer"])
                ).count()

            if len(self.rejections) > total_officers / 2:
                embed = EmbedBuilder.info(
                    "配当金の否決",
                    "配当金の分配が否決されました"
                )
                await interaction.message.edit(embed=embed, view=None)
            else:
                await interaction.response.send_message(
                    f"否決完了（{len(self.rejections)}/{math.ceil(total_officers/2)}）",
                    ephemeral=True
                )

        finally:
            db.close()

class EventParticipationView(discord.ui.View):
    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id = event_id

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.green, emoji="✅")
    async def join_event(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = SessionLocal()
        try:
            # イベント情報の取得
            event = db.query(CompanyEvent).get(self.event_id)
            if not event:
                await interaction.response.send_message(
                    "イベントが見つかりません", ephemeral=True
                )
                return

            # 参加者の確認
            user = db.query(User).filter(User.discord_id == str(interaction.user.id)).first()
            existing = db.query(CompanyEventParticipant)\
                .filter(
                    CompanyEventParticipant.event_id == self.event_id,
                    CompanyEventParticipant.user_id == user.id
                ).first()

            if existing:
                await interaction.response.send_message(
                    "既にイベントに参加しています", ephemeral=True
                )
                return

            # 参加登録
            participant = CompanyEventParticipant(
                event_id=self.event_id,
                user_id=user.id
            )
            db.add(participant)
            db.commit()

            # 参加者リストの更新
            participants = db.query(CompanyEventParticipant)\
                .filter(CompanyEventParticipant.event_id == self.event_id)\
                .all()

            embed = interaction.message.embeds[0]
            participants_field = discord.EmbedField(
                name="👥 参加者",
                value="\n".join([f"<@{p.user.discord_id}>" for p in participants]),
                inline=False
            )

            # 既存の参加者フィールドを更新または追加
            fields = [f for f in embed.fields if f.name != "👥 参加者"]
            fields.append(participants_field)
            embed.clear_fields()
            for field in fields:
                embed.add_field(name=field.name, value=field.value, inline=field.inline)

            await interaction.message.edit(embed=embed)
            await interaction.response.send_message(
                "イベントへの参加を受け付けました", ephemeral=True
            )

        except Exception as e:
            db.rollback()
            await interaction.response.send_message(
                "参加処理中にエラーが発生しました", ephemeral=True
            )
        finally:
            db.close()

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel_participation(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.discord_id == str(interaction.user.id)).first()
            participant = db.query(CompanyEventParticipant)\
                .filter(
                    CompanyEventParticipant.event_id == self.event_id,
                    CompanyEventParticipant.user_id == user.id
                ).first()

            if not participant:
                await interaction.response.send_message(
                    "イベントに参加していません", ephemeral=True
                )
                return

            db.delete(participant)
            db.commit()

            # 参加者リストの更新
            participants = db.query(CompanyEventParticipant)\
                .filter(CompanyEventParticipant.event_id == self.event_id)\
                .all()

            embed = interaction.message.embeds[0]
            if participants:
                participants_field = discord.EmbedField(
                    name="👥 参加者",
                    value="\n".join([f"<@{p.user.discord_id}>" for p in participants]),
                    inline=False
                )
            else:
                participants_field = discord.EmbedField(
                    name="👥 参加者",
                    value="まだ参加者がいません",
                    inline=False
                )

            fields = [f for f in embed.fields if f.name != "👥 参加者"]
            fields.append(participants_field)
            embed.clear_fields()
            for field in fields:
                embed.add_field(name=field.name, value=field.value, inline=field.inline)

            await interaction.message.edit(embed=embed)
            await interaction.response.send_message(
                "イベントの参加をキャンセルしました", ephemeral=True
            )

        except Exception as e:
            db.rollback()
            await interaction.response.send_message(
                "キャンセル処理中にエラーが発生しました", ephemeral=True
            )
        finally:
            db.close()
