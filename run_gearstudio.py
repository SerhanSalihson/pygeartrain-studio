"""Launcher for pyGearTrain Studio (also the PyInstaller entry point)."""
import sys

from gearstudio.app import main

if __name__ == '__main__':
    sys.exit(main())
