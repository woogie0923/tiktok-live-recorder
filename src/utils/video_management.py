import os
import time
from pathlib import Path

import ffmpeg

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

            (
                ffmpeg.input(list_path, format="concat", safe=0, fflags="+genpts")
                .output(output, c="copy", **{"async": "1"})
                .overwrite_output()
                .run(quiet=True, cmd=VideoManagement._ffmpeg_cmd(ffmpeg_path))
            )
        except ffmpeg.Error as e:
            logger.error(
                "ffmpeg segment merge failed: "
                f"{e.stderr.decode() if hasattr(e, 'stderr') else str(e)}"
            )
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
    ) -> None:
        """
        Merge segments (if needed) and convert the capture to MP4.
        """
        if not segments:
            return

        if not VideoManagement.merge_segments(segments, output_path, ffmpeg_path):
            return

        VideoManagement.convert_flv_to_mp4(
            output_path, bitrate, ffmpeg_path, fix_sync=fix_sync
        )

    @staticmethod
    def convert_flv_to_mp4(file, bitrate=None, ffmpeg_path=None, fix_sync=False):
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

        if fix_sync:
            output_args = {
                "c:v": "libx264",
                "preset": "fast",
                "c:a": "aac",
                "b:a": "128k",
                "vsync": "vfr",
                "async": "1",
            }
            if bitrate:
                output_args["b:v"] = bitrate
            else:
                output_args["crf"] = "23"
            logger.info(
                "Repairing A/V sync with full re-encode (recommended for laggy streams)."
            )
        elif bitrate:
            output_args = {
                "b:v": bitrate,
                "c:v": "libx264",
                "c:a": "copy",
                "async": "1",
            }
        else:
            output_args = {
                "c": "copy",
                "async": "1",
            }

        try:
            (
                ffmpeg.input(file, fflags="+genpts+discardcorrupt")
                .output(output_file, **output_args)
                .overwrite_output()
                .run(quiet=True, cmd=VideoManagement._ffmpeg_cmd(ffmpeg_path))
            )

        except ffmpeg.Error as e:
            logger.error(
                f"ffmpeg conversion failed: {e.stderr.decode() if hasattr(e, 'stderr') else str(e)}"
            )
            return

        os.remove(file)
        logger.info(f"Finished converting {Path(output_file).resolve()}\n")
