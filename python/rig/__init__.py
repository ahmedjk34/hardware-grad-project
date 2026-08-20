"""Everything that talks to the rig: `config` and the serial `link`.

Kept free of cv2, argparse and prints for the same reason vision/ is — so a
terminal tool can import it without dragging a preview window along.

Nothing is imported here on purpose. The viewers want `rig.config` and nothing
else, and importing `rig.link` from this file would make pyserial a hard
dependency of drawing a grid on a picture.
"""
