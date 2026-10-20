"""PyInstaller entry point. No repository checkout is needed at runtime."""

from multiprocessing import freeze_support

if __name__ == "__main__":
    freeze_support()
    from canvas_bridge.desktop import main

    main()
