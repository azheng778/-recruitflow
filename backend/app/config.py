from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
load_dotenv(PROJECT_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env", override=True)


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _optional_secret(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    if not value or value.lower() in {"replace-me", "change-me", "your-api-key"}:
        return None
    return value


_configured_llm_model = os.getenv("LLM_MODEL", "qwen3.7-max-2026-06-08").strip()
_is_deepseek_model = _configured_llm_model.lower().startswith("deepseek")


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "RecruitFlow")
    app_env: str = os.getenv("APP_ENV", "development")
    debug: bool = _bool("DEBUG")
    timezone: str = os.getenv("APP_TIMEZONE", "Asia/Shanghai")
    secret_key: str = os.getenv("SECRET_KEY", "development-only-change-me-at-least-32-bytes")
    access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))

    db_host: str = os.getenv("DB_HOST", "localhost")
    db_port: int = int(os.getenv("DB_PORT", "3306"))
    db_name: str = os.getenv("DB_NAME", "hr_recruitment")
    db_username: str = os.getenv("DB_USERNAME", "root")
    db_password: str = os.getenv("DB_PASSWORD", "")
    db_charset: str = os.getenv("DB_CHARSET", "utf8mb4")
    test_db_name: str = os.getenv("TEST_DB_NAME", "hr_recruitment_test")
    database_url_override: str | None = os.getenv("DATABASE_URL")

    llm_api_key: str | None = (
        _optional_secret("DEEPSEEK_API_KEY") if _is_deepseek_model else _optional_secret("LLM_API_KEY")
    )
    llm_base_url: str = (
        os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
        if _is_deepseek_model
        else os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").strip()
    )
    llm_model: str = _configured_llm_model
    llm_timeout_seconds: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    llm_max_retries: int = int(os.getenv("LLM_MAX_RETRIES", "2"))
    llm_enable_thinking: bool = _bool("LLM_ENABLE_THINKING", False)
    llm_thinking_budget: int = int(os.getenv("LLM_THINKING_BUDGET", "256"))
    response_llm_enabled: bool = _bool("RESPONSE_LLM_ENABLED", True)
    response_llm_model: str | None = os.getenv("RESPONSE_LLM_MODEL", "").strip() or None
    response_llm_timeout_seconds: int = int(os.getenv("RESPONSE_LLM_TIMEOUT_SECONDS", "8"))
    response_llm_max_retries: int = int(os.getenv("RESPONSE_LLM_MAX_RETRIES", "1"))
    response_llm_thinking_budget: int = int(os.getenv("RESPONSE_LLM_THINKING_BUDGET", "128"))

    agent_v2_enabled: bool = _bool("AGENT_V2_ENABLED", True)
    agent_v2_shadow_mode: bool = _bool("AGENT_V2_SHADOW_MODE", False)
    agent_memory_enabled: bool = _bool("AGENT_MEMORY_ENABLED", True)
    agent_llm_router_enabled: bool = _bool(
        "AGENT_LLM_ROUTER_ENABLED", os.getenv("APP_ENV", "development") != "test"
    )
    agent_read_confidence: float = float(os.getenv("AGENT_READ_CONFIDENCE", "0.75"))
    agent_write_confidence: float = float(os.getenv("AGENT_WRITE_CONFIDENCE", "0.85"))
    agent_recent_message_limit: int = int(os.getenv("AGENT_RECENT_MESSAGE_LIMIT", "12"))
    agent_max_tool_steps: int = int(os.getenv("AGENT_MAX_TOOL_STEPS", "3"))
    agent_prompt_version: str = os.getenv("AGENT_PROMPT_VERSION", "recruitflow-agent-v2.0")
    agent_trace_enabled: bool = _bool("AGENT_TRACE_ENABLED", False)
    agent_trace_dir: Path = Path(
        os.getenv("AGENT_TRACE_DIR", str(BACKEND_DIR / "data" / "test-artifacts"))
    )
    agent_trace_sample_rate: float = float(os.getenv("AGENT_TRACE_SAMPLE_RATE", "1.0"))
    agent_trace_sql_text: bool = _bool("AGENT_TRACE_SQL_TEXT", False)
    background_worker_enabled: bool = _bool("BACKGROUND_WORKER_ENABLED", True)

    checkpoint_path: Path = Path(
        os.getenv("LANGGRAPH_CHECKPOINT_PATH", str(BACKEND_DIR / "data" / "langgraph.sqlite"))
    )
    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", str(BACKEND_DIR / "data" / "uploads")))
    export_dir: Path = Path(os.getenv("EXPORT_DIR", str(BACKEND_DIR / "data" / "exports")))
    max_resume_size_mb: int = int(os.getenv("MAX_RESUME_SIZE_MB", "10"))
    aliyun_ocr_endpoint: str = os.getenv(
        "ALIYUN_OCR_ENDPOINT", "https://gjbsb.market.alicloudapi.com/ocrservice/advanced"
    ).strip()
    aliyun_ocr_appcode: str | None = _optional_secret("ALIYUN_OCR_APPCODE")
    aliyun_ocr_timeout_seconds: int = int(os.getenv("ALIYUN_OCR_TIMEOUT_SECONDS", "20"))
    aliyun_ocr_max_page_count: int = int(os.getenv("ALIYUN_OCR_MAX_PAGE_COUNT", "10"))

    wecom_enabled: bool = _bool("WECOM_ENABLED")
    tencent_docs_enabled: bool = _bool("TENCENT_DOCS_ENABLED")

    def database_url(self, database_name: str | None = None) -> str:
        if self.database_url_override and database_name is None:
            return self.database_url_override
        name = database_name or self.db_name
        return (
            f"mysql+pymysql://{quote_plus(self.db_username)}:{quote_plus(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{name}?charset={self.db_charset}"
        )

    def llm_extra_body(self, *, response: bool = False) -> dict[str, object]:
        """Return provider-specific request fields without leaking them across APIs."""
        if "dashscope.aliyuncs.com" not in self.llm_base_url.lower():
            return {}
        if not self.llm_enable_thinking:
            return {"enable_thinking": False}
        return {
            "enable_thinking": True,
            "thinking_budget": (
                self.response_llm_thinking_budget if response else self.llm_thinking_budget
            ),
        }

    def validate_database_boundary(self, database_name: str | None = None) -> None:
        name = database_name or self.db_name
        if name.lower() == "langchain_db":
            raise RuntimeError("RecruitFlow refuses to connect to protected database langchain_db")
        if self.app_env == "test" and name == self.db_name and name != self.test_db_name:
            raise RuntimeError("Tests must use TEST_DB_NAME, not the development database")

    def ensure_directories(self) -> None:
        for path in (self.checkpoint_path.parent, self.upload_dir, self.export_dir, self.agent_trace_dir):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
