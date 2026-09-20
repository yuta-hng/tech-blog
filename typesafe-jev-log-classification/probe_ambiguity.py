"""Supplementary HAND-WRITTEN ambiguous examples, separate from real local logs."""
from datetime import datetime, timezone
import json
from experiment import Client, QUESTIONS, ROOT, key_from_file, route

CASES = [
    {'id':'upstream_unknown','state':'Request failed. Upstream service unavailable. No status code, endpoint, or stack trace was recorded.'},
    {'id':'database_or_network','state':'Database connection attempt timed out after 5 seconds. Database health and network connectivity have not been checked.'},
    {'id':'recovered_retry','state':'First request failed with HTTP 503. Retried once and got HTTP 200. Subsequent requests succeeded.'}
]
if __name__ == '__main__':
    client=Client(key_from_file(ROOT/'api.env'))
    target=ROOT/'results'/('ambiguity-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.json')
    rows=[]
    for case in CASES:
        row={**case,'source':'handwritten_synthetic_no_ground_truth',**client.call(case['state'],QUESTIONS,'jev-1.13.0')}
        if row['ok']: row['route']=route(row['response'])
        rows.append(row)
    client.close(); target.write_text(json.dumps(rows,indent=2)+'\n'); print(target.name)
    for row in rows:
        print(row['id'],row.get('response',{}).get('answers',{}),row.get('route'))
