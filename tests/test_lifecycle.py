"""Tests for source/core/lifecycle.py — _clear_folder."""


from source.core.lifecycle import _clear_folder


class TestClearFolder:
    def test_removes_files(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("hello")
        f2.write_text("world")
        _clear_folder(str(tmp_path))
        assert not f1.exists()
        assert not f2.exists()

    def test_preserves_subdirectories(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        f = tmp_path / "file.txt"
        f.write_text("data")
        _clear_folder(str(tmp_path))
        assert not f.exists()
        assert sub.is_dir()  # directories are preserved

    def test_nonexistent_folder_is_noop(self):
        _clear_folder("/nonexistent/path/xyz")  # should not raise

    def test_empty_folder(self, tmp_path):
        _clear_folder(str(tmp_path))  # should not raise
