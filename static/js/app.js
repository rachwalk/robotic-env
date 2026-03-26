/**
 * Robotic Environment — Three.js viewer
 *
 * Connects to the FastAPI backend via WebSocket, renders the world in real
 * time, and handles camera-frame rendering requests from the /camera endpoint.
 *
 * Coordinate mapping
 * ------------------
 *   sim (x, y)  →  Three.js (x, 0, -y)   (Y-up world, north = -Z)
 *   sim rotation 0 = north, 90 = east, clockwise
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// =========================================================================== //
//  Renderer & scene                                                            //
// =========================================================================== //

const container = document.getElementById('canvas-container');

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
container.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x87ceeb);
scene.fog = new THREE.Fog(0x87ceeb, 60, 120);

// =========================================================================== //
//  Viewer cameras                                                              //
// =========================================================================== //

const aspect = () => window.innerWidth / window.innerHeight;

const perspCam = new THREE.PerspectiveCamera(55, aspect(), 0.1, 300);
perspCam.position.set(0, 30, 30);
perspCam.lookAt(0, 0, 0);

const orthoCam = new THREE.OrthographicCamera(-10, 10, 10, -10, 0.1, 300);
orthoCam.position.set(0, 80, 0);
orthoCam.up.set(0, 0, -1);
orthoCam.lookAt(0, 0, 0);

const controls = new OrbitControls(perspCam, renderer.domElement);
controls.target.set(0, 0, 0);
controls.maxPolarAngle = Math.PI / 2.1;
controls.enabled = false;

let viewMode = 'topdown';
const activeCamera = () => viewMode === 'topdown' ? orthoCam : perspCam;

// =========================================================================== //
//  Robot's on-board camera (offscreen)                                        //
// =========================================================================== //

const robotCam = new THREE.PerspectiveCamera(60, 4 / 3, 0.1, 100);
const robotRT = new THREE.WebGLRenderTarget(640, 480);

// =========================================================================== //
//  Lighting                                                                    //
// =========================================================================== //

scene.add(new THREE.AmbientLight(0xffffff, 0.55));

const sun = new THREE.DirectionalLight(0xffffff, 0.9);
sun.position.set(8, 30, -15);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
sun.shadow.camera.near = 0.5;
sun.shadow.camera.far = 100;
sun.shadow.camera.left = -25;
sun.shadow.camera.right = 25;
sun.shadow.camera.top = 25;
sun.shadow.camera.bottom = -25;
scene.add(sun);

scene.add(new THREE.HemisphereLight(0x87ceeb, 0x4a7c59, 0.3));

// =========================================================================== //
//  Ground                                                                      //
// =========================================================================== //

const groundGroup = new THREE.Group();
scene.add(groundGroup);
let currentWorldSize = null;

function buildGround(sizeX, sizeY, bgColor) {
  while (groundGroup.children.length) groundGroup.remove(groundGroup.children[0]);

  scene.background = new THREE.Color(bgColor);
  scene.fog.color = new THREE.Color(bgColor);

  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(sizeX, sizeY),
    new THREE.MeshLambertMaterial({ color: 0x5a9e47 })
  );
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  groundGroup.add(floor);

  const gridSize = Math.max(sizeX, sizeY);
  const grid = new THREE.GridHelper(gridSize, gridSize, 0x000000, 0x2a4a2a);
  grid.material.opacity = 0.25;
  grid.material.transparent = true;
  groundGroup.add(grid);

  const edgeGeo = new THREE.EdgesGeometry(new THREE.BoxGeometry(sizeX, 0.02, sizeY));
  const edgeMat = new THREE.LineBasicMaterial({ color: 0xffffff, opacity: 0.35, transparent: true });
  groundGroup.add(new THREE.LineSegments(edgeGeo, edgeMat));

  positionViewerCameras(sizeX, sizeY);
}

function positionViewerCameras(sizeX, sizeY) {
  const maxS = Math.max(sizeX, sizeY);

  perspCam.position.set(0, maxS * 0.9, maxS * 0.9);
  perspCam.lookAt(0, 0, 0);
  controls.target.set(0, 0, 0);
  controls.update();

  const half = maxS / 2 * 1.15;
  const a = aspect();
  orthoCam.left   = -half * a;
  orthoCam.right  =  half * a;
  orthoCam.top    =  half;
  orthoCam.bottom = -half;
  orthoCam.position.set(0, 80, 0);
  orthoCam.up.set(0, 0, -1);
  orthoCam.lookAt(0, 0, 0);
  orthoCam.updateProjectionMatrix();
}

// =========================================================================== //
//  Object mesh factories                                                       //
// =========================================================================== //

function makeRobotMesh(color) {
  const g = new THREE.Group();

  const body = new THREE.Mesh(
    new THREE.CylinderGeometry(0.38, 0.38, 0.22, 24),
    new THREE.MeshLambertMaterial({ color: new THREE.Color(color) })
  );
  body.position.y = 0.11;
  body.castShadow = true;
  g.add(body);

  // Direction arrow — yellow cone pointing -Z (north at rotation=0)
  const arrow = new THREE.Mesh(
    new THREE.ConeGeometry(0.11, 0.32, 8),
    new THREE.MeshLambertMaterial({ color: 0xfdd835 })
  );
  arrow.position.set(0, 0.24, -0.32);
  arrow.rotation.x = -Math.PI / 2;
  arrow.castShadow = true;
  g.add(arrow);

  // Camera body
  const camBody = new THREE.Mesh(
    new THREE.BoxGeometry(0.17, 0.09, 0.11),
    new THREE.MeshLambertMaterial({ color: 0x212121 })
  );
  camBody.position.set(0, 0.28, -0.18);
  g.add(camBody);

  // Lens
  const lens = new THREE.Mesh(
    new THREE.CylinderGeometry(0.035, 0.035, 0.055, 8),
    new THREE.MeshLambertMaterial({ color: 0x29b6f6 })
  );
  lens.position.set(0, 0.28, -0.245);
  lens.rotation.x = Math.PI / 2;
  g.add(lens);

  return g;
}

function makeWallMesh(obj) {
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(obj.width, 1.2, obj.height),
    new THREE.MeshLambertMaterial({ color: new THREE.Color(obj.color) })
  );
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

function makeBallMesh(obj) {
  const mesh = new THREE.Mesh(
    new THREE.SphereGeometry(obj.radius ?? 0.3, 20, 20),
    new THREE.MeshLambertMaterial({ color: new THREE.Color(obj.color) })
  );
  mesh.castShadow = true;
  return mesh;
}

function makeDropZoneMesh(obj) {
  const g = new THREE.Group();
  const w = obj.width, h = obj.height;

  // Translucent fill
  const fill = new THREE.Mesh(
    new THREE.PlaneGeometry(w, h),
    new THREE.MeshBasicMaterial({
      color: new THREE.Color(obj.color),
      transparent: true,
      opacity: 0.35,
      depthWrite: false,
    })
  );
  fill.rotation.x = -Math.PI / 2;
  fill.position.y = 0.01;
  g.add(fill);

  // Border outline
  const pts = [
    new THREE.Vector3(-w / 2, 0, -h / 2),
    new THREE.Vector3( w / 2, 0, -h / 2),
    new THREE.Vector3( w / 2, 0,  h / 2),
    new THREE.Vector3(-w / 2, 0,  h / 2),
    new THREE.Vector3(-w / 2, 0, -h / 2),
  ];
  const border = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(pts),
    new THREE.LineBasicMaterial({ color: new THREE.Color(obj.color) })
  );
  border.position.y = 0.02;
  g.add(border);

  return g;
}

// Map type → factory.  Add entries here for new object types.
const MESH_FACTORY = {
  wall:     makeWallMesh,
  ball:     makeBallMesh,
  dropzone: makeDropZoneMesh,
};

// =========================================================================== //
//  Scene mesh registry                                                         //
// =========================================================================== //

const meshes = {}; // key → THREE.Object3D

function getOrCreateMesh(key, factory, ...args) {
  if (!meshes[key]) {
    const mesh = factory(...args);
    if (!mesh) return null;
    meshes[key] = mesh;
    scene.add(mesh);
  }
  return meshes[key];
}

function removeStaleMeshes(seenKeys) {
  for (const key of Object.keys(meshes)) {
    if (!seenKeys.has(key)) {
      scene.remove(meshes[key]);
      delete meshes[key];
    }
  }
}

// =========================================================================== //
//  State → scene update                                                        //
// =========================================================================== //

const robotStates = {}; // robot_id → latest robot state dict

function applyState(state) {
  const { world, robots, objects } = state;

  if (
    !currentWorldSize ||
    currentWorldSize.x !== world.size_x ||
    currentWorldSize.y !== world.size_y
  ) {
    buildGround(world.size_x, world.size_y, world.background_color);
    currentWorldSize = { x: world.size_x, y: world.size_y };
  }

  const seen = new Set();

  // ---- Robots ----
  for (const robot of robots) {
    robotStates[robot.id] = robot;
    const key = `__robot__${robot.id}`;
    seen.add(key);

    const rm = getOrCreateMesh(key, makeRobotMesh, robot.color);
    if (!rm) continue;
    rm.position.set(robot.x, 0.0, -robot.y);
    // rotation.y = θ rotates +Z to (sinθ, 0, cosθ).
    // Arrow points -Z at rest, so θ = π - sim_rot achieves: rot=0→-Z(north), rot=90→+X(east)
    rm.rotation.y = Math.PI - THREE.MathUtils.degToRad(robot.rotation);
  }

  // ---- World objects ----
  for (const obj of objects) {
    seen.add(obj.id);
    const factory = MESH_FACTORY[obj.type];
    if (!factory) continue;

    const mesh = getOrCreateMesh(obj.id, factory, obj);
    if (!mesh) continue;

    if (obj.type === 'wall') {
      mesh.position.set(obj.x, 0.6, -obj.y);
    } else if (obj.type === 'ball') {
      const r = obj.radius ?? 0.3;
      mesh.position.set(obj.x, obj.grabbed ? 0.5 : r, -obj.y);
    } else if (obj.type === 'dropzone') {
      mesh.position.set(obj.x, 0, -obj.y);
      // Brighten fill when delivered
      mesh.children[0].material.opacity = obj.delivered ? 0.75 : 0.35;
    }
  }

  removeStaleMeshes(seen);

  // ---- HUD ----
  updateHUD(robots);
}

// =========================================================================== //
//  HUD                                                                         //
// =========================================================================== //

function updateHUD(robots) {
  document.getElementById('hud-robots').innerHTML = robots.map(robot => {
    const moving = robot.is_moving || robot.is_rotating;
    const stateLabel = robot.is_moving ? 'Moving' : robot.is_rotating ? 'Rotating' : 'Idle';
    return `
      <div class="robot-entry">
        <div class="robot-name" style="color:${robot.color}">${robot.id}</div>
        <div class="hud-row">
          <span class="hud-label">Pos</span>
          <span class="hud-value">(${robot.x.toFixed(1)}, ${robot.y.toFixed(1)})</span>
        </div>
        <div class="hud-row">
          <span class="hud-label">Rot</span>
          <span class="hud-value">${robot.rotation.toFixed(0)}°</span>
        </div>
        <div class="hud-row">
          <span class="hud-label">Holds</span>
          <span class="hud-value">${robot.held_object ?? '—'}</span>
        </div>
        <div class="hud-row">
          <span class="hud-label">State</span>
          <span class="${moving ? 'hud-moving' : 'hud-idle'}">${stateLabel}</span>
        </div>
      </div>`;
  }).join('');
}

// =========================================================================== //
//  Robot camera rendering                                                      //
// =========================================================================== //

function renderRobotCamera(robotId) {
  const robot = robotStates[robotId] ?? Object.values(robotStates)[0];
  if (!robot) return;

  const rotRad = THREE.MathUtils.degToRad(robot.rotation);
  const fwdX =  Math.sin(rotRad);
  const fwdZ = -Math.cos(rotRad);
  const camHeight = 0.32;

  robotCam.position.set(robot.x, camHeight, -robot.y);
  robotCam.lookAt(robot.x + fwdX * 10, camHeight, -robot.y + fwdZ * 10);
  robotCam.fov = robot.camera_fov ?? 60;
  robotCam.updateProjectionMatrix();

  const w = robotRT.width, h = robotRT.height;
  renderer.setRenderTarget(robotRT);
  renderer.render(scene, robotCam);
  renderer.setRenderTarget(null);

  const pixels = new Uint8Array(w * h * 4);
  renderer.readRenderTargetPixels(robotRT, 0, 0, w, h, pixels);

  // Flip vertically (WebGL is bottom-up)
  const canvas = document.createElement('canvas');
  canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext('2d');
  const imgData = ctx.createImageData(w, h);
  for (let row = 0; row < h; row++) {
    const srcRow = h - 1 - row;
    imgData.data.set(pixels.subarray(srcRow * w * 4, (srcRow + 1) * w * 4), row * w * 4);
  }
  ctx.putImageData(imgData, 0, 0);

  ws.send(JSON.stringify({ type: 'camera_frame', data: canvas.toDataURL('image/png').split(',')[1] }));
}

// =========================================================================== //
//  WebSocket — with auto-reconnect                                             //
// =========================================================================== //

let ws;

function connect() {
  ws = new WebSocket(`ws://${window.location.host}/ws`);

  ws.addEventListener('open', () => {
    document.getElementById('status').textContent = 'Connected';
    document.getElementById('status').className = 'connected';
  });

  ws.addEventListener('close', () => {
    document.getElementById('status').textContent = 'Disconnected';
    document.getElementById('status').className = 'disconnected';
    setTimeout(connect, 2000);
  });

  ws.addEventListener('message', (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === 'state') {
      applyState(msg.data);
    } else if (msg.type === 'camera_request') {
      renderRobotCamera(msg.robot_id);
    }
  });
}

connect();

// =========================================================================== //
//  UI controls                                                                 //
// =========================================================================== //

document.getElementById('btn-view').addEventListener('click', () => {
  viewMode = viewMode === 'topdown' ? 'angled' : 'topdown';
  controls.enabled = viewMode === 'angled';
  document.getElementById('btn-view').textContent =
    viewMode === 'topdown' ? 'Switch to Angled View' : 'Switch to Top-Down View';
});

window.addEventListener('resize', () => {
  renderer.setSize(window.innerWidth, window.innerHeight);
  perspCam.aspect = aspect();
  perspCam.updateProjectionMatrix();
  if (currentWorldSize) positionViewerCameras(currentWorldSize.x, currentWorldSize.y);
});

// =========================================================================== //
//  Animation loop                                                              //
// =========================================================================== //

function animate() {
  requestAnimationFrame(animate);
  if (viewMode === 'angled') controls.update();
  renderer.render(scene, activeCamera());
}

animate();
