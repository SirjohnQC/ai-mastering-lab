"""v0.27.0 first real-time JUCE multistem playback milestone.

These structural checks are a cross-platform smoke gate. Native compilation
and actual Windows audio-device behaviour require local acceptance tests.
"""
from pathlib import Path
import ast
import unittest

ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'native'/'src'/'live_stems.cpp'
GUI=ROOT/'src'/'mastering_lab'/'live_stem_ui.py'
ALBUM=ROOT/'src'/'mastering_lab'/'album_studio_ui.py'


class LiveStemMilestoneTests(unittest.TestCase):
    def test_native_realtime_target_exists_without_replacing_offline_host(self):
        cmake=(ROOT/'native'/'CMakeLists.txt').read_text(encoding='utf-8')
        self.assertIn('juce_add_console_app(mastering-host',cmake)
        self.assertIn('juce_add_console_app(frankenstem-live',cmake)
        self.assertIn('src/live_stems.cpp',cmake)

    def test_native_audio_callback_uses_read_ahead_and_atomic_controls(self):
        c=NATIVE.read_text(encoding='utf-8')
        for text in ('BufferingAudioSource',
                     'TimeSliceThread', 'AudioSourcePlayer',
                     'AudioDeviceManager', 'std::atomic<float> drive',
                     'std::atomic<bool> enabled',
                     'getNextAudioBlock(', 'std::tanh(',
                     'setNextReadPosition(', 'prop(msg,"cmd")',
                     'action=="seek"', 'action=="pause"',
                     'action=="set"', 'action=="status"',
                     'Stem sample rates differ', 'Stems differ in length',
                     'getCurrentSampleRate()'):
            self.assertIn(text,c)
        self.assertNotIn('WavAudioFormat',c)
        self.assertNotIn('createWriterFor',c)

    def test_gui_starts_separate_engine_and_sends_parameter_commands(self):
        src=GUI.read_text(encoding='utf-8')
        ast.parse(src)
        for needle in ('class LiveStemDialog(QDialog):',
                       'self.process=QProcess(self)',
                       "self.process.setArguments(['--stems'",
                       'self.process.write(',
                       "self._send({'cmd':'set','stem':self.active,**value})",
                       'self.effect.currentIndexChanged.connect(self._change_fx)',
                       'self.drive.valueChanged.connect(self._change_fx)',
                       'self.wet.valueChanged.connect(self._change_fx)',
                       'self.enabled.toggled.connect(self._change_fx)',
                       'self.solo.toggled.connect(self._change_fx)',
                       'self.mute.toggled.connect(self._change_fx)',
                       'self._shutdown()',
                       "self.selection=validated_selections(self.config,selection)"):
            self.assertIn(needle,src)

    def test_album_approval_is_explicit_and_old_qc_invalidated(self):
        src=ALBUM.read_text(encoding='utf-8')
        ast.parse(src)
        self.assertIn("live_btn=QPushButton('▶ Live FX')",src)
        self.assertIn('from .live_stem_ui import LiveStemDialog',src)
        self.assertIn("track['stem_saturation']=dialog.selection",src)
        self.assertIn("track['status']='waiting'",src)
        self.assertIn('dialog.exec()!=QDialog.Accepted',src)

    def test_version_and_python_module_parse(self):
        version=(ROOT/'src'/'mastering_lab'/'version.py').read_text()
        self.assertIn('0.27.0',version)
        ast.parse(version)


if __name__=='__main__':
    unittest.main()
