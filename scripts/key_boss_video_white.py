"""Remove studio plates from World Boss hero MP4s onto Encounter Stage dark.

Uses border flood-fill + near-white key, then H264 via imageio_ffmpeg.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "static" / "video" / "bosses"
# Mid Encounter Stage tone (#081426) — reads as space, keeps dark armor slightly visible
BG_BGR = np.array([38, 20, 8], dtype=np.float32)
BOSSES = (
    "rogue_ai_nexus",
    "planet_eater",
    "void_titan",
    "ancient_leviathan",
)


def near_white_alpha(frame_bgr: np.ndarray) -> np.ndarray:
    f = frame_bgr.astype(np.float32)
    b, g, r = f[:, :, 0], f[:, :, 1], f[:, :, 2]
    lum = (r + g + b) / 3.0
    sat = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
    alpha = np.zeros(lum.shape, dtype=np.float32)
    hard = (lum >= 235.0) & (sat <= 40.0)
    soft = (lum >= 195.0) & (sat <= 60.0) & (~hard)
    alpha[hard] = 1.0
    if np.any(soft):
        t = np.clip((lum[soft] - 195.0) / 40.0, 0.0, 1.0)
        sfactor = 1.0 - np.clip(sat[soft] / 60.0, 0.0, 1.0)
        alpha[soft] = (t * sfactor) ** 1.15
    return alpha


def flood_plate_alpha(frame_bgr: np.ndarray) -> np.ndarray:
    """Flood-fill from border seeds; tolerance sized for grey studio plates."""
    h, w = frame_bgr.shape[:2]
    work = frame_bgr.copy()
    mask = np.zeros((h + 2, w + 2), np.uint8)
    # lo/hi Diff in BGR — grey plates vary ~25-40
    lo = (42, 42, 42)
    hi = (42, 42, 42)
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    seeds = [
        (0, 0),
        (w - 1, 0),
        (0, h - 1),
        (w - 1, h - 1),
        (w // 2, 0),
        (w // 2, h - 1),
        (0, h // 2),
        (w - 1, h // 2),
        (w // 4, 0),
        (3 * w // 4, 0),
        (w // 4, h - 1),
        (3 * w // 4, h - 1),
    ]
    for x, y in seeds:
        cv2.floodFill(work, mask, (int(x), int(y)), 0, lo, hi, flags)
    filled = mask[1:-1, 1:-1]
    alpha = (filled > 0).astype(np.float32)
    f = frame_bgr.astype(np.float32)
    lum = (f[:, :, 2] + f[:, :, 1] + f[:, :, 0]) / 3.0
    sat = np.maximum(np.maximum(f[:, :, 2], f[:, :, 1]), f[:, :, 0]) - np.minimum(
        np.minimum(f[:, :, 2], f[:, :, 1]), f[:, :, 0]
    )
    # Never eat dark model armor / voids — flood can leak through grey→dark gradients
    alpha = np.where(lum < 118.0, 0.0, alpha)
    # Soften edge
    alpha = cv2.GaussianBlur(alpha, (7, 7), 0)
    # Protect weapon / energy glows
    protect = sat >= 70.0
    alpha = np.where(protect, alpha * 0.12, alpha)
    return np.clip(alpha, 0.0, 1.0)


def plate_alpha(frame_bgr: np.ndarray) -> np.ndarray:
    a = np.maximum(near_white_alpha(frame_bgr), flood_plate_alpha(frame_bgr))
    a_u8 = np.clip(a * 255.0, 0, 255).astype(np.uint8)
    # Close small holes in plate, keep model interior
    kernel = np.ones((3, 3), np.uint8)
    a_u8 = cv2.morphologyEx(a_u8, cv2.MORPH_CLOSE, kernel, iterations=1)
    a_u8 = cv2.GaussianBlur(a_u8, (5, 5), 0)
    return a_u8.astype(np.float32) / 255.0


def ensure_backup(dest: Path) -> Path:
    bak = dest.with_name(dest.stem + ".mp4.whitebak")
    if bak.exists():
        return bak
    if not dest.exists():
        raise FileNotFoundError(dest)
    dest.replace(bak)
    return bak


def process(src: Path, dest: Path) -> None:
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise SystemExit(f"cannot open {src}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 24.0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    tmp = dest.with_suffix(".keyed.tmp.mp4")
    tmp.unlink(missing_ok=True)

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{w}x{h}",
        "-r",
        f"{fps:.4f}",
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "fast",
        "-crf",
        "19",
        "-movflags",
        "+faststart",
        str(tmp),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    n = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            a = plate_alpha(frame)[:, :, None]
            keyed = frame.astype(np.float32) * (1.0 - a) + BG_BGR * a
            proc.stdin.write(np.clip(keyed, 0, 255).astype(np.uint8).tobytes())
            n += 1
    finally:
        cap.release()
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
        code = proc.wait()
    if code != 0 or not tmp.exists() or tmp.stat().st_size < 1000:
        raise SystemExit(f"ffmpeg failed for {dest.name} (code={code}):\n{err[-2000:]}")

    out_final = dest.with_suffix(".keyed.audio.tmp.mp4")
    out_final.unlink(missing_ok=True)
    mux = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(tmp),
            "-i",
            str(src),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0?",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(out_final),
        ],
        capture_output=True,
        text=True,
    )
    if mux.returncode == 0 and out_final.exists() and out_final.stat().st_size > 1000:
        tmp.unlink(missing_ok=True)
        dest.unlink(missing_ok=True)
        out_final.replace(dest)
    else:
        out_final.unlink(missing_ok=True)
        dest.unlink(missing_ok=True)
        tmp.replace(dest)
    print(f"{dest.name}: {n} frames @ {fps:.2f}fps {w}x{h}")


def main() -> None:
    for junk in list(SRC.glob("*.keyed.tmp.mp4")) + list(SRC.glob("*.keyed.audio.tmp.mp4")):
        junk.unlink(missing_ok=True)
    for key in BOSSES:
        dest = SRC / f"{key}.mp4"
        try:
            src = ensure_backup(dest)
        except FileNotFoundError:
            print(f"skip missing {key}")
            continue
        process(src, dest)
    print("done")


if __name__ == "__main__":
    main()
