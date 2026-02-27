#!/usr/bin/env bash
# =============================================================================
# Neethi AI — Lightning AI API Setup & Run Script
# =============================================================================
#
# Run this once on a fresh Lightning AI studio session:
#   bash run_api.sh
#
# What it does:
#   1. Installs all Phase 6 FastAPI packages
#   2. Verifies key dependencies import correctly
#   3. Starts the FastAPI server on port 8000
#
# To run end-to-end tests (in a second terminal):
#   python backend/tests/test_api_e2e.py
#   python backend/tests/test_api_e2e.py --groups auth sections  # run specific groups only
# =============================================================================

set -e  # Exit on first error

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
RESET='\033[0m'

echo -e "\n${BOLD}${CYAN}============================================================${RESET}"
echo -e "${BOLD}${CYAN}  Neethi AI — Phase 6: FastAPI Setup${RESET}"
echo -e "${BOLD}${CYAN}============================================================${RESET}\n"

# =============================================================================
# Step 1 — Verify environment variables
# =============================================================================
echo -e "${BOLD}Step 1: Checking required environment variables...${RESET}"

MISSING=0
check_env() {
    if [ -z "${!1}" ]; then
        echo -e "  ${RED}✗ $1 is NOT set${RESET}"
        MISSING=$((MISSING + 1))
    else
        echo -e "  ${GREEN}✓ $1 is set${RESET}"
    fi
}

check_env DATABASE_URL
check_env QDRANT_URL
check_env QDRANT_API_KEY
check_env GROQ_API_KEY

echo -e "\n  Optional (warning only):"
warn_env() {
    if [ -z "${!1}" ]; then
        echo -e "  ${YELLOW}⚠ $1 not set — $2 will be disabled${RESET}"
    else
        echo -e "  ${GREEN}✓ $1 is set${RESET}"
    fi
}
warn_env ANTHROPIC_API_KEY   "Document drafting (Claude Sonnet)"
warn_env MISTRAL_API_KEY     "Mistral fallback"
warn_env SARVAM_API_KEY      "Translation and Voice (TTS/STT)"
warn_env SERP_API_KEY        "Nearby legal resources"
warn_env JWT_SECRET_KEY      "JWT (will use insecure default)"

if [ $MISSING -gt 0 ]; then
    echo -e "\n${RED}${BOLD}$MISSING required env vars are missing. Set them in .env and source it:${RESET}"
    echo -e "  ${YELLOW}source .env  # or: export DATABASE_URL=...${RESET}"
    echo -e "Continuing anyway — some endpoints will fail.\n"
fi

# =============================================================================
# Step 2 — Install Phase 6 packages
# =============================================================================
echo -e "\n${BOLD}Step 2: Installing Phase 6 FastAPI packages...${RESET}"

pip install --quiet \
    "fastapi==0.115.6" \
    "uvicorn[standard]==0.34.0" \
    "python-jose[cryptography]==3.3.0" \
    "passlib[bcrypt]==1.7.4" \
    "python-multipart==0.0.20" \
    "email-validator==2.2.0" \
    "reportlab==4.2.5"

echo -e "${GREEN}✓ Phase 6 packages installed${RESET}"

# =============================================================================
# Step 3 — Verify critical imports
# =============================================================================
echo -e "\n${BOLD}Step 3: Verifying imports...${RESET}"

python -c "
import sys
checks = [
    ('fastapi',           'FastAPI'),
    ('uvicorn',           'uvicorn'),
    ('jose',              'python-jose (JWT)'),
    ('passlib',           'passlib (bcrypt)'),
    ('multipart',         'python-multipart'),
    ('email_validator',   'email-validator'),
    ('reportlab',         'reportlab (PDF)'),
    ('sqlalchemy',        'SQLAlchemy'),
    ('asyncpg',           'asyncpg'),
    ('qdrant_client',     'qdrant-client'),
    ('crewai',            'crewai'),
    ('litellm',           'litellm'),
    ('httpx',             'httpx'),
]
failed = []
for module, label in checks:
    try:
        __import__(module)
        print(f'  \033[92m✓\033[0m {label}')
    except ImportError as e:
        print(f'  \033[91m✗\033[0m {label}: {e}')
        failed.append(label)
if failed:
    print(f'\n\033[91mFailed imports: {failed}\033[0m')
    sys.exit(1)
else:
    print('\n\033[92mAll imports OK\033[0m')
"

# =============================================================================
# Step 4 — Verify backend package structure
# =============================================================================
echo -e "\n${BOLD}Step 4: Verifying backend module structure...${RESET}"

python -c "
import sys, os
sys.path.insert(0, os.getcwd())
checks = [
    'backend.main',
    'backend.api.dependencies',
    'backend.api.schemas',
    'backend.api.routes.auth',
    'backend.api.routes.query',
    'backend.api.routes.sections',
    'backend.api.routes.cases',
    'backend.api.routes.documents',
    'backend.api.routes.resources',
    'backend.api.routes.translate',
    'backend.api.routes.voice',
    'backend.api.routes.admin',
    'backend.db.database',
    'backend.db.models.user',
    'backend.services.cache',
]
failed = []
for mod in checks:
    try:
        __import__(mod)
        print(f'  \033[92m✓\033[0m {mod}')
    except Exception as e:
        print(f'  \033[91m✗\033[0m {mod}: {e}')
        failed.append(mod)
if failed:
    print(f'\n\033[91mModule import failures: {len(failed)}\033[0m')
    sys.exit(1)
else:
    print('\n\033[92mAll backend modules loaded OK\033[0m')
"

# =============================================================================
# Step 5 — Create DB tables (dev mode)
# =============================================================================
echo -e "\n${BOLD}Step 5: Creating database tables (dev mode)...${RESET}"

python -c "
import asyncio, os, sys
sys.path.insert(0, os.getcwd())
os.environ.setdefault('ENVIRONMENT', 'development')

async def create():
    from backend.db.database import create_all_tables
    await create_all_tables()
    print('  \033[92m✓ Tables created/verified\033[0m')

asyncio.run(create())
" || echo -e "${YELLOW}⚠ DB table creation failed (check DATABASE_URL) — server will still start${RESET}"

# =============================================================================
# Step 6 — Start the server
# =============================================================================
echo -e "\n${BOLD}${CYAN}Step 6: Starting FastAPI server...${RESET}"
echo -e "${YELLOW}  Swagger UI:  http://localhost:8000/docs${RESET}"
echo -e "${YELLOW}  ReDoc:       http://localhost:8000/redoc${RESET}"
echo -e "${YELLOW}  Health:      http://localhost:8000/health${RESET}"
echo -e "\n${BOLD}  Run e2e tests in another terminal:${RESET}"
echo -e "  ${CYAN}python test_api_e2e.py${RESET}"
echo -e "  ${CYAN}python test_api_e2e.py --groups auth sections query${RESET}"
echo -e "\n${YELLOW}Press Ctrl+C to stop the server${RESET}\n"

uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload \
    --reload-dir backend \
    --log-level info
