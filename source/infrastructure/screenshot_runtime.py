import tkinter as tk
import PIL.ImageGrab as ImageGrab
from PIL import Image, ImageTk
import os
import datetime
from pynput import keyboard
import threading
import platform
import time
import logging
from io import BytesIO
import subprocess

logger = logging.getLogger(__name__)

# Fix for high DPI displays on Windows
if platform.system() == "Windows":
    try:
        import ctypes
        from ctypes import wintypes

        # Set DPI awareness for the process - try multiple methods for better compatibility
        try:
            # Windows 10, version 1703 and later (best option)
            ctypes.windll.shcore.SetProcessDpiAwarenessContext(
                -4
            )  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        except Exception:
            try:
                # Windows 10, version 1607 and later
                ctypes.windll.shcore.SetProcessDpiAwareness(
                    2
                )  # PROCESS_PER_MONITOR_DPI_AWARE
            except Exception:
                try:
                    # Windows Vista and later (fallback)
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass  # Fallback: do nothing if DPI functions aren't available

        def get_dpi_scale():
            """Get the DPI scaling factor for the primary monitor"""
            try:
                # Try to get DPI for the monitor containing the cursor
                try:
                    # Get cursor position
                    cursor_pos = wintypes.POINT()
                    ctypes.windll.user32.GetCursorPos(ctypes.byref(cursor_pos))

                    # Get monitor handle for the cursor position
                    monitor = ctypes.windll.user32.MonitorFromPoint(
                        cursor_pos,
                        1,  # MONITOR_DEFAULTTOPRIMARY
                    )

                    # Get DPI for this specific monitor (Windows 10+)
                    dpi_x = ctypes.c_uint()
                    dpi_y = ctypes.c_uint()
                    ctypes.windll.shcore.GetDpiForMonitor(
                        monitor,
                        0,
                        ctypes.byref(dpi_x),
                        ctypes.byref(dpi_y),  # MDT_EFFECTIVE_DPI
                    )
                    return dpi_x.value / 96.0
                except Exception:
                    # Fallback to system DPI
                    hdc = ctypes.windll.user32.GetDC(0)
                    dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
                    ctypes.windll.user32.ReleaseDC(0, hdc)
                    return dpi / 96.0
            except Exception:
                return 1.0

    except ImportError:

        def get_dpi_scale():
            return 1.0
else:

    def get_dpi_scale():
        return 1.0


def copy_image_to_clipboard(image, dpi_scale=None):
    """
    Robust way to copy a PIL Image to the Windows clipboard.
    Handles 64-bit handles, DPI scaling, and busy clipboards.
    """
    if platform.system() != "Windows":
        return False

    try:
        import ctypes
        import io

        # If no scale provided, try to get it
        if dpi_scale is None:
            dpi_scale = get_dpi_scale()

        # 96 is standard; 144 is 150%, etc.
        dpi = int(96 * dpi_scale)
        output = io.BytesIO()
        # Convert to RGB and save as BMP with DPI metadata
        # Setting DPI ensures apps like Word/Photoshop scale it correctly
        image.convert("RGB").save(output, "BMP", dpi=(dpi, dpi))
        data = output.getvalue()[14:]  # Strip 14-byte BMP header to get DIB
        output.close()

        # Define Windows API types (CRITICAL for 64-bit support to prevent handle truncation)
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32

        # Use c_void_p for handles to be safe on 64-bit
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

        # Retry loop: Clipboard is often locked momentarily by managers or other apps
        for _ in range(10):
            if user32.OpenClipboard(0):
                try:
                    user32.EmptyClipboard()
                    # GMEM_MOVEABLE (0x0002) | GMEM_ZEROINIT (0x0040) = 0x0042
                    h_mem = kernel32.GlobalAlloc(0x0042, len(data))
                    if h_mem:
                        p_mem = kernel32.GlobalLock(h_mem)
                        if p_mem:
                            ctypes.memmove(p_mem, data, len(data))
                            kernel32.GlobalUnlock(h_mem)

                            # CF_DIB = 8
                            user32.SetClipboardData(8, h_mem)
                finally:
                    user32.CloseClipboard()
                return True
            time.sleep(0.05)

    except Exception as e:
        logger.error("Error copying to clipboard: %s", e)

    return False


