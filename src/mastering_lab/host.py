"""Thin, safe subprocess bridge to the JUCE mastering host."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path


def run_host(executable: str | Path, command: str, *, plugin: str | Path,
             input_file: str | Path | None = None, output_file: str | Path | None = None,
             parameter_index: int | None = None, value: float | None = None,
             state_in: str | Path | None = None, state_out: str | Path | None = None,
             parameter_changes: list[tuple[int, float]] | None = None,
             timeout: int = 180) -> dict:
    if command not in ("inspect", "render"):
        raise ValueError("command must be inspect or render")
    args = [str(executable), command, "--plugin", str(plugin)]
    if command == "render":
        if input_file is None or output_file is None:
            raise ValueError("render requires input_file and output_file")
        if Path(input_file).resolve() == Path(output_file).resolve():
            raise ValueError("input and output must differ")
        args += ["--input", str(input_file), "--output", str(output_file)]
    if parameter_index is not None:
        if value is None or not 0 <= value <= 1:
            raise ValueError("parameter value must be between 0 and 1")
        args += ["--parameter-index", str(parameter_index), "--value", str(value)]
    for idx, normalized in (parameter_changes or []):
        if isinstance(idx, bool) or not isinstance(idx, int) or idx < 0 or not isinstance(normalized, (float, int)) or not 0 <= normalized <= 1:
            raise ValueError("parameter_changes entries must be (nonnegative integer, float 0..1)")
        args += ["--set", f"{idx}:{normalized}"]
    for key, path in (("--state-in", state_in), ("--state-out", state_out)):
        if path is not None:
            args += [key, str(path)]
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Host failed (exit {result.returncode}): {result.stderr or result.stdout}") from exc
    if result.returncode or "error" in payload:
        raise RuntimeError(f"Host error (exit {result.returncode}): {payload.get('error', payload)}")
    return payload
