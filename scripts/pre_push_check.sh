#!/bin/bash
set -e
echo "=== NOXEN PRE-PUSH CHECK ==="
ERRORS=0

check() {
  local name=$1
  local result=$2
  if [ -z "$result" ]; then
    echo "OK   $name"
  else
    echo "FAIL $name"
    echo "$result"
    ERRORS=$((ERRORS+1))
  fi
}

# 1. API keys hardcoded (exclude tests, skills, .neural history)
check "No API keys" "$(grep -r \
  'sk-ant-[a-zA-Z0-9]\|xai-[a-zA-Z0-9]\|ghp_[a-zA-Z0-9]\|AIza[a-zA-Z0-9]' \
  --include='*.py' --include='*.js' \
  --include='*.yaml' --include='*.yml' \
  --exclude-dir='.git' --exclude-dir='.venv' \
  --exclude-dir='tests' --exclude-dir='skills' \
  --exclude-dir='.neural' \
  --exclude='*.example' . 2>/dev/null || true)"

# 2. Rename completo (source code only, exclude docs/history)
check "Rename complete" "$(grep -r \
  'Neural Hub\|NeuralHub\|neural_hub\|NEURAL_HUB_' \
  --include='*.py' --include='*.js' \
  --include='*.html' \
  --exclude-dir='.git' --exclude-dir='.venv' \
  --exclude-dir='skills' --exclude-dir='.neural-hub' \
  --exclude-dir='.noxen' --exclude-dir='.neural' \
  --exclude-dir='tests' . 2>/dev/null || true)"

# 3. File .env
check "No .env files" "$(find . -name '.env' \
  -not -name '.env.example' \
  -not -path './.git/*' \
  -not -path './.venv/*' 2>/dev/null || true)"

# 4. Database files (exclude skills, data — runtime artifacts)
check "No DB files" "$(find . \
  \( -name '*.db' -o -name '*.sqlite' \) \
  -not -path './.git/*' \
  -not -path './.venv/*' \
  -not -path './skills/*' \
  -not -path './data/*' 2>/dev/null || true)"

# 5. LICENSE esiste
[ -f LICENSE ] && echo "OK   LICENSE exists" \
  || { echo "FAIL LICENSE missing"; ERRORS=$((ERRORS+1)); }

# 6. .env.example esiste
[ -f .env.example ] && echo "OK   .env.example exists" \
  || { echo "FAIL .env.example missing"; ERRORS=$((ERRORS+1)); }

# 7. Test suite
echo -n "Running tests... "
RESULT=$(.venv/bin/python -m pytest tests/ -q --tb=no 2>&1 | tail -1)
echo "$RESULT"
echo "$RESULT" | grep -q "passed" \
  || { ERRORS=$((ERRORS+1)); }

echo ""
if [ $ERRORS -eq 0 ]; then
  echo "ALL CHECKS PASSED. Ready to push to GitHub."
  exit 0
else
  echo "$ERRORS check(s) FAILED. Fix before pushing."
  exit 1
fi
