from unittest.mock import patch
import pytest
from mastering_lab.host import run_host


def test_rejects_same_input_output():
    with pytest.raises(ValueError):
        run_host('host.exe', 'render', plugin='x.vst3', input_file='a.wav', output_file='a.wav')


def test_rejects_invalid_parameter_value():
    with pytest.raises(ValueError):
        run_host('host.exe', 'inspect', plugin='x.vst3', parameter_index=2, value=2)


def test_inspect_command():
    class Result:
        returncode = 0
        stdout = '{"name":"test","parameters":[]}'
        stderr = ''
    with patch('subprocess.run', return_value=Result()) as call:
        output = run_host('host.exe', 'inspect', plugin='x.vst3')
    assert output['name'] == 'test'
    assert call.call_args.args[0][1] == 'inspect'


def test_multiple_parameter_changes():
    class Result:
        returncode = 0
        stdout = '{"status":"ok"}'
        stderr = ''
    with patch('subprocess.run', return_value=Result()) as call:
        output = run_host('host.exe', 'render', plugin='x.vst3', input_file='a.wav',
                          output_file='b.wav', parameter_changes=[(0, 1.0), (3, 0.6)])
    assert output['status'] == 'ok'
    assert call.call_args.args[0][-4:] == ['--set', '0:1.0', '--set', '3:0.6']
