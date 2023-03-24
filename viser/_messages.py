"""Message type definitions. For synchronization with the TypeScript definitions, see
`_typescript_interface_gen.py.`"""

from __future__ import annotations

import base64
import dataclasses
import functools
import io
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Dict,
    List,
    Optional,
    Tuple,
    Type,
    Union,
)

import imageio.v3 as iio
import msgpack
import numpy as onp
import numpy.typing as onpt
from typing_extensions import Literal, assert_never

if TYPE_CHECKING:
    from ._server import ClientId
else:
    ClientId = Any


def _prepare_for_serialization(value: Any) -> Any:
    """Prepare any special types for serialization. Currently just maps numpy arrays to
    their underlying data buffers."""

    if isinstance(value, onp.ndarray):
        return value.data if value.data.c_contiguous else value.copy().data
    else:
        return value


def _colors_to_uint8(colors: onp.ndarray) -> onpt.NDArray[onp.uint8]:
    """Convert intensity values to uint8. We assume the range [0,1] for floats, and
    [0,255] for integers."""
    if colors.dtype != onp.uint8:
        if onp.issubdtype(colors.dtype, onp.floating):
            colors = onp.clip(colors * 255.0, 0, 255).astype(onp.uint8)
        if onp.issubdtype(colors.dtype, onp.integer):
            colors = onp.clip(colors, 0, 255).astype(onp.uint8)
    return colors


class Message:
    """Base message type for controlling our viewer."""

    type: ClassVar[str]
    excluded_self_client: Optional[ClientId] = None
    """Don't send this message to a particular client. Example of when this is useful:
    for synchronizing GUI stuff, we want to """

    def serialize(self) -> bytes:
        """Convert a Python Message object into bytes."""
        mapping = {k: _prepare_for_serialization(v) for k, v in vars(self).items()}
        out = msgpack.packb({"type": self.type, **mapping})
        assert isinstance(out, bytes)
        return out

    @staticmethod
    def deserialize(message: bytes) -> Message:
        """Convert bytes into a Python Message object."""
        mapping = msgpack.unpackb(message)
        message_type = Message._subclass_from_type_string()[mapping.pop("type")]
        return message_type(**mapping)

    @staticmethod
    @functools.lru_cache
    def _subclass_from_type_string() -> Dict[str, Type[Message]]:
        subclasses = Message.get_subclasses()
        return {s.type: s for s in subclasses}

    @staticmethod
    def get_subclasses() -> List[Type[Message]]:
        """Recursively get message subclasses."""

        def _get_subclasses(typ: Type[Message]) -> List[Type[Message]]:
            out = []
            for sub in typ.__subclasses__():
                out.append(sub)
                out.extend(_get_subclasses(sub))
            return out

        return _get_subclasses(Message)


@dataclasses.dataclass
class ViewerCameraMessage(Message):
    """Message for a posed viewer camera.
    Pose is in the form T_world_camera, OpenCV convention, +Z forward."""

    type: ClassVar[str] = "viewer_camera"
    wxyz: Tuple[float, float, float, float]
    position: Tuple[float, float, float]
    fov: float
    aspect: float
    # Should we include near and far?


@dataclasses.dataclass
class CameraFrustumMessage(Message):
    """Variant of CameraMessage used for visualizing camera frustums.

    OpenCV convention, +Z forward."""

    type: ClassVar[str] = "camera_frustum"
    name: str
    fov: float
    aspect: float
    scale: float
    color: int

    @staticmethod
    def make(
        name: str,
        fov: float,
        aspect: float,
        scale: float = 0.3,
        color: Union[Tuple[int, int, int], Tuple[float, float, float]] = (90, 119, 255),
    ) -> CameraFrustumMessage:
        color = tuple(
            value if isinstance(value, int) else int(value * 255) for value in color
        )
        return CameraFrustumMessage(
            name=name,
            fov=fov,
            aspect=aspect,
            scale=scale,
            # (255, 255, 255) => 0xffffff, etc
            color=color[0] * (256**2) + color[1] * 256 + color[2],
        )


@dataclasses.dataclass
class FrameMessage(Message):
    """Coordinate frame message.

    Position and orientation should follow a `T_parent_local` convention, which
    corresponds to the R matrix and t vector in `p_parent = [R | t] p_local`."""

    type: ClassVar[str] = "frame"
    name: str
    wxyz: Tuple[float, float, float, float]
    position: Tuple[float, float, float]
    show_axes: bool = True
    axes_length: float = 0.5
    axes_radius: float = 0.025


