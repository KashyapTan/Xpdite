"""Package entrypoint for the bundled backend executable."""

from multiprocessing import freeze_support

from source.main import main


if __name__ == "__main__":
    freeze_support()
    main()
