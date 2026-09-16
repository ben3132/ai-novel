# Local evidence query configuration.
# Copy this file to agent_query.ps1 and fill in your own machine paths.
# agent_query.ps1 is git-ignored so machine-specific paths stay out of the repo.
$env:IP_SOURCE_DATA_ROOT = "D:\path\to\xs_data"
$env:IP_VECTOR_INDEX_DIR = "D:\path\to\xs_data\data\ip\<ip-domain>\processed\vector"
$env:IP_EMBEDDING_MODEL  = "D:\path\to\models\bge-small-zh-v1.5"
