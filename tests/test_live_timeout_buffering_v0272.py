"""v0.27.2 safety: nonblocking JUCE read-ahead and truthful timeout reporting."""
from pathlib import Path
import ast
import unittest

ROOT=Path(__file__).resolve().parents[1]
NATIVE=(ROOT/'native/src/live_stems.cpp').read_text(encoding='utf-8')
UI=(ROOT/'src/mastering_lab/live_stem_ui.py').read_text(encoding='utf-8')


class LiveTimeoutRegressionTests(unittest.TestCase):
    def test_disk_buffer_prefill_does_not_block_startup_per_stem(self):
        self.assertIn('stem->reader.get(),readAhead,false,65536,stem->channels,false',NATIVE)
        self.assertNotIn('stem->reader.get(),readAhead,false,65536,stem->channels,true',NATIVE)

    def test_native_startup_checkpoint_brackets_callbacks(self):
        for marker in ('before player.setSource','after player.setSource',
                       'before devices.addAudioCallback',
                       'after devices.addAudioCallback'):
            self.assertIn(marker,NATIVE)
        self.assertIn('Starting JUCE audio callback',NATIVE)
        self.assertIn('std::fflush(stderr)',NATIVE)

    def test_timeout_not_mislabeled_as_crash(self):
        ast.parse(UI)
        self.assertIn("self._forced_timeout=True",UI)
        self.assertIn("if self._forced_timeout or self._closing_engine:",UI)
        self.assertIn("self.watchdog.start()",UI)
        self.assertIn("Ce n’est pas un crash natif confirmé",UI)
        self.assertIn("self._startup_phase='timeout'",UI)

    def test_versions_and_conservative_audio(self):
        version=(ROOT/'src/mastering_lab/version.py').read_text(encoding='utf-8')
        self.assertIn('0.27.2',version)
        self.assertIn('AudioSourcePlayer player;',NATIVE)
        self.assertIn('devices.removeAudioCallback(&player);',NATIVE)
        self.assertIn('thread.stopThread(2000);',NATIVE)


if __name__=='__main__':
    unittest.main()
