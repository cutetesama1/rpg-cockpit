/** Source stride stays constant when the camera zooms or the output is enlarged. */
export function spriteFrameOffset(imageWidth: number, frameWidth: number, frames: number, frame: number): number {
  return frames > 1 && imageWidth >= frameWidth * frames ? frame * frameWidth : 0;
}
