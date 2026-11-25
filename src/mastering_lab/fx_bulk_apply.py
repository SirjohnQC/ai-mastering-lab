"""Safe, deterministic bulk application of reviewed Auto FX suggestions.

No audio rendering or user-authored effect replacement happens in this helper.
"""
from __future__ import annotations
import copy


def apply_proposals(tracks: list[dict], proposals: list[dict], *, enable_new: bool) -> dict:
    """Append proposed plugins to matched track indexes; preserve existing effects.

    Expects user-approved proposals. A proposal index must correspond to exactly
    the source file analyzed; a changed selection is refused instead of guessing.
    """
    # Validate *all* proposals before mutating any track.
    seen=set()
    for proposal in proposals:
        index=proposal.get('index')
        if type(index) is not int or index<0 or index>=len(tracks) or index in seen:
            raise ValueError('Invalid or duplicated stem index')
        seen.add(index)
        if tracks[index].get('file') != proposal.get('file'):
            raise ValueError('Stem selection has changed since analysis')
        for step in proposal.get('fx_chain',[]):
            if not step.get('plugin') or not step.get('role'):
                raise ValueError('Incomplete FX suggestion')
    result={'added':0,'tracks_changed':[],'already_present':0}
    for proposal in proposals:
        i=proposal['index'];track=tracks[i]
        chain=track.setdefault('fx_chain',[])
        existing={(x.get('role'),x.get('plugin')) for x in chain}
        added_track=False
        for suggested in proposal.get('fx_chain',[]):
            key=(suggested['role'],suggested['plugin'])
            if key in existing:
                result['already_present']+=1
                continue
            step=copy.deepcopy(suggested)
            step['enabled']=bool(enable_new)
            step['auto_fx_suggestion']=True
            chain.append(step)
            existing.add(key)
            result['added']+=1
            added_track=True
        if added_track:result['tracks_changed'].append(i)
    return result
