from dataclasses import dataclass, field


@dataclass
class Config:
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Audio
    MP3_BITRATE: int = 128        # kbps
    CHANNELS: int = 1             # mono
    SAMPLE_RATE: int = 44100
    CHUNK_SIZE: int = 2048        # bytes per broadcast chunk

    # TTS — edge-tts voices (alternating per article)
    TTS_VOICES: list[str] = field(default_factory=lambda: [
        "ko-KR-SunHiNeural",                # female
        "ko-KR-HyunsuMultilingualNeural",   # male
    ])
    TTS_RATE: str = "+5%"
    TTS_VOLUME: str = "+0%"

    # Queue — buffer watermarks
    BUFFER_CRITICAL: int = 60    # < 60s: run pipeline immediately
    BUFFER_LOW: int = 300        # < 300s: buffer low, pipeline needed
    BUFFER_FULL: int = 900       # >= 900s: buffer full, skip pipeline

    # Scheduler
    FETCH_INTERVAL_MINUTES: int = 10
    WATCHDOG_INTERVAL_SECONDS: int = 30

    # LLM — OpenAI-compatible endpoint (Ollama by default)
    LLM_BASE_URL: str = "http://localhost:11434/v1"
    LLM_MODEL: str = "bnksys/eeve:korean-instruct"
    LLM_API_KEY: str = "ollama"   # Ollama ignores the value; set to real key for remote APIs
    LLM_TEMPERATURE: float = 0.75
    LLM_MAX_TOKENS: int = 4096    # thinking models consume tokens before output; keep ≥ 4096

    # Script QA
    SCRIPT_MIN_WORDS: int = 150           # regular articles
    SCRIPT_MIN_WORDS_BREAKING: int = 100  # breaking news (thin source material)

    # Storage
    DB_PATH: str = "data/articles.db"
    ARTICLE_TTL_DAYS: int = 1
    CACHE_DIR: str = "cache"

    # Logging
    LOG_LEVEL: str = "INFO"

    # Broadcaster
    CLIENT_QUEUE_MAXSIZE: int = 256


# Global singleton
config = Config()
