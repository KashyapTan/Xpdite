"""Tests for source/infrastructure/screenshot_runtime.py."""

import base64
import os
import platform
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image

from source.infrastructure import screenshot_runtime as sr


def test_copy_image_to_clipboard_returns_false_off_windows():
    image = Image.new("RGB", (10, 10), color="red")

    with patch("source.infrastructure.screenshot_runtime.platform.system", return_value="Linux"):
        assert sr.copy_image_to_clipboard(image) is False


def test_copy_image_to_clipboard_returns_true_only_after_set_clipboard_succeeds():
    class DummyFunction:
        def __init__(self, return_value=None):
            self.return_value = return_value
            self.argtypes = None
            self.restype = None

        def __call__(self, *args, **kwargs):
            return self.return_value

    kernel32 = SimpleNamespace(
        GlobalAlloc=DummyFunction(123),
        GlobalFree=DummyFunction(None),
        GlobalLock=DummyFunction(456),
        GlobalUnlock=DummyFunction(None),
    )
    user32 = SimpleNamespace(
        OpenClipboard=DummyFunction(True),
        EmptyClipboard=DummyFunction(None),
        CloseClipboard=DummyFunction(None),
        SetClipboardData=DummyFunction(1),
    )
    fake_ctypes = SimpleNamespace(
        c_void_p=object,
        c_uint=int,
        c_size_t=int,
        windll=SimpleNamespace(kernel32=kernel32, user32=user32),
        memmove=DummyFunction(None),
    )

    with (
        patch("source.infrastructure.screenshot_runtime.platform.system", return_value="Windows"),
        patch.dict(sys.modules, {"ctypes": fake_ctypes}),
    ):
        assert sr.copy_image_to_clipboard(Image.new("RGB", (10, 10), color="red"), dpi_scale=1.0) is True


def test_copy_image_to_clipboard_returns_false_when_set_clipboard_fails():
    class DummyFunction:
        def __init__(self, return_value=None):
            self.return_value = return_value
            self.argtypes = None
            self.restype = None

        def __call__(self, *args, **kwargs):
            return self.return_value

    kernel32 = SimpleNamespace(
        GlobalAlloc=DummyFunction(123),
        GlobalFree=DummyFunction(None),
        GlobalLock=DummyFunction(456),
        GlobalUnlock=DummyFunction(None),
    )
    user32 = SimpleNamespace(
        OpenClipboard=DummyFunction(True),
        EmptyClipboard=DummyFunction(None),
        CloseClipboard=DummyFunction(None),
        SetClipboardData=DummyFunction(0),
    )
    fake_ctypes = SimpleNamespace(
        c_void_p=object,
        c_uint=int,
        c_size_t=int,
        windll=SimpleNamespace(kernel32=kernel32, user32=user32),
        memmove=DummyFunction(None),
    )

    with (
        patch("source.infrastructure.screenshot_runtime.platform.system", return_value="Windows"),
        patch("source.infrastructure.screenshot_runtime.time.sleep", return_value=None),
        patch.dict(sys.modules, {"ctypes": fake_ctypes}),
    ):
        assert sr.copy_image_to_clipboard(Image.new("RGB", (10, 10), color="red"), dpi_scale=1.0) is False


def test_copy_image_to_clipboard_returns_false_when_memory_lock_fails():
    class DummyFunction:
        def __init__(self, return_value=None):
            self.return_value = return_value
            self.argtypes = None
            self.restype = None

        def __call__(self, *args, **kwargs):
            return self.return_value

    kernel32 = SimpleNamespace(
        GlobalAlloc=DummyFunction(123),
        GlobalFree=DummyFunction(None),
        GlobalLock=DummyFunction(0),
        GlobalUnlock=DummyFunction(None),
    )
    user32 = SimpleNamespace(
        OpenClipboard=DummyFunction(True),
        EmptyClipboard=DummyFunction(None),
        CloseClipboard=DummyFunction(None),
        SetClipboardData=DummyFunction(1),
    )
    fake_ctypes = SimpleNamespace(
        c_void_p=object,
        c_uint=int,
        c_size_t=int,
        windll=SimpleNamespace(kernel32=kernel32, user32=user32),
        memmove=DummyFunction(None),
    )

    with (
        patch("source.infrastructure.screenshot_runtime.platform.system", return_value="Windows"),
        patch("source.infrastructure.screenshot_runtime.time.sleep", return_value=None),
        patch.dict(sys.modules, {"ctypes": fake_ctypes}),
    ):
        assert sr.copy_image_to_clipboard(Image.new("RGB", (10, 10), color="red"), dpi_scale=1.0) is False


