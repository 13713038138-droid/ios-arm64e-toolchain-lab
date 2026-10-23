#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
RUNTIME="$ROOT/runtime"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/lib"
cp "$RUNTIME/ensure-python3.sh" "$TMP/lib/ensure-python3.sh"
cp "$RUNTIME/minis-dev-ultra" "$TMP/bin/minis-dev-ultra"
cp "$RUNTIME/minis-bin" "$TMP/bin/minis-bin"
cp "$RUNTIME/minis-tk" "$TMP/bin/minis-tk"
cp "$RUNTIME/minis-deb" "$TMP/bin/minis-deb"
cp "$RUNTIME/minis-abi" "$TMP/bin/minis-abi"
cat > "$TMP/lib/devctl.py" <<'PY'
import sys
print("DEVCTL_ARGS:" + "|".join(sys.argv[1:]))
PY
cat > "$TMP/lib/tk_optimizer.py" <<'PY'
import sys
print("TK_ARGS:" + "|".join(sys.argv[1:]))
PY
cat > "$TMP/lib/deb_factory.py" <<'PY'
import sys
print("DEB_ARGS:" + "|".join(sys.argv[1:]))
PY
cat > "$TMP/lib/abi_v2_gate.py" <<'PY'
import sys
print("ABI_ARGS:" + "|".join(sys.argv[1:]))
PY
chmod +x "$TMP/bin/minis-dev-ultra" "$TMP/bin/minis-bin" "$TMP/bin/minis-tk" "$TMP/bin/minis-deb" "$TMP/bin/minis-abi"
PYTHON_BIN="$(command -v python3)"
PYTHON_DIR="$(dirname "$PYTHON_BIN")"
NORMAL_PATH="$PYTHON_DIR:/bin:/usr/bin"
out="$(PATH="$NORMAL_PATH" MINIS_DEV_ULTRA_LIB="$TMP/lib" "$TMP/bin/minis-dev-ultra" route --task 'SwiftUI keyboard')"
printf '%s' "$out" | grep -q 'DEVCTL_ARGS:route|--task|SwiftUI keyboard'
out="$(PATH="$NORMAL_PATH" MINIS_DEV_ULTRA_LIB="$TMP/lib" "$TMP/bin/minis-bin" sample.ipa)"
printf '%s' "$out" | grep -q 'DEVCTL_ARGS:inspect|sample.ipa'
out="$(PATH="$NORMAL_PATH" MINIS_DEV_ULTRA_LIB="$TMP/lib" "$TMP/bin/minis-tk" audit sample.log)"
printf '%s' "$out" | grep -q 'TK_ARGS:audit|sample.log'
out="$(PATH="$NORMAL_PATH" MINIS_DEV_ULTRA_LIB="$TMP/lib" "$TMP/bin/minis-deb" auto --project /tmp/test-project --arch auto)"
printf '%s' "$out" | grep -q 'DEB_ARGS:auto|--project|/tmp/test-project|--arch|auto'
out="$(PATH="$NORMAL_PATH" MINIS_DEV_ULTRA_LIB="$TMP/lib" "$TMP/bin/minis-deb")"
printf '%s' "$out" | grep -q 'DEB_ARGS:auto'
out="$(PATH="$NORMAL_PATH" MINIS_DEV_ULTRA_LIB="$TMP/lib" "$TMP/bin/minis-abi" preflight)"
printf '%s' "$out" | grep -q 'ABI_ARGS:preflight'
out="$(PATH="$NORMAL_PATH" MINIS_DEV_ULTRA_LIB="$TMP/lib" "$TMP/bin/minis-abi")"
printf '%s' "$out" | grep -q 'ABI_ARGS:doctor'

# Simulate a fresh Alpine guest where python3 is absent: apk installs a stub executable.
mkdir -p "$TMP/fakebin"
cat > "$TMP/fakebin/apk" <<'APK'
#!/bin/sh
printf '#!/bin/sh\nprintf "BOOTSTRAPPED_PYTHON3"\nprintf " <%s>" "$@"\nprintf "\\n"\n' > "$MINIS_DEV_ULTRA_TEST_BIN/python3"
 /bin/chmod +x "$MINIS_DEV_ULTRA_TEST_BIN/python3"
APK
chmod +x "$TMP/fakebin/apk"
out="$(PATH="$TMP/fakebin" MINIS_DEV_ULTRA_TEST_BIN="$TMP/fakebin" MINIS_DEV_ULTRA_LIB="$TMP/lib" MINIS_DEV_ULTRA_BOOTSTRAP_LOG="$TMP/bootstrap.log" "$TMP/bin/minis-dev-ultra" doctor)"
printf '%s' "$out" | grep -q 'BOOTSTRAPPED_PYTHON3'
printf '%s\n' 'PASS: wrappers dispatch to intended Python tools, including R32 ABI gate, and bootstrap Python 3 when missing'
