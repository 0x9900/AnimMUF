#!/usr/bin/env python3

import argparse
import json
import logging
import os
import pathlib
import shutil
import sys
import urllib.request
from dataclasses import dataclass, field
from subprocess import PIPE, Popen
from typing import Optional, Tuple, Type

import yaml
from PIL import Image, ImageDraw, ImageFont

CONFIG_NAME = 'animmuf.yaml'
NOAA = "https://services.swpc.noaa.gov/experimental"
SOURCE_JSON = NOAA + "/products/animations/ctipe_muf.json"
RESAMPLING = Image.Resampling.LANCZOS
DEFAULT_FONT = "/System/Library/Fonts/Supplemental/Arial Narrow.ttf"
IMG_SIZE = (800, 440)  # suitables image size (1290, 700) (640, 400) (800, 600)
MARGIN_COLOR = (0xcf, 0xcf, 0xcf)


@dataclass(slots=True)
class Config:
  target_dir: pathlib.Path
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
    logging.debug('Config file "%s" not found', filename)
  else:
    logging.error('No Configuration file found')
    sys.exit(os.EX_CONFIG)

  logging.debug('Reading config file "%s"', filename)
  with filename.open('r', encoding='utf-8') as confd:
    config = yaml.safe_load(confd)
  return Config(**config)


def download_with_etag(url: str, filename: pathlib.Path) -> bool:
  etag_file = filename.with_suffix('.etag')
  etag = None
  if etag_file.exists():
    with open(etag_file, "r", encoding='utf-8') as fde:
      etag = fde.read().strip()

  request = urllib.request.Request(url)
  if etag:
    request.add_header("If-None-Match", etag)

  try:
    with urllib.request.urlopen(request) as response:
      if response.status == 304:
        return False
      with open(filename, "wb") as fd:
        fd.write(response.read())
      if "ETag" in response.headers:
        with open(etag_file, "w", encoding='utf-8') as fd:
          fd.write(response.headers["ETag"])
        return True
  except urllib.error.HTTPError as e:
    if e.code == 304:
      return False
    raise
  return False


def retrieve_files(src_json: pathlib.Path, target_dir: pathlib.Path) -> bool:
  if not download_with_etag(SOURCE_JSON, src_json):
    logging.info('No new version of %s', src_json.name)
    return False

  logging.info('New %s file has been downloaded: processing', src_json)
  with src_json.open('r', encoding='utf-8') as fdin:
    data_source = json.load(fdin)
    for url in data_source:
      retrieve_image(pathlib.Path(url['url']), target_dir)
  return True


def retrieve_image(source_path: pathlib.Path, target_dir: pathlib.Path) -> None:
  target_name = target_dir.joinpath(source_path.name)
  if target_name.exists():
    return
  urllib.request.urlretrieve(NOAA + str(source_path), target_name)
  logging.info('%s saved', target_name)


def cleanup(muf_file: pathlib.Path, target_dir: pathlib.Path) -> None:
  """Cleanup old muf image that are not present in the json manifest"""
  logging.info('Cleaning up non active MUF images')
  current_files = set([])
  with muf_file.open('r', encoding='utf-8') as fdm:
    data = json.load(fdm)
    for entry in data:
      current_files.add(pathlib.Path(entry['url']).name)

  for filename in target_dir.glob('CTIPe-MUF_*'):
    if filename.name not in current_files:
      try:
        filename.unlink()
        logging.info('Delete file: %s', filename)
      except IOError as exp:
        logging.error(exp)


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
    image.save(output_path, format="jpeg")
    logging.debug('Save: %s', output_path)
  except Exception as err:
    logging.warning('Error processing %s: %s', image_path, err)


def select_files(config: Config,  workdir: pathlib.Path) -> int:
  file_list = sorted(config.target_dir.glob('CTIPe-MUF_*'))
  if not file_list:
    return 0
  logging.info('Processing: %d images', len(file_list))
  for count, image_path in enumerate(file_list):
    output_path = workdir.joinpath(f'CTIPe-MUF-{count:04d}.jpg')
    process_image(config, image_path, output_path)
  return len(file_list)


def gen_video(video_file: pathlib.Path, workdir: pathlib.Path) -> None:
  ffmpeg = shutil.which('ffmpeg')
  if not ffmpeg:
    raise FileNotFoundError('ffmpeg not found')

  logfile = pathlib.Path('/tmp/animmuf-ffmpeg.log')
  tmp_file = workdir.joinpath(f'video-{os.getpid()}.mp4')
  muf_files = workdir.joinpath('CTIPe-MUF-*.jpg')

  in_args: list[str] = f'-y -framerate 10 -pattern_type glob -i {muf_files}'.split()
  ou_args: list[str] = '-g 10 -crf 23 -c:v libx264 -pix_fmt yuv420p'.split()
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


def mk_thumbnail(target_dir: pathlib.Path) -> None:
  muf_files = []
  width, hight = (IMG_SIZE[0], int(IMG_SIZE[0] / (16 / 9)))
  for filename in target_dir.glob('CTIPe-MUF_*'):
    muf_files.append((filename.stat().st_ctime, filename))
  muf_files.sort()
  tn_source = muf_files.pop()[1]
  latest = tn_source.with_name('latest.png')

  image = Image.open(tn_source)
  image = image.convert('RGB')
  image = image.resize((width, hight))

  if latest.exists():
    latest.unlink()
  image.save(latest, format="png")
  logging.info('Latest: %s', latest)


def run(force: bool) -> int:
  config = read_config()
  if not config.target_dir.is_dir():
    logging.error("The target directory %s does not exist", config.target_dir)
    return os.EX_IOERR

  if not retrieve_files(config.muf_file, config.target_dir) and not force:
    logging.warning('No new images to process')
    return os.EX_OK

  mk_thumbnail(config.target_dir)

  cleanup(config.muf_file, config.target_dir)
  try:
    with Workdir(config.target_dir) as workdir:
      if select_files(config, workdir) > 1:
        gen_video(config.video_file, workdir)
      else:
        logging.warning('No MUF files selected')
  except IOError as err:
    logging.error(err)
    raise SystemExit(err) from None
  return os.EX_OK


def main() -> int:

  log_file = None if os.isatty(sys.stdout.fileno()) else '/tmp/animmuf.log'
  logging.basicConfig(
    format='%(asctime)s %(name)s:%(lineno)3d %(levelname)s - %(message)s', datefmt='%x %X',
    level=logging.getLevelName(os.getenv('LOG_LEVEL', 'INFO')),
    filename=log_file
  )

  parser = argparse.ArgumentParser(description='Generate the MUF animation')
  parser.add_argument('-f', '--force', action="store_true", default=False,
                      help="Create the video, even if there is no new data")
  opts = parser.parse_args()

  logging.warning('Start')
  status = run(opts.force)
  logging.warning('Stop')
  return status


if __name__ == "__main__":
  sys.exit(main())
