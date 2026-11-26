"""v0.27.1 live audio startup and hang recovery regression tests."""
from __future__ import annotations

import ast
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mastering_lab.live_engine_startup import check_engine,locate_engine

ROOT=Path(__file__).resolve().parents[1]/'src'/'mastering_lab'
NATIVE=Path(__file__).resolve().parents[1]/'native'/'src'/'live_stems.cpp'


class StartupPreflightTests(unittest.TestCase):
    def test_missing_engine_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as temp:
            status=check_engine(temp)
        self.assertFalse(status['ready'])
        self.assertIn('non compilé',status['reason'])

    def test_successful_device_probe(self):
        with patch('mastering_lab.live_engine_startup.locate_engine',return_value=Path('juce.exe')), \
             patch('mastering_lab.live_engine_startup.subprocess.run',
                return_value=subprocess.CompletedProcess(
                    [],0,stdout='{"status":"progress","message":"checking"}\n'
                       '{"status":"probe_ok","device":"WASAPI","sample_rate":48000}\n',
                    stderr='')) as run:
            result=check_engine('.',timeout=5)
        self.assertTrue(result['ready'])
        self.assertIn('WASAPI',result['reason'])
        self.assertEqual(run.call_args.kwargs['timeout'],5)

    def test_probe_timeout_does_not_hang_app(self):
        with patch('mastering_lab.live_engine_startup.locate_engine',return_value=Path('juce.exe')), \
             patch('mastering_lab.live_engine_startup.subprocess.run',
                side_effect=subprocess.TimeoutExpired(['juce.exe'],5)):
            result=check_engine('.')
        self.assertFalse(result['ready'])
        self.assertIn('dépassé',result['reason'])

    def test_native_preflight_and_stage_diagnostics(self):
        code=NATIVE.read_text(encoding='utf-8')
        self.assertIn('args[0]=="--probe"',code)
        self.assertIn('JUCE audio device unavailable',code)
        self.assertIn('Opening stem files',code)
        self.assertIn('Opening JUCE output device',code)
        self.assertIn('Preparing streaming buffers',code)
        self.assertIn('msg->setProperty("status","ready")',code)

    def test_ui_has_bounded_watchdog_and_gui_fallback(self):
        ui=(ROOT/'live_stem_ui.py').read_text(encoding='utf-8')
        desktop=(ROOT/'desktop.py').read_text(encoding='utf-8')
        for f in (ui,desktop,(ROOT/'live_engine_startup.py').read_text(encoding='utf-8')):
            ast.parse(f)
        for needle in ('self.watchdog=QTimer(self)',
                       'self.watchdog.setInterval(12000)',
                       'self.watchdog.timeout.connect(self._startup_timeout)',
                       'self.process.kill()', "status=='progress'",
                       'self.watchdog.stop()'):
            self.assertIn(needle,ui)
        self.assertIn('QSplashScreen(splash_art)',desktop)
        self.assertIn('check_engine(root,timeout=5)',desktop)
        self.assertIn('splash.finish(win)',desktop)


if __name__=='__main__':
    unittest.main()
