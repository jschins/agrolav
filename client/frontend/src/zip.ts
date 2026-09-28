/** Store-only zip. Workbooks are already compressed, so the archive does not deflate them again. */

function crc32(data: Uint8Array): number {
  let c = 0xffffffff;
  for (let i = 0; i < data.length; i += 1) {
    c ^= data[i];
    for (let k = 0; k < 8; k += 1) {
      c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
    }
  }
  return (~c) >>> 0;
}

function u16(view: DataView, offset: number, value: number): void {
  view.setUint16(offset, value, true);
}

function u32(view: DataView, offset: number, value: number): void {
  view.setUint32(offset, value, true);
}

export function zipStore(files: { name: string; bytes: Uint8Array }[]): Blob {
  const enc = new TextEncoder();
  const parts: Uint8Array[] = [];
  const centrals: Uint8Array[] = [];
  let offset = 0;
  for (const file of files) {
    const name = enc.encode(file.name.replace(/\\/g, "/"));
    const crc = crc32(file.bytes);
    const size = file.bytes.length;
    const local = new Uint8Array(30 + name.length);
    const view = new DataView(local.buffer);
    u32(view, 0, 0x04034b50);
    u16(view, 4, 20);
    u16(view, 6, 0x0800);
    u32(view, 14, crc);
    u32(view, 18, size);
    u32(view, 22, size);
    u16(view, 26, name.length);
    local.set(name, 30);
    parts.push(local, file.bytes);
    const central = new Uint8Array(46 + name.length);
    const directory = new DataView(central.buffer);
    u32(directory, 0, 0x02014b50);
    u16(directory, 4, 20);
    u16(directory, 6, 20);
    u16(directory, 8, 0x0800);
    u32(directory, 16, crc);
    u32(directory, 20, size);
    u32(directory, 24, size);
    u16(directory, 28, name.length);
    u32(directory, 42, offset);
    central.set(name, 46);
    centrals.push(central);
    offset += local.length + size;
  }
  const centralSize = centrals.reduce((sum, part) => sum + part.length, 0);
  const end = new Uint8Array(22);
  const tail = new DataView(end.buffer);
  u32(tail, 0, 0x06054b50);
  u16(tail, 8, files.length);
  u16(tail, 10, files.length);
  u32(tail, 12, centralSize);
  u32(tail, 16, offset);
  const blobParts: BlobPart[] = [];
  for (const part of [...parts, ...centrals, end]) {
    const copy = new ArrayBuffer(part.byteLength);
    new Uint8Array(copy).set(part);
    blobParts.push(copy);
  }
  return new Blob(blobParts, { type: "application/zip" });
}
