"""Example for sending images to the web viewer.

We can send backgrond images to display behind the viewer (useful for visualizing
NeRFs), or images to display in 3D with respect to coordinate frames.
"""

import time

import imageio.v3 as iio
import numpy as onp

import viser

server = viser.ViserServer()

# Add a background image.
server.set_background_image(
    iio.imread("./assets/Cal_logo.png"),
    format="png",
)

# Add main image.
server.add_frame(
    "/main",
    wxyz=(1.0, 0.0, 0.0, 0.0),
    position=(2.0, 2.0, 0.0),
    show_axes=False,
)
server.add_image(
    "/main/img",
    iio.imread("./assets/Cal_logo.png"),
    4.0,
    4.0,
    format="png",
)

# Add constantly changing noise image.
server.add_frame(
    "/main/noise",
    wxyz=(1.0, 0.0, 0.0, 0.0),
    position=(0.0, 0.0, -1e-2),
    show_axes=False,
)
while True:
    server.add_image(
        "/main/noise/img",
        onp.random.randint(
            0,
            256,
            size=(400, 400, 3),
            dtype=onp.uint8,
        ),
        4.0,
        4.0,
        format="jpeg",
    )
    time.sleep(0.2)
