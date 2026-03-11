# ================================================================
# JournalFlow 配置文件
# ================================================================
# 填写后直接运行 app.py 即可，无需其他配置

# ── LetPub Cookie ────────────────────────────────────────────────
# 获取方式：
#   1. 浏览器登录 letpub.com.cn
#   2. F12 → Network → 刷新页面
#   3. 点击任意 letpub.com.cn 请求 → Request Headers → 复制 Cookie 值
LETPUB_COOKIE = "your_cookie_here"

# ── LLM API 配置 ─────────────────────────────────────────────────
# 支持任何兼容 OpenAI 格式的接口（OpenAI / DeepSeek / 本地 Ollama 等）
LLM_API_KEY    = "your_api_key_here"
LLM_BASE_URL   = "https://api.deepseek.com"   # DeepSeek 示例
LLM_MODEL      = "deepseek-chat"

# OpenAI 示例：
# LLM_BASE_URL = "https://api.openai.com/v1"
# LLM_MODEL    = "gpt-4o-mini"

# ── 服务器配置 ───────────────────────────────────────────────────
HOST = "0.0.0.0"
PORT = 5000
DEBUG = False

# ── 抓取限制 ─────────────────────────────────────────────────────
MAX_COMMENTS    = 200   # 单次最多抓取条数（防止过载）
DEFAULT_COMMENTS = 50   # 默认抓取条数
