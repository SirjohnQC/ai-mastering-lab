import json
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
import soundfile as sf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from mastering_lab.pro_c3_parameter_validation import (prepare_scenario, validate_readback, run_validation, SCENARIOS)
from mastering_lab.pro_c3_testbench import RATE

DISPLAY = {
 'threshold': {0.85: ('-9.00 dB',-9.0), 0.70: ('-18.00 dB',-18.0)},
 'ratio': {0.30: ('1.50:1',1.5), 0.70: ('6.00:1',6.0)},
 'attack': {0.30: ('6.755 ms',6.755)},
 'release': {0.30: ('115.0 ms',115.0)},
}

def grid():
 return {'read_only': True,'method':'getText','display_mapping_status': {k:'text_grid_plausible' for k in DISPLAY},
         'probe_points':{k:[{'normalized':n,'display_text':v[0],'physical':v[1]} for n,v in vals.items()] for k,vals in DISPLAY.items()}}

class Tests(unittest.TestCase):
 def test_exact_grid_points_only(self):
  e,c=prepare_scenario(grid(),'gentle')
  self.assertIn((19,0.0),c)
  self.assertEqual(e['threshold']['physical'],-9)
  bad=grid();bad['probe_points']['threshold']=[]
  with self.assertRaises(ValueError):prepare_scenario(bad,'gentle')
 def test_readback_never_trust_missing_or_wrong(self):
  exp,changes=prepare_scenario(grid(),'firm')
  def echo(override=None):
   vals={k:{'index':idx,'text':exp[k]['display_text']} for k,idx in [('threshold',1),('ratio',4),('attack',7),('release',8)]}
   arr=list(vals.values())+[{'index':19,'text':'Off'}]
   if override:arr[1]['text']=override
   return {'parameter_changes':arr}
  self.assertEqual(len(validate_readback(echo(),exp)),4)
  with self.assertRaises(ValueError):validate_readback(echo('24.40:1'),exp)
  with self.assertRaises(ValueError):validate_readback({'parameter_changes':[]},exp)
 def test_realistic_mocked_renders_and_reporting(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'settings').mkdir()
   (root/'settings/pro_c3_multipoint.json').write_text(json.dumps(grid()))
   h=root/'mastering-host.exe';h.touch()
   p=root/'FabFilter Pro-C 3.vst3';p.mkdir()
   names={1:'Threshold',4:'Ratio',7:'Attack',8:'Release',19:'Auto Gain'}
   def runner(host, mode, **kw):
    if mode=='inspect':return {'name':'Pro-C 3','parameters':[{'index':i,'name':names.get(i,'Other'),'automatable':True} for i in range(20)]}
    s,r=sf.read(str(kw['input_file']),always_2d=True,dtype='float32')
    changes=dict(kw['parameter_changes'])
    firm=changes[4] == .70
    out=s.copy()
    # Construct a deterministic synthetic compression effect.
    for lo in (RATE,3*RATE):out[lo:lo+RATE]*=(.38 if firm else .84)
    sf.write(str(kw['output_file']),np.vstack([out,np.zeros((64,2),dtype='float32')]),r)
    ix_to_role={1:'threshold',4:'ratio',7:'attack',8:'release'}
    items=[{'index':idx,'text':DISPLAY[ix_to_role[idx]][n][0], 'normalized_value':n} for idx,n in kw['parameter_changes'] if idx in ix_to_role]
    items.append({'index':19,'text':'Off'})
    return {'parameter_changes':items,'tail_samples':64}
   report=run_validation(root,host=h,plugin=p,runner=runner)
   self.assertEqual(report['status'],'needs_review',report.get('error'))
   self.assertFalse(report['ready_to_render'])
   self.assertGreater(report['comparison']['high_level_attenuation_delta_db'],1)
   self.assertEqual(len(list(root.rglob('synthetic-*.wav'))),3)
   self.assertTrue(Path(report['report_path']).exists())
 def test_failure_still_creates_report_and_locks(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'settings').mkdir();(root/'settings/pro_c3_multipoint.json').write_text(json.dumps(grid()))
   h=root/'host.exe';h.touch();p=root/'FabFilter Pro-C 3.vst3';p.mkdir()
   names={1:'Threshold',4:'Ratio',7:'Attack',8:'Release',19:'Auto Gain'}
   def runner(h,mode,**kw):
    if mode=='inspect':return {'name':'Pro-C 3','parameters':[{'index':i,'name':names.get(i,'Other'),'automatable':True} for i in range(20)]}
    return {'parameter_changes':[], 'tail_samples':0}
   report=run_validation(root,host=h,plugin=p,runner=runner)
   self.assertEqual(report['status'],'failed')
   self.assertFalse(report['automatic_compression_enabled'])

if __name__=='__main__':unittest.main()
