#!/usr/bin/env python3

import argparse
import gc
import json
import logging
import os
import re
import sys
import yaml

from subprocess import Popen, PIPE

from urllib.request import urlretrieve
from datetime import datetime, timedelta

from PIL import Image, ImageFont, ImageDraw

CONFIG_NAME = 'animmuf.yaml'
NOAA = "https://services.swpc.noaa.gov/experimental"
SOURCE_JSON = NOAA + "/products/animations/ctipe_muf.json"

RE_TIME = re.compile(r'.*_(\d+T\d+).png').match

logging.basicConfig(
  format='%(asctime)s %(name)s:%(lineno)d %(levelname)s - %(message)s',
  datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('animmuf')

def read_config():
  config_path = (
    os.path.join('.', CONFIG_NAME),
    os.path.join(os.path.expanduser('~'), '.' + CONFIG_NAME),
    os.path.join(os.path.expanduser('~'), '.local', CONFIG_NAME),
    os.path.join('/etc', CONFIG_NAME),
  )
  for filename in config_path:
    if os.path.exists(filename):
      break
    logger.debug('Config file "%s" not found', filename)
  else:
    logger.error('No Configuration file found', CONFIG_NAME)
    sys.exit(os.EX_CONFIG)

  logger.debug('Reading config file "%s"', filename)
  with open(filename, 'r', encoding='utf-8') as confd:
    config = yaml.safe_load(confd)
  return type('Config', (object,), config)


def extract_time(name):
  str_time = RE_TIME(name).group(1)
  return datetime.strptime(str_time, '%Y%m%dT%H%M%S')


def retreive_files(config):
  urlretrieve(SOURCE_JSON, config.muf_file)
  logger.debug('Downloading: %s, into: %s', SOURCE_JSON, config.muf_file)
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
  logger.info('Cleaning up old MUF images')
  expire_time = datetime.utcnow() - timedelta(days=1, hours=12)
  for name in os.listdir(config.target_dir):
    if not name.startswith('CTIPe-MUF'):
      continue
    try:
      file_d = extract_time(name)
      if file_d < expire_time:
        os.unlink(os.path.join(config.target_dir, name))
        logger.info('Delete file: %s', name)
    except IOError as err:
      logger.error(err)


def animate(config):
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
    image = image.resize(img_size, Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
    draw.text((25, 555), "W6BSD - MUF 36 hours animation", font=font, fill="gray")
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
  with open(logfile, "w") as err:
    print(cmd, file=err)
    proc = Popen(cmd.split(), shell=False, stdout=PIPE, stderr=err)
  logger.info(f"Saving %s video file", config.video_file)
  proc.wait()
  if proc.returncode != 0:
    logger.error('Error generating the video file. Status code: %d', proc.returncode)


def main(args=sys.argv[:1]):
  global logger
  logger.setLevel(logging.getLevelName(os.getenv('LOG_LEVEL', 'INFO')))

  config = read_config()
  parser = argparse.ArgumentParser(description='MUF animation')
  parser.add_argument('-v', '--no-video', action='store_false', default=True,
                      help='Produce an mp4 video')
  opts = parser.parse_args()

  if not os.path.isdir(config.target_dir):
    logger.error("The target directory %s does not exist", config.target_dir)
    return

  retreive_files(config)
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
