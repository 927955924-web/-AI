---
name: auto-verify-fix
description: "Automatically verify all functional modules of the e-commerce customer service system, detect errors, fix them, and re-verify in a loop until all modules work correctly. Use when the user asks to test, verify, validate, check, or fix all modules, or mentions 'auto verify', 'auto fix', 'module check', or 'full system check'."
---

# Auto Verify & Fix - Module Verification Loop

Automatically simulate manual verification of every functional module, fix discovered errors, and re-verify until all modules pass.

## Overview

This skill performs a **verify -> fix -> re-verify** loop across all project modules:

1. **Backend** (Django REST API)
2. **Frontend** (Vue 3 + Vite)
3. **Electron Client**
4. **Python Desktop App** (legacy src/)

Each iteration produces a status report. The loop continues until all modules report no errors, or a maximum of **5 iterations** is reached.

## Execution Workflow

### Phase 0: Environment Preparation

Before starting, check runtime availability:

```
Task Progress:
- [ ] Check Python environment
- [ ] Check Node.js environment
- [ ] Install backend dependencies if needed
- [ ] Install frontend dependencies if needed
- [ ] Install electron-client dependencies if needed
```

1. **Python**: Run `python --version`. If missing, inform the user.
2. **Node.js**: Run `node --version` and `npm --version`. If missing, inform the user.
3. **Backend deps**: Check `backend/requirements.txt` installed via `pip list`.
4. **Frontend deps**: Check `frontend/node_modules` exists, run `npm install` if missing.
5. **Electron deps**: Check `electron-client/node_modules` exists, run `npm install` if missing.

### Phase 1: Backend Verification

Run the following checks **sequentially** in `backend/`:

| Step | Command | What it validates |
|------|---------|-------------------|
| 1 | `python manage.py check --deploy 2>&1` | Django system checks (settings, security, models) |
| 2 | `python manage.py makemigrations --check --dry-run 2>&1` | Pending migration detection |
| 3 | `python manage.py migrate --run-syncdb 2>&1` | Database schema sync |
| 4 | `python -m py_compile <each .py file>` | Python syntax validation |
| 5 | `python manage.py test 2>&1` or `pytest 2>&1` | Run existing tests |

**Syntax validation scope** - check all `.py` files under:
- `backend/apps/accounts/`
- `backend/apps/shops/`
- `backend/apps/products/`
- `backend/apps/chat/`
- `backend/apps/ai/`
- `backend/apps/knowledge/`
- `backend/apps/quick_replies/`
- `backend/apps/statistics/`
- `backend/apps/learning/`
- `backend/apps/client/`
- `backend/core/`
- `backend/config/`

**Error collection format:**
```
MODULE: backend/<app_name>
FILE: <file_path>
ERROR_TYPE: syntax|import|migration|test|check
ERROR: <error message>
```

### Phase 2: Frontend Verification

Run the following checks in `frontend/`:

| Step | Command | What it validates |
|------|---------|-------------------|
| 1 | `npm run build 2>&1` | Build compilation (Vite + Vue SFC) |
| 2 | `npx vue-tsc --noEmit 2>&1` (if available) | TypeScript type checking |
| 3 | `npm run lint 2>&1` (if configured) | ESLint code quality |

**Verification scope** - all `.vue` and `.js` files under:
- `frontend/src/api/`
- `frontend/src/router/`
- `frontend/src/store/`
- `frontend/src/components/`
- `frontend/src/views/`
- `frontend/src/main.js`
- `frontend/src/App.vue`

### Phase 3: Electron Client Verification

Run the following checks in `electron-client/`:

| Step | Command | What it validates |
|------|---------|-------------------|
| 1 | `node --check main.js 2>&1` | Main process syntax |
| 2 | `node --check preload/qianniu.js 2>&1` | Preload script syntax |
| 3 | `node --check preload/douyin.js 2>&1` | Preload script syntax |
| 4 | Validate all `.js` files in `services/`, `adapters/`, `utils/` | Module syntax |
| 5 | `npm run build 2>&1` (if configured, use `--dry-run` if available) | Build check |

### Phase 4: Python Desktop App Verification (Legacy)

Run syntax checks on `src/` directory:

| Step | Command | What it validates |
|------|---------|-------------------|
| 1 | `python -m py_compile src/main.py` | Entry point syntax |
| 2 | `python -m py_compile src/ui/app.py` | Main UI syntax |
| 3 | All `.py` files under `src/domain/`, `src/infrastructure/`, `src/services/` | Module syntax |
| 4 | `pytest tests/ 2>&1` (if tests exist) | Unit tests |

### Phase 5: Cross-Module Verification

Check integration points between modules:

