#!/usr/bin/env python3

import argparse
import gc
import json
import logging
import os
import sys
import time

from subprocess import Popen, PIPE

from urllib.request import urlretrieve

from PIL import Image, ImageFont, ImageDraw
import yaml

CONFIG_NAME = 'animmuf.yaml'
NOAA = "https://services.swpc.noaa.gov/experimental"
SOURCE_JSON = NOAA + "/products/animations/ctipe_muf.json"

logging.basicConfig(
  format='%(asctime)s %(name)s:%(lineno)d %(levelname)s - %(message)s',
  datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('animmuf')

def read_config():
  home = os.path.expanduser('~')
  config_path = (
    os.path.join('.', CONFIG_NAME),
    os.path.join(home, '.' + CONFIG_NAME),
    os.path.join(home, '.local', CONFIG_NAME),
    os.path.join('/etc', CONFIG_NAME),
  )
  for filename in config_path:
    if os.path.exists(filename):
      break
    logger.debug('Config file "%s" not found', filename)
  else:
    logger.error('No Configuration file found')
    sys.exit(os.EX_CONFIG)

  logger.debug('Reading config file "%s"', filename)
  with open(filename, 'r', encoding='utf-8') as confd:
    config = yaml.safe_load(confd)
  return type('Config', (object,), config)


def retrieve_files(config):
  try:
    file_time = os.stat(config.muf_file).st_mtime
    if time.time() - file_time < 3600:
      return
  except FileNotFoundError:
    pass

  urlretrieve(SOURCE_JSON, config.muf_file)
  logger.info('Downloading: %s, into: %s', SOURCE_JSON, config.muf_file)
  with open(config.muf_file, 'r', encoding='utf-8') as fdin:
    data_source = json.load(fdin)
    for url in data_source:
      filename = os.path.basename(url['url'])
      target_name = os.path.join(config.target_dir, filename)
      if os.path.exists(target_name):
        continue
      urlretrieve(NOAA + url['url'], target_name)
      logger.info('%s saved', target_name)


def cleanup(config):
  """Cleanup old muf image that are not present in the json manifest"""
  logger.info('Cleaning up non active MUF images')
  current_files = set([])
  with open(config.muf_file, 'r', encoding='utf-8') as fdm:
    data = json.load(fdm)
    for entry in data:
      current_files.add(os.path.basename(entry['url']))

  for name in os.listdir(config.target_dir):
    if name.startswith('CTIPe-MUF') and name not in current_files:
      try:
        os.unlink(os.path.join(config.target_dir, name))
        logger.info('Delete file: %s', name)
      except IOError as exp:
        logger.error(exp)


def animate(config):
  try:
    resampling = Image.Resampling.LANCZOS # This if for new versions of PIL
  except AttributeError:
    resampling = Image.LANCZOS            # Older versions of PIL

  # suitables image size (1290, 700) (640, 400) (800, 600)
  img_size = (800, 600)
  font = ImageFont.truetype(config.font, int(config.font_size))
  animation = os.path.join(config.target_dir, 'muf.gif')
  image_list = []

  file_list = []
  for name in sorted(os.listdir(config.target_dir)):
    if not name.startswith('CTIPe-MUF_'):
      continue
    file_list.append(name)

  logger.info('Processing: %d images', len(file_list))
  for name in file_list:
    logger.debug('Add %s', name)
    image = Image.open(os.path.join(config.target_dir, name))
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
  logfile = os.path.join(config.target_dir, 'muf.log')
  gif_file = os.path.join(config.target_dir, 'muf.gif')

  if not os.path.isfile(config.converter):
    logger.error('Video converter %s not found', config.converter)
    return

  cmd = f'{config.converter} {gif_file} {config.video_file}'
  with open(logfile, "w", encoding='utf-8') as fdlog:
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
