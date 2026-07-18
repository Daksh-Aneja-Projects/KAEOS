"""
KAEOS Support Domain — Knowledge Base Models
"""
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Text, Boolean, Numeric
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class KBCategory(Base):
    """Knowledge base folder structure (e.g. Account Security, Billing FAQ)."""
    __tablename__ = "sup_kb_categories"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(128), nullable=False)
    slug = Column(String(128), nullable=False, unique=True)
    description = Column(String(256), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class KBArticle(Base):
    """Self-service articles used by customer portal and AI resolvers."""
    __tablename__ = "sup_kb_articles"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    category_id = Column(String, ForeignKey("sup_kb_categories.id"), nullable=True)

    title = Column(String(256), nullable=False)
    content_md = Column(Text, nullable=False)
    
    is_published = Column(Boolean, default=False)
    views = Column(Integer, default=0)
    helpfulness_score = Column(Numeric(4, 2), default=0.00) # 0.00 to 5.00
    
    author_id = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class ArticleFeedback(Base):
    """User ratings and comments evaluating article helpfulness."""
    __tablename__ = "sup_kb_article_feedback"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    article_id = Column(String, ForeignKey("sup_kb_articles.id"), nullable=False, index=True)

    is_helpful = Column(Boolean, nullable=False)
    comment = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