def test_copy_image_to_clipboard_logs_and_returns_false_on_unexpected_error():
    image = MagicMock()
    image.convert.side_effect = RuntimeError("bmp encode failed")

    with patch("source.infrastructure.screenshot_runtime.platform.system", return_value="Windows"):
        assert sr.copy_image_to_clipboard(image, dpi_scale=1.0) is False


def test_copy_file_to_clipboard_returns_false_when_file_missing_or_non_windows(tmp_path):
    missing_path = tmp_path / "missing.png"

    with patch("source.infrastructure.screenshot_runtime.platform.system", return_value="Linux"):
        assert sr.copy_file_to_clipboard(str(missing_path)) is False

    with patch("source.infrastructure.screenshot_runtime.platform.system", return_value="Windows"):
        assert sr.copy_file_to_clipboard(str(missing_path)) is False


def test_copy_file_to_clipboard_uses_powershell_on_windows(tmp_path):
    image_path = tmp_path / "capture.png"
    image_path.write_bytes(b"png")

    with (
        patch("source.infrastructure.screenshot_runtime.platform.system", return_value="Windows"),
        patch("source.infrastructure.screenshot_runtime.subprocess.run") as mock_run,
    ):
        assert sr.copy_file_to_clipboard(str(image_path)) is True

    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0][:3] == ["powershell", "-NoProfile", "-Command"]
    assert "Set-Clipboard -Path" in args[0][3]
    assert kwargs["check"] is True


def test_copy_file_to_clipboard_returns_false_when_powershell_fails(tmp_path):
    image_path = tmp_path / "capture.png"
    image_path.write_bytes(b"png")

    with (
        patch("source.infrastructure.screenshot_runtime.platform.system", return_value="Windows"),
        patch(
            "source.infrastructure.screenshot_runtime.subprocess.run",
            side_effect=RuntimeError("clipboard busy"),
        ),
    ):
        assert sr.copy_file_to_clipboard(str(image_path)) is False


def test_take_fullscreen_screenshot_saves_file_and_copies_to_clipboard(tmp_path):
    fake_screen = Image.new("RGB", (80, 40), color="blue")

    with (
        patch("source.infrastructure.screenshot_runtime.ImageGrab.grab", return_value=fake_screen),
        patch("source.infrastructure.screenshot_runtime.copy_image_to_clipboard", return_value=True) as mock_copy_image,
        patch("source.infrastructure.screenshot_runtime.copy_file_to_clipboard", return_value=True) as mock_copy_file,
    ):
        screenshot_path = sr.take_fullscreen_screenshot(str(tmp_path))

    assert screenshot_path is not None
    assert os.path.exists(screenshot_path)
    assert os.path.basename(screenshot_path).startswith("fullscreen_")
    mock_copy_image.assert_called_once()
    mock_copy_file.assert_called_once_with(screenshot_path)


def test_take_fullscreen_screenshot_returns_none_on_capture_failure(tmp_path):
    with patch(
        "source.infrastructure.screenshot_runtime.ImageGrab.grab",
        side_effect=RuntimeError("screen unavailable"),
    ):
        assert sr.take_fullscreen_screenshot(str(tmp_path)) is None


