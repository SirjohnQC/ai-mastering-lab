"""Local VST3 registry and user-selected plugin roles. No plugin code is loaded while scanning."""
from __future__ import annotations
from pathlib import Path
import json, os

ROLES = {
    "corrective_eq": "Corrective EQ",
    "compression": "Compression / dynamics",
    "resonance": "Resonance / de-esser",
    "reverb": "Reverb / spatial",
    "limiter": "Limiter / final master",
    "color": "Color / saturation",
}
KEYWORDS = {
    "corrective_eq": [("pro-q 4", 100), ("pro-q", 95), ("equalizer", 65), ("eq", 30)],
    "compression": [("pro-c", 95), ("compressor", 90), ("comp", 50), ("dynamics", 45)],
    "resonance": [("soothe", 100), ("resonance", 65), ("de-esser", 60), ("deesser", 60)],
    "reverb": [("pro-r", 100), ("reverb", 85), ("room", 20)],
    "limiter": [("pro-l", 100), ("maximizer", 95), ("limiter", 90), ("ozone", 40)],
    "color": [("saturn", 100), ("volcano", 85), ("saturat", 80), ("tape", 30)],
}

def default_scan_dirs() -> list[Path]:
    roots=[Path(os.environ.get("COMMONPROGRAMFILES",r"C:\Program Files\Common Files"))/"VST3",
           Path(os.environ.get("PROGRAMFILES",r"C:\Program Files"))/"Common Files"/"VST3",
           Path.home()/"AppData"/"Local"/"Programs"/"Common"/"VST3"]
    return list(dict.fromkeys(roots))

def discover_plugins(roots: list[Path]) -> list[dict]:
    """Inventory paths, including directories ending in .vst3, without executing plugin code."""
    found={}
    for root in roots:
        if not root.exists():continue
        for path in root.rglob("*.vst3"):
            if path.suffix.lower() != ".vst3":continue
            try:canonical=str(path.resolve())
            except OSError:continue
            found.setdefault(canonical.casefold(),{"name":path.stem,"path":canonical})
    return sorted(found.values(),key=lambda p:(p["name"].casefold(),p["path"].casefold()))

def suggested_roles(plugins: list[dict]) -> dict[str,str]:
    choices={}
    for role, terms in KEYWORDS.items():
        rankings=[]
        for p in plugins:
            name=p["name"].casefold()
            score=max((weight for term,weight in terms if term in name),default=0)
            if score: rankings.append((score, p["name"].casefold(), p["path"]))
        if rankings:
            # Strongest text match, deterministic tie-breaking
            rankings.sort(key=lambda r:(-r[0],r[1],r[2]))
            choices[role]=rankings[0][2]
    return choices

def read_settings(path:Path) -> dict:
    if not path.is_file():return {"schema_version":1,"roles":{},"setup_complete":False}
    data=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data,dict) or not isinstance(data.get("roles",{}),dict):
        raise ValueError("Invalid plugin settings")
    return data

def save_settings(path:Path, roles:dict, *, setup_complete=True) -> None:
    clean={key:str(roles.get(key,"")) for key in ROLES}
    path.parent.mkdir(parents=True,exist_ok=True)
    data={"schema_version":1,"setup_complete":bool(setup_complete),"roles":clean}
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(path)

def selected_proq4(settings_path:Path) -> Path|None:
    """Only Pro-Q 4 currently has a verified normalized parameter adapter."""
    data=read_settings(settings_path)
    candidate=str(data.get("roles",{}).get("corrective_eq", ""))
    p=Path(candidate) if candidate else None
    return p if p is not None and p.exists() and "pro-q 4" in p.stem.casefold() else None
