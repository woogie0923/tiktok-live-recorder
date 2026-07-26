import os
import subprocess
import time
from pathlib import Path

from utils.logger_manager import logger


class VideoManagement:
    @staticmethod
    def wait_for_file_release(file, timeout=10):
        """
        Wait until the file is released (not locked anymore) or timeout is reached.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with open(file, "ab"):
                    return True
            except PermissionError:
                time.sleep(0.5)
        return False

    @staticmethod
    def _ffmpeg_cmd(ffmpeg_path=None):
        return ffmpeg_path or "ffmpeg"

    @staticmethod
    def _run_ffmpeg(args: list[str], ffmpeg_path=None) -> None:
        cmd = [VideoManagement._ffmpeg_cmd(ffmpeg_path), *args]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(details or f"ffmpeg exited with code {result.returncode}")

    @staticmethod
    def _write_concat_list(segments: list[str], list_path: str) -> None:
        with open(list_path, "w", encoding="utf-8") as list_file:
            for segment in segments:
                escaped = Path(segment).resolve().as_posix().replace("'", "'\\''")
                list_file.write(f"file '{escaped}'\n")

    @staticmethod
    def merge_segments(segments: list[str], output: str, ffmpeg_path=None) -> bool:
        """
        Merge recording segments into one file, regenerating timestamps.
        """
        if not segments:
            return False

        if len(segments) == 1:
            if segments[0] != output:
                os.replace(segments[0], output)
            return True

        logger.info(f"Merging {len(segments)} recording segments...")

        list_path = f"{output}.concat.txt"
        try:
            VideoManagement._write_concat_list(segments, list_path)
            VideoManagement._run_ffmpeg(
                [
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    list_path,
                    "-fflags",
                    "+genpts",
                    "-c",
                    "copy",
                    "-async",
                    "1",
                    output,
                ],
                ffmpeg_path,
            )
        except RuntimeError as e:
            logger.error(f"ffmpeg segment merge failed: {e}")
            return False
        finally:
            Path(list_path).unlink(missing_ok=True)
            for segment in segments:
                if segment != output:
                    Path(segment).unlink(missing_ok=True)

        return True

    @staticmethod
    def finalize_recording(
        segments: list[str],
        output_path: str,
        bitrate=None,
        ffmpeg_path=None,
        fix_sync=False,
        keep_source=False,
    ) -> None:
        """
        Merge segments (if needed) and convert the capture to MP4.
        """
        if not segments:
            return

        if not VideoManagement.merge_segments(segments, output_path, ffmpeg_path):
            return

        if keep_source:
            VideoManagement.remux_to_ts(output_path, ffmpeg_path)

        VideoManagement.convert_flv_to_mp4(
            output_path,
            bitrate,
            ffmpeg_path,
            fix_sync=fix_sync,
            keep_source=keep_source,
        )

    @staticmethod
    def remux_to_ts(file, ffmpeg_path=None):
        ts_file = file.replace("_flv.mp4", ".ts")
        logger.info(f"Remuxing {file} to TS format...")

        if not VideoManagement.wait_for_file_release(file):
            logger.error(f"File {file} is still locked after waiting. Skipping TS remux.")
            return

        try:
            VideoManagement._run_ffmpeg(
                [
                    "-y",
                    "-fflags",
                    "+genpts+discardcorrupt",
                    "-i",
                    file,
                    "-c",
                    "copy",
                    "-async",
                    "1",
                    "-f",
                    "mpegts",
                    ts_file,
                ],
                ffmpeg_path,
            )
        except RuntimeError as e:
            logger.error(f"ffmpeg TS remux failed: {e}")
            return

        logger.info(f"Finished remuxing {Path(ts_file).resolve()}\n")

    @staticmethod
    def convert_flv_to_mp4(
        file, bitrate=None, ffmpeg_path=None, fix_sync=False, keep_source=False
    ):
        """
        Convert the video from flv format to mp4 format.
        Applies timestamp repair by default; use fix_sync for full re-encode.
        """
        logger.info("Converting {} to MP4 format...".format(file))

        if not VideoManagement.wait_for_file_release(file):
            logger.error(
                f"File {file} is still locked after waiting. Skipping conversion."
            )
            return

        output_file = file.replace("_flv.mp4", ".mp4")
        args = ["-y", "-fflags", "+genpts+discardcorrupt", "-i", file]

        if fix_sync:
            args.extend(
                [
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "128k",
                    "-vsync",
                    "vfr",
                    "-async",
                    "1",
                ]
            )
            if bitrate:
                args.extend(["-b:v", bitrate])
            else:
                args.extend(["-crf", "23"])
            logger.info(
                "Repairing A/V sync with full re-encode (recommended for laggy streams)."
            )
        elif bitrate:
            args.extend(["-b:v", bitrate, "-c:v", "libx264", "-c:a", "copy", "-async", "1"])
        else:
            args.extend(["-c", "copy", "-async", "1"])

        args.append(output_file)

        try:
            VideoManagement._run_ffmpeg(args, ffmpeg_path)
        except RuntimeError as e:
            logger.error(f"ffmpeg conversion failed: {e}")
            return

        if keep_source:
            logger.info(f"Kept source capture: {Path(file).resolve()}")
        else:
            os.remove(file)
        logger.info(f"Finished converting {Path(output_file).resolve()}\n")

    @staticmethod
    def log_video_stream_info(file_path: str, ffmpeg_path=None) -> None:
        cmd = [
            VideoManagement._ffmpeg_cmd(ffmpeg_path),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,avg_frame_rate,r_frame_rate",
            "-of",
            "csv=p=0",
            file_path,
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError:
            return

        if result.returncode != 0:
            return

        info = (result.stdout or "").strip()
        if info:
            logger.info(f"Recorded video stream: {info}")
