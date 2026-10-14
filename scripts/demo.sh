#!/usr/bin/env bash
# End-to-end demo against a running stack (docker compose up first).
set -euo pipefail
API="${API:-http://localhost:8000}"
KEY="${KEY:-dev-key-123}"
H=(-H "x-api-key: $KEY" -H "content-type: application/json")

echo "== 1. health =="
curl -s "$API/health"; echo

echo "== 2. ingest a document =="
curl -s "$API/v1/documents" "${H[@]}" \
  -d '{"title":"UD Fresh Market","text":"UD Fresh Market is a fresh food store in Udon Thani, Thailand. It sells organic vegetables, free-range chicken, and freshly caught river fish every morning."}'; echo

echo "== 3. ask (grounded RAG + citations) =="
curl -s "$API/v1/ask" "${H[@]}" \
  -d '{"question":"What does UD Fresh Market sell and where is it?"}'; echo

echo "== 4. A/B prompt eval =="
curl -s "$API/v1/eval/compare" "${H[@]}" \
  -d '{"prompt_name":"rag_default","version_a":1,"version_b":1,"body_b":"Answer in <=10 words from context.\n{{context}}\nQ: {{question}}"}' \
  | python -c "import sys,json;d=json.load(sys.stdin);print('summary:',d['summary']);print('A agg:',d['aggregate_a']);print('B agg:',d['aggregate_b'])"

echo "== 5. usage / cost =="
curl -s "$API/v1/usage" "${H[@]}"; echo

echo "== done =="
