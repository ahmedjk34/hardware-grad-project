"""Small Tk presentation layer shared by the camera viewers.

The viewers still produce ordinary OpenCV/NumPy frames.  This module owns only
the presentation: a resizable Tk Canvas for the image and a status/control
area below it.  Keeping this separate prevents diagnostic text from becoming
part of the camera pixels and gives the live feed, grid viewer, and build UI
the same interaction model as Camera Studio.
"""

from __future__ import annotations

import tkinter as tk
import time
from tkinter import ttk

import cv2


class TkCameraWindow:
    """Display BGR frames in Tk and expose OpenCV-like polling semantics.

    ``show`` must be called from the UI/main thread.  ``poll_key`` returns the
    next key code as an integer, matching the useful subset of ``waitKey``.
    Mouse callbacks receive image-space coordinates, not Canvas coordinates.
    """

    def __init__(self, title, size, *, display_scale=1.0, mouse_callback=None,
                 buttons=(), close_request=None):
        self.root = tk.Tk()
        self.root.title(title)
        self._close_request = close_request
        self.root.protocol("WM_DELETE_WINDOW", self._request_close)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self._photo = None
        self._image_item = None
        self._layout = None
        self._keys = []
        self._closed = False
        self._mouse_callback = mouse_callback
        self._display_scale = float(display_scale)

        self.video = tk.Canvas(self.root, background="#0c0c0c",
                               highlightthickness=0, takefocus=True)
        self.video.grid(row=0, column=0, sticky="nsew")
        self.video.bind("<Motion>", self._motion)
        self.video.bind("<Button-1>", self._click)
        self.root.bind("<Configure>", self._on_resize)

        panel = ttk.Frame(self.root, padding=(8, 6))
        panel.grid(row=1, column=0, sticky="ew")
        panel.columnconfigure(0, weight=1)
        self.status = tk.Label(panel, anchor="nw", justify="left",
                               relief="flat", background="#f2f2f2",
                               foreground="#333333", font="TkFixedFont")
        self.status.grid(row=0, column=0, sticky="ew", pady=(0, 5))

        button_bar = ttk.Frame(panel)
        button_bar.grid(row=1, column=0, sticky="ew")
        self._button_bar = button_bar
        self._buttons = []
        for label, key in buttons:
            button = ttk.Button(
                button_bar, text=label,
                command=lambda value=key: self.push_key(value),
            )
            self._buttons.append(button)
        button_bar.bind("<Configure>", self._layout_buttons)

        self.root.bind_all("<KeyPress>", self._key)
        self._status_text = None
        self._pending_status = None
        self._last_status_at = 0.0
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(max(780, int(size[0] * self._display_scale)), screen_w - 80)
        # Reserve room for the multi-line diagnostics/control panel.  The
        # camera row is weighted and gives back space on smaller displays, so
        # the status area never silently falls below the build/calibration
        # information it is meant to replace.
        height = min(max(560, int(size[1] * self._display_scale) + 240), screen_h - 100)
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(min(640, screen_w), min(420, screen_h))
        self.root.update_idletasks()
        self._layout_buttons()

    @property
    def closed(self):
        return self._closed

    def push_key(self, key):
        if isinstance(key, str):
            key = ord(key)
        self._keys.append(int(key))

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
            self.status.configure(wraplength=max(420, self.root.winfo_width() - 32))

    def _layout_buttons(self, _event=None):
        """Wrap action buttons so narrow windows never hide a control."""
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
            return
        self.close()

    def _image_point(self, event):
        if not self._layout:
            return None
        dx = event.x - self._layout["x"]
        dy = event.y - self._layout["y"]
        if not (0 <= dx < self._layout["w"] and 0 <= dy < self._layout["h"]):
            return None
        scale = self._layout["scale"] or 1.0
        return (dx / scale, dy / scale)

    def _motion(self, event):
        if self._mouse_callback:
            point = self._image_point(event)
            self._mouse_callback("move", point)

    def _click(self, event):
        self.video.focus_set()
        if self._mouse_callback:
            self._mouse_callback("click", self._image_point(event))

    def show(self, frame, status_lines=()):
        if self._closed:
            return
        self.root.update_idletasks()
        vw = max(2, self.video.winfo_width())
        vh = max(2, self.video.winfo_height())
        h, w = frame.shape[:2]
        scale = min(vw / w, vh / h, 1.0)
        iw, ih = max(1, round(w * scale)), max(1, round(h * scale))
        shown = frame if scale == 1.0 else cv2.resize(
            frame, (iw, ih), interpolation=cv2.INTER_AREA)
        canvas = cv2.cvtColor(shown, cv2.COLOR_BGR2RGB)
        header = b"P6 %d %d 255 " % (iw, ih)
        self._photo = tk.PhotoImage(data=header + canvas.tobytes())
        x, y = (vw - iw) // 2, (vh - ih) // 2
        self._layout = {"x": x, "y": y, "w": iw, "h": ih,
                        "scale": scale, "render_w": w, "render_h": h}
        if self._image_item is None:
            self._image_item = self.video.create_image(x, y, anchor="nw",
                                                       image=self._photo)
        else:
            self.video.coords(self._image_item, x, y)
            self.video.itemconfigure(self._image_item, image=self._photo)
        self.set_status(status_lines)
        self.root.update()

    def set_status(self, lines):
        if isinstance(lines, str):
            lines = [lines]
        text = "\n".join(str(line) for line in lines)
        if text != self._pending_status:
            self._pending_status = text
        elif text == self._status_text:
            return
        now = time.monotonic()
        # FPS and frame counters change every iteration.  Updating a Tk text
        # widget at camera rate needlessly competes with capture/rendering, so
        # diagnostics are refreshed at a readable 10 Hz while the image keeps
        # updating every iteration.
        if self._status_text is not None and now - self._last_status_at < 0.1:
            return
        self._status_text = text
        self._last_status_at = now
        self.status.configure(text=text,
                              wraplength=max(420, self.root.winfo_width() - 32))

    def poll_key(self):
        if self._closed or not self._keys:
            return -1
        return self._keys.pop(0)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.root.destroy()
        except tk.TclError:
            pass
