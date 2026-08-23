"""Hybrid Tk dashboard and OpenCV camera preview shared by camera tools.

Tk is intentionally kept out of the video-pixel path.  It owns controls,
status text and keyboard shortcuts while HighGUI presents the NumPy/OpenCV
frame directly.  This avoids the BGR -> RGB -> PPM -> Tcl ``PhotoImage`` copy
that previously dominated every viewer on the Raspberry Pi.
"""

from __future__ import annotations

from collections import deque
import time
import tkinter as tk
from tkinter import ttk

import cv2


class TkCameraWindow:
    """A Tk control dashboard paired with one clean OpenCV preview window.

    ``show`` and ``pump`` must run on the UI/main thread.  Mouse callbacks use
    corrected-frame coordinates even when ``display_scale`` resizes the
    HighGUI image.  Keys received by either Tk or OpenCV are merged into the
    queue returned by :meth:`poll_key`.
    """

    STATUS_INTERVAL_S = 0.1

    def __init__(self, title, size, *, display_scale=1.0, mouse_callback=None,
                 buttons=(), close_request=None, key_filter=None):
        if display_scale <= 0:
            raise ValueError("display_scale must be positive")
        self.root = tk.Tk()
        self.root.title(f"{title} - Controls")
        self.preview_title = f"{title} - Preview"
        self._close_request = close_request
        self._key_filter = key_filter
        self.root.protocol("WM_DELETE_WINDOW", self._request_close)
        self.root.columnconfigure(0, weight=1)

        self._keys = deque()
        self._closed = False
        self._mouse_callback = mouse_callback
        self._display_scale = float(display_scale)
        self._source_size = tuple(size)
        self._shown_size = tuple(size)
        self._preview_created = False
        self._preview_was_presented = False

        panel = ttk.Frame(self.root, padding=(8, 7))
        panel.grid(row=0, column=0, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        self.status = tk.Label(panel, anchor="nw", justify="left",
                               relief="flat", background="#f2f2f2",
                               foreground="#333333", font="TkFixedFont")
        self.status.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self._button_bar = ttk.Frame(panel)
        self._button_bar.grid(row=1, column=0, sticky="ew")
        self._buttons = []
        for label, key in buttons:
            button = ttk.Button(
                self._button_bar, text=label,
                command=lambda value=key: self.push_key(value),
            )
            self._buttons.append(button)
        self._button_bar.bind("<Configure>", self._layout_buttons)

        self.root.bind_all("<KeyPress>", self._key)
        self.root.bind("<Configure>", self._on_resize)
        self._status_text = None
        self._pending_status = ""
        self._last_status_at = 0.0

        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        width = min(max(680, self.root.winfo_reqwidth()), max(320, screen_w - 80))
        self.root.geometry(f"{width}x{max(180, self.root.winfo_reqheight())}")
        self.root.minsize(min(520, screen_w), 150)
        self.root.update_idletasks()
        self._layout_buttons()

    @property
    def closed(self):
        return self._closed

    def push_key(self, key):
        if isinstance(key, str):
            key = ord(key)
        key = int(key)
        key_filter = getattr(self, "_key_filter", None)
        if key_filter is None or key_filter(key):
            self._keys.append(key)

    def _key(self, event):
        if event.keysym == "Escape":
            self.push_key(27)
        elif event.keysym == "Return":
            self.push_key(13)
        elif event.keysym == "BackSpace":
            self.push_key(8)
        elif event.char:
            self.push_key(ord(event.char))
        return "break"

    def _on_resize(self, _event=None):
        if not self._closed:
            self.status.configure(wraplength=max(360, self.root.winfo_width() - 32))

    def _layout_buttons(self, _event=None):
        """Wrap action buttons so narrow dashboards never hide a control."""
        if not self._buttons:
            return
        available = max(260, self._button_bar.winfo_width())
        row = column = used = 0
        for button in self._buttons:
            wanted = button.winfo_reqwidth() + 5
            if column and used + wanted > available:
                row += 1
                column = used = 0
            button.grid(row=row, column=column, padx=(0, 5), pady=(0, 3),
                        sticky="w")
            used += wanted
            column += 1

    def _request_close(self):
        if self._close_request is not None and not self._close_request():
            return False
        self.close()
        return True

    def _create_preview(self):
        if self._preview_created or self._closed:
            return
        cv2.namedWindow(self.preview_title, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(self.preview_title, self._opencv_mouse)
        self._preview_created = True

    def _opencv_mouse(self, event, x, y, _flags, _param=None):
        if self._mouse_callback is None:
            return
        shown_w, shown_h = self._shown_size
        source_w, source_h = self._source_size
        if shown_w <= 0 or shown_h <= 0:
            return
        point = None
        if 0 <= x < shown_w and 0 <= y < shown_h:
            point = (min(source_w - 1, x * source_w / shown_w),
                     min(source_h - 1, y * source_h / shown_h))
        if event == cv2.EVENT_MOUSEMOVE:
            self._mouse_callback("move", point)
        elif event == cv2.EVENT_LBUTTONDOWN:
            self._mouse_callback("click", point)

    def present(self, frame):
        """Present one BGR frame without copying it through Tk/Tcl."""
        if self._closed:
            return
        self._create_preview()
        h, w = frame.shape[:2]
        self._source_size = (w, h)
        shown = frame
        if abs(self._display_scale - 1.0) > 1e-6:
            shown_w = max(1, round(w * self._display_scale))
            shown_h = max(1, round(h * self._display_scale))
            interpolation = (cv2.INTER_AREA if self._display_scale < 1.0
                             else cv2.INTER_LINEAR)
            shown = cv2.resize(frame, (shown_w, shown_h), interpolation=interpolation)
        self._shown_size = shown.shape[1::-1]
        cv2.imshow(self.preview_title, shown)
        self._preview_was_presented = True

    def show(self, frame, status_lines=()):
        """Compatibility wrapper: present a frame, update status, pump events."""
        self.present(frame)
        self.set_status(status_lines)
        self.pump()

    def set_status(self, lines, *, force=False):
        if isinstance(lines, str):
            lines = [lines]
        text = "\n".join(str(line) for line in lines)
        self._pending_status = text
        now = time.monotonic()
        if not force and self._status_text is not None:
            if text == self._status_text or now - self._last_status_at < self.STATUS_INTERVAL_S:
                return
        self._status_text = text
        self._last_status_at = now
        self.status.configure(text=text,
                              wraplength=max(360, self.root.winfo_width() - 32))

    def pump(self, status_lines=None):
        """Service Tk and HighGUI without presenting or reprocessing a frame."""
        if self._closed:
            return
        if status_lines is not None:
            self.set_status(status_lines)
        try:
            self.root.update()
        except tk.TclError:
            self._closed = True
            return

        try:
            key = cv2.waitKey(1)
            if key >= 0:
                self.push_key(key & 0xFF)
        except cv2.error:
            # ``present`` raises a useful error when HighGUI is unavailable;
            # do not mask it with an event-pump failure during teardown.
            key = -1

        if self._preview_created and self._preview_was_presented:
            try:
                visible = cv2.getWindowProperty(
                    self.preview_title, cv2.WND_PROP_VISIBLE)
            except cv2.error:
                visible = -1
            if visible < 1:
                self._preview_created = False
                self._preview_was_presented = False
                if not self._request_close():
                    # A running Rig Build can deny closure. Recreate the camera
                    # surface on the next frame while the dashboard stays live.
                    self._preview_created = False

    def poll_key(self):
        if self._closed or not self._keys:
            return -1
        return self._keys.popleft()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._preview_created:
            try:
                cv2.destroyWindow(self.preview_title)
            except cv2.error:
                pass
            self._preview_created = False
        try:
            self.root.destroy()
        except tk.TclError:
            pass
