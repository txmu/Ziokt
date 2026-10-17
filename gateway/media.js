/* Native Range playback for public files. Encrypted formats require an explicit decoder. */
export function attachMedia(element, root) {
  if (!/^[a-f0-9]{64}$/.test(root)) throw new Error('Invalid content address');
  element.src = '/stream/' + root;
  element.preload = 'metadata';
  element.controls = true;
}