def copy_file_to_clipboard(filepath):
    """Uses PowerShell to copy the actual file to clipboard (so you can paste into folders)"""
    if platform.system() != "Windows" or not os.path.exists(filepath):
        return False
    try:
        abspath = os.path.abspath(filepath).replace("'", "''")
        cmd = f'Set-Clipboard -Path "{abspath}"'
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            creationflags=0x08000000,
            check=True,
        )
        return True
    except Exception as e:
        logger.error("PowerShell file copy failed: %s", e)
        return False


class ScreenshotService:
    def __init__(self, callback=None, start_callback=None):
        self.listener = None
        self.running = False
        self.callback = callback  # Function to call when screenshot is taken
        self.start_callback = (
            start_callback  # Function to call when screenshot capture starts
        )
        self.capturing = False
        self._lock = threading.Lock()
        self._last_trigger_time = 0  # Debounce timestamp

    def _do_capture(self, save_folder):
        try:
            path = take_region_screenshot(save_folder)
            if path:
                logger.info("Screenshot saved: %s", path)
                if self.callback:
                    threading.Thread(
                        target=self.callback, args=(path,), daemon=True
                    ).start()
            else:
                logger.info("Screenshot cancelled.")
        finally:
            with self._lock:
                self.capturing = False

    def start_listener(self, save_folder="screenshots"):
        """Start listening for Alt+. keyboard shortcut (strict)."""
        self.running = True
        logger.info(
            "Screenshot service started. Press Alt+. to take a region screenshot."
        )
        logger.info("Press Ctrl+C to stop the service.")

        def on_activate():
            current_time = time.time()
            with self._lock:
                if not self.running:  # Check if service is still running
                    return
                if self.capturing:
                    return
                # Debounce: ignore triggers within 1.5s of the last one
                if current_time - self._last_trigger_time < 1.5:
                    return
                self.capturing = True
                self._last_trigger_time = current_time
            logger.info("Hotkey detected! Starting region selection...")

            # Call the start callback if provided
            if self.start_callback:
                threading.Thread(target=self.start_callback, daemon=True).start()

            threading.Thread(
                target=self._do_capture, args=(save_folder,), daemon=True
            ).start()

        self.listener = keyboard.GlobalHotKeys({"<alt>+.": on_activate})
        self.listener.start()
        try:
            while self.running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            logger.info("Screenshot service stopped.")
        finally:
            self.stop_listener()

    def stop_listener(self):
        """Stop the keyboard listener."""
        self.running = False
        if self.listener:
            try:
                self.listener.stop()
                logger.info("Keyboard listener stopped")
            except Exception as e:
                logger.error("Error stopping keyboard listener: %s", e)
            self.listener = None


