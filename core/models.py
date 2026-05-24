"""SQLAlchemy ORM models matching the frankie.db schema.

Auto-generated from existing tables.  Each model maps to a table
in the SQLite database and uses the same column names/types.
"""
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, ForeignKey, UniqueConstraint,
    CheckConstraint
)
from sqlalchemy.orm import relationship
from core.database_orm import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)
    display_name = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    last_login = Column(String)
    status = Column(String)
    trial_ends_at = Column(String)
    stripe_customer_id = Column(String)
    tenant_id = Column(Integer, ForeignKey("users.id"))

    __table_args__ = (
        CheckConstraint("role IN ('admin', 'user', 'affiliate')"),
    )


class Affiliate(Base):
    __tablename__ = "affiliates"
    code = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    phone = Column(String, default="")
    total_earnings = Column(Float, default=0)
    paid_earnings = Column(Float, default=0)
    status = Column(String, default="active")
    created_at = Column(String, nullable=False)
    last_login = Column(String)


class AffiliateLead(Base):
    __tablename__ = "affiliate_leads"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    ref_code = Column(String)
    lead_email = Column(String)
    lead_name = Column(String)
    status = Column(String, default="lead")
    commission = Column(Float)
    created_at = Column(String)


class AgentConfig(Base):
    __tablename__ = "agent_configs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    agent_id = Column(String, nullable=False)
    enabled = Column(Integer, default=1)
    model = Column(String, default="deepseek-chat")
    api_key = Column(String)
    api_base = Column(String)
    system_prompt_file = Column(String)
    task_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    last_invoked = Column(String)
    last_draft_preview = Column(String)
    status = Column(String, default="idle")
    autonomy = Column(String, default="manual")
    confidence_threshold = Column(Float, default=0.7)

    __table_args__ = (
        UniqueConstraint("user_id", "agent_id"),
    )


class AgentFeedback(Base):
    __tablename__ = "agent_feedback"
    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    agent_id = Column(String)
    feedback_type = Column(String)
    content = Column(String)
    approved = Column(Integer)
    created_at = Column(String)


class AgentFinding(Base):
    __tablename__ = "agent_findings"
    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    source_agent = Column(String)
    finding_type = Column(String)
    summary = Column(String)
    detail = Column(String)
    created_at = Column(String)
    expires_at = Column(String)


class AgentPreference(Base):
    __tablename__ = "agent_preferences"
    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    agent_id = Column(String)
    pref_key = Column(String)
    pref_value = Column(String)
    updated_at = Column(String)


class AgentSchedule(Base):
    __tablename__ = "agent_schedules"
    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    agent_id = Column(String, nullable=False)
    task_template = Column(String, nullable=False)
    cron_expr = Column(String, nullable=False)
    enabled = Column(Integer, default=1)
    language = Column(String, default="en")
    created_at = Column(String, nullable=False)
    last_run = Column(String)


class ClientDetail(Base):
    __tablename__ = "client_details"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    business_name = Column(String)
    contact_name = Column(String)
    email = Column(String)
    phone = Column(String)
    city = Column(String)
    services = Column(String)
    niche = Column(String)
    package = Column(String)
    price = Column(Float)
    affiliate_code = Column(String)
    payment_status = Column(String, default="pending")
    created_at = Column(String)
    managed_service = Column(Integer, default=0)
    managed_since = Column(String)
    site_url = Column(String)


class Commission(Base):
    __tablename__ = "commissions"
    id = Column(String, primary_key=True)
    affiliate_code = Column(String, nullable=False)
    client_email = Column(String)
    client_name = Column(String)
    amount = Column(Float, nullable=False)
    status = Column(String, default="pending")
    created_at = Column(String, nullable=False)
    paid_at = Column(String)


class ExecutionLog(Base):
    __tablename__ = "execution_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    execution_id = Column(String)
    agent_name = Column(String)
    tool_name = Column(String)
    draft_preview = Column(String)
    success = Column(Integer, default=0)
    result = Column(String)
    error = Column(String)
    timestamp = Column(String)


class Lead(Base):
    __tablename__ = "leads"
    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String)
    phone = Column(String)
    service = Column(String)
    urgency = Column(String)
    created_at = Column(String)
    status = Column(String, default="new")


class McpCredential(Base):
    __tablename__ = "mcp_credentials"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    server_name = Column(String, nullable=False)
    platform = Column(String)
    credential_key = Column(String, nullable=False)
    credential_value = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "server_name", "platform", "credential_key"),
    )


class Payout(Base):
    __tablename__ = "payouts"
    id = Column(String, primary_key=True)
    affiliate_code = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(String, default="pending")
    created_at = Column(String, nullable=False)
    processed_at = Column(String)


class PendingAction(Base):
    __tablename__ = "pending_actions"
    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    agent_name = Column(String, nullable=False)
    tool_name = Column(String, nullable=False)
    provider = Column(String, default="web")
    content = Column(String, nullable=False)
    subject = Column(String)
    status = Column(String, default="pending")
    created_at = Column(String, nullable=False)
    completed_at = Column(String)


class SchemaVersion(Base):
    __tablename__ = "schema_version"
    version = Column(Integer, primary_key=True)
    applied_at = Column(String, nullable=False)


class Thread(Base):
    __tablename__ = "threads"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    thread_id = Column(String, nullable=False)
    routed_agent = Column(String)
    agent_task = Column(String)
    agent_draft = Column(String)
    approved = Column(Integer, default=0)
    feedback = Column(String)
    final_result = Column(String)
    status = Column(String, default="pending")
    created_at = Column(String)
    updated_at = Column(String)