def test_take_region_screenshot_saves_scaled_selection_and_copies_outputs(tmp_path):
    roots = []
    canvases = []

    class FakeTkEngine:
        def call(self, *_args):
            raise RuntimeError("dpi unavailable")

    class FakeRoot:
        def __init__(self):
            self.tk = FakeTkEngine()
            self.bindings = {}
            self.destroyed = False
            self.withdrawn = False
            self.after_callback = None
            roots.append(self)

        def attributes(self, *_args):
            return None

        def configure(self, **_kwargs):
            return None

        def withdraw(self):
            self.withdrawn = True

        def after(self, _delay, callback, *args):
            self.after_callback = (callback, args)

        def mainloop(self):
            callback, args = self.after_callback
            callback(*args)
            canvas = canvases[-1]
            canvas.bindings["<Button-1>"](SimpleNamespace(x=10, y=5))
            canvas.bindings["<B1-Motion>"](SimpleNamespace(x=60, y=30))
            canvas.bindings["<ButtonRelease-1>"](SimpleNamespace(x=60, y=30))

        def deiconify(self):
            return None

        def update_idletasks(self):
            return None

        def winfo_screenwidth(self):
            return 100

        def winfo_screenheight(self):
            return 50

        def bind(self, event, callback):
            self.bindings[event] = callback

        def update(self):
            return None

        def destroy(self):
            self.destroyed = True

    class FakeCanvas:
        def __init__(self, _root, cursor=None):
            self.cursor = cursor
            self.bindings = {}
            self.deleted = []
            self.images = []
            self.rectangles = []
            self.focused = False
            canvases.append(self)

        def pack(self, **_kwargs):
            return None

        def create_image(self, x, y, **kwargs):
            self.images.append((x, y, kwargs))

        def create_rectangle(self, x1, y1, x2, y2, **kwargs):
            self.rectangles.append((x1, y1, x2, y2, kwargs))

        def delete(self, tag):
            self.deleted.append(tag)

        def bind(self, event, callback):
            self.bindings[event] = callback

        def focus_set(self):
            self.focused = True

    class FakeLabel:
        def __init__(self, *_args, **_kwargs):
            self.placed = False

        def place(self, **_kwargs):
            self.placed = True

    screen = Image.new("RGB", (200, 100), color="purple")

    with (
        patch("source.infrastructure.screenshot_runtime.tk.Tk", FakeRoot),
        patch("source.infrastructure.screenshot_runtime.tk.Canvas", FakeCanvas),
        patch("source.infrastructure.screenshot_runtime.tk.Label", FakeLabel),
        patch("source.infrastructure.screenshot_runtime.tk.BOTH", "both"),
        patch("source.infrastructure.screenshot_runtime.tk.NW", "nw"),
        patch("source.infrastructure.screenshot_runtime.tk.N", "n"),
        patch("source.infrastructure.screenshot_runtime.platform.system", return_value="Windows"),
        patch("source.infrastructure.screenshot_runtime.get_dpi_scale", return_value=2.0),
        patch("source.infrastructure.screenshot_runtime.ImageGrab.grab", return_value=screen),
        patch("source.infrastructure.screenshot_runtime.ImageTk.PhotoImage", side_effect=lambda image: image.size),
        patch("source.infrastructure.screenshot_runtime.copy_image_to_clipboard") as mock_copy_image,
        patch("source.infrastructure.screenshot_runtime.copy_file_to_clipboard") as mock_copy_file,
    ):
        path = sr.take_region_screenshot(str(tmp_path), debug=True)

    assert path is not None
    assert os.path.exists(path)
    saved = Image.open(path)
    assert saved.size == (100, 50)
    assert mock_copy_image.call_count == 1
    assert mock_copy_image.call_args[0][1] == 2.0
    mock_copy_file.assert_called_once_with(path)
    assert canvases[-1].focused is True
    assert roots[-1].destroyed is True


