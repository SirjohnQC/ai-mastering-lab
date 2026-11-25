"""Carefully add a read-only Pro-C3 text probe to the existing native host source.

Run from project root: python scripts/install_pro_c3_probe.py
Makes a .pre_probe_backup.cpp backup and refuses unknown source layout.
"""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = root / 'native/src/main.cpp'
if not source.is_file():
    raise SystemExit('native/src/main.cpp introuvable — aucune modification faite.')
old = source.read_text(encoding='utf-8')
if 'PRO_C3_TEXT_PROBE_V1' in old:
    print('Probe déjà présent. Aucun changement.'); raise SystemExit(0)
anchor = '    if (cmd == "inspect") { printJson(describe(*plugin)); plugin->releaseResources(); return 0; }'
if old.count(anchor) != 1:
    raise SystemExit('Structure native différente. Patch refusé : demande une adaptation manuelle.')
probe = r'''    // PRO_C3_TEXT_PROBE_V1: READ ONLY, no setValue(), no processBlock(), no WAV.
    if (cmd == "probe") {
        auto* obj = new DynamicObject();
        obj->setProperty("name", plugin->getName());
        obj->setProperty("read_only", true);
        obj->setProperty("method", "getText");
        Array<var> readings;
        auto& params = plugin->getParameters();
        const int ids[] = {1, 4, 7, 8};
        const double grid[] = {0.05, 0.15, 0.30, 0.50, 0.70, 0.85, 0.95};
        for (int idx : ids) {
            if (idx < 0 || idx >= params.size()) {
                printJson(error("Pro-C 3 parameter index missing"));
                plugin->releaseResources(); return 5;
            }
            auto* param = params[idx];
            for (double value : grid) {
                auto* pt = new DynamicObject();
                pt->setProperty("index", idx);
                pt->setProperty("name", param->getName(256));
                pt->setProperty("normalized", value);
                pt->setProperty("display_text", param->getText((float)value, 100));
                readings.add(var(pt));
            }
        }
        obj->setProperty("probe_points", var(readings));
        printJson(var(obj));
        plugin->releaseResources(); return 0;
    }
'''
backup = source.with_suffix('.pre_probe_backup.cpp')
if backup.exists():
    raise SystemExit('Sauvegarde existante. Patch refusé pour ne rien écraser.')
backup.write_text(old, encoding='utf-8')
source.write_text(old.replace(anchor, probe + anchor), encoding='utf-8')
print('Probe lecture seule ajouté. Recompiler mastering-host.exe avant de calibrer.')
