import * as THREE from 'three';

const root = document.querySelector('[data-geometry]');

function startGeometry() {
    if (!root) return;
    const canvas = root.querySelector('canvas');
    const toggle = root.querySelector('[data-motion-toggle]');
    const context = canvas.getContext('webgl2', {alpha: true, antialias: true, powerPreference: 'low-power'});
    if (!context) {
        root.dataset.geometryState = 'fallback';
        return;
    }

    const renderer = new THREE.WebGLRenderer({canvas, context, alpha: true, antialias: true});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
    renderer.setClearColor(0x000000, 0);
    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-3.5, 3.5, 3.5, -3.5, 0.1, 50);
    camera.position.z = 12;
    const construction = new THREE.Group();
    const orbit = new THREE.Group();
    scene.add(construction, orbit);

    const resources = new Set();
    const lineMaterial = (color, opacity) => {
        const material = new THREE.LineBasicMaterial({color, transparent: true, opacity, depthWrite: false});
        resources.add(material);
        return material;
    };
    const ink = lineMaterial(0x315c53, 0.8);
    const accent = lineMaterial(0x448f7c, 0.65);
    const faint = lineMaterial(0x6d9786, 0.22);

    function line(points, material, parent = construction, loop = false) {
        const geometry = new THREE.BufferGeometry().setFromPoints(points.map(point => new THREE.Vector3(...point)));
        resources.add(geometry);
        const shape = loop ? new THREE.LineLoop(geometry, material) : new THREE.Line(geometry, material);
        parent.add(shape);
        return shape;
    }

    function circle(radius, material, parent = construction) {
        const points = Array.from({length: 160}, (_, index) => {
            const angle = index * Math.PI * 2 / 160;
            return [Math.cos(angle) * radius, Math.sin(angle) * radius, 0];
        });
        return line(points, material, parent, true);
    }

    const vertices = [[0, 2.5, 0], [-Math.sqrt(3) * 1.25, -1.25, 0], [Math.sqrt(3) * 1.25, -1.25, 0]];
    line(vertices, ink, construction, true);
    circle(2.5, faint);
    circle(1.25, accent);
    line([[-3.15, 0, -0.01], [3.15, 0, -0.01]], faint);
    line([[0, -3.15, -0.01], [0, 3.15, -0.01]], faint);
    line([[0, -1.11, 0], [0.14, -1.11, 0], [0.14, -1.25, 0]], accent);
    const ring = circle(2.8, faint, orbit);
    ring.rotation.x = 1.12;
    ring.rotation.z = -0.35;
    const solid = new THREE.IcosahedronGeometry(2.5, 0);
    const edges = new THREE.EdgesGeometry(solid);
    solid.dispose();
    resources.add(edges);
    const wireframe = new THREE.LineSegments(edges, lineMaterial(0x6c8d7b, 0.15));
    orbit.add(wireframe);

    const dotGeometry = new THREE.SphereGeometry(0.035, 10, 8);
    const dotMaterial = new THREE.MeshBasicMaterial({color: 0x26766c});
    resources.add(dotGeometry);
    resources.add(dotMaterial);
    [...vertices, [0, 0, 0]].forEach(point => {
        const dot = new THREE.Mesh(dotGeometry, dotMaterial);
        dot.position.set(...point);
        construction.add(dot);
    });

    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    let paused = preference.matches;
    let inView = true;
    let disposed = false;
    let frame = null;
    let previousTime = null;
    let elapsed = 0;
    let width = 1;
    let height = 1;
    const pointer = {x: 0, y: 0};
    const labelNodes = ['a', 'b', 'c'].map(name => root.querySelector(`.website-geometry-label-${name}`));
    const projected = new THREE.Vector3();

    function draw() {
        construction.rotation.z = Math.sin(elapsed * 0.13) * 0.045 + pointer.x * 0.018;
        wireframe.rotation.set(elapsed * 0.035 + 0.4, elapsed * 0.045 + pointer.x * 0.06, 0.25);
        ring.rotation.y = Math.sin(elapsed * 0.09) * 0.2;
        orbit.position.y = Math.sin(elapsed * 0.2) * 0.035;
        renderer.render(scene, camera);
        vertices.forEach((point, index) => {
            projected.set(...point).applyMatrix4(construction.matrixWorld).project(camera);
            labelNodes[index].style.left = `${(projected.x * 0.5 + 0.5) * width + 12}px`;
            labelNodes[index].style.top = `${(-projected.y * 0.5 + 0.5) * height - 15}px`;
        });
    }

    function animate(now) {
        frame = null;
        if (previousTime !== null) elapsed += Math.min((now - previousTime) / 1000, 0.05);
        previousTime = now;
        draw();
        if (!disposed && !paused && inView && !document.hidden) frame = requestAnimationFrame(animate);
    }

    function sync() {
        if (frame !== null) cancelAnimationFrame(frame);
        frame = null;
        previousTime = null;
        root.dataset.motion = paused ? 'paused' : 'running';
        toggle.textContent = paused ? 'Play motion' : 'Pause motion';
        toggle.setAttribute('aria-label', paused ? 'Play geometry animation' : 'Pause geometry animation');
        if (!disposed && inView && !document.hidden) {
            draw();
            if (!paused) frame = requestAnimationFrame(animate);
        }
    }

    function resize() {
        if (disposed) return;
        const box = root.getBoundingClientRect();
        width = Math.max(1, box.width);
        height = Math.max(1, box.height);
        const aspect = width / height;
        camera.left = -3.5 * aspect;
        camera.right = 3.5 * aspect;
        camera.updateProjectionMatrix();
        renderer.setSize(width, height, false);
        draw();
    }

    toggle.removeAttribute('aria-pressed');
    toggle.hidden = false;
    toggle.addEventListener('click', () => { paused = !paused; sync(); });
    preference.addEventListener('change', () => { paused = preference.matches; sync(); });
    root.addEventListener('pointermove', event => {
        const box = root.getBoundingClientRect();
        pointer.x = (event.clientX - box.left) / box.width - 0.5;
    }, {passive: true});
    document.addEventListener('visibilitychange', sync);
    const resizer = new ResizeObserver(resize);
    resizer.observe(root);
    const observer = new IntersectionObserver(entries => { inView = entries[0].isIntersecting; sync(); });
    observer.observe(root);
    canvas.addEventListener('webglcontextlost', () => {
        paused = true;
        sync();
        root.classList.remove('is-live');
        toggle.hidden = true;
        root.dataset.geometryState = 'fallback';
    });
    window.addEventListener('pagehide', event => {
        if (frame !== null) cancelAnimationFrame(frame);
        if (event.persisted) return;
        disposed = true;
        observer.disconnect();
        resizer.disconnect();
        resources.forEach(resource => resource.dispose());
        renderer.dispose();
    });
    window.addEventListener('pageshow', sync);
    resize();
    sync();
    root.classList.add('is-live');
    root.dataset.geometryState = 'ready';
}

try {
    startGeometry();
} catch {
    if (root) root.dataset.geometryState = 'fallback';
}
