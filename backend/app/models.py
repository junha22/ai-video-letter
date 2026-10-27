from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    kakao_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    parent: Mapped["ParentProfile | None"] = relationship(back_populates="user", uselist=False)


class AccountCredential(Base):
    """Separate credentials preserve legacy account IDs and their content."""

    __tablename__ = "account_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AuthSession(Base):
    """Only the hash of the random cookie session identifier is stored."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    auth_method: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class AuthRateLimit(Base):
    """Short-lived shared counters; hashed keys contain no raw email or IP."""

    __tablename__ = "auth_rate_limits"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class ParentProfile(Base):
    """MVP는 자녀 1명 : 부모님 1명. 가족 그룹은 확장 단계에서 별도 테이블로 분리한다."""

    __tablename__ = "parent_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    nickname: Mapped[str] = mapped_column(String(20))  # 호칭: 엄마, 할머니 ...
    relation: Mapped[str] = mapped_column(String(20))  # 어머니, 할머니 ...
    phone: Mapped[str] = mapped_column(String(20))
    # 부모님이 자녀를 부르는 이름. 카카오 닉네임 대신 대본과 시청 페이지에 쓴다
    child_call_name: Mapped[str] = mapped_column(String(20), default="")
    # 평소 부모님께 쓰는 말투: 반말 | 존댓말 | ""(정하지 않음 → 메모 어미로 판단)
    speech_level: Mapped[str] = mapped_column(String(10), default="")
    tone_examples: Mapped[str] = mapped_column(Text, default="")  # 평소 자녀가 보내는 메시지 예시
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="parent")

    @property
    def child_name(self) -> str:
        return self.child_call_name or self.user.name


class Consent(Base):
    """동의 이력. 철회해도 행을 지우지 않고 withdrawn_at만 기록한다."""

    __tablename__ = "consents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # voice | face | parent_receive
    version: Mapped[str] = mapped_column(String(20))
    agreed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime)


class Recipient(Base):
    """Conversation recipient. The legacy onboarding profile remains the primary contact."""

    __tablename__ = "recipients"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    legacy_parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("parent_profiles.id", ondelete="SET NULL"), unique=True
    )
    nickname: Mapped[str] = mapped_column(String(20))
    relation: Mapped[str] = mapped_column(String(20))
    phone: Mapped[str] = mapped_column(String(20), default="")
    child_call_name: Mapped[str] = mapped_column(String(20), default="")
    speech_level: Mapped[str] = mapped_column(String(10), default="")
    tone_examples: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship()

    @property
    def child_name(self) -> str:
        return self.child_call_name or self.user.name


class VoiceProfile(Base):
    __tablename__ = "voice_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    # recording -> processing -> ready (zero-shot 사용 가능) / failed
    status: Mapped[str] = mapped_column(String(20), default="recording")
    sentences: Mapped[list] = mapped_column(JSON)  # text, legacy kind, category, hint, guide, focus
    reference_path: Mapped[str | None] = mapped_column(String(500))
    # TTS_PROVIDER=wemeet: TTS 서버에 등록한 목소리. 다시 녹음할 때마다 새 id를 쓴다
    tts_voice_id: Mapped[str | None] = mapped_column(String(64))
    tts_registered_at: Mapped[datetime | None] = mapped_column(DateTime)
    # S3GEN_TRAINING: queued -> training -> applied(어댑터 사용) / skipped(기본 목소리가 같거나 나음, 녹음 부족) / failed
    s3gen_status: Mapped[str | None] = mapped_column(String(20))
    s3gen_adapter_path: Mapped[str | None] = mapped_column(String(500))  # 적용한 어댑터. TTS 서버에 다시 등록할 때 같이 올린다
    s3gen_report: Mapped[dict | None] = mapped_column(JSON)  # 분할, 학습 결과, 유사도 비교, 판단 이유
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class VoiceSample(Base):
    __tablename__ = "voice_samples"
    __table_args__ = (UniqueConstraint("user_id", "index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(String(500))
    duration: Mapped[float] = mapped_column(Float)
    speech_db: Mapped[float] = mapped_column(Float)
    snr_db: Mapped[float] = mapped_column(Float)
    ok: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    path: Mapped[str] = mapped_column(String(500))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    face: Mapped[list] = mapped_column(JSON)  # [x, y, w, h]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Message(Base):
    """영상 편지 1건. 누가 어떤 목소리로 무슨 내용을 만들었는지 남는 생성 로그 역할도 한다."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("parent_profiles.id", ondelete="CASCADE"))
    recipient_id: Mapped[int | None] = mapped_column(ForeignKey("recipients.id", ondelete="CASCADE"), index=True)
    voice_profile_id: Mapped[int | None] = mapped_column(Integer)
    memo: Mapped[str] = mapped_column(Text)
    template: Mapped[str] = mapped_column(String(20))
    # AI가 만든 후보 [{"style", "label", "script", "source"}]와 자녀가 고른 분위기 (선호 데이터)
    candidates: Mapped[list | None] = mapped_column(JSON)
    chosen_style: Mapped[str | None] = mapped_column(String(20))
    speech_level: Mapped[str | None] = mapped_column(String(10))  # 이 메시지 후보를 쓴 말투
    # 후보를 만들 때 넣은 최근 대화 {"previous_script", "replies": [...]}. 부모님 답글이 없었으면 None.
    # 화면의 사실 경고도 같은 답글을 기준으로 계산하려고 남긴다
    script_context: Mapped[dict | None] = mapped_column(JSON)
    script: Mapped[str] = mapped_column(Text, default="")
    script_source: Mapped[str] = mapped_column(String(20), default="llm")  # llm | fallback | edited
    # draft -> generating -> ready -> approved -> sent -> viewed / failed / deleted
    status: Mapped[str] = mapped_column(String(20), default="draft")
    audio_path: Mapped[str | None] = mapped_column(String(500))
    tts_seed: Mapped[int | None] = mapped_column(Integer)  # 같은 seed로 다시 만들면 같은 음성이 나온다
    emotion: Mapped[str | None] = mapped_column(String(20))  # 영상 만들 때 사용자가 고른 표정 (video.EMOTIONS)
    video_path: Mapped[str | None] = mapped_column(String(500))
    poster_path: Mapped[str | None] = mapped_column(String(500))
    captions: Mapped[list | None] = mapped_column(JSON)
    duration: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    rendered_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime)

    parent: Mapped[ParentProfile] = relationship()
    recipient: Mapped[Recipient | None] = relationship()


