"""Meshes

Visualize a mesh. To get the demo data, see `./assets/download_dragon_mesh.sh`.
"""

import time
from pathlib import Path

import numpy as onp
import trimesh
from scipy.spatial.transform import Rotation

import viser

mesh = trimesh.load_mesh(Path(__file__).parent / "assets/dragon.obj")
assert isinstance(mesh, trimesh.Trimesh)

vertices = mesh.vertices * 0.5
faces = mesh.faces
print(f"Loaded mesh with {vertices.shape} vertices, {faces.shape} faces")

server = viser.ViserServer()
server.add_frame(
    name="/frame",
    # so(3) => xyzw => wxyz
    wxyz=onp.roll(Rotation.from_rotvec(onp.array((onp.pi / 2, 0.0, 0.0))).as_quat(), 1),
    position=(0.0, 0.0, 0.0),
    show_axes=False,
)
server.add_mesh(name="/frame/dragon", vertices=vertices, faces=faces)

while True:
    time.sleep(10.0)
