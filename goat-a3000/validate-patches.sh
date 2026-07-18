#!/bin/bash
# Validate GOAT A3000 LiDAR patches are active in the home-assistant container.

CONTAINER=home-assistant
SITE=/usr/local/lib/python3.14/site-packages/deebot_client
PASS=0
FAIL=0

check() {
  local description="$1"
  local command="$2"
  if eval "$command" &>/dev/null; then
    echo "  PASS  $description"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $description"
    FAIL=$((FAIL + 1))
  fi
}

echo ""
echo "=== GOAT A3000 patch validation ==="
echo ""

echo "cr0e4u.py:"
check "GetCleanInfo imported"                 "docker exec $CONTAINER grep -q 'GetCleanInfo' $SITE/hardware/cr0e4u.py"
check "GetCleanInfoV2 not present"            "docker exec $CONTAINER grep -vq 'GetCleanInfoV2' $SITE/hardware/cr0e4u.py"
check "CleanMower imported"                   "docker exec $CONTAINER grep -q 'CleanMower' $SITE/hardware/cr0e4u.py"
check "CapabilityCleanAction uses CleanMower" "docker exec $CONTAINER grep -q 'command=CleanMower' $SITE/hardware/cr0e4u.py"

echo ""
echo "clean.py:"
check "CleanMower class present"              "docker exec $CONTAINER grep -q 'class CleanMower' $SITE/commands/json/clean.py"
check "CleanMower uses clean endpoint"        "docker exec $CONTAINER grep -q 'NAME = .clean.' $SITE/commands/json/clean.py"
check "CleanMower uses type auto"             "docker exec $CONTAINER grep -q '\"type\": \"auto\"' $SITE/commands/json/clean.py"

echo ""
echo "messages/json/__init__.py:"
check "onScheduleTaskInfo route present"      "docker exec $CONTAINER grep -q 'onScheduleTaskInfo' $SITE/messages/json/__init__.py"
check "OnChargeInfoMower handler present"     "docker exec $CONTAINER grep -q 'OnChargeInfoMower' $SITE/messages/json/__init__.py"
check "goCharging guard present"              "docker exec $CONTAINER grep -q 'goCharging' $SITE/messages/json/__init__.py"

echo ""
echo "pycache (rebuilt from patched source after restart):"
check "hardware cr0e4u.pyc newer than source" \
  "docker exec $CONTAINER bash -c \
    'src=$SITE/hardware/cr0e4u.py; \
     pyc=\$(ls $SITE/hardware/__pycache__/cr0e4u*.pyc 2>/dev/null | head -1); \
     [ -z \"\$pyc\" ] || [ \"\$pyc\" -nt \"\$src\" ]'"
check "commands/json clean.pyc newer than source" \
  "docker exec $CONTAINER bash -c \
    'src=$SITE/commands/json/clean.py; \
     pyc=\$(ls $SITE/commands/json/__pycache__/clean*.pyc 2>/dev/null | head -1); \
     [ -z \"\$pyc\" ] || [ \"\$pyc\" -nt \"\$src\" ]'"
check "messages/json __init__.pyc newer than source" \
  "docker exec $CONTAINER bash -c \
    'src=$SITE/messages/json/__init__.py; \
     pyc=\$(ls $SITE/messages/json/__pycache__/__init__*.pyc 2>/dev/null | head -1); \
     [ -z \"\$pyc\" ] || [ \"\$pyc\" -nt \"\$src\" ]'"

echo ""
echo "authentication.py:"
# Ecovacs API rejects appVersion 1.6.3 with error 1013 ("Please update").
# Replace with the version string Ecovacs currently accepts.
# Find the correct value at: https://github.com/DeebotUniverse/client.py/issues (search "1013")
APP_VERSION="1.6.3"  # <-- UPDATE THIS when Ecovacs bumps their minimum
check "appVersion is $APP_VERSION" \
  "docker exec $CONTAINER grep -q '\"appVersion\": \"$APP_VERSION\"' $SITE/authentication.py"
if ! docker exec $CONTAINER grep -q "\"appVersion\": \"$APP_VERSION\"" $SITE/authentication.py 2>/dev/null; then
  echo "         Patching appVersion to $APP_VERSION ..."
  docker exec $CONTAINER sed -i \
    "s/\"appVersion\": \"[^\"]*\"/\"appVersion\": \"$APP_VERSION\"/" \
    $SITE/authentication.py
fi

echo "deebot-client version:"
GOT=$(docker exec $CONTAINER python -c "import importlib.metadata; print(importlib.metadata.version('deebot-client'))" 2>/dev/null)
if [ "$GOT" = "18.3.0" ]; then
  echo "  PASS  deebot-client $GOT (expected 18.3.0)"
  PASS=$((PASS + 1))
else
  echo "  WARN  deebot-client $GOT found, patches built for 18.3.0"
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
echo ""
[ $FAIL -eq 0 ] && exit 0 || exit 1
