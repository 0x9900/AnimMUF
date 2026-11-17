#! /usr/bin/env python
# vim:fenc=utf-8
#
# Copyright (C) 2026 fred <github-fred@hidzz.com>
#
# Distributed under terms of the BSD 3-Clause license.
# pylint: disable=duplicate-code

import logging
import os
import sys
from datetime import UTC, datetime
from itertools import chain
from pathlib import Path
from typing import Generator

from animmuf import Config

log_file = None if os.isatty(sys.stdout.fileno()) else '/tmp/animmuf.log'
logging.basicConfig(
  format='%(asctime)s %(name)s:%(lineno)3d %(levelname)s - %(message)s', datefmt='%x %X',
  level=os.getenv('LOG_LEVEL', 'INFO'),
  filename=log_file
)

FILE_PATTERNS = ['*.png', '*.svg']


def select_files(root: Path, days: int) -> Generator[Path]:
  path = Path(root)
  days = days * 86400
  now = datetime.now(UTC).timestamp()

  files = chain.from_iterable(path.rglob(p) for p in FILE_PATTERNS)

  for filename in files:
    f_stat = filename.stat()
    if f_stat.st_mtime < now - days:
      yield filename


def main() -> None:
  Config.load_config()

  logging.info('Purge end')

  for path in [Config.muf_path, Config.fof2_path]:
    for expired_file in select_files(path, Config.purge_images):
      logging.info('File "%s" expired', expired_file)
      expired_file.unlink()

  logging.info('Purge end')


if __name__ == "__main__":
  main()
