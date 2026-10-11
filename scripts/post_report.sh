#!/usr/bin/env bash
# Post (or update) the receipts comment and keep exactly one receipt:* label on the PR/issue.
#
# Inputs (all set by report/action.yml from values that `receipts render` already validated):
#   GH_TOKEN, REPO (owner/name), NUMBER (integer), LABEL (may be empty), COMMENT_FILE
set -euo pipefail

: "${GH_TOKEN:?}" "${REPO:?}" "${NUMBER:?}" "${COMMENT_FILE:?}"
LABEL="${LABEL:-}"

# Defence in depth: refuse anything that is not exactly what we expect.
[[ "$NUMBER" =~ ^[1-9][0-9]{0,9}$ ]] || { echo "refusing bad subject number" >&2; exit 1; }
[[ "$REPO" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] || { echo "refusing bad repository" >&2; exit 1; }
case "$LABEL" in
  ""|receipt:verified|receipt:needs-work|receipt:missing|receipt:invalid) ;;
  *) echo "refusing unknown label" >&2; exit 1 ;;
esac
[[ -s "$COMMENT_FILE" ]] || { echo "empty comment" >&2; exit 1; }

marker='<!-- receipts:v1 -->'

# Update our own previous comment (bot-authored, starts with the marker) instead of adding a new one.
existing="$(gh api --paginate "repos/$REPO/issues/$NUMBER/comments" \
  --jq ".[] | select(.user.type == \"Bot\" and (.body | startswith(\"$marker\"))) | .id" | head -n 1 || true)"

if [[ -n "$existing" ]]; then
  gh api -X PATCH "repos/$REPO/issues/comments/$existing" -F "body=@$COMMENT_FILE" > /dev/null
  echo "updated comment $existing"
else
  gh api -X POST "repos/$REPO/issues/$NUMBER/comments" -F "body=@$COMMENT_FILE" > /dev/null
  echo "created comment"
fi

declare -A colors=(
  ["receipt:verified"]="2da44e"
  ["receipt:needs-work"]="d4a72c"
  ["receipt:missing"]="8250df"
  ["receipt:invalid"]="cf222e"
)

for name in "${!colors[@]}"; do
  gh label create "$name" --repo "$REPO" --color "${colors[$name]}" \
    --description "Set automatically by receipts" > /dev/null 2>&1 || true
done

# Remove stale receipt:* labels, then add the current one (none for infrastructure errors).
for name in "${!colors[@]}"; do
  if [[ "$name" != "$LABEL" ]]; then
    gh api -X DELETE "repos/$REPO/issues/$NUMBER/labels/${name/:/%3A}" > /dev/null 2>&1 || true
  fi
done
if [[ -n "$LABEL" ]]; then
  gh api -X POST "repos/$REPO/issues/$NUMBER/labels" -f "labels[]=$LABEL" > /dev/null
  echo "label: $LABEL"
fi
