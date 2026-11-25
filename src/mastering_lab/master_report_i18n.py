"""Localized presentation of technical mastering results.

Raw FFmpeg/JUCE reports stay language-independent. Formatting never changes
audio processing, files or measured values.
"""
from __future__ import annotations


def format_master_result(result: dict, language='fr') -> tuple[str,str]:
    en = language == 'en'
    ok = result.get('status') == 'qc_pass'
    status = ('✓ QC checks passed' if en else '✓ Contrôles QC réussis') if ok else (
        '⚠ Master rendered — QC review required' if en else '⚠ Master créé — QC à revoir')
    issues = result.get('qc_issues') or []
    label = 'Review required: ' if en else 'À vérifier : '
    done = ('Technical QC completed. Critical listening and album consistency still required.'
            if en else 'QC technique terminé. Écoute critique et cohérence album encore nécessaires.')
    info = ('Integrated loudness' if en else 'LUFS intégrés')
    target = 'target' if en else 'cible'
    peak = 'ceiling' if en else 'plafond'
    text = (
        f"{info}: {result['output_lufs']:.2f} LUFS ({target} {result['target_lufs']:.1f})\n"
        f"True peak: {result['output_true_peak_dbtp']:.2f} dBTP "
        f"({peak} {result['target_true_peak_dbtp']:.1f})\n"
        f"24-bit PCM · {result['output']['sample_rate']} Hz · stereo WAV\n"
        f"{result['file']}\n"
        + (label + '; '.join(issues) if issues else done)
    )
    return status, text
