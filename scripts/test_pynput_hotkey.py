
import platform
import logging
from pynput import keyboard

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def test_hotkey():
    is_mac = platform.system() == "Darwin"
    hotkey_str = "<ctrl>+." if is_mac else "<alt>+."
    
    logger.info(f"Testing hotkey: {hotkey_str}")
    logger.info("Press the hotkey to see if it triggers. Press Ctrl+C to exit.")

    def on_activate():
        logger.info("HOTKEY TRIGGERED! <ctrl>+. detected")

    try:
        # pynput hotkeys on Mac sometimes need exactly what it expects
        # <ctrl> is usually Control key.
        with keyboard.GlobalHotKeys({hotkey_str: on_activate}) as h:
            h.join()
    except KeyboardInterrupt:
        logger.info("Test stopped.")
    except Exception as e:
        logger.error(f"Error: {e}")

if __name__ == "__main__":
    test_hotkey()
