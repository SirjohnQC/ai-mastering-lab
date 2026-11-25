"""Run from the project root, or provide --root path."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from mastering_lab.compression_diagnostics import main
if __name__ == '__main__':
    main()
