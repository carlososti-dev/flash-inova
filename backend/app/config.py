from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Conexão da aplicação: usuário SEM privilégio de superusuário, para o Row Level Security valer.
    database_url: str = "postgresql+psycopg://flash_app:flash_app@localhost:5433/flash_inova"

    secret_key: str = "troque-esta-chave-em-producao-antes-de-publicar"
    session_cookie: str = "flash_session"
    session_hours: int = 8
    cookie_secure: bool = False

    # Hospital pelo subdomínio: hnsg.<base_domain>. Em desenvolvimento, também por cabeçalho X-Tenant ou ?tenant=.
    base_domain: str = "localhost"
    allow_tenant_override: bool = True

    # Montagem de links nos e-mails
    public_scheme: str = "http"
    frontend_port: str = "5173"

    email_backend: str = "console"  # console | memory
    email_from: str = "nao-responda@flashinova.local"

    storage_dir: str = "storage"
    # Anexos das ideias: fora da pasta pública /files; só saem pela API, com conferência de permissão.
    private_storage_dir: str = "storage_private"
    max_logo_bytes: int = 2 * 1024 * 1024
    max_banner_bytes: int = 5 * 1024 * 1024
    max_attachment_bytes: int = 10 * 1024 * 1024

    reset_token_hours: int = 1
    activation_token_hours: int = 72


@lru_cache
def get_settings() -> Settings:
    return Settings()
