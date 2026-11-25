from pathlib import Path
import json
from mastering_lab.gui_models import list_audio, find_report, audio_choices, audition_gain, store_preference


def test_list_audio(tmp_path):
    for n in ('B.MP3','a.wav','readme.txt'):(tmp_path/n).touch()
    assert [p.name for p in list_audio(tmp_path)]==['a.wav','B.MP3']


def test_report_selection(tmp_path):
    root=tmp_path;source=root/'source.wav';source.touch()
    report=root/'sound'/'output'/'candidates'/'song'/'candidate-report.json'
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({'source':str(source)}))
    assert find_report(root,source)==report


def test_choices_missing_output(tmp_path):
    src=tmp_path/'source.wav';src.touch()
    report={'candidate_profiles':{'warm':{'status':'rendered','wav':str(tmp_path/'missing.wav')}}}
    assert audio_choices(report,src)=={'original':src}


def test_audition_attenuates_louder():
    report={'original':{'rms_dbfs':-20},'candidate_profiles':{
        'warm':{'status':'rendered','metrics':{'analysis':{'rms_dbfs':-14}}},
        'balanced':{'status':'rendered','metrics':{'analysis':{'rms_dbfs':-22}}}}}
    assert audition_gain(report,'balanced')==1
    assert .39<audition_gain(report,'warm')<.41
    assert .79<audition_gain(report,'original')<.80


def test_preference_saved(tmp_path):
    path=tmp_path/'preferences.json'
    src=tmp_path/'a.wav';ref=tmp_path/'b.mp3'
    store_preference(path,src,ref,'warm')
    store_preference(path,src,ref,'balanced')
    values=json.loads(path.read_text())
    assert [v['selected'] for v in values]==['warm','balanced']
