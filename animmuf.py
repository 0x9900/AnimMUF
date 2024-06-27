#!/usr/bin/env python3

import argparse
import gc
import json
import logging
import os
import pathlib
import sys
import time
from subprocess import PIPE, Popen
from urllib.request import urlretrieve

import yaml
from PIL import Image, ImageDraw, ImageFont

CONFIG_NAME = 'animmuf.yaml'
NOAA = "https://services.swpc.noaa.gov/experimental"
SOURCE_JSON = NOAA + "/products/animations/ctipe_muf.json"

logging.basicConfig(
  format='%(asctime)s %(name)s:%(lineno)d %(levelname)s - %(message)s',
  datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('animmuf')


def read_config():
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
  return type('Config', (object,), config)


def retrieve_files(config):
  muf_file = pathlib.Path(config.muf_file)
  try:
    file_time = muf_file.stat().st_mtime
    if time.time() - file_time < 3600:
      return
  except FileNotFoundError:
    pass

  logger.info('Downloading: %s, into: %s', SOURCE_JSON, muf_file)
  urlretrieve(SOURCE_JSON, muf_file)
  with muf_file.open('r', encoding='utf-8') as fdin:
    data_source = json.load(fdin)
    for url in data_source:
      filename = pathlib.Path(url['url'])
      target_name = pathlib.Path(config.target_dir).joinpath(filename.name)
      if target_name.exists():
        continue
      urlretrieve(NOAA + url['url'], target_name)
      logger.info('%s saved', target_name)


def cleanup(config):
  """Cleanup old muf image that are not present in the json manifest"""
  logger.info('Cleaning up non active MUF images')
  muf_file = pathlib.Path(config.muf_file)
  current_files = set([])
  with muf_file.open('r', encoding='utf-8') as fdm:
    data = json.load(fdm)
    for entry in data:
      current_files.add(pathlib.Path(entry['url']).name)

  target_dir = pathlib.Path(config.target_dir)
  for filename in target_dir.glob('CTIPe-MUF_*'):
    if filename.name not in current_files:
      try:
        filename.unlink()
        logger.info('Delete file: %s', filename)
      except IOError as exp:
        logger.error(exp)


def animate(config):
  target_dir = pathlib.Path(config.target_dir)
  try:
    resampling = Image.Resampling.LANCZOS  # This if for new versions of PIL
  except AttributeError:
    resampling = Image.LANCZOS            # Older versions of PIL

  # suitables image size (1290, 700) (640, 400) (800, 600)
  img_size = (800, 600)
  font = ImageFont.truetype(config.font, int(config.font_size))
  animation = target_dir.joinpath('muf.gif')
  image_list = []

  file_list = sorted(target_dir.glob('CTIPe-MUF_*'))
  logger.info('Processing: %d images', len(file_list))
  for filename in file_list:
    logger.debug('Add %s', filename.name)
    image = Image.open(filename)
    image = image.convert('RGB')
    image = image.resize(img_size, resampling)
    draw = ImageDraw.Draw(image)
    draw.text((25, 550), "MUF 36 hours animation\nhttps://bsdworld.org/", font=font, fill="gray")
    image_list.append(image)

  if len(image_list) > 2:
    logger.info('Saving animation into %s', animation)
    image_list[0].save(animation, save_all=True, duration=75, loop=0,
                       append_images=image_list[1:])
  else:
    logger.info('Nothing to animate')

  del image_list
  gc.collect()


def gen_video(config):
  target_dir = pathlib.Path(config.target_dir)
  logfile = target_dir.joinpath('muf.log')
  gif_file = target_dir.joinpath('muf.gif')

  converter = pathlib.Path(config.converter)
  if not converter.exists():
    logger.error('Video converter %s not found', config.converter)
    return

  cmd = f'{converter} {gif_file} {config.video_file}'
  with logfile.open("w", encoding='utf-8') as fdlog:
    print(cmd, file=fdlog)
    with Popen(cmd.split(), shell=False, stdout=PIPE, stderr=fdlog) as proc:
      logger.info("Saving %s video file", config.video_file)
      proc.wait()
  if proc.returncode != 0:
    logger.error('Error generating the video file. Status code: %d', proc.returncode)


def main():
  logger.setLevel(logging.getLevelName(os.getenv('LOG_LEVEL', 'INFO')))

  config = read_config()
  parser = argparse.ArgumentParser(description='MUF animation')
  parser.add_argument('-v', '--no-video', action='store_false', default=True,
                      help='Produce an mp4 video')
  opts = parser.parse_args()

  if not os.path.isdir(config.target_dir):
    logger.error("The target directory %s does not exist", config.target_dir)
    return

  retrieve_files(config)
  cleanup(config)
  if opts.no_video:
    animate(config)
    gen_video(config)


if __name__ == "__main__":
  try:
    main()
  except KeyboardInterrupt as err:
    print(err)
  finally:
    sys.exit()
