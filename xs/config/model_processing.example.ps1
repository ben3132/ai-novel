# 处理层模型配置示例。真实密钥只能放环境变量，禁止写入代码/YAML/JSONL。
$env:IP_LLM_PROVIDER = "ollama"
# 本机 Ollama 默认端口；换成远端 OpenAI 兼容服务时改这里即可
$env:IP_LLM_BASE_URL = "http://localhost:11434"
$env:IP_LLM_MODEL = "qwen2.5:3b"
$env:IP_LLM_NUM_CTX = "4096"
$env:IP_LLM_NUM_PREDICT = "512"
# OpenAI-compatible 服务才需要：$env:IP_LLM_API_KEY = "replace-in-local-session"
