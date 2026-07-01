import subprocess
import sys
from pathlib import Path

def main() -> None:
    app_path = Path(__file__).resolve().parent.parent / "dashboard" / "app.py"

    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path)],
        check=True,
    )

if __name__ == "__main__":
    main()