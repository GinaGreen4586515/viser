import { decode } from "@msgpack/msgpack";
import AwaitLock from "await-lock";
import React, { MutableRefObject, RefObject } from "react";
import * as THREE from "three";
import { TextureLoader } from "three";

import { SceneNode, UseSceneTree } from "./SceneTree";
import { CoordinateFrame, CameraFrustum } from "./ThreeAssets";
import { Message } from "./WebsocketMessages";

/** React hook for handling incoming messages, and using them for scene tree manipulation. */
function useMessageHandler(
  useSceneTree: UseSceneTree,
  wrapperRef: RefObject<HTMLDivElement>
) {
  const removeSceneNode = useSceneTree((state) => state.removeSceneNode);
  const resetScene = useSceneTree((state) => state.resetScene);
  const addSceneNode = useSceneTree((state) => state.addSceneNode);

  // Return message handler.
  return (message: Message) => {
    switch (message.type) {
      // Add a coordinate frame.
      case "frame": {
        const node = new SceneNode(message.name, (ref) => (
          <CoordinateFrame
            ref={ref}
            scale={message.scale}
            position={new THREE.Vector3().fromArray(message.position)}
            quaternion={
              new THREE.Quaternion(
                message.wxyz[1],
                message.wxyz[2],
                message.wxyz[3],
                message.wxyz[0]
              )
            }
            show_axes={message.show_axes}
          />
        ));
        return () => addSceneNode(node);
      }
      // Add a point cloud.
      case "point_cloud": {
        const geometry = new THREE.BufferGeometry();
        const pointCloudMaterial = new THREE.PointsMaterial({
          size: message.point_size,
          vertexColors: true,
        });

        // Reinterpret cast: uint8 buffer => float32 for positions.
        geometry.setAttribute(
          "position",
          new THREE.Float32BufferAttribute(
            new Float32Array(
              message.position_f32.buffer.slice(
                message.position_f32.byteOffset,
                message.position_f32.byteOffset +
                  message.position_f32.byteLength
              )
            ),
            3
          )
        );
        geometry.computeBoundingSphere();

        // Wrap uint8 buffer for colors. Note that we need to set normalized=true.
        geometry.setAttribute(
          "color",
          new THREE.Uint8BufferAttribute(message.color_uint8, 3, true)
        );

        const node = new SceneNode(message.name, (ref) => (
          <points ref={ref} geometry={geometry} material={pointCloudMaterial} />
        ));
        return () => addSceneNode(node);
      }
      // Add a camera frustum.
      case "camera_frustum": {
        const node = new SceneNode(message.name, (ref) => (
          <CameraFrustum
            ref={ref}
            fov={message.fov}
            aspect={message.aspect}
            scale={message.scale}
          ></CameraFrustum>
        ));
        return () => addSceneNode(node);
      }
      // Add a background image.
      case "background_image": {
        return () => {
          if (wrapperRef.current != null) {
            wrapperRef.current.style.backgroundImage = `url(data:${message.media_type};base64,${message.base64_data})`;
            wrapperRef.current.style.backgroundSize = "cover";
            wrapperRef.current.style.backgroundRepeat = "no-repeat";
            wrapperRef.current.style.backgroundPosition = "center center";
          }
        };
      }
      // Add an image.
      case "image": {
        // It's important that we load the texture outside of the node
        // construction callback; this prevents flickering by ensuring that the
        // texture is ready before the scene tree updates.
        const colorMap = new TextureLoader().load(
          `data:${message.media_type};base64,${message.base64_data}`
        );
        const node = new SceneNode(message.name, (ref) => {
          return (
            <mesh ref={ref}>
              <planeGeometry
                attach="geometry"
                args={[message.render_width, message.render_height]}
              />
              <meshBasicMaterial
                attach="material"
                transparent={true}
                side={THREE.DoubleSide}
                map={colorMap}
              />
            </mesh>
          );
        });
        return () => addSceneNode(node);
      }
      // Remove a scene node by name.
      case "remove_scene_node": {
        console.log("Removing scene node:", message.name);
        return () => removeSceneNode(message.name);
      }
      // Reset the entire scene, removing all scene nodes.
      case "reset_scene": {
        console.log("Resetting scene!");
        return () => resetScene();
      }
      default: {
        console.log("Received message did not match any known types:", message);
        return () => undefined;
      }
    }
  };
}

/** Component for handling websocket connections. Rendered as a connection indicator. */
function useWebsocketInterface(
  useSceneTree: UseSceneTree,
  websocketRef: MutableRefObject<WebSocket | null>,
  wrapperRef: RefObject<HTMLDivElement>,
  host: string
) {
  const [connected, setConnected] = React.useState(false);

  // Handle state updates in batches, at regular intervals. This helps reduce
  // re-renders when there are a lot of messages.
  //
  // Could be revisited.
  const stateUpdateQueue = React.useRef<(() => void)[]>([]);
  React.useEffect(() => {
    const batchedMessageHandler = setInterval(() => {
      // Thread-safe pop for all state updates in the queue.
      const stateUpdateBatch = [...stateUpdateQueue.current];
      stateUpdateQueue.current.splice(0, stateUpdateBatch.length);

      // Handle all messages.
      stateUpdateBatch.forEach((handle) => handle());
    }, 50);
    return () => clearInterval(batchedMessageHandler);
  }, [stateUpdateQueue]);

  const handleMessage = useMessageHandler(useSceneTree, wrapperRef);

  React.useEffect(() => {
    // Lock for making sure messages are handled in order. This is important
    // especially when we are removing scene nodes.
    const orderLock = new AwaitLock();

    function tryConnect(): void {
      const ws = new WebSocket(host);

      ws.onopen = () => {
        console.log("Connected!");
        console.log(ws);
        websocketRef.current = ws;
        setConnected(true);
      };

      ws.onclose = () => {
        console.log("Disconnected!");
        websocketRef.current = null;
        setConnected(false);

        // Try to reconnect.
        setTimeout(tryConnect, 1000);
      };

      ws.onmessage = async (event) => {
        // Async message handler. This is structured to reduce websocket
        // backpressure.
        const messagePromise = new Promise<Message>(async (resolve) => {
          resolve(decode(await event.data.arrayBuffer()) as Message);
        });

        // Handle messages in order.
        await orderLock.acquireAsync();
        try {
          const stateUpdate = handleMessage(await messagePromise);
          stateUpdateQueue.current.push(stateUpdate);
        } finally {
          orderLock.release();
        }
      };
    }

    let timeout = setTimeout(tryConnect, 500);
    return () => {
      clearTimeout(timeout);
    };
  }, [handleMessage, websocketRef]);

  return connected;
}

export default useWebsocketInterface;
