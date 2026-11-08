#!/usr/bin/env python3
"""Tavern draft-run tester: POST run, parse SSE, show nodes + answer.
usage: tavern_test.py <conversation_id|NEW> <player_key> <query>"""
import json, subprocess, sys

APP = "2d5ae7b7-0ece-4d95-a4b7-6d40af4c3ca0"
conv, player, query = sys.argv[1], sys.argv[2], sys.argv[3]
body = {"inputs": {"player_key": player}, "query": query}
if conv != "NEW":
    body["conversation_id"] = conv
json.dump(body, open("/tmp/_run.json", "w", encoding="utf-8"), ensure_ascii=False)

out = subprocess.run(
    ["/root/dify_api.sh", "post-file",
     f"/apps/{APP}/advanced-chat/workflows/draft/run", "/tmp/_run.json"],
    capture_output=True, text=True).stdout

events = []
for line in out.splitlines():
    if line.startswith("data: "):
        try:
            events.append(json.loads(line[6:]))
        except Exception:
            pass

conv_id = None
answer = []
nodes = {}
final = None
for e in events:
    et = e.get("event")
    if et == "workflow_started":
        conv_id = e.get("conversation_id")
    elif et == "node_finished":
        d = e.get("data", {})
        title = d.get("node_type", "?")
        outp = d.get("outputs")
        nodes[title] = (d.get("status"), json.dumps(outp, ensure_ascii=False)[:260] if outp else "")
    elif et == "message":
        answer.append(e.get("answer", ""))
    elif et == "workflow_finished":
        final = e.get("data", {}).get("status")
    elif et == "error":
        print("ERROR EVENT:", json.dumps(e, ensure_ascii=False)[:400])

print("conversation_id:", conv_id)
print("workflow:", final)
for t, (st, o) in nodes.items():
    print(f"[{t}] {st} -> {o}")
print("ANSWER:", "".join(answer)[:500])
