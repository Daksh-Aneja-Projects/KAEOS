"""KAEOS Backend — Core Configuration"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "KAEOS"
    APP_VERSION: str = "1.1.0"
    DEBUG: bool = False
    # Safe default: auth is ENFORCED unless DEV_MODE is explicitly enabled
    # (e.g. DEV_MODE=true in a local .env). Never ship DEV_MODE=true to production.
    DEV_MODE: bool = False
    # Deployment environment marker: development | staging | production.
    # DEV_MODE combined with staging/production REFUSES TO BOOT (see main.py).
    ENVIRONMENT: str = "development"
    API_PREFIX: str = "/api/v1"
    SECRET_KEY: str = ""  # REQUIRED in prod: python -c "import secrets; print(secrets.token_urlsafe(32))"
    ADMIN_SECRET: str = ""  # REQUIRED in prod: set a unique admin secret

    # ── Admin bootstrap ────────────────────────────────────────────────────
    # The first/root admin account is provisioned from these values at startup
    # instead of a hardcoded public demo login. If ADMIN_PASSWORD is empty the
    # account is NOT seeded outside DEV_MODE (no public credentials ever ship).
    ADMIN_EMAIL: str = "admin@kaeos.ai"
    ADMIN_PASSWORD: str = ""            # set in .env — this is the login password
    ADMIN_DISPLAY_NAME: str = "KAEOS Admin"
    ADMIN_TENANT: str = "tenant_acme"
    # Seed the fictional demo dataset (tenant_acme). Turn OFF for a real deploy
    # so dashboards only show genuinely ingested data.
    SEED_DEMO_DATA: bool = True

    # LLM governance safety: outside DEV_MODE, refuse to let governance gates
    # (compliance/fairness/debate/HITL) pass on SIMULATED output when no real
    # provider is reachable. Set True only for offline local testing.
    ALLOW_SIMULATED_LLM: bool = False

    # ── Security & governance hardening ─────────────────────────────────────
    # Expose Prometheus /metrics. Off by default: it leaks per-endpoint traffic
    # and should be scraped over an internal network, not the public internet.
    EXPOSE_METRICS: bool = False
    # Force-enable/disable interactive API docs (/docs, /redoc, /openapi.json).
    # None = auto (on only in a development ENVIRONMENT). Set False for prod.
    ENABLE_DOCS: bool | None = None
    # Persist a real security audit trail (auth events, RBAC denials, config
    # changes, data exports). See app/core/audit.py.
    AUDIT_LOG_ENABLED: bool = True

    # Run the singleton background loops (precog, event bus, scheduler) in THIS
    # process. Set False on every replica except one so they don't run N times
    # (N× LLM spend + races). A real deployment should use a leader lock.
    RUN_BACKGROUND_JOBS: bool = True

    # Login brute-force protection.
    LOGIN_MAX_FAILURES: int = 5          # failures before lockout
    LOGIN_LOCKOUT_SECONDS: int = 900     # 15 min lockout window
    MIN_PASSWORD_LENGTH: int = 10        # enforced on user creation

    # High-consequence action tags that ALWAYS route to a human, regardless of
    # confidence (payments, terminations, contract execution, external sends).
    HIGH_CONSEQUENCE_TAGS: list[str] = [
        "payment", "payout", "wire_transfer", "termination", "offboarding",
        "contract_execution", "external_send", "data_deletion", "irreversible",
    ]

    # ── Data protection / residency ─────────────────────────────────────────
    # "local" (or "eu"/"in") forbids sending any data to cloud LLM providers:
    # the router refuses cloud models and cloud fallback, keeping PII in-region.
    # Empty = cloud allowed (BYOK). Set per deployment for regulated data.
    DATA_RESIDENCY: str = ""
    @property
    def local_llm_only(self) -> bool:
        return self.DATA_RESIDENCY.lower() in ("local", "eu", "in", "on_prem", "on-prem")
    # Run the PII scrubber (Presidio) over any prompt before it leaves to a
    # cloud LLM provider. On by default when a residency is set; opt-in otherwise.
    SCRUB_PII_BEFORE_LLM: bool = False

    # Loaded (fully-burdened) hourly labor rate used to convert hours-saved
    # into a cost-savings estimate on the ROI dashboard. This is a documented
    # platform default (blended knowledge-worker loaded cost); override per
    # deployment/tenant. hours_saved is itself a heuristic (0.5h/automated task),
    # so cost derives transparently from the same figure rather than a second
    # unpopulated table.
    LOADED_HOURLY_RATE_USD: float = 85.0

    # Database — SQLite for local dev, PostgreSQL for production
    DATABASE_URL: str = "sqlite+aiosqlite:///./kaeos.db"
    DATABASE_URL_SYNC: str = "sqlite:///./kaeos.db"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    SKILLS_CACHE_TTL: int = 300

    # Neo4j (Graph Store)
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = ""

    # Kafka (Data Fabric L0)
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_SCHEMA_REGISTRY_URL: str = "http://localhost:8081"

    # LLM Configuration — 4-tier routing
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    LLM_MODEL_CLASSIFICATION: str = "claude-haiku-4-5-20251001"
    LLM_MODEL_EXTRACTION: str = "claude-sonnet-4-6"
    LLM_MODEL_REASONING: str = "claude-opus-4-8"
    LLM_CACHE_ENABLED: bool = True

    # Confidence Thresholds
    CONFIDENCE_AUTO_COMMIT: float = 0.85
    CONFIDENCE_VALIDATION: float = 0.60
    CONFIDENCE_AUTONOMOUS_EXEC: float = 0.82
    CONFIDENCE_SPECULATIVE_MAX: float = 0.29
    CONFIDENCE_INFERRED_MAX: float = 0.59
    CONFIDENCE_VALIDATED_PEER_MAX: float = 0.74
    CONFIDENCE_VALIDATED_DH_MAX: float = 0.84

    # Elicitation
    MAX_QUESTIONS_PER_WEEK: int = 3
    QUESTION_MIN_QUALITY: float = 0.7

    # Agent Runtime
    AGENT_SANDBOX_MEMORY_MB: int = 512
    AGENT_SANDBOX_TIMEOUT_SEC: int = 300
    AGENT_MAX_REFUNDS_PER_HOUR: int = 50
    # Register the `python_sandbox` arbitrary-code tool for agents. OFF by
    # default: it is a prompt-injection RCE surface (untrusted content can steer
    # an agent into calling it). Only enable in a trusted, isolated deployment.
    ENABLE_PYTHON_SANDBOX_TOOL: bool = False

    # Decay
    DECAY_CHECK_INTERVAL_HOURS: int = 1

    # Slack
    SLACK_BOT_TOKEN: str = ""
    SLACK_SIGNING_SECRET: str = ""

    # Temporal
    TEMPORAL_HOST: str = "localhost:7233"
    TEMPORAL_NAMESPACE: str = "kaeos"

    # TimescaleDB
    TIMESCALE_URL: str = ""  # Set in .env if using TimescaleDB

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"]

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Ignore unknown env vars (e.g. VITE_* frontend vars)


    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.DATABASE_URL

    @property
    def simulated_llm_allowed(self) -> bool:
        """Whether governance gates may pass on SIMULATED (no-provider) output.

        Allowed only for local development/testing. In any real environment a
        missing LLM provider must FAIL CLOSED (deny/HITL) rather than rubber-stamp.
        """
        return self.DEV_MODE or self.ALLOW_SIMULATED_LLM

    @property
    def is_production_like(self) -> bool:
        return self.ENVIRONMENT.lower() in ("production", "prod", "staging")

    @property
    def docs_enabled(self) -> bool:
        """Whether to serve /docs, /redoc, /openapi.json.

        Explicit ENABLE_DOCS wins; otherwise on only in a dev environment. This
        means a prod deploy that merely forgot to flip a flag does NOT hand the
        full API map to anonymous users.
        """
        if self.ENABLE_DOCS is not None:
            return self.ENABLE_DOCS
        return not self.is_production_like

    def validate_production_security(self) -> list[str]:
        """Return a list of fatal security misconfigurations when not in DEV_MODE.

        Outside DEV_MODE the app must have a real SECRET_KEY and ADMIN_SECRET so
        JWT sessions and admin endpoints are not left open. An empty list means OK.
        """
        if self.DEV_MODE:
            return []
        problems: list[str] = []
        if not self.SECRET_KEY or len(self.SECRET_KEY) < 16:
            problems.append("SECRET_KEY must be set (>=16 chars) when DEV_MODE is off.")
        if not self.ADMIN_SECRET or self.ADMIN_SECRET in ("", "dev_secret", "dev_admin_2026"):
            problems.append("ADMIN_SECRET must be set to a unique value when DEV_MODE is off.")
        problems.extend(self.validate_production_database())
        return problems

    def validate_production_database(self) -> list[str]:
        """Fatal DB misconfigurations for a production-like deployment.

        RLS — the only tenant-isolation backstop that does not depend on every
        query remembering its `.where(tenant_id==…)` — exists ONLY on Postgres
        and ONLY when the app connects as a NON-OWNER role. Refuse to run
        production on SQLite (no RLS at all). Owner-vs-non-owner is verified at
        runtime (see app/core/database.assert_rls_effective) since it needs a
        live connection.
        """
        if not self.is_production_like:
            return []
        problems: list[str] = []
        if self.is_sqlite:
            problems.append(
                "DATABASE_URL is SQLite in a production environment: SQLite has no "
                "row-level security, so tenant isolation would rely solely on "
                "application query filters. Use PostgreSQL in production."
            )
        return problems


@lru_cache()
def get_settings() -> Settings:
    return Settings()
