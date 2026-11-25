"""Optional local Ollama *measurement-aware* review of heuristic FX suggestions.

No audio is uploaded, and no claim is made that text LLMs can hear quality.
Only bounded numerical measurements and sanitized category/track labels are shared.
Model output is advisory: cannot add plugins, change parameter values, or enable FX.
"""
from __future__ import annotations
import json
import math
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ALLOWED_DECISIONS = {'keep', 'omit', 'review'}

class AIReviewError(RuntimeError):
    pass


def _local_endpoint(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.username or parsed.password:
        raise AIReviewError('Only local Ollama http://127.0.0.1 or localhost is allowed')
    if parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise AIReviewError('Provide only the Ollama base URL, without a path')
    return base_url.rstrip('/') + '/api/chat'


def _payload(proposals: list[dict]) -> list[dict]:
    safe=[]
    for p in proposals:
        measurements={k:round(float(v),4) for k,v in p.get('metrics',{}).items()
                      if k in {'peak_dbfs','rms_dbfs','crest_db','level_variation_db','low_share','low_mid_share','presence_share','high_share'}
                      and isinstance(v,(int,float)) and math.isfinite(v)}
        safe.append({'index':int(p['index']), 'category':str(p.get('category','other'))[:40],
                     'measurements':measurements,
                     'suggested_roles':[s['role'] for s in p.get('fx_chain',[])],
                     'warnings':[str(x)[:180] for x in p.get('warnings',[])][:5]})
    return safe


def review_proposals(proposals: list[dict], *, model: str='qwen2.5:7b', base_url: str='http://127.0.0.1:11434',
                     timeout: float=25, transport=None) -> list[dict]:
    """Returns advisory decisions without mutating proposals or rendering audio.

    `transport` is injectable for isolated tests; takes (endpoint, body, timeout).
    """
    if not proposals:return []
    if not model.strip() or len(model)>120:raise AIReviewError('Invalid Ollama model name')
    endpoint=_local_endpoint(base_url)
    system=("You are an assistant to a cautious audio engineer. You CANNOT hear the audio. "
            "Only interpret provided approximate audio measurements and heuristic suggestions. "
            "Never claim an audible problem is confirmed, do not suggest new effects or exact settings, "
            "do not treat high-frequency energy as proof of AI generation. Return JSON only, as "
            "{\"reviews\":[{\"index\":integer,\"roles\":[{\"role\":string,\"decision\":\"keep|omit|review\",\"reason\":string}],\"note\":string}]}. "
            "Use the existing roles only; if insufficient evidence, choose review. Reasons in French, max 140 chars.")
    body={'model':model,'stream':False,'format':'json','options':{'temperature':0},
          'messages':[{'role':'system','content':system},
                      {'role':'user','content':json.dumps(_payload(proposals),ensure_ascii=False)}]}
    if transport is None:
        def transport(url, data, seconds):
            req=Request(url,data=json.dumps(data).encode('utf-8'),headers={'Content-Type':'application/json'},method='POST')
            with urlopen(req,timeout=seconds) as res:return json.loads(res.read(512_000).decode('utf-8'))
    try:
        result=transport(endpoint,body,timeout)
        text=result['message']['content']
        parsed=json.loads(text) if isinstance(text,str) else text
        raw=parsed['reviews']
    except Exception as exc:
        raise AIReviewError(f'Ollama response unavailable/invalid: {exc}') from exc
    if not isinstance(raw,list):raise AIReviewError('AI response must contain a reviews list')
    original={int(p['index']):{step['role'] for step in p.get('fx_chain',[])} for p in proposals}
    safe=[];seen=set()
    for r in raw:
        if not isinstance(r,dict) or type(r.get('index')) is not int:continue
        idx=r['index']
        if idx not in original or idx in seen:continue
        seen.add(idx)
        roles=[];roles_seen=set()
        for s in (r.get('roles') if isinstance(r.get('roles'),list) else []):
            if not isinstance(s,dict):continue
            role=s.get('role');decision=s.get('decision')
            if role not in original[idx] or role in roles_seen or decision not in ALLOWED_DECISIONS:continue
            roles_seen.add(role)
            roles.append({'role':role,'decision':decision,'reason':str(s.get('reason',''))[:140]})
        safe.append({'index':idx,'roles':roles,'note':str(r.get('note',''))[:220]})
    return safe


def merge_review(proposals: list[dict], reviews: list[dict]) -> list[dict]:
    """Return safe copies, removing only suggestions marked 'omit'. Never enables FX."""
    import copy
    output=copy.deepcopy(proposals)
    mapped={r['index']:r for r in reviews}
    for p in output:
        review=mapped.get(p['index'])
        if not review:continue
        decision={r['role']:r for r in review['roles']}
        p['fx_chain']=[fx for fx in p['fx_chain'] if decision.get(fx['role'],{}).get('decision')!='omit']
        p.setdefault('reasons',[]).append('IA locale (mesures uniquement) : '+review.get('note','')[:180])
        for fx in p['fx_chain']:
            fx['enabled']=False
            if fx['role'] in decision:
                fx['ai_review']=decision[fx['role']]
    return output
