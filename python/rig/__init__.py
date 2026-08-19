"""Everything that talks to the rig: config, and later the serial link.

Kept free of cv2, argparse and prints for the same reason vision/ is — so a
terminal tool can import it without dragging a preview window along.
"""