def take_region_screenshot(save_folder="screenshots", debug=False):
    """
    Opens a region selection tool and returns the path to the saved screenshot
    """
    if not os.path.exists(save_folder):
        os.makedirs(save_folder)

    class RegionSelector:
        def __init__(self, debug=False):
            self.start_x = 0
            self.start_y = 0
            self.end_x = 0
            self.end_y = 0
            self.rect_id = None
            self.result_path = None
            self.dpi_scale = get_dpi_scale()
            self.debug = debug

        def select_region(self):
            root = tk.Tk()

            # Configure Tkinter for high DPI on Windows
            if platform.system() == "Windows":
                try:
                    root.tk.call("tk", "scaling", self.dpi_scale)
                except Exception:
                    pass

            root.attributes("-fullscreen", True)
            root.attributes("-alpha", 1.0)  # Fully visible for region selection UI
            root.configure(bg="grey")
            root.attributes("-topmost", True)
            root.withdraw()  # Hide initially

            root.after(100, self._show_selector, root)
            root.mainloop()
            return self.result_path

        def _show_selector(self, root):
            root.deiconify()

            # Capture the screen at full resolution first
            screen = ImageGrab.grab()
            screen_width, screen_height = screen.size

            # Get Tkinter's view of screen dimensions
            root.update_idletasks()
            tk_width = root.winfo_screenwidth()
            tk_height = root.winfo_screenheight()

            # Calculate coordinate transformation ratios
            # These handle the case where Tkinter coordinates != actual pixels
            scale_x = screen_width / tk_width
            scale_y = screen_height / tk_height

            if self.debug:
                logger.debug("Screen resolution: %dx%d", screen_width, screen_height)
                logger.debug("Tkinter resolution: %dx%d", tk_width, tk_height)
                logger.debug("Scale factors: %.3fx, %.3fy", scale_x, scale_y)
                logger.debug("DPI scale: %.3f", self.dpi_scale)

            # Create display version - scale down screen capture to match Tkinter's coordinate system
            # This ensures the preview matches what the user will select
            if scale_x != 1.0 or scale_y != 1.0:
                display_screen = screen.resize(
                    (tk_width, tk_height), Image.Resampling.LANCZOS
                )
            else:
                display_screen = screen
            # Create dimmed overlay for the display
            screen_rgba = display_screen.convert("RGBA")
            overlay = Image.new("RGBA", screen_rgba.size, (0, 0, 0, 100))
            dimmed = Image.alpha_composite(screen_rgba, overlay)
            dimmed_photo = ImageTk.PhotoImage(dimmed)
            original_photo = ImageTk.PhotoImage(display_screen)

            canvas = tk.Canvas(root, cursor="cross")
            canvas.pack(fill=tk.BOTH, expand=True)
            canvas.create_image(0, 0, anchor=tk.NW, image=dimmed_photo, tags=("base",))

            # Store references to prevent garbage collection
            canvas.dimmed_photo = dimmed_photo  # type: ignore
            canvas.original_photo = original_photo  # type: ignore

            def on_button_press(event):
                self.start_x = event.x
                self.start_y = event.y

            def on_move_press(event):
                canvas.delete("reveal")
                canvas.delete("outline")
                self.end_x = event.x
                self.end_y = event.y
                x1 = min(self.start_x, self.end_x)
                y1 = min(self.start_y, self.end_y)
                x2 = max(self.start_x, self.end_x)
                y2 = max(self.start_y, self.end_y)
                if x2 > x1 and y2 > y1:
                    # Use display coordinates for the preview
                    region = display_screen.crop((x1, y1, x2, y2))
                    region_photo = ImageTk.PhotoImage(region)
                    canvas.create_image(
                        x1, y1, anchor=tk.NW, image=region_photo, tags=("reveal",)
                    )
                    canvas._reveal_photo = region_photo  # type: ignore
                    canvas.create_rectangle(
                        x1, y1, x2, y2, outline="white", width=2, tags=("outline",)
                    )

            def on_button_release(event):
                self.end_x = event.x
                self.end_y = event.y
                root.withdraw()
                root.update()
                x1 = min(self.start_x, self.end_x)
                y1 = min(self.start_y, self.end_y)
                x2 = max(self.start_x, self.end_x)
                y2 = max(self.start_y, self.end_y)
                if x2 > x1 and y2 > y1:
                    # Convert Tkinter coordinates to actual screen pixel coordinates
                    actual_x1 = int(x1 * scale_x)
                    actual_y1 = int(y1 * scale_y)
                    actual_x2 = int(x2 * scale_x)
                    actual_y2 = int(y2 * scale_y)

                    # Ensure coordinates are within screen bounds
                    actual_x1 = max(0, min(actual_x1, screen_width))
                    actual_y1 = max(0, min(actual_y1, screen_height))
                    actual_x2 = max(0, min(actual_x2, screen_width))
                    actual_y2 = max(0, min(actual_y2, screen_height))

                    if self.debug:
                        logger.debug(
                            "Tkinter coords: (%s,%s) to (%s,%s)", x1, y1, x2, y2
                        )
                        logger.debug(
                            "Actual coords: (%s,%s) to (%s,%s)",
                            actual_x1,
                            actual_y1,
                            actual_x2,
                            actual_y2,
                        )

                    # Crop from the original full-resolution screen capture
                    region_screenshot = screen.crop(
                        (actual_x1, actual_y1, actual_x2, actual_y2)
                    )
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"screenshot_{timestamp}.png"
                    filepath = os.path.join(save_folder, filename)
                    region_screenshot.save(filepath)
                    self.result_path = filepath

                    # Copy to clipboard (both pixels and file reference)
                    copy_image_to_clipboard(region_screenshot, self.dpi_scale)
                    copy_file_to_clipboard(filepath)

                    if self.debug:
                        logger.debug(
                            "Saved %dx%d screenshot",
                            region_screenshot.size[0],
                            region_screenshot.size[1],
                        )
                root.destroy()

            def on_escape(event):
                root.destroy()

            canvas.bind("<Button-1>", on_button_press)
            canvas.bind("<B1-Motion>", on_move_press)
            canvas.bind("<ButtonRelease-1>", on_button_release)
            canvas.bind("<Escape>", on_escape)
            root.bind("<Escape>", on_escape)
            instructions = tk.Label(
                root,
                text="Click & drag to select region. Press ESC to cancel.",
                bg="black",
                fg="white",
                font=("Arial", 12),
            )
            instructions.place(relx=0.5, rely=0.02, anchor=tk.N)
            canvas.focus_set()
            canvas.screen_photo = original_photo  # type: ignore

    selector = RegionSelector(debug)
    return selector.select_region()


