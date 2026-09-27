// Images attached to a prompt: a sketch of a plan, a photo of the plot, a reference building.
// Read here, sent with the prompt, and shown in the conversation. The limits mirror
// backend/schemas/attachments.py, which re-validates and has the last word.

export const MAX_IMAGES = 6;
export const MAX_BYTES = 8 * 1024 * 1024;
export const ACCEPT = "image/png,image/jpeg,image/gif,image/webp";

const TYPES = new Set(ACCEPT.split(","));

export interface Attachment {
  id: string;
  name: string;
  mediaType: string;
  size: number;
  /** base64 without the `data:` prefix — what the backend takes. */
  data: string;
  /** Thumbnail source; never persisted (it would fill localStorage). */
  dataUrl: string;
}

export const formatSize = (bytes: number) =>
  (bytes >= 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} kB`);

async function readImage(file: File): Promise<Attachment> {
  if (!TYPES.has(file.type)) throw new Error(`${file.name} is not a PNG, JPEG, GIF or WebP image.`);
  if (file.size > MAX_BYTES) throw new Error(`${file.name} is ${formatSize(file.size)}; images must stay under ${MAX_BYTES / 1e6} MB.`);
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error(`Couldn't read ${file.name}.`));
    reader.readAsDataURL(file);
  });
  return {
    id: crypto.randomUUID(),
    name: file.name,
    mediaType: file.type,
    size: file.size,
    data: dataUrl.slice(dataUrl.indexOf(",") + 1),
    dataUrl,
  };
}

/** Read what we can of a batch; `error` is one line about everything that was left out. */
export async function readImages(files: File[], already = 0): Promise<{ images: Attachment[]; error: string | null }> {
  const room = Math.max(0, MAX_IMAGES - already);
  const problems = files.length > room ? [`Only ${MAX_IMAGES} images can go with one prompt.`] : [];
  const images: Attachment[] = [];
  for (const file of files.slice(0, room)) {
    try {
      images.push(await readImage(file));
    } catch (e) {
      problems.push(e instanceof Error ? e.message : String(e));
    }
  }
  return { images, error: problems.join(" ") || null };
}

/** The images among dropped, pasted or picked files. */
export const imageFiles = (files: FileList | File[] | null | undefined) =>
  [...(files ?? [])].filter((f) => f.type.startsWith("image/"));

/** The OS file picker. Tauri's webview opens a native dialog for a file input too. */
export function pickImages(): Promise<File[]> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ACCEPT;
    input.multiple = true;
    input.onchange = () => resolve(imageFiles(input.files));
    input.oncancel = () => resolve([]);
    input.click();
  });
}