1. **API contract consistency**: Read `backend/config/urls.py` and all app `urls.py` files. Compare API paths with `frontend/src/api/*.js` request URLs to detect mismatches.
2. **Electron-Backend communication**: Read `electron-client/main.js` for API base URL and endpoint calls. Verify they match backend routes.
3. **Import chain validation**: For each Python app, attempt `python -c "import apps.<name>"` to verify import chains.

## Fix Strategy

When errors are found, apply fixes based on error type:

### Python Errors
| Error Type | Fix Approach |
|-----------|-------------|
| **SyntaxError** | Read the file, identify the syntax issue, apply Edit tool fix |
| **ImportError** | Check if module exists, fix import path or install missing package |
| **ModuleNotFoundError** | Add to requirements.txt and install via pip |
| **Migration conflict** | Run `makemigrations --merge` or recreate migration |
| **Django check warning** | Read the warning, apply the recommended fix |
| **Test failure** | Read failing test, understand expected behavior, fix source code or test |

### JavaScript/Vue Errors
| Error Type | Fix Approach |
|-----------|-------------|
| **Build error** | Read Vite/webpack error output, fix the referenced file and line |
| **ESLint error** | Apply auto-fix first (`npx eslint --fix`), then manual fix remaining |
| **SyntaxError** | Read file, fix syntax at reported location |
| **Missing dependency** | Run `npm install <package>` |
| **Vue template error** | Read .vue file, fix template/script/style section |

### Cross-Module Errors
| Error Type | Fix Approach |
|-----------|-------------|
| **API path mismatch** | Update frontend API files to match backend URL configuration |
| **Missing endpoint** | Create the missing view/serializer/url in backend |
| **Response format mismatch** | Align serializer fields with frontend expectations |

## Loop Control

```
MAX_ITERATIONS = 5
iteration = 0

while iteration < MAX_ITERATIONS:
    iteration += 1
    
    errors = []
    errors += verify_backend()
    errors += verify_frontend()
    errors += verify_electron()
    errors += verify_legacy_app()
    errors += verify_cross_module()
    
    if len(errors) == 0:
        PRINT "ALL MODULES PASSED - iteration {iteration}"
        break
    
    PRINT "Found {len(errors)} errors in iteration {iteration}"
    
    for error in errors:
        fix(error)
    
    PRINT "Fixes applied, starting re-verification..."

if iteration == MAX_ITERATIONS and len(errors) > 0:
    PRINT "WARNING: Max iterations reached. Remaining errors:"
    for error in errors:
        PRINT error
    ASK USER for guidance
```

## Status Report Format

After each iteration, produce a report:

```markdown
## Verification Report - Iteration N

### Backend (Django)
| Module | Status | Errors |
|--------|--------|--------|
| accounts | PASS/FAIL | error description or - |
| shops | PASS/FAIL | ... |
| products | PASS/FAIL | ... |
| chat | PASS/FAIL | ... |
| ai | PASS/FAIL | ... |
| knowledge | PASS/FAIL | ... |
| quick_replies | PASS/FAIL | ... |
| statistics | PASS/FAIL | ... |
| learning | PASS/FAIL | ... |
| client | PASS/FAIL | ... |

### Frontend (Vue 3)
| Check | Status | Errors |
|-------|--------|--------|
| Build | PASS/FAIL | ... |
| Lint | PASS/FAIL | ... |

### Electron Client
| Check | Status | Errors |
|-------|--------|--------|
| main.js | PASS/FAIL | ... |
| preload scripts | PASS/FAIL | ... |
| services | PASS/FAIL | ... |

### Legacy Python App
| Check | Status | Errors |
|-------|--------|--------|
| Syntax | PASS/FAIL | ... |
| Tests | PASS/FAIL | ... |

### Cross-Module
| Check | Status | Errors |
|-------|--------|--------|
| API contracts | PASS/FAIL | ... |
| Import chains | PASS/FAIL | ... |

**Summary**: X/Y modules passed. Z errors fixed this iteration.
```

## Important Rules

1. **Read before fix**: ALWAYS read the full file before attempting any fix.
2. **Minimal changes**: Only fix what is broken. Do not refactor, improve, or add features.
3. **One fix at a time**: Apply one fix, then re-verify that specific module before moving on.
4. **Preserve intent**: When fixing code, preserve the original developer's intent and patterns.
5. **No data loss**: Never delete data, drop tables, or remove functionality during fixes.
6. **Log everything**: Report every error found and every fix applied.
7. **Ask when unsure**: If a fix is ambiguous or could break other modules, ask the user.
8. **Skip unavailable**: If a runtime (Python/Node) is unavailable, skip those modules and report it.
9. **Environment safety**: Never modify .env files or credentials during verification.
10. **Max 5 iterations**: Stop after 5 verify-fix cycles to prevent infinite loops.
