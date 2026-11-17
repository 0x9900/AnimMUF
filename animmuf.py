#!/usr/bin/env python3

import logging
import os
import pathlib
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from subprocess import PIPE, Popen
from typing import List, Optional, Sequence, Tuple, Type, get_type_hints

import yaml
from PIL import Image

__version__ = "0.2.3"

CONFIG_NAME = 'animmuf.yaml'
NOAA = "https://services.swpc.noaa.gov/experimental"
SOURCE_JSON = NOAA + "/products/animations/ctipe_muf.json"
RESAMPLING = Image.Resampling.LANCZOS
IMG_SIZE = (850, 570)
MARGIN_COLOR = (0xcf, 0xcf, 0xcf)

RX = re.compile(r'^\w+-(.*Z)\..\w+')

log_file = None if os.isatty(sys.stdout.fileno()) else '/tmp/animmuf.log'
logging.basicConfig(
  format='%(asctime)s %(name)s:%(lineno)3d %(levelname)s - %(message)s', datefmt='%x %X',
  level=os.getenv('LOG_LEVEL', 'INFO'),
  filename=log_file
)


@dataclass
class Config:
  # pylint: disable=too-many-instance-attributes, no-member
  muf_path: pathlib.Path
  muf_video: pathlib.Path
  fof2_path: pathlib.Path
  fof2_video: pathlib.Path
  video_hours: int = 36
  image_size: Tuple[int, int] = IMG_SIZE
  purge_images: int = 3

  @classmethod
  def load_config(cls) -> None:
    home = pathlib.Path("~").expanduser()
    config_paths = (
        pathlib.Path(".") / CONFIG_NAME,
        home / f".{CONFIG_NAME}",
        home / ".local" / CONFIG_NAME,
        pathlib.Path("/etc") / CONFIG_NAME,
    )
    for filename in config_paths:
      if filename.exists():
        break
      logging.debug('Config file "%s" not found', filename)
    else:
      logging.error("No Configuration file found")
      sys.exit(os.EX_CONFIG)

    logging.debug('Reading config file "%s"', filename)
    with filename.open("r", encoding="utf-8") as confd:
      config = yaml.safe_load(confd)

    for name, value in config.items():
      if name not in cls.__dataclass_fields__:
        logging.warning("%s is not a valid configuration field", name)
        continue
      _type = get_type_hints(cls)[name]
      setattr(cls, name, _type(value))


class Workdir:
  def __init__(self, source: pathlib.Path) -> None:
    self.workdir = source.joinpath('_workdir')

  def __enter__(self) -> pathlib.Path:
    try:
      self.workdir.mkdir()
      return self.workdir
    except IOError as err:
      raise err

  def __exit__(self, _1: Optional[Type[BaseException]],
               _2: Optional[BaseException],
               _3: Optional[Type[BaseException]]) -> None:
    shutil.rmtree(self.workdir)


def process_image(source_img: pathlib.Path, output_img: pathlib.Path) -> None:
  try:
    image: Image.Image = Image.open(source_img)
    image = image.convert('RGB')
    image = image.resize(Config.image_size, RESAMPLING)
    image.save(output_img, format="jpeg", dpi=(100, 100))
    logging.debug('Save: %s', output_img)
  except Exception as err:
    logging.warning('Error processing %s: %s', source_img, err)


def select_files(source_path: pathlib.Path, workdir, pattern: str) -> int:
  file_list = sorted(source_path.glob(pattern))
  if not file_list:
    return 0

  selected_files: List[Tuple[datetime, pathlib.Path]] = []

  for image_path in file_list:
    if not (match := RX.match(image_path.name)):
      continue

    file_date = datetime.fromisoformat(match[1])
    selected_files.append((file_date, image_path))

  selected_files.sort()
  start = selected_files[-1][0] - timedelta(hours=Config.video_hours)
  file_list = [s[1] for s in selected_files if s[0] > start]
  logging.info('Processing: %d images', len(file_list))

  for count, image_path in enumerate(file_list):
    image_dest = workdir.joinpath(f'anim-{count:04d}.jpg')
    process_image(image_path, image_dest)

  return len(file_list)


def gen_video(workdir: pathlib.Path, video_file: pathlib.Path) -> None:
  ffmpeg = shutil.which('ffmpeg')
  if not ffmpeg:
    raise FileNotFoundError('ffmpeg not found')

  logfile = pathlib.Path('/tmp/animmuf-ffmpeg.log')
  tmp_file = video_file.with_name(f'tmp-{os.getpid()}.mp4')
  muf_files = workdir.joinpath('anim-*.jpg')

  in_args: Sequence[str] = f'-y -framerate 10 -pattern_type glob -i {muf_files}'.split()
  ou_args: Sequence[str] = '-g 10 -crf 23 -c:v libx264 -pix_fmt yuv420p'.split()
  cmd = [ffmpeg, *in_args, *ou_args, str(tmp_file)]
  txt_cmd = ' '.join(cmd)

  logging.info('Writing ffmpeg output in %s', logfile)
  logging.info("Saving %s video file", tmp_file)
  with logfile.open("a", encoding='ascii') as err:
    err.write(txt_cmd)
    err.write('\n\n')
    err.flush()
    with Popen(cmd, shell=False, stdout=PIPE, stderr=err) as proc:
      proc.wait()
    if proc.returncode != 0:
      logging.error('Error generating the video file')
      return
    logging.info('mv %s %s', tmp_file, video_file)
    tmp_file.rename(video_file)


def run(source: pathlib.Path, video_file: pathlib.Path, pattern: str) -> None:
  try:
    with Workdir(source) as workdir:
      if select_files(source, workdir, pattern) > 1:
        gen_video(workdir, video_file)
      else:
        logging.warning('No MUF files selected')
  except IOError as err:
    logging.error(err)
    raise SystemExit(err) from None


def main() -> int:
  Config.load_config()
  logging.warning('Start')
  run(Config.muf_path, Config.muf_video, 'muf-*.png')
  run(Config.fof2_path, Config.fof2_video, 'foF2-*.png')
  logging.warning('Stop')
  return os.EX_OK


if __name__ == "__main__":
  sys.exit(main())
