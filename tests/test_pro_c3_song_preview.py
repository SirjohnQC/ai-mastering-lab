import json
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
import soundfile as sf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from mastering_lab.pro_c3_song_preview import verify_source, verify_output, make_preview, audition_files, save_choice
from mastering_lab.pro_c3_parameter_validation import prepare_scenario

VALUES={'threshold':{.85:('-9.00 dB',-9),.7:('-18.00 dB',-18)},'ratio':{.3:('1.50:1',1.5),.7:('6.00:1',6)},'attack':{.3:('6.755 ms',6.755)},'release':{.3:('115.0 ms',115)}}
def grid():
 return {'read_only':True,'method':'getText','display_mapping_status':{k:'text_grid_plausible' for k in VALUES},'probe_points':{k:[{'normalized':n,'display_text':v[0],'physical':v[1]} for n,v in vals.items()] for k,vals in VALUES.items()}}

class PreviewTests(unittest.TestCase):
 def setUp(self):
  self.ctx=tempfile.TemporaryDirectory(); self.addCleanup(self.ctx.cleanup)
  self.root=Path(self.ctx.name)
  self.source=self.root/'song.wav'
  t=np.arange(96000,dtype=np.float32)/48000
  a=.22*np.sin(t*440*2*np.pi)
  sf.write(str(self.source),np.stack([a,a],axis=-1),48000)
 def test_source_restrictions(self):
  src,info=verify_source(self.source);self.assertEqual(info.frames,96000)
  bad=self.root/'bad.wav';sf.write(str(bad),np.zeros((96000,1)),48000)
  with self.assertRaises(ValueError):verify_source(bad)
  bad2=self.root/'wrong.wav';sf.write(str(bad2),np.zeros((96000,2)),44100)
  with self.assertRaises(ValueError):verify_source(bad2)
 def test_shape_rejects_wrong_tail_and_empty_audio(self):
  _,info=verify_source(self.source)
  good=self.root/'good.wav'
  x,_=sf.read(str(self.source),dtype='float32',always_2d=True)
  sf.write(str(good),np.vstack([x,np.zeros((64,2))]),48000)
  self.assertEqual(verify_output(good,info,64)['extra_tail_frames'],64)
  with self.assertRaises(ValueError):verify_output(good,info,63)
  bad=self.root/'silent.wav';sf.write(str(bad),np.zeros_like(x),48000)
  with self.assertRaises(ValueError):verify_output(bad,info,0)
 def test_approved_copy_only_and_readback(self):
  (self.root/'settings').mkdir()
  (self.root/'settings/pro_c3_multipoint.json').write_text(json.dumps(grid()))
  host=self.root/'host.exe';host.touch()
  plugin=self.root/'FabFilter Pro-C 3.vst3';plugin.mkdir()
  names={1:'Threshold',4:'Ratio',7:'Attack',8:'Release',19:'Auto Gain'}
  def runner(h,mode,**kw):
   if mode=='inspect':return {'name':'Pro-C 3','parameters':[{'index':i,'name':names.get(i,'Other'),'automatable':True} for i in range(20)]}
   inp,r=sf.read(str(kw['input_file']),dtype='float32',always_2d=True)
   changes=dict(kw['parameter_changes'])
   out=inp*(.55 if changes[4]==.7 else .87)
   sf.write(str(kw['output_file']),np.vstack([out,np.zeros((64,2))]),r)
   roles={1:'threshold',4:'ratio',7:'attack',8:'release'}
   return {'tail_samples':64,'parameter_changes':[{'index':idx,'text':VALUES[roles[idx]][v][0],'normalized_value':v} for idx,v in kw['parameter_changes'] if idx in roles]+[{'index':19,'text':'Off'}]}
  before_bytes=self.source.read_bytes()
  result=make_preview(self.root,self.source,host=host,plugin=plugin,runner=runner)
  self.assertEqual(result['status'],'needs_review',result.get('error'))
  self.assertEqual(self.source.read_bytes(),before_bytes)
  self.assertEqual(set(audition_files(self.root,result)),{'original','gentle','firm'})
  self.assertFalse(result['automatic_compression_enabled'])
  self.assertTrue(save_choice(self.root,result,'gentle').is_file())
  self.assertFalse(json.loads((self.root/'settings/pro_c3_song_preview_choices.jsonl').read_text().splitlines()[0])['use_for_hermes'])
  result['scenarios']['gentle']['output_path']=str(self.source)
  with self.assertRaises(ValueError):audition_files(self.root,result)
 def test_failure_does_not_export_or_authorize(self):
  (self.root/'settings').mkdir()
  (self.root/'settings/pro_c3_multipoint.json').write_text(json.dumps(grid()))
  host=self.root/'host.exe';host.touch();plugin=self.root/'FabFilter Pro-C 3.vst3';plugin.mkdir()
  names={1:'Threshold',4:'Ratio',7:'Attack',8:'Release',19:'Auto Gain'}
  def broken(h,mode,**kw):
   if mode=='inspect':return {'name':'Pro-C 3','parameters':[{'index':i,'name':names.get(i,'Other'),'automatable':True} for i in range(20)]}
   return {'tail_samples':64,'parameter_changes':[]}
  report=make_preview(self.root,self.source,host=host,plugin=plugin,runner=broken)
  self.assertEqual(report['status'],'failed')
  self.assertFalse(report['ready_to_render'])
  with self.assertRaises(ValueError):audition_files(self.root,report)

if __name__=='__main__': unittest.main()