class SeniorReply(Base):
    __tablename__ = "senior_replies"
    __table_args__ = (
        UniqueConstraint("recipient_id", "client_id", name="uq_reply_recipient_client"),
        Index("ix_reply_recipient_created", "recipient_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("recipients.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    share_link_id: Mapped[int | None] = mapped_column(ForeignKey("share_links.id", ondelete="SET NULL"))
    client_id: Mapped[str] = mapped_column(String(80))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class MonthlyPortfolio(Base):
    __tablename__ = "monthly_portfolios"
    __table_args__ = (UniqueConstraint("recipient_id", "month", name="uq_portfolio_recipient_month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("recipients.id", ondelete="CASCADE"), index=True)
    month: Mapped[str] = mapped_column(String(7))
    source_fingerprint: Mapped[str] = mapped_column(String(64))
    source_reply_count: Mapped[int] = mapped_column(Integer, default=0)
    source_latest_reply_id: Mapped[int] = mapped_column(Integer, default=0)
    report: Mapped[dict] = mapped_column(JSON)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Job(Base):
    """DB 기반 작업 큐. 나중에 Celery/Redis로 옮겨도 상태·비용 기록은 이 테이블에 남긴다."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(20))  # video | voice | voice_delete | voice_train
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    payload: Mapped[dict | None] = mapped_column(JSON)  # voice_delete, voice_train: {"voice_id": ...}
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)  # queued | running | done | failed | canceled
    stage: Mapped[str | None] = mapped_column(String(20))  # tts | video | encode
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text)
    tts_provider: Mapped[str | None] = mapped_column(String(20))
    video_provider: Mapped[str | None] = mapped_column(String(20))
    gpu_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class ShareLink(Base):
    __tablename__ = "share_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), unique=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    first_viewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    message: Mapped[Message] = relationship()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    recipient_id: Mapped[int | None] = mapped_column(ForeignKey("recipients.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(20))  # viewed | voice_ready | voice_failed
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)


class DeletionLog(Base):
    """동의 철회 시 무엇을 지웠는지 남기는 기록 (운영자 확인용)."""

    __tablename__ = "deletion_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    reason: Mapped[str] = mapped_column(String(50))
    detail: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
