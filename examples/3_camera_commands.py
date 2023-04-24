# mypy: disable-error-code="assignment"
#
# Asymmetric properties are supported in Pyright, but not yet in mypy.
# - https://github.com/python/mypy/issues/3004
# - https://github.com/python/mypy/pull/11643
"""Camera commands

In addition to reads, camera parameters also support writes. These are synced to the
corresponding client automatically.
"""

import time

import numpy as onp
from scipy.spatial.transform import Rotation

import viser

server = viser.ViserServer()
server.world_axes.visible = True


def rotate_camera(client: viser.ClientHandle) -> None:
    """Apply a rotation to the camera of a particular client.

    `.atomic()` is used to make sure that orientation and position updates happen
    at the same time."""
    delta = Rotation.from_rotvec((0.0, 0.0, 0.05))
    with client.atomic():
        client.camera.wxyz = onp.roll(
            (delta * Rotation.from_quat(onp.roll(client.camera.wxyz, -1))).as_quat(),
            1,
        )
        client.camera.position = delta.apply(client.camera.position)


while True:
    for client in server.get_clients().values():
        # Rotate the camera of all connected clients.
        rotate_camera(client)
    time.sleep(0.005)