@dataclasses.dataclass
class PointCloudMessage(Message):
    """Point cloud message.

    Positions are internally canonicalized to float32, colors to uint8.

    Float color inputs should be in the range [0,1], int color inputs should be in the
    range [0,255].
    """

    type: ClassVar[str] = "point_cloud"
    name: str
    position: onp.ndarray
    color: onp.ndarray
    point_size: float = 0.1

    def __post_init__(self):
        # Check shapes.
        assert self.position.shape == self.color.shape
        assert self.position.shape[-1] == 3

        # Canonicalize dtypes.
        # Positions should be float32, colors should be uint8.
        if self.position.dtype != onp.float32:
            self.position = self.position.astype(onp.float32)
        self.color = _colors_to_uint8(self.color)


@dataclasses.dataclass
class MeshMessage(Message):
    """Mesh message.

    Vertices are internally canonicalized to float32, faces to uint32.
    """

    type: ClassVar[str] = "mesh"
    name: str
    vertices: onp.ndarray
    faces: onp.ndarray

    def __post_init__(self):
        if self.vertices.dtype != onp.float32:
            self.vertices = self.vertices.astype(onp.float32)

        assert onp.issubdtype(self.faces.dtype, onp.integer)
        if self.faces.dtype != onp.uint32:
            self.faces = self.faces.astype(onp.uint32)

        assert self.vertices.shape[-1] == 3
        assert self.faces.shape[-1] == 3


@dataclasses.dataclass
class BackgroundImageMessage(Message):
    """Message for rendering a background image."""

    type: ClassVar[str] = "background_image"
    media_type: Literal["image/jpeg", "image/png"]
    base64_data: str

    @staticmethod
    def encode(
        image: onp.ndarray,
        format: Literal["png", "jpeg"] = "jpeg",
        quality: Optional[int] = None,
    ) -> BackgroundImageMessage:
        image = _colors_to_uint8(image)
        with io.BytesIO() as data_buffer:
            if format == "png":
                media_type = "image/png"
                iio.imwrite(data_buffer, image, format="PNG")
            elif format == "jpeg":
                media_type = "image/jpeg"
                iio.imwrite(
                    data_buffer,
                    image[..., :3],  # Strip alpha.
                    format="JPEG",
                    quality=75 if quality is None else quality,
                )
            else:
                assert_never(format)

            base64_data = base64.b64encode(data_buffer.getvalue()).decode("ascii")

        return BackgroundImageMessage(media_type=media_type, base64_data=base64_data)


@dataclasses.dataclass
class ImageMessage(Message):
    """Message for rendering 2D images."""

    # Note: it might be faster to do the bytes->base64 conversion on the client.
    # Potentially worth revisiting.

    type: ClassVar[str] = "image"
    name: str
    media_type: Literal["image/jpeg", "image/png"]
    base64_data: str
    render_width: float
    render_height: float

    @staticmethod
    def encode(
        name: str,
        image: onp.ndarray,
        render_width: float,
        render_height: float,
        format: Literal["png", "jpeg"] = "jpeg",
        quality: Optional[int] = None,
    ) -> ImageMessage:
        proxy = BackgroundImageMessage.encode(image, format=format, quality=quality)
        return ImageMessage(
            name=name,
            media_type=proxy.media_type,
            base64_data=proxy.base64_data,
            render_width=render_width,
            render_height=render_height,
        )


@dataclasses.dataclass
class RemoveSceneNodeMessage(Message):
    """Remove a particular node from the scene."""

    type: ClassVar[str] = "remove_scene_node"
    name: str


@dataclasses.dataclass
class SetSceneNodeVisibilityMessage(Message):
    """Set the visibility of a particular node in the scene."""

    type: ClassVar[str] = "set_scene_node_visibility"
    name: str
    visible: bool


@dataclasses.dataclass
class ResetSceneMessage(Message):
    """Reset scene."""

    type: ClassVar[str] = "reset_scene"


@dataclasses.dataclass
class GuiAddMessage(Message):
    """Sent server->client to add a new GUI input."""

    type: ClassVar[str] = "add_gui"
    name: str
    folder: str
    leva_conf: Any


@dataclasses.dataclass
class GuiRemoveMessage(Message):
    """Sent server->client to add a new GUI input."""

    type: ClassVar[str] = "remove_gui"
    name: str


@dataclasses.dataclass
class GuiUpdateMessage(Message):
    """Sent client->server when a GUI input is changed."""

    type: ClassVar[str] = "gui_update"
    name: str
    value: Any


@dataclasses.dataclass
class GuiSetValueMessage(Message):
    """Sent server->client to set the value of a particular input."""

    type: ClassVar[str] = "gui_set"
    name: str
    value: Any


@dataclasses.dataclass
class GuiSetLevaConfMessage(Message):
    """Sent server->client to override some part of an input's Leva config."""

    type: ClassVar[str] = "gui_set_leva_conf"
    name: str
    leva_conf: Any
