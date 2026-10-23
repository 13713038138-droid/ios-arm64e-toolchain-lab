#!/bin/sh
# Source this file, then call ensure_python3. Uses Alpine/iSH apk only if needed.
ensure_python3() {
  if command -v python3 >/dev/null 2>&1; then
    return 0
  fi
  if ! command -v apk >/dev/null 2>&1; then
    printf '%s\n' 'NO-GO: python3 is missing and apk is unavailable; no development command was run.' >&2
    return 127
  fi
  log="${MINIS_DEV_ULTRA_BOOTSTRAP_LOG:-/tmp/minis-dev-ultra-python-bootstrap.log}"
  if ! apk add --quiet python3 >> "$log" 2>&1; then
    printf '%s\n' "NO-GO: Alpine could not install python3; see $log" >&2
    return 127
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' 'NO-GO: apk returned without making python3 available.' >&2
    return 127
  fi
}