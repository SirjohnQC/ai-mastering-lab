"""Launch AI Mastering Lab desktop GUI from the existing project root."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from mastering_lab.desktop import main
if __name__ == '__main__':
    sys.exit(main(ROOT))
