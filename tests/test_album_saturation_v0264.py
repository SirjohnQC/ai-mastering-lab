"""v0.26.4 saturation A/B: gentle modes, bounded controls, strict safety."""
from __future__ import annotations

import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import soundfile as sf

from mastering_lab.album_saturation_preview import (
    SATURATION_STYLES, validate_settings, process_saturation_wav,
    render_saturation_preview, SAFE_STRENGTHS,
)

ROOT=Path(__file__).resolve().parents[1]/'src'/'mastering_lab'


class SaturationPreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.wav=self.root/'original.wav'
        rate=48000
        t=np.arange(rate,dtype=np.float64)/rate
        signal=(.33*np.sin(2*np.pi*450*t)).astype(np.float64)
        sf.write(self.wav,np.column_stack((signal,signal)),rate,subtype='PCM_24')
        self.before=self.wav.read_bytes()

    def test_all_curves_produce_finite_stereo_audio_without_touching_original(self):
        for name in SATURATION_STYLES:
            output=self.root/f'{name}.wav'
            process_saturation_wav(self.wav,output,style=name,drive=1.0,mix=.2)
            with sf.SoundFile(output) as f:
                self.assertEqual((f.channels,f.samplerate,f.subtype),(2,48000,'PCM_24'))
                audio=f.read(dtype='float64')
                self.assertTrue(np.isfinite(audio).all())
                self.assertEqual(len(audio),48000)
            self.assertGreater(float(np.abs(audio).max()),0.01)
        self.assertEqual(self.wav.read_bytes(),self.before)

    def test_reject_bad_knobs(self):
        for style,drive,mix in (('unsupported',1,.2),('tape',10,.2),
                                ('tape',1,0),('tube',1,.6),
                                ('softclip',float('nan'),.1)):
            with self.assertRaises(ValueError):
                validate_settings(style,drive,mix)

    def test_independent_lufs_and_true_peak_with_adaptive_safety(self):
        calls=[]
        data=iter([
            {'input_i':'-14','input_tp':'-1.18'},
            {'input_i':'-13.9','input_tp':'-1.2'},
            {'input_i':'-14.0','input_tp':'-0.8'},
            {'input_i':'-13.95','input_tp':'-1.2'},
            {'input_i':'-14.01','input_tp':'-1.12'},
        ])
        def fake_processor(src,dst,*,style,drive,mix):
            calls.append((style,drive,mix))
            dst.write_bytes(b'a'*64)
        def fake_render(ffmpeg,src,dst,filter_chain):
            self.assertIn('volume=',filter_chain)
            dst.write_bytes(b'b'*64)
        with patch('mastering_lab.album_saturation_preview._probe_wav',return_value={
            'channels':2,'frames':48000,'sample_rate':48000,'subtype':'PCM_24'}), \
             patch('mastering_lab.album_saturation_preview._render',side_effect=fake_render):
            result=render_saturation_preview(
                self.wav,{'status':'measured'},self.root/'cache',style='tube',
                drive=1.0,mix=.2,ffmpeg_path='ffmpeg',
                processor_fn=fake_processor,measure_fn=lambda _:next(data))
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0],('tube',1.0,.2))
        self.assertEqual(calls[1],('tube',.75,.15))
        self.assertEqual(result['intensity'],.75)
        self.assertEqual(result['mode'],'saturation')
        self.assertFalse(result['approved'])
        self.assertEqual(result['saturation_style'],'tube')
        self.assertLessEqual(result['verified_true_peak_dbtp'],-1.0)
        self.assertEqual(self.wav.read_bytes(),self.before)

    def test_failure_does_not_expose_unsafe_preview(self):
        values=[{'input_i':-14,'input_tp':-1.15}]
        for _ in SAFE_STRENGTHS:
            values += [{'input_i':-13.9,'input_tp':-1.2},
                       {'input_i':-14,'input_tp':-.7}]
        iterator=iter(values)
        def fake_processor(_src,dst,**_kw):
            dst.write_bytes(b'x'*64)
        def fake_render(_ffmpeg,_src,dst,_filter):
            dst.write_bytes(b'x'*64)
        with patch('mastering_lab.album_saturation_preview._probe_wav',return_value={
            'channels':2,'frames':48000,'sample_rate':48000,'subtype':'PCM_24'}), \
             patch('mastering_lab.album_saturation_preview._render',side_effect=fake_render):
            with self.assertRaisesRegex(RuntimeError,'No safe saturation B'):
                render_saturation_preview(
                    self.wav,{'status':'measured'},self.root/'cache',
                    ffmpeg_path='ffmpeg',processor_fn=fake_processor,
                    measure_fn=lambda _:next(iterator))
        self.assertFalse(list((self.root/'cache').glob('album-saturation-ab-*.wav')))
        self.assertEqual(self.wav.read_bytes(),self.before)

    def test_qt_wiring_and_version(self):
        for name in ('album_saturation_preview.py','album_studio_ui.py',
                     'album_tonal_preview.py','version.py'):
            ast.parse((ROOT/name).read_text(encoding='utf-8'))
        ui=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        for token in ('render_saturation_preview(', 'self.drive_slider=QSlider(Qt.Horizontal)',
                      'self.wet_slider=QSlider(Qt.Horizontal)',
                      "('saturation','tape')", "('saturation','tube')",
                      "('saturation','softclip')", 'self._preview_loaded',
                      'self._update_active_indicator()'):
            self.assertIn(token,ui)


if __name__=='__main__':
    unittest.main()