def test_take_region_screenshot_returns_none_when_selection_is_cancelled(tmp_path):
    roots = []
    canvases = []

    class FakeRoot:
        def __init__(self):
            self.tk = SimpleNamespace(call=lambda *_args: None)
            self.after_callback = None
            self.bindings = {}
            self.destroyed = False
            roots.append(self)

        def attributes(self, *_args):
            return None

        def configure(self, **_kwargs):
            return None

        def withdraw(self):
            return None

        def after(self, _delay, callback, *args):
            self.after_callback = (callback, args)

        def mainloop(self):
            callback, args = self.after_callback
            callback(*args)
            self.bindings["<Escape>"](None)

        def deiconify(self):
            return None

        def update_idletasks(self):
            return None

        def winfo_screenwidth(self):
            return 20

        def winfo_screenheight(self):
            return 10

        def bind(self, event, callback):
            self.bindings[event] = callback

        def update(self):
            return None

        def destroy(self):
            self.destroyed = True

    class FakeCanvas:
        def __init__(self, *_args, **_kwargs):
            self.bindings = {}
            canvases.append(self)

        def pack(self, **_kwargs):
            return None

        def create_image(self, *_args, **_kwargs):
            return None

        def create_rectangle(self, *_args, **_kwargs):
            return None

        def delete(self, *_args, **_kwargs):
            return None

        def bind(self, event, callback):
            self.bindings[event] = callback

        def focus_set(self):
            return None

    class FakeLabel:
        def __init__(self, *_args, **_kwargs):
            return None

        def place(self, **_kwargs):
            return None

    with (
        patch("source.infrastructure.screenshot_runtime.tk.Tk", FakeRoot),
        patch("source.infrastructure.screenshot_runtime.tk.Canvas", FakeCanvas),
        patch("source.infrastructure.screenshot_runtime.tk.Label", FakeLabel),
        patch("source.infrastructure.screenshot_runtime.tk.BOTH", "both"),
        patch("source.infrastructure.screenshot_runtime.tk.NW", "nw"),
        patch("source.infrastructure.screenshot_runtime.tk.N", "n"),
        patch("source.infrastructure.screenshot_runtime.platform.system", return_value="Linux"),
        patch(
            "source.infrastructure.screenshot_runtime.ImageGrab.grab",
            return_value=Image.new("RGB", (20, 10), color="white"),
        ),
        patch("source.infrastructure.screenshot_runtime.ImageTk.PhotoImage", side_effect=lambda image: image.size),
        patch("source.infrastructure.screenshot_runtime.copy_image_to_clipboard") as mock_copy_image,
        patch("source.infrastructure.screenshot_runtime.copy_file_to_clipboard") as mock_copy_file,
    ):
        path = sr.take_region_screenshot(str(tmp_path))

    assert path is None
    mock_copy_image.assert_not_called()
    mock_copy_file.assert_not_called()
    assert roots[-1].destroyed is True


def test_create_thumbnail_returns_base64_png(tmp_path):
    image_path = tmp_path / "shot.png"
    Image.new("RGB", (600, 400), color="green").save(image_path)

    thumbnail = sr.create_thumbnail(str(image_path), max_size=(100, 100))

    assert thumbnail is not None
    decoded = base64.b64decode(thumbnail)
    loaded = Image.open(sr.BytesIO(decoded))
    assert loaded.width <= 100
    assert loaded.height <= 100


def test_create_thumbnail_returns_none_on_error():
    assert sr.create_thumbnail("/missing/file.png") is None


def test_screenshot_service_do_capture_invokes_callback_and_clears_flag(tmp_path):
    screenshot_path = str(tmp_path / "region.png")
    callback = MagicMock()
    started_threads = []

    class FakeThread:
        def __init__(self, target=None, args=(), daemon=None):
            self.target = target
            self.args = args
            started_threads.append((target, args, daemon))

        def start(self):
            if self.target:
                self.target(*self.args)

    service = sr.ScreenshotService(callback=callback)
    service.capturing = True

    with (
        patch("source.infrastructure.screenshot_runtime.take_region_screenshot", return_value=screenshot_path),
        patch("source.infrastructure.screenshot_runtime.threading.Thread", FakeThread),
    ):
        service._do_capture(str(tmp_path))

    assert service.capturing is False
    callback.assert_called_once_with(screenshot_path)
    assert started_threads[0][1] == (screenshot_path,)


