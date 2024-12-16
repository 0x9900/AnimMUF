#!/usr/bin/env python3

import json
import logging
import os
import pathlib
import shutil
import sys
import time
from dataclasses import dataclass, field
from subprocess import PIPE, Popen
from typing import Iterator, Optional, Tuple, Type
from urllib.request import urlretrieve

import yaml
from PIL import Image, ImageDraw, ImageFont

CONFIG_NAME = 'animmuf.yaml'
NOAA = "https://services.swpc.noaa.gov/experimental"
SOURCE_JSON = NOAA + "/products/animations/ctipe_muf.json"
RESAMPLING = Image.Resampling.LANCZOS
DEFAULT_FONT = "/System/Library/Fonts/Supplemental/Arial Narrow.ttf"
IMG_SIZE = (800, 600)  # suitables image size (1290, 700) (640, 400) (800, 600)
MARGIN_COLOR = (0xcf, 0xcf, 0xcf)

logging.basicConfig(
  format='%(asctime)s %(name)s:%(lineno)d %(levelname)s - %(message)s',
  datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('animmuf')


@dataclass(slots=True)
class Config:
  target_dir: pathlib.Path
  converter: pathlib.Path
  muf_file: pathlib.Path
  video_file: pathlib.Path
  font: pathlib.Path = field(default_factory=lambda: pathlib.Path(DEFAULT_FONT))
  font_size: int = field(default=16)
  image_size: Tuple[int, int] = field(default=IMG_SIZE)

  def __post_init__(self):
    # pylint: disable=no-member
    for name, _field in self.__dataclass_fields__.items():
      value = getattr(self, name)
      if isinstance(value, str):
        setattr(self, name, pathlib.Path(value))


class Workdir:
  def __init__(self, source: pathlib.Path) -> None:
    self.workdir = source.joinpath('_workdir')

  def __enter__(self) -> pathlib.Path:
    try:
      self.workdir.mkdir()
      return self.workdir
    except IOError as err:
      raise err

  def __exit__(self, exc_type: Optional[Type[BaseException]],
               exc_value: Optional[BaseException],
               traceback: Optional[Type[BaseException]]) -> None:
    shutil.rmtree(self.workdir)


def read_config() -> Config:
  home = pathlib.Path('~').expanduser()
  config_path = (
    pathlib.Path('.').joinpath(CONFIG_NAME),
    pathlib.Path(home).joinpath('.' + CONFIG_NAME),
    pathlib.Path(home).joinpath('.local', CONFIG_NAME),
    pathlib.Path('/etc').joinpath(CONFIG_NAME),
  )
  for filename in config_path:
    if filename.exists():
      break
    logger.debug('Config file "%s" not found', filename)
  else:
    logger.error('No Configuration file found')
    sys.exit(os.EX_CONFIG)

  logger.debug('Reading config file "%s"', filename)
  with filename.open('r', encoding='utf-8') as confd:
    config = yaml.safe_load(confd)
  return Config(**config)


def retrieve_files(config: Config) -> None:
  try:
    file_time = config.muf_file.stat().st_mtime
    if time.time() - file_time < 3600:
      return
  except FileNotFoundError:
    pass

  logger.info('Downloading: %s, into: %s', SOURCE_JSON, config.muf_file)
  urlretrieve(SOURCE_JSON, config.muf_file)
  with config.muf_file.open('r', encoding='utf-8') as fdin:
    data_source = json.load(fdin)
    for url in data_source:
      filename = pathlib.Path(url['url'])
      target_name = config.target_dir.joinpath(filename.name)
      if target_name.exists():
        continue
      urlretrieve(NOAA + url['url'], target_name)
      logger.info('%s saved', target_name)


def cleanup(config: Config) -> None:
  """Cleanup old muf image that are not present in the json manifest"""
  logger.info('Cleaning up non active MUF images')
  current_files = set([])
  with config.muf_file.open('r', encoding='utf-8') as fdm:
    data = json.load(fdm)
    for entry in data:
      current_files.add(pathlib.Path(entry['url']).name)

  for filename in config.target_dir.glob('CTIPe-MUF_*'):
    if filename.name not in current_files:
      try:
        filename.unlink()
        logger.info('Delete file: %s', filename)
      except IOError as exp:
        logger.error(exp)


def counter(start: int = 1) -> Iterator[str]:
  cnt = start
  while True:
    yield f'{cnt:06d}'
    cnt += 1


def add_margin(image: Image.Image, top: int, right: int, bottom: int, left: int) -> Image.Image:
  color = MARGIN_COLOR
  width, height = image.size
  new_width = width + right + left
  new_height = height + top + bottom
  new_image = Image.new(image.mode, (new_width, new_height), color)
  new_image.paste(image, (left, top))
  return new_image


def process_image(config: Config, image_path: pathlib.Path, output_path: pathlib.Path) -> None:
  font = ImageFont.truetype(config.font, int(config.font_size))
  try:
    image = Image.open(image_path)
    image = image.convert('RGB')
    image = image.resize(config.image_size, RESAMPLING)
    draw = ImageDraw.Draw(image)
    draw.text((25, 550), "MUF 36 hours animation\nhttps://bsdworld.org/", font=font, fill="gray")
    image = add_margin(image, 0, 0, 40, 0)
    image.save(output_path, format="PNG")
    logger.info('Save: %s', output_path)
  except Exception as err:
    logger.warning('Error processing %s: %s', image_path, err)


def select_files(config: Config,  workdir: pathlib.Path) -> None:
  count = counter()
  file_list = sorted(config.target_dir.glob('CTIPe-MUF_*'))
  logger.info('Processing: %d images', len(file_list))
  for image_path in file_list:
    output_path = workdir.joinpath(f'CTIPe-MUF-{next(count)}.png')
    process_image(config, image_path, output_path)


def gen_video(video_file: pathlib.Path, workdir: pathlib.Path) -> None:
  ffmpeg = shutil.which('ffmpeg')
  if not ffmpeg:
    raise FileNotFoundError('ffmpeg not found')

  logfile = pathlib.Path('/tmp/animmuf.log')
  tmp_file = workdir.joinpath(f'video-{os.getpid()}.mp4')
  pngfiles = workdir.joinpath('CTIPe-MUF-*.png')

  in_args: list[str] = f'-y -framerate 10 -pattern_type glob -i {pngfiles}'.split()
  ou_args: list[str] = '-crf 23 -c:v libx264 -pix_fmt yuv420p'.split()
  cmd = [ffmpeg, *in_args, *ou_args, str(tmp_file)]
  txt_cmd = ' '.join(cmd)

  logger.info('Writing ffmpeg output in %s', logfile)
  logger.info("Saving %s video file", tmp_file)
  with logfile.open("a", encoding='ascii') as err:
    err.write(txt_cmd)
    err.write('\n\n')
    err.flush()
    with Popen(cmd, shell=False, stdout=PIPE, stderr=err) as proc:
      proc.wait()
    if proc.returncode != 0:
      logger.error('Error generating the video file')
      return
    logger.info('mv %s %s', tmp_file, video_file)
    tmp_file.rename(video_file)


def main() -> None:
  logger.setLevel(logging.getLevelName(os.getenv('LOG_LEVEL', 'INFO')))

  config = read_config()
  if not config.target_dir.is_dir():
    logger.error("The target directory %s does not exist", config.target_dir)
    return

  retrieve_files(config)
  cleanup(config)
  try:
    with Workdir(config.target_dir) as workdir:
      select_files(config, workdir)
      gen_video(config.video_file, workdir)
  except IOError as err:
    logging.error(err)
    raise SystemExit(err) from None


if __name__ == "__main__":
  main()