def take_region_screenshot_debug(save_folder="screenshots"):
    """
    Debug version of take_region_screenshot that shows coordinate mapping info
    """
    return take_region_screenshot(save_folder, debug=True)


def take_fullscreen_screenshot(save_folder="screenshots"):
    """
    Capture entire screen without UI overlay.
    Returns the path to the saved screenshot.
    """
    if not os.path.exists(save_folder):
        os.makedirs(save_folder)

    try:
        # Capture the entire screen
        screen = ImageGrab.grab()

        # Generate unique filename with timestamp
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"fullscreen_{timestamp}.png"
        filepath = os.path.join(save_folder, filename)

        # Save the screenshot
        screen.save(filepath)
        logger.info("Fullscreen screenshot saved: %s", filepath)

        # Copy to clipboard (both pixels and file reference)
        copy_image_to_clipboard(screen)
        copy_file_to_clipboard(filepath)

        return filepath
    except Exception as e:
        logger.error("Error taking fullscreen screenshot: %s", e)
        return None


def create_thumbnail(image_path, max_size=(300, 300)):
    """
    Create a base64 encoded thumbnail from an image file.
    Returns base64 string for preview display.
    """
    import base64

    try:
        with Image.open(image_path) as img:
            # Create thumbnail preserving aspect ratio
            img.thumbnail(max_size, Image.Resampling.LANCZOS)

            # Convert to base64 with good quality
            buffer = BytesIO()
            img.save(buffer, format="PNG", optimize=False)
            buffer.seek(0)

            return base64.b64encode(buffer.read()).decode("utf-8")
    except Exception as e:
        logger.error("Error creating thumbnail: %s", e)
        return None


def start_screenshot_service(save_folder="screenshots", callback=None):
    """Start the screenshot service with keyboard shortcut"""
    service = ScreenshotService(callback)
    try:
        service.start_listener(save_folder)
    except KeyboardInterrupt:
        logger.info("Service stopped by user.")
    return service


if __name__ == "__main__":
    logger.info("Starting screenshot service...")
    logger.info("Press Alt+. to take a region screenshot")
    logger.info("Press Ctrl+C to exit")
    start_screenshot_service("screenshots")
