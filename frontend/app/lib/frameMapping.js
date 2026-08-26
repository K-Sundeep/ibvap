/**
 * Mapping between normalized frame coordinates (0-1, how the backend sends
 * both track boxes and fence points) and pixels inside a tile.
 *
 * The <video> is rendered with object-cover, so when the source aspect ratio
 * differs from the tile's the browser crops the frame. Overlays have to apply
 * the same transform or they drift — and the fence editor needs the inverse
 * too, to turn a click back into a point the backend can store.
 */
export function getFrameTransform(video, width, height) {
  const frameWidth = video?.videoWidth || width;
  const frameHeight = video?.videoHeight || height;
  const scale = Math.max(width / frameWidth, height / frameHeight);

  return {
    frameWidth,
    frameHeight,
    scale,
    offsetX: (width - frameWidth * scale) / 2,
    offsetY: (height - frameHeight * scale) / 2,
  };
}

export function frameToPixel(point, transform) {
  const { frameWidth, frameHeight, scale, offsetX, offsetY } = transform;
  return [offsetX + point[0] * frameWidth * scale, offsetY + point[1] * frameHeight * scale];
}

export function pixelToFrame(x, y, transform) {
  const { frameWidth, frameHeight, scale, offsetX, offsetY } = transform;
  return [
    clamp01((x - offsetX) / (frameWidth * scale)),
    clamp01((y - offsetY) / (frameHeight * scale)),
  ];
}

const clamp01 = (value) => Math.min(Math.max(value, 0), 1);
