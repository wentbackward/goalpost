from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    collector_database_url: str = "postgresql+asyncpg://social:changeme@postgres:5432/social_analytics"

    # Collector auth
    collector_api_key: str = "changeme_collector_key"

    # Postiz bridge
    postiz_bridge_mode: str = "db"  # "db" or "api"
    postiz_api_key: str = ""
    database_url: str = "postgresql://social:changeme@postgres:5432/social_analytics"
    next_public_backend_url: str = "http://postiz:3000"

    # Twitter
    twitter_bearer_token: str = ""
    twitter_api_key: str = ""
    twitter_api_secret: str = ""
    twitter_access_token: str = ""
    twitter_access_token_secret: str = ""

    # LinkedIn
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_access_token: str = ""

    # Instagram
    instagram_access_token: str = ""
    instagram_business_account_id: str = ""

    # Facebook
    facebook_access_token: str = ""
    facebook_page_id: str = ""

    # YouTube
    youtube_api_key: str = ""
    youtube_oauth_client_id: str = ""
    youtube_oauth_client_secret: str = ""
    youtube_refresh_token: str = ""
    youtube_channel_id: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
