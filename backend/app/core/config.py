"""KAEOS Backend — Core Configuration"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "KAEOS"
    # Tracks the git tag series (v1.0.0 ... v1.3.0), which is the authoritative
    # release history. See the note at the top of CHANGELOG.md about the
    # never-tagged 2.x sprint numbering this supersedes.
    APP_VERSION: str = "1.9.0"
    DEBUG: bool = False
    # Safe default: auth is ENFORCED unless DEV_MODE is explicitly enabled
    # (e.g. DEV_MODE=true in a local .env). Never ship DEV_MODE=true to production.
    DEV_MODE: bool = False

    # Host-header validation (TrustedHostMiddleware). ["*"] keeps dev/test
    # permissive; production deployments MUST list their real hostnames,
    # e.g. ALLOWED_HOSTS=["kaeos.example.com","api.kaeos.example.com"].
    ALLOWED_HOSTS: list[str] = ["*"]
    # Deployment environment marker: development | staging | production.
    # DEV_MODE combined with staging/production REFUSES TO BOOT (see main.py).
    ENVIRONMENT: str = "development"
    API_PREFIX: str = "/api/v1"
    SECRET_KEY: str = ""  # REQUIRED in prod: python -c "import secrets; print(secrets.token_urlsafe(32))"
    # Dedicated at-rest data key for encrypting stored secrets (connector creds,
    # SSO client secrets, MFA secrets). Kept SEPARATE from the JWT-signing
    # SECRET_KEY so a leak of one context does not compromise the other. Falls
    # back to SECRET_KEY when unset (existing deployments keep decrypting).
    CONNECTOR_ENCRYPTION_KEY: str = ""
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

    # Commercial surface (open-core + managed cloud). Self-host default = False:
    # require_entitlement is a no-op and every feature is reachable (Apache-2.0
    # open core). Managed cloud sets True so Tenant.plan gates managed/enterprise
    # features (SSO, SCIM, webhooks, advanced connectors) and Stripe metering runs.
    KAEOS_MANAGED_CLOUD: bool = False
    # Default LLM spend ceiling provisioned for a new managed-cloud tenant, so a
    # tenant that never visits the budgets screen still has a real cap instead of
    # unlimited token burn. Self-host (managed cloud off) stays uncapped - the
    # operator runs their own inference and pays for it directly.
    DEFAULT_TENANT_TOKEN_LIMIT: int = 20_000_000
    DEFAULT_TENANT_COST_LIMIT_USD: float = 200.0
    STRIPE_API_KEY: str = ""          # sk_...; empty => Stripe provider is a no-op
    STRIPE_WEBHOOK_SECRET: str = ""   # whsec_...; authenticates /billing/webhook
    # Embedding model that drives the pgvector column width. Empty keeps the
    # existing 1536-dim behaviour; change only alongside a dim migration + re-embed.
    EMBEDDING_MODEL: str = ""

    # How often the leader-guarded metrics rollup snapshots the per-tenant
    # time-series (safe-autonomy rate, execution volume, cost). Default hourly.
    METRICS_ROLLUP_INTERVAL_MINUTES: int = 60

    # Tenant base/reporting currency (ISO 4217). The GL converts every foreign
    # journal line to this at post time and reports in it. Change only with a
    # deliberate re-statement: it does not retroactively re-convert posted lines.
    FINANCE_BASE_CURRENCY: str = "USD"

    # Optional Content-Security-Policy override for the API responses. Empty uses
    # the hardened middleware default (which already allows the cross-origin API +
    # WebSocket). Set to pin connect-src to a fixed API domain in production.
    CONTENT_SECURITY_POLICY: str = ""

    # Polymorphic tool code-generation ast-compiles LLM-authored Python into the
    # import path. It is an arbitrary-code-execution risk and is OFF by default;
    # only enable where a human-approval + real sandbox exists.
    ALLOW_POLYMORPHIC_CODEGEN: bool = False
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

    @property
    def pii_egress_fail_closed(self) -> bool:
        """Whether a PII-scrub failure must BLOCK a cloud LLM call (vs degrade).

        Under a declared data-residency policy, or when PII scrubbing is
        explicitly required, a scrubber error must fail closed — silently sending
        unscrubbed PII to a cloud provider is the worst possible outcome. Outside
        those postures the scrub degrades so a transient error never takes down
        inference.
        """
        return bool(self.DATA_RESIDENCY) or self.SCRUB_PII_BEFORE_LLM

    # Loaded (fully-burdened) hourly labor rate used to convert TENANT-SUPPLIED
    # hours-saved into a cost figure on the ROI dashboard. A documented platform
    # default (blended knowledge-worker loaded cost); override per deployment.
    #
    # This rate is only ever applied to hours a tenant actually configured. It is
    # NOT applied to a derived hours figure: hours-saved used to be a heuristic
    # (0.5h/automated task) and multiplying this rate onto it stacked a second
    # fabrication on the first. See HOURS_SAVED_NOTE in workforce/models/core.py.
    LOADED_HOURLY_RATE_USD: float = 85.0

    # Database — SQLite for local dev, PostgreSQL for production
    DATABASE_URL: str = "sqlite+aiosqlite:///./kaeos.db"
    DATABASE_URL_SYNC: str = "sqlite:///./kaeos.db"
    # Per-WORKER pool sizes. The prod image runs gunicorn -w4, so total server
    # connections = workers x (DB_POOL_SIZE + DB_MAX_OVERFLOW) PLUS the separate
    # maintenance pool. At the old 20+10 that was 4x30 = 120 alone — over Postgres'
    # default max_connections=100 — so bursts hit "remaining connection slots are
    # reserved". Sized down to 10+5 => 4x15 = 60, leaving headroom for the
    # maintenance/owner pool and admin sessions. Front with PgBouncer (transaction
    # pooling) to raise effective concurrency without more server connections.
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5

    # Service-to-service auth: the agent-mesh / cost / model-routing endpoints are
    # machine-called and were previously reachable by any authed viewer. In
    # production they now require this shared token (X-Service-Token) or an
    # elevated role. Empty in dev; REQUIRED to expose those endpoints in prod.
    SERVICE_AUTH_TOKEN: str = ""

    # Rate limiting + request limits
    RATE_LIMIT_RPM: int = 1000          # requests/minute per tenant (or IP pre-auth)
    MAX_REQUEST_BODY_BYTES: int = 10 * 1024 * 1024   # 10 MiB — reject larger (OOM guard)

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    SKILLS_CACHE_TTL: int = 300

    # SSO / OIDC (enterprise single sign-on)
    # PUBLIC_BASE_URL is this API's externally-reachable origin; the OIDC redirect
    # URI (registered at the IdP) is derived as {PUBLIC_BASE_URL}{API_PREFIX}/auth/sso/oidc/callback.
    # Leave empty to derive from the incoming request (dev only — Host-spoofable).
    PUBLIC_BASE_URL: str = ""
    # Where the browser is sent back with the freshly-minted session after a
    # successful SSO login (the SPA reads the token from the URL fragment).
    FRONTEND_BASE_URL: str = ""

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
    # Gate 3 fail-closed cap: applied when the tenant's measured confidence
    # ceiling cannot be read (Redis/DB failure, cold cache). MUST stay below
    # CONFIDENCE_AUTONOMOUS_EXEC so a lookup failure routes the decision to a
    # human instead of letting the skill's raw declared confidence stand.
    FAILSAFE_CONFIDENCE_CEILING: float = 0.30

    # Elicitation
    MAX_QUESTIONS_PER_WEEK: int = 3
    QUESTION_MIN_QUALITY: float = 0.7

    # LLM call timeouts (seconds). Cloud APIs answer in seconds; a local
    # CPU-bound Ollama model routinely needs minutes to generate a few hundred
    # tokens, so local (ollama/custom) models get their own, longer budget -
    # a 30s ceiling made every local reasoning call time out and trip the
    # circuit breaker.
    LLM_TIMEOUT_SECONDS: int = 30
    LLM_LOCAL_TIMEOUT_SECONDS: int = 240

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

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",  # Ignore unknown env vars (e.g. VITE_* frontend vars)
    )


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
        # A shipped placeholder (e.g. the Helm chart's SECRET_KEY=CHANGE_ME...) is
        # world-known on a public repo: an unrotated deploy would let anyone forge
        # admin JWTs. Reject placeholders explicitly, not just short strings.
        _PLACEHOLDERS = ("change_me", "changeme", "replace", "your-secret",
                         "your_secret", "placeholder", "example", "dev_secret",
                         "dev_admin_2026")

        def _is_placeholder(v: str) -> bool:
            low = (v or "").lower()
            return any(p in low for p in _PLACEHOLDERS)

        if not self.SECRET_KEY or len(self.SECRET_KEY) < 32 or _is_placeholder(self.SECRET_KEY):
            problems.append("SECRET_KEY must be a real, unique value (>=32 chars, no placeholder) when DEV_MODE is off.")
        if not self.ADMIN_SECRET or _is_placeholder(self.ADMIN_SECRET):
            problems.append("ADMIN_SECRET must be set to a unique, non-placeholder value when DEV_MODE is off.")
        if self.CONNECTOR_ENCRYPTION_KEY and _is_placeholder(self.CONNECTOR_ENCRYPTION_KEY):
            problems.append("CONNECTOR_ENCRYPTION_KEY must not be a placeholder when DEV_MODE is off.")
        if self.ADMIN_PASSWORD and (len(self.ADMIN_PASSWORD) < 12 or _is_placeholder(self.ADMIN_PASSWORD)):
            problems.append("ADMIN_PASSWORD must be a strong, non-placeholder value (>=12 chars) when DEV_MODE is off.")
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