def test_screenshot_service_do_capture_handles_cancelled_selection(tmp_path):
    callback = MagicMock()
    service = sr.ScreenshotService(callback=callback)
    service.capturing = True

    with patch("source.infrastructure.screenshot_runtime.take_region_screenshot", return_value=None):
        service._do_capture(str(tmp_path))

    assert service.capturing is False
    callback.assert_not_called()


def test_stop_listener_handles_listener_stop_errors():
    class BadListener:
        def stop(self):
            raise RuntimeError("cannot stop")

    service = sr.ScreenshotService()
    service.running = True
    service.listener = BadListener()

    service.stop_listener()

    assert service.running is False
    assert service.listener is None


def test_start_listener_debounces_hotkey_and_runs_callbacks(tmp_path):
    events = []
    screenshot_path = str(tmp_path / "region.png")

    class FakeThread:
        def __init__(self, target=None, args=(), daemon=None):
            self.target = target
            self.args = args

        def start(self):
            if self.target:
                self.target(*self.args)

    class FakeListener:
        def __init__(self, mapping):
            self.mapping = mapping
            self.stopped = False

        def start(self):
            hotkey = "<ctrl>+." if platform.system() == "Darwin" else "<alt>+."
            self.mapping[hotkey]()
            self.mapping[hotkey]()

        def stop(self):
            self.stopped = True

    service = sr.ScreenshotService(
        callback=lambda path: events.append(("callback", path)),
        start_callback=lambda: events.append(("start", None)),
    )

    time_values = iter([100.0, 100.2])

    def fake_sleep(_seconds):
        service.running = False

    with (
        patch("source.infrastructure.screenshot_runtime.keyboard.GlobalHotKeys", FakeListener),
        patch("source.infrastructure.screenshot_runtime.threading.Thread", FakeThread),
        patch("source.infrastructure.screenshot_runtime.take_region_screenshot", return_value=screenshot_path),
        patch("source.infrastructure.screenshot_runtime.time.time", side_effect=lambda: next(time_values)),
        patch("source.infrastructure.screenshot_runtime.time.sleep", side_effect=fake_sleep),
    ):
        service.start_listener(str(tmp_path))

    assert events == [("start", None), ("callback", screenshot_path)]
    assert service.listener is None


def test_start_listener_handles_keyboard_interrupt_and_stops_listener(tmp_path):
    class FakeListener:
        def __init__(self, _mapping):
            self.stopped = False

        def start(self):
            return None

        def stop(self):
            self.stopped = True

    service = sr.ScreenshotService()

    with (
        patch("source.infrastructure.screenshot_runtime.keyboard.GlobalHotKeys", FakeListener),
        patch("source.infrastructure.screenshot_runtime.time.sleep", side_effect=KeyboardInterrupt),
    ):
        service.start_listener(str(tmp_path))

    assert service.listener is None


def test_start_screenshot_service_returns_service_after_keyboard_interrupt(tmp_path):
    fake_service = MagicMock()
    fake_service.start_listener.side_effect = KeyboardInterrupt

    with patch("source.infrastructure.screenshot_runtime.ScreenshotService", return_value=fake_service):
        service = sr.start_screenshot_service(str(tmp_path))

    assert service is fake_service
    fake_service.start_listener.assert_called_once_with(str(tmp_path))


def test_start_screenshot_service_returns_service_instance(tmp_path):
    fake_service = MagicMock()

    with patch("source.infrastructure.screenshot_runtime.ScreenshotService", return_value=fake_service):
        service = sr.start_screenshot_service(str(tmp_path))

    assert service is fake_service
    fake_service.start_listener.assert_called_once_with(str(tmp_path))
