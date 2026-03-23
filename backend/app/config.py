from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="Cold Chain Backend", validation_alias="APP_NAME")
    app_env: str = Field(default="dev", validation_alias="APP_ENV")
    app_debug: bool = Field(default=True, validation_alias="APP_DEBUG")
    app_host: str = Field(default="0.0.0.0", validation_alias="APP_HOST")
    app_port: int = Field(default=8000, validation_alias="APP_PORT")

    app_secret_key: str = Field(
        default="replace-with-64-char-random-secret",
        validation_alias="APP_SECRET_KEY",
    )
    jwt_secret_key: str = Field(
        default="replace-with-jwt-signing-secret",
        validation_alias="JWT_SECRET_KEY",
    )
    jwt_expire_minutes: int = Field(default=1440, validation_alias="JWT_EXPIRE_MINUTES")

    database_url: str = Field(
        default="sqlite:///./cold_chain.db",
        validation_alias="DATABASE_URL",
    )
    sql_echo: bool = Field(default=False, validation_alias="SQL_ECHO")

    mqtt_broker: str = Field(default="127.0.0.1", validation_alias="MQTT_BROKER")
    mqtt_port: int = Field(default=1883, validation_alias="MQTT_PORT")
    mqtt_username: str | None = Field(default=None, validation_alias="MQTT_USERNAME")
    mqtt_password: str | None = Field(default=None, validation_alias="MQTT_PASSWORD")
    mqtt_topic: str = Field(default="esp32/data", validation_alias="MQTT_TOPIC")
    mqtt_client_id: str = Field(
        default="cold_chain_server",
        validation_alias="MQTT_CLIENT_ID",
    )

    tdengine_host: str = Field(default="replace-with-tdengine-host", validation_alias="TDENGINE_HOST")
    tdengine_native_port: int = Field(
        default=6030,
        validation_alias="TDENGINE_NATIVE_PORT",
    )
    tdengine_rest_port: int = Field(
        default=6041,
        validation_alias="TDENGINE_REST_PORT",
    )
    tdengine_username: str = Field(
        default="replace-with-tdengine-username",
        validation_alias="TDENGINE_USERNAME",
    )
    tdengine_password: str = Field(
        default="replace-with-tdengine-password",
        validation_alias="TDENGINE_PASSWORD",
    )
    tdengine_db: str = Field(default="cold_chain", validation_alias="TDENGINE_DB")

    eth_rpc_url: str | None = Field(default=None, validation_alias="ETH_RPC_URL")
    eth_contract_address: str | None = Field(default=None, validation_alias="ETH_CONTRACT_ADDRESS")
    eth_private_key: str | None = Field(default=None, validation_alias="ETH_PRIVATE_KEY")
    eth_aes_key: str | None = Field(default=None, validation_alias="ETH_AES_KEY")

    super_admin_username: str = Field(
        default="admin",
        validation_alias="SUPER_ADMIN_USERNAME",
    )
    super_admin_password: str = Field(
        default="replace-with-strong-admin-password",
        validation_alias="SUPER_ADMIN_PASSWORD",
    )
    cors_origins: str = Field(
        default="http://localhost:5173,https://app.example.com",
        validation_alias="CORS_ORIGINS",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def tdengine_rest_url(self) -> str:
        return f"http://{self.tdengine_host}:{self.tdengine_rest_port}/rest/sql"

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [item.strip() for item in self.cors_origins.split(",") if item.strip()]
        return origins or ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
