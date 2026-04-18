# =============================================================================
# Neethi AI — Development Shortcuts
# =============================================================================
#
# Usage:
#   make backend     Start FastAPI on :8000 (auto-reload, watches backend/ only)
#   make frontend    Start Next.js on :3000
#   make install     Install all Python + Node dependencies
#   make migrate     Run Alembic DB migrations
#
# Run both servers in separate terminals:
#   Terminal 1: make backend
#   Terminal 2: make frontend
# =============================================================================

.PHONY: backend frontend install migrate help

# ── Backend ────────────────────────────────────────────────────────────────
backend:
	uvicorn backend.main:app \
		--reload \
		--reload-dir backend \
		--host 0.0.0.0 \
		--port 8000 \
		--loop asyncio
# Flags explained:
#   --reload-dir backend : watch ONLY backend/ — prevents node_modules restarts
#   --loop asyncio       : required for CrewAI nest_asyncio compatibility

# ── Frontend ───────────────────────────────────────────────────────────────
frontend:
	cd frontend && npm run dev

# ── Install ────────────────────────────────────────────────────────────────
install:
	pip install -r requirements.txt
	cd frontend && npm install --legacy-peer-deps

# ── Database migrations ────────────────────────────────────────────────────
migrate:
	alembic upgrade head

# ── Help ───────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "Neethi AI — Development Commands"
	@echo "---------------------------------"
	@echo "  make backend    Start FastAPI on :8000"
	@echo "  make frontend   Start Next.js on :3000"
	@echo "  make install    Install Python + Node dependencies"
	@echo "  make migrate    Run DB migrations"
	@echo ""
